"""Server-side management endpoints used by the local DB Admin.

These endpoints deliberately live in web-api because only web-api is deployed.
The local db-admin sends authenticated commands; it never opens server SQLite
files directly.
"""
from __future__ import annotations

import hmac
import os
import sqlite3
from pathlib import Path
from typing import Iterable

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy import func, text

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

_SNAPSHOT_CONFIG = {
    "catalog": (
        "WALLETSAVIOR_PUBLIC_DB",
        _DEFAULT_CATALOG_DB,
        {"products", "categories", "unified_categories", "snapshot_meta"},
    ),
    "external-hotdeals": (
        "WALLETSAVIOR_EXTERNAL_HOTDEAL_DB",
        _DEFAULT_EXTERNAL_HOTDEAL_DB,
        {"hotdeal_posts"},
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
            meta = {}
            if "snapshot_meta" in tables:
                row = connection.execute(
                    "SELECT revision, built_at FROM snapshot_meta WHERE id=1"
                ).fetchone()
                if row:
                    meta = {"revision": row[0], "built_at": row[1]}
            return {"tables": sorted(tables), **meta}
        finally:
            connection.close()
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"snapshot 검증 실패: {exc}") from exc


@router.put("/snapshots/{kind}", dependencies=[Depends(require_remote_admin)])
async def upload_snapshot(request: Request, kind: str):
    target, required_tables = _snapshot_target(kind)
    target.parent.mkdir(parents=True, exist_ok=True)
    uploading = target.with_suffix(target.suffix + ".uploading")
    max_bytes = int(os.getenv("WALLETSAVIOR_SNAPSHOT_MAX_BYTES", str(512 * 1024 * 1024)))
    written = 0

    try:
        with uploading.open("wb") as handle:
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

        validation = _validate_sqlite(uploading, required_tables)
        os.replace(uploading, target)
        return {
            "ok": True,
            "kind": kind,
            "path": str(target),
            "bytes": written,
            "validation": validation,
        }
    finally:
        if uploading.exists():
            uploading.unlink(missing_ok=True)
