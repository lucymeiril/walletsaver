"""Server-side management endpoints used by the local DB Admin.

These endpoints deliberately live in web-api because only web-api is deployed.
Local admin tools send authenticated commands; they never open server SQLite
files directly.
"""
from __future__ import annotations

import asyncio
import hmac
import os
import shutil
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy import func, text
from starlette.concurrency import run_in_threadpool

from services.board_storage import (
    Comment as CommentModel,
    Post as PostModel,
    User as BoardUserModel,
    get_board_session_factory,
)

router = APIRouter(prefix="/api/admin/remote", tags=["Remote Admin"])

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CATALOG_DB = _BACKEND_ROOT / "storage" / "public_snapshot.sqlite"
_DEFAULT_EXTERNAL_HOTDEAL_DB = _BACKEND_ROOT / "storage" / "external_hotdeals.sqlite"
# Keep the default aligned with shared.core.fuel_store: <repo>/data/opinet.db.
_DEFAULT_OPINET_DB = Path(__file__).resolve().parents[5] / "data" / "opinet.db"

_SNAPSHOT_CONFIG = {
    "catalog": (
        "WALLETSAVIOR_PUBLIC_DB",
        _DEFAULT_CATALOG_DB,
        {
            "products", "categories", "unified_categories", "snapshot_meta",
            "normalized_canonical_products", "normalized_product_variants",
            "normalized_source_listings", "normalized_offer_events",
        },
    ),
    "external-hotdeals": (
        "WALLETSAVIOR_EXTERNAL_HOTDEAL_DB",
        _DEFAULT_EXTERNAL_HOTDEAL_DB,
        {"hotdeal_posts"},
    ),
    "opinet": (
        "OPINET_DB_PATH",
        _DEFAULT_OPINET_DB,
        {"fuel_stations", "fuel_prices"},
    ),
}


def _configured_admin_token() -> str:
    return os.getenv("WALLETSAVIOR_REMOTE_ADMIN_TOKEN", "").strip()


def require_remote_admin(
    authorization: str | None = Header(default=None),
    x_walletsavior_admin_token: str | None = Header(
        default=None,
        alias="X-WalletSavior-Admin-Token",
    ),
) -> None:
    expected = _configured_admin_token()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="원격 관리 API가 비활성화되어 있습니다",
        )

    supplied = (x_walletsavior_admin_token or "").strip()
    if not supplied and authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer":
            supplied = value.strip()

    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="원격 관리 인증에 실패했습니다")


def _board_factory():
    try:
        return get_board_session_factory()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="게시판 저장소를 사용할 수 없습니다",
        ) from exc


def _post_dict(post: PostModel, *, include_content: bool = True) -> dict:
    active_comments = sum(1 for comment in post.comments if not comment.is_deleted)
    return {
        "id": int(post.id),
        "title": post.title,
        "content": post.content if include_content else "",
        "post_type": post.post_type.value if post.post_type else "free",
        "author_id": int(post.author_id),
        "author": post.author.nickname if post.author else f"#{post.author_id}",
        "category_id": post.category_id,
        "custom_category": post.custom_category,
        "product_id": None,
        "deal_price": post.deal_price,
        "original_price": post.original_price,
        "deal_url": post.deal_url,
        "tags": [],
        "view_count": int(post.view_count or 0),
        "comment_count": active_comments,
        "vote_count": len(post.votes),
        "is_pinned": False,
        "is_deleted": bool(post.is_deleted),
        "created_at": post.created_at.isoformat() if post.created_at else "",
        "updated_at": post.updated_at.isoformat() if post.updated_at else "",
    }


def _comment_dict(comment: CommentModel) -> dict:
    return {
        "id": int(comment.id),
        "post_id": int(comment.post_id),
        "parent_id": int(comment.parent_id) if comment.parent_id is not None else None,
        "content": comment.content,
        "author_id": int(comment.author_id),
        "author": comment.author.nickname if comment.author else f"#{comment.author_id}",
        "is_deleted": bool(comment.is_deleted),
        "created_at": comment.created_at.isoformat() if comment.created_at else "",
        "updated_at": comment.created_at.isoformat() if comment.created_at else "",
    }


