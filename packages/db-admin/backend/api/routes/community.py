"""Community moderation surfaces for DB Admin."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_

from api.auth import require_viewer, require_moderator
from api.security import escape_like
from services.base import get_session, managed_session
from storage.models import Comment, Post, PostType, User, Vote

router = APIRouter(prefix="/community", tags=["community"])


def _post_row(session, post: Post) -> dict:
    author = post.author.nickname if post.author else None
    comments = session.query(func.count(Comment.id)).filter(Comment.post_id == post.id).scalar() or 0
    votes = session.query(func.count(Vote.id)).filter(Vote.post_id == post.id).scalar() or 0
    return {
        "id": post.id,
        "title": post.title,
        "content": post.content,
        "post_type": post.post_type.value if hasattr(post.post_type, "value") else post.post_type,
        "author_id": post.author_id,
        "author": author,
        "category_id": post.category_id,
        "custom_category": post.custom_category,
        "product_id": post.product_id,
        "deal_price": post.deal_price,
        "deal_url": post.deal_url,
        "tags": post.tags or [],
        "view_count": post.view_count,
        "comment_count": comments,
        "vote_count": votes,
        "is_pinned": post.is_pinned,
        "is_deleted": post.is_deleted,
        "created_at": post.created_at.isoformat() if post.created_at else None,
        "updated_at": post.updated_at.isoformat() if post.updated_at else None,
    }


def _comment_row(comment: Comment) -> dict:
    author = comment.author.nickname if comment.author else None
    return {
        "id": comment.id,
        "post_id": comment.post_id,
        "parent_id": comment.parent_id,
        "content": comment.content,
        "author_id": comment.author_id,
        "author": author,
        "is_deleted": comment.is_deleted,
        "created_at": comment.created_at.isoformat() if comment.created_at else None,
        "updated_at": comment.updated_at.isoformat() if comment.updated_at else None,
    }


@router.get("/posts")
def list_posts(
    status: str = Query("active", pattern="^(active|deleted|all|reported)$"),
    post_type: str | None = Query(None),
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    identity: dict = Depends(require_viewer),
):
    """List community posts for moderation.

    The current schema has no report table. ``reported`` therefore returns an
    empty list plus a note, while active/deleted/all support deletion workflows.
    """
    if status == "reported":
        return {
            "items": [],
            "total": 0,
            "page": page,
            "per_page": per_page,
            "total_pages": 1,
            "note": "신고 테이블이 없어 신고된 게시글 필터는 아직 데이터가 없습니다.",
        }

    session = get_session()
    try:
        query = session.query(Post).outerjoin(User, Post.author_id == User.id)
        if status == "active":
            query = query.filter(Post.is_deleted == False)
        elif status == "deleted":
            query = query.filter(Post.is_deleted == True)
        if post_type:
            try:
                query = query.filter(Post.post_type == PostType(post_type))
            except ValueError:
                raise HTTPException(400, "Invalid post_type")
        if search:
            like = f"%{escape_like(search)}%"
            query = query.filter(or_(Post.title.ilike(like), Post.content.ilike(like), User.nickname.ilike(like)))

        total = query.count()
        posts = (
            query.order_by(Post.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )
        return {
            "items": [_post_row(session, p) for p in posts],
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": max(1, (total + per_page - 1) // per_page),
        }
    finally:
        session.close()


@router.get("/posts/{post_id}")
def get_post_detail(post_id: int, identity: dict = Depends(require_viewer)):
    """Return full post content and comments for moderation review."""
    session = get_session()
    try:
        post = session.get(Post, post_id)
        if not post:
            raise HTTPException(404, "Post not found")
        comments = (
            session.query(Comment)
            .outerjoin(User, Comment.author_id == User.id)
            .filter(Comment.post_id == post_id)
            .order_by(Comment.created_at.asc(), Comment.id.asc())
            .all()
        )
        return {
            "post": _post_row(session, post),
            "comments": [_comment_row(comment) for comment in comments],
        }
    finally:
        session.close()


@router.delete("/posts/{post_id}")
def delete_post(post_id: int, request: Request, identity: dict = Depends(require_moderator)):
    """Soft-delete a community post."""
    with managed_session() as session:
        post = session.get(Post, post_id)
        if not post:
            raise HTTPException(404, "Post not found")
        post.is_deleted = True
        return {"deleted": True, "id": post_id}


@router.post("/posts/{post_id}/restore")
def restore_post(post_id: int, request: Request, identity: dict = Depends(require_moderator)):
    """Restore a soft-deleted community post."""
    with managed_session() as session:
        post = session.get(Post, post_id)
        if not post:
            raise HTTPException(404, "Post not found")
        post.is_deleted = False
        return {"restored": True, "id": post_id}


@router.delete("/comments/{comment_id}")
def delete_comment(comment_id: int, request: Request, identity: dict = Depends(require_moderator)):
    """Soft-delete a community comment."""
    with managed_session() as session:
        comment = session.get(Comment, comment_id)
        if not comment:
            raise HTTPException(404, "Comment not found")
        comment.is_deleted = True
        return {"deleted": True, "id": comment_id}


@router.post("/comments/{comment_id}/restore")
def restore_comment(comment_id: int, request: Request, identity: dict = Depends(require_moderator)):
    """Restore a soft-deleted community comment."""
    with managed_session() as session:
        comment = session.get(Comment, comment_id)
        if not comment:
            raise HTTPException(404, "Comment not found")
        comment.is_deleted = False
        return {"restored": True, "id": comment_id}
