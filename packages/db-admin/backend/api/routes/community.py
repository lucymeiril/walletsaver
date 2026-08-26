"""Community moderation across the main user DB and isolated board SQLite DB."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from api.auth import require_moderator, require_viewer
from services import community_board_store as board_store
from services.base import get_session
from storage.models import User

router = APIRouter(prefix="/community", tags=["community"])
logger = logging.getLogger(__name__)


def _storage_error(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=f"게시판 저장소를 사용할 수 없습니다: {exc}",
    )


def _set_authoritative_user_active(user_id: int, active: bool) -> dict | None:
    """Update the main users table, which is the public authentication authority."""
    session = get_session()
    try:
        user = session.get(User, user_id)
        if user is None:
            return None
        if active and user.is_deleted:
            raise HTTPException(status_code=409, detail="삭제된 계정은 정지 해제할 수 없습니다")

        user.is_active = active
        session.commit()
        session.refresh(user)
        role = user.role.value if hasattr(user.role, "value") else str(user.role or "user")
        return {
            "id": user.id,
            "email": user.email,
            "nickname": user.nickname,
            "role": role,
            "is_active": bool(user.is_active),
            "is_deleted": bool(user.is_deleted),
        }
    except HTTPException:
        session.rollback()
        raise
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _sync_board_user_active(user_id: int, active: bool) -> None:
    """Best-effort mirror update for community ownership/display state."""
    try:
        board_store.set_user_active(user_id, active)
    except Exception:
        # The main user DB is authoritative. A user may not have a board mirror yet.
        logger.exception("Failed to mirror user active state to community DB: user_id=%s", user_id)


@router.get("/posts")
def list_posts(
    status: str = Query("active", pattern="^(active|deleted|all|reported)$"),
    post_type: str | None = Query(None),
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    identity: dict = Depends(require_viewer),
):
    try:
        return board_store.list_posts(
            status=status,
            post_type=post_type,
            search=search,
            page=page,
            per_page=per_page,
        )
    except Exception as exc:
        raise _storage_error(exc) from exc


@router.get("/posts/{post_id}")
def get_post_detail(post_id: int, identity: dict = Depends(require_viewer)):
    try:
        result = board_store.get_post(post_id)
    except Exception as exc:
        raise _storage_error(exc) from exc
    if result is None:
        raise HTTPException(404, "Post not found")
    return result


@router.delete("/posts/{post_id}")
def delete_post(post_id: int, request: Request, identity: dict = Depends(require_moderator)):
    try:
        changed = board_store.set_post_deleted(post_id, True)
    except Exception as exc:
        raise _storage_error(exc) from exc
    if not changed:
        raise HTTPException(404, "Post not found")
    return {"deleted": True, "id": post_id}


@router.post("/posts/{post_id}/restore")
def restore_post(post_id: int, request: Request, identity: dict = Depends(require_moderator)):
    try:
        changed = board_store.set_post_deleted(post_id, False)
    except Exception as exc:
        raise _storage_error(exc) from exc
    if not changed:
        raise HTTPException(404, "Post not found")
    return {"restored": True, "id": post_id}


@router.delete("/comments/{comment_id}")
def delete_comment(comment_id: int, request: Request, identity: dict = Depends(require_moderator)):
    try:
        changed = board_store.set_comment_deleted(comment_id, True)
    except Exception as exc:
        raise _storage_error(exc) from exc
    if not changed:
        raise HTTPException(404, "Comment not found")
    return {"deleted": True, "id": comment_id}


@router.post("/comments/{comment_id}/restore")
def restore_comment(comment_id: int, request: Request, identity: dict = Depends(require_moderator)):
    try:
        changed = board_store.set_comment_deleted(comment_id, False)
    except Exception as exc:
        raise _storage_error(exc) from exc
    if not changed:
        raise HTTPException(404, "Comment not found")
    return {"restored": True, "id": comment_id}


@router.post("/users/{user_id}/ban")
def ban_user(user_id: int, request: Request, identity: dict = Depends(require_moderator)):
    try:
        user = _set_authoritative_user_active(user_id, False)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="회원 저장소를 사용할 수 없습니다") from exc
    if user is None:
        raise HTTPException(404, "User not found")

    _sync_board_user_active(user_id, False)
    return {"banned": True, "user": user}


@router.post("/users/{user_id}/unban")
def unban_user(user_id: int, request: Request, identity: dict = Depends(require_moderator)):
    try:
        user = _set_authoritative_user_active(user_id, True)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="회원 저장소를 사용할 수 없습니다") from exc
    if user is None:
        raise HTTPException(404, "User not found")

    _sync_board_user_active(user_id, True)
    return {"unbanned": True, "user": user}