@router.get("/community/posts", dependencies=[Depends(require_remote_admin)])
def list_community_posts(
    status: str = Query("active", pattern="^(active|deleted|all)$"),
    post_type: str | None = Query(None),
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    factory = _board_factory()
    with factory() as session:
        query = session.query(PostModel)
        if status == "active":
            query = query.filter(PostModel.is_deleted.is_(False))
        elif status == "deleted":
            query = query.filter(PostModel.is_deleted.is_(True))

        if post_type:
            query = query.filter(PostModel.post_type == post_type)
        if search:
            pattern = f"%{search}%"
            query = query.outerjoin(BoardUserModel, BoardUserModel.id == PostModel.author_id).filter(
                (PostModel.title.ilike(pattern))
                | (PostModel.content.ilike(pattern))
                | (BoardUserModel.nickname.ilike(pattern))
            )

        total = int(query.with_entities(func.count(PostModel.id)).scalar() or 0)
        posts = (
            query.order_by(PostModel.created_at.desc(), PostModel.id.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )
        return {
            "items": [_post_dict(post) for post in posts],
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": max(1, (total + per_page - 1) // per_page),
        }


@router.get("/community/posts/{post_id}", dependencies=[Depends(require_remote_admin)])
def get_community_post(post_id: int):
    factory = _board_factory()
    with factory() as session:
        post = session.get(PostModel, post_id)
        if post is None:
            raise HTTPException(status_code=404, detail="Post not found")
        comments = (
            session.query(CommentModel)
            .filter(CommentModel.post_id == post_id)
            .order_by(CommentModel.created_at.asc(), CommentModel.id.asc())
            .all()
        )
        return {
            "post": _post_dict(post),
            "comments": [_comment_dict(comment) for comment in comments],
        }


def _set_post_deleted(post_id: int, deleted: bool) -> None:
    factory = _board_factory()
    with factory() as session:
        post = session.get(PostModel, post_id)
        if post is None:
            raise HTTPException(status_code=404, detail="Post not found")
        post.is_deleted = deleted
        session.commit()


@router.delete("/community/posts/{post_id}", dependencies=[Depends(require_remote_admin)])
def delete_community_post(post_id: int):
    _set_post_deleted(post_id, True)
    return {"deleted": True, "id": post_id}


@router.post("/community/posts/{post_id}/restore", dependencies=[Depends(require_remote_admin)])
def restore_community_post(post_id: int):
    _set_post_deleted(post_id, False)
    return {"restored": True, "id": post_id}


def _set_comment_deleted(comment_id: int, deleted: bool) -> None:
    factory = _board_factory()
    with factory() as session:
        comment = session.get(CommentModel, comment_id)
        if comment is None:
            raise HTTPException(status_code=404, detail="Comment not found")
        comment.is_deleted = deleted
        session.commit()


@router.delete("/community/comments/{comment_id}", dependencies=[Depends(require_remote_admin)])
def delete_community_comment(comment_id: int):
    _set_comment_deleted(comment_id, True)
    return {"deleted": True, "id": comment_id}


@router.post("/community/comments/{comment_id}/restore", dependencies=[Depends(require_remote_admin)])
def restore_community_comment(comment_id: int):
    _set_comment_deleted(comment_id, False)
    return {"restored": True, "id": comment_id}


def _account_session_factory(request: Request):
    account_storage = getattr(request.app.state, "account_storage", None)
    session_factory = getattr(account_storage, "SessionLocal", None)
    if session_factory is None:
        storage = getattr(request.app.state, "storage", None)
        session_factory = getattr(storage, "SessionLocal", None)
    if session_factory is None:
        raise HTTPException(status_code=503, detail="회원 저장소를 사용할 수 없습니다")
    return session_factory


def _set_account_active(request: Request, user_id: int, active: bool) -> dict:
    factory = _account_session_factory(request)
    with factory() as session:
        row = session.execute(
            text(
                "SELECT id, email, nickname, role, is_active, is_deleted "
                "FROM users WHERE id=:user_id"
            ),
            {"user_id": user_id},
        ).mappings().first()
        if row is None:
            raise HTTPException(status_code=404, detail="User not found")
        if active and bool(row.get("is_deleted")):
            raise HTTPException(status_code=409, detail="삭제된 계정은 정지 해제할 수 없습니다")
        session.execute(
            text("UPDATE users SET is_active=:active WHERE id=:user_id"),
            {"active": bool(active), "user_id": user_id},
        )
        session.commit()

    board_factory = _board_factory()
    with board_factory() as board_session:
        board_user = board_session.get(BoardUserModel, user_id)
        if board_user is not None:
            board_user.is_active = bool(active)
            board_session.commit()

    role = row.get("role")
    role_value = getattr(role, "value", role)
    return {
        "id": int(row["id"]),
        "email": row["email"],
        "nickname": row["nickname"],
        "role": str(role_value or "user").lower(),
        "is_active": bool(active),
        "is_deleted": bool(row.get("is_deleted")),
    }


@router.post("/community/users/{user_id}/ban", dependencies=[Depends(require_remote_admin)])
def ban_community_user(request: Request, user_id: int):
    return {"banned": True, "user": _set_account_active(request, user_id, False)}


@router.post("/community/users/{user_id}/unban", dependencies=[Depends(require_remote_admin)])
def unban_community_user(request: Request, user_id: int):
    return {"unbanned": True, "user": _set_account_active(request, user_id, True)}


def _snapshot_target(kind: str) -> tuple[Path, set[str]]:
    config = _SNAPSHOT_CONFIG.get(kind)
    if config is None:
        raise HTTPException(status_code=404, detail="지원하지 않는 snapshot 종류입니다")
    env_name, default_path, required_tables = config
    configured = os.getenv(env_name, "").strip()
    target = Path(configured).expanduser() if configured else default_path
    return target.resolve(), set(required_tables)


def _validate_sqlite(path: Path, required_tables: Iterable[str]) -> dict:
    try:
        with path.open("rb") as handle:
            if handle.read(16) != b"SQLite format 3\x00":
                raise ValueError("SQLite header mismatch")

        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=10)
        try:
            result = connection.execute("PRAGMA quick_check").fetchone()
            if not result or result[0] != "ok":
                raise ValueError(f"SQLite quick_check failed: {result}")
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            missing = set(required_tables) - tables
            if missing:
                raise ValueError(f"required tables missing: {', '.join(sorted(missing))}")
            if "normalized_offer_events" in tables:
                pending_offers = int(connection.execute(
                    "SELECT COUNT(*) FROM normalized_offer_events "
                    "WHERE offer_state='pending_review'"
                ).fetchone()[0])
                if pending_offers:
                    raise ValueError(
                        f"pending_review offers are not publishable: {pending_offers}"
                    )
            if {
                "unified_categories", "normalized_canonical_products"
            }.issubset(tables):
                category_rows = connection.execute(
                    "SELECT id, parent_id FROM unified_categories"
                ).fetchall()
                parents = {
                    str(row[0]): (str(row[1]) if row[1] is not None else None)
                    for row in category_rows
                }
                for category_id in parents:
                    seen: set[str] = set()
                    cursor: str | None = category_id
                    depth = 0
                    while cursor is not None:
                        if cursor not in parents:
                            raise ValueError(f"category parent not found: {cursor}")
                        if cursor in seen:
                            raise ValueError(f"category cycle detected: {category_id}")
                        seen.add(cursor)
                        depth += 1
                        if depth > 4:
                            raise ValueError(
                                f"category depth exceeds four levels: {category_id}"
                            )
                        cursor = parents[cursor]
                bad_products = int(connection.execute(
                    "SELECT COUNT(*) FROM normalized_canonical_products p "
                    "WHERE p.is_active=1 AND (p.unified_category_id IS NULL OR NOT EXISTS ("
                    "SELECT 1 FROM unified_categories current "
                    "WHERE current.id=p.unified_category_id) OR EXISTS ("
                    "SELECT 1 FROM unified_categories child "
                    "WHERE child.parent_id=p.unified_category_id))"
                ).fetchone()[0])
                if bad_products:
                    raise ValueError(
                        f"active products without a leaf category: {bad_products}"
                    )
            meta = {}
            if "normalized_canonical_products" in tables:
                columns = {row[1] for row in connection.execute(
                    "PRAGMA table_info(normalized_canonical_products)"
                )}
                if {"public_product_id", "unified_category_id", "attributes"} <= columns:
                    from core.catalog_identity import validate_snapshot_groups
                    product_rows = [dict(zip(
                        ("public_product_id", "unified_category_id", "attributes"), row
                    )) for row in connection.execute(
                        "SELECT public_product_id, unified_category_id, attributes "
                        "FROM normalized_canonical_products"
                    )]
                    meta["reviewed_groups_compatible"] = validate_snapshot_groups(product_rows)
            if "snapshot_meta" in tables:
                row = connection.execute(
                    "SELECT revision, built_at FROM snapshot_meta WHERE id=1"
                ).fetchone()
                if row:
                    meta.update(revision=row[0], built_at=row[1])
            return {"tables": sorted(tables), **meta}
        finally:
            connection.close()
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"snapshot 검증 실패: {exc}") from exc


