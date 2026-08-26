"""Local DB Admin facade for server-owned community moderation."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import require_moderator, require_viewer
from services import remote_web_admin

router = APIRouter(prefix="/community", tags=["community"])


def _remote_error(exc: Exception) -> HTTPException:
    if isinstance(exc, remote_web_admin.RemoteWebAdminError):
        return HTTPException(status_code=exc.status_code, detail=str(exc))
    return HTTPException(status_code=503, detail=f"원격 웹 관리 API를 사용할 수 없습니다: {exc}")


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
        return remote_web_admin.list_community_posts(
            status=status,
            post_type=post_type,
            search=search,
            page=page,
            per_page=per_page,
        )
    except Exception as exc:
        raise _remote_error(exc) from exc


@router.get("/posts/{post_id}")
def get_post_detail(post_id: int, identity: dict = Depends(require_viewer)):
    try:
        return remote_web_admin.get_community_post(post_id)
    except Exception as exc:
        raise _remote_error(exc) from exc


@router.delete("/posts/{post_id}")
def delete_post(post_id: int, identity: dict = Depends(require_moderator)):
    try:
        return remote_web_admin.delete_community_post(post_id)
    except Exception as exc:
        raise _remote_error(exc) from exc


@router.post("/posts/{post_id}/restore")
def restore_post(post_id: int, identity: dict = Depends(require_moderator)):
    try:
        return remote_web_admin.restore_community_post(post_id)
    except Exception as exc:
        raise _remote_error(exc) from exc


@router.delete("/comments/{comment_id}")
def delete_comment(comment_id: int, identity: dict = Depends(require_moderator)):
    try:
        return remote_web_admin.delete_community_comment(comment_id)
    except Exception as exc:
        raise _remote_error(exc) from exc


@router.post("/comments/{comment_id}/restore")
def restore_comment(comment_id: int, identity: dict = Depends(require_moderator)):
    try:
        return remote_web_admin.restore_community_comment(comment_id)
    except Exception as exc:
        raise _remote_error(exc) from exc


@router.post("/users/{user_id}/ban")
def ban_user(user_id: int, identity: dict = Depends(require_moderator)):
    try:
        return remote_web_admin.ban_community_user(user_id)
    except Exception as exc:
        raise _remote_error(exc) from exc


@router.post("/users/{user_id}/unban")
def unban_user(user_id: int, identity: dict = Depends(require_moderator)):
    try:
        return remote_web_admin.unban_community_user(user_id)
    except Exception as exc:
        raise _remote_error(exc) from exc
