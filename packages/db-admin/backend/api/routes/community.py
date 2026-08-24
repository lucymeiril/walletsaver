"""Community moderation surfaces backed by the isolated board SQLite DB."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from api.auth import require_moderator, require_viewer
from services import community_board_store as board_store

router = APIRouter(prefix="/community", tags=["community"])


def _storage_error(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=f"게시판 저장소를 사용할 수 없습니다: {exc}",
    )


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
        user = board_store.set_user_active(user_id, False)
    except Exception as exc:
        raise _storage_error(exc) from exc
    if user is None:
        raise HTTPException(404, "User not found")
    return {"banned": True, "user": user}


@router.post("/users/{user_id}/unban")
def unban_user(user_id: int, request: Request, identity: dict = Depends(require_moderator)):
    try:
        user = board_store.set_user_active(user_id, True)
    except Exception as exc:
        raise _storage_error(exc) from exc
    if user is None:
        raise HTTPException(404, "User not found")
    return {"unbanned": True, "user": user}