def _replace_with_retry(source: Path, target: Path, *, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.05)


@contextmanager
def _snapshot_lock(target: Path, *, timeout: float = 5.0):
    """Serialize local workers using a persistent per-target OS lock file."""
    target = target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target.with_suffix(target.suffix + ".snapshot.lock")
    with lock_path.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            def acquire():
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            def release():
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            def acquire():
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            def release():
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        deadline = time.monotonic() + timeout
        while True:
            try:
                acquire()
                break
            except (BlockingIOError, PermissionError):
                if time.monotonic() >= deadline:
                    raise HTTPException(status_code=503, detail="snapshot 교체 작업이 진행 중입니다")
                time.sleep(0.05)
        try:
            yield
        finally:
            release()
    # Never unlink the lock file: another worker may already hold its inode.


def _snapshot_copy(source: Path, target: Path, role: str) -> Path:
    """Prepare a synced same-filesystem copy without moving a reader's path."""
    descriptor, name = tempfile.mkstemp(prefix=target.name + f".{role}-", dir=target.parent)
    copied = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as output, source.open("rb") as input_file:
            shutil.copyfileobj(input_file, output)
            output.flush()
            os.fsync(output.fileno())
        return copied
    except BaseException:
        copied.unlink(missing_ok=True)
        raise


def _install_snapshot_locked(uploading: Path, target: Path) -> Path | None:
    previous = target.with_suffix(target.suffix + ".previous")
    backup = _snapshot_copy(target, target, "previous") if target.is_file() else None
    retain_backup = False
    try:
        # Readers keep the old inode until replacement, then open the complete
        # candidate. Never rename current away before installing its successor.
        _replace_with_retry(uploading, target)
        if backup is not None:
            try:
                _replace_with_retry(backup, previous)
            except Exception:
                try:
                    _replace_with_retry(backup, target)
                except Exception:
                    # Keep the old valid copy if the recovery rename also
                    # fails. Do not claim success or discard recovery evidence.
                    retain_backup = True
                    raise
                raise
        return previous if backup is not None else None
    finally:
        if backup is not None and not retain_backup:
            backup.unlink(missing_ok=True)


def _install_uploaded_snapshot(uploading: Path, target: Path) -> Path | None:
    with _snapshot_lock(target):
        return _install_snapshot_locked(uploading, target)


def _complete_uploaded_snapshot(uploading: Path, target: Path, required_tables: set[str]):
    # The worker owns the completed file until validation/replacement finishes.
    # An HTTP task cancellation must not unlink a file it is still using.
    try:
        validation = _validate_sqlite(uploading, required_tables)
        previous = _install_uploaded_snapshot(uploading, target)
        return validation, previous
    finally:
        uploading.unlink(missing_ok=True)


@router.put("/snapshots/{kind}", dependencies=[Depends(require_remote_admin)])
async def upload_snapshot(request: Request, kind: str):
    target, required_tables = _snapshot_target(kind)
    target.parent.mkdir(parents=True, exist_ok=True)
    max_bytes = int(os.getenv("WALLETSAVIOR_SNAPSHOT_MAX_BYTES", str(512 * 1024 * 1024)))
    descriptor, name = tempfile.mkstemp(prefix=target.name + ".uploading-", dir=target.parent)
    uploading = Path(name)
    written = 0
    work = None

    try:
        with os.fdopen(descriptor, "wb") as handle:
            async for chunk in request.stream():
                if not chunk:
                    continue
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(status_code=413, detail="snapshot 파일이 허용 크기를 초과했습니다")
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())

        if written == 0:
            raise HTTPException(status_code=400, detail="빈 snapshot 파일은 업로드할 수 없습니다")

        work = asyncio.create_task(run_in_threadpool(
            _complete_uploaded_snapshot, uploading, target, required_tables,
        ))
        # Anyio shields its own cancellation scopes by default, but native
        # asyncio cancellation can still interrupt the threadpool await. Keep
        # the offload task alive and its file ownership independent of that.
        work.add_done_callback(lambda task: None if task.cancelled() else task.exception())
        try:
            validation, previous = await asyncio.shield(work)
        except asyncio.CancelledError:
            try:
                await asyncio.shield(work)
            except (Exception, asyncio.CancelledError):
                pass
            raise
        return {
            "ok": True,
            "kind": kind,
            "path": str(target),
            "bytes": written,
            "validation": validation,
            "previous_path": str(previous) if previous else None,
        }
    finally:
        if work is None and uploading.exists():
            uploading.unlink(missing_ok=True)


@router.get("/snapshots/{kind}", dependencies=[Depends(require_remote_admin)])
def snapshot_status(kind: str):
    target, required_tables = _snapshot_target(kind)
    previous = target.with_suffix(target.suffix + ".previous")
    with _snapshot_lock(target):
        return {
            "kind": kind,
            "current": _validate_sqlite(target, required_tables) if target.is_file() else None,
            "rollback": _validate_sqlite(previous, required_tables) if previous.is_file() else None,
        }


@router.post("/snapshots/{kind}/rollback", dependencies=[Depends(require_remote_admin)])
def rollback_snapshot(kind: str):
    target, required_tables = _snapshot_target(kind)
    previous = target.with_suffix(target.suffix + ".previous")
    with _snapshot_lock(target):
        if not previous.is_file():
            raise HTTPException(status_code=409, detail="되돌릴 snapshot이 없습니다")
        validation = _validate_sqlite(previous, required_tables)
        candidate = _snapshot_copy(previous, target, "rollback")
        try:
            _install_snapshot_locked(candidate, target)
        finally:
            candidate.unlink(missing_ok=True)
    return {"ok": True, "kind": kind, "validation": validation}
