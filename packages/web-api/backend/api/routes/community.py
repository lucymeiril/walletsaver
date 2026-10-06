"""Community API backed only by the isolated board SQLite database.

Authentication identity comes from the server-owned accounts.sqlite database.
community_users contains a minimal mirror with the same numeric id so board
foreign keys remain isolated without inventing a second account authority.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field
from sqlalchemy import case, desc, func, text
from sqlalchemy.orm import joinedload, selectinload

from api.middleware.auth import get_current_user, require_auth
from api.schemas.common import ApiResponse, PaginationMeta
from api.schemas.community import CommentCreate, PostCreate, PostUpdate, VoteRequest
from services.board_storage import (
    Comment as CommentModel,
    Post as PostModel,
    PostType as DBPostType,
    User as UserModel,
    Vote as VoteModel,
    VoteType as DBVoteType,
    get_board_session_factory,
)

router = APIRouter()
logger = logging.getLogger(__name__)


class CommunityListResponse(ApiResponse):
    pinned_posts: list[dict] = Field(default_factory=list)


def _session_factory():
    try:
        return get_board_session_factory()
    except Exception as exc:
        logger.exception("Community board DB unavailable")
        raise HTTPException(status_code=503, detail="게시판 저장소를 사용할 수 없습니다") from exc


def _ensure_user(session, user: dict) -> UserModel:
    """Mirror an accounts.sqlite user into board.sqlite without reusing another owner id."""
    user_id = int(user["id"])
    email = (user.get("email") or "").strip().lower()
    nickname = (user.get("nickname") or "").strip() or f"user{user_id}"

    existing = session.get(UserModel, user_id)
    if existing is not None:
        # Never overwrite a board owner with a different e-mail. If account ids
        # ever diverge, explicit migration is safer than transferring old posts.
        if email and existing.email.strip().lower() != email:
            raise HTTPException(
                status_code=409,
                detail="기존 게시판 사용자 ID와 현재 계정이 충돌합니다. 게시판 데이터 마이그레이션이 필요합니다.",
            )
        if existing.is_deleted or existing.is_active is False:
            raise HTTPException(status_code=403, detail="커뮤니티 이용이 제한된 계정입니다")
        if nickname and existing.nickname != nickname:
            existing.nickname = nickname
            session.flush()
        return existing

    if email:
        same_email = session.query(UserModel).filter(UserModel.email == email).first()
        if same_email is not None and same_email.id != user_id:
            raise HTTPException(
                status_code=409,
                detail="기존 게시판 계정과 현재 회원 ID가 일치하지 않습니다. 게시판 데이터 마이그레이션이 필요합니다.",
            )

    mirror = UserModel(
        id=user_id,
        email=email or f"user-{user_id}@mirror.walletsavior.local",
        nickname=nickname,
        is_active=True,
        is_deleted=False,
    )
    session.add(mirror)
    session.flush()
    return mirror


def _raise_if_banned(session, user: dict) -> None:
    board_user = session.get(UserModel, int(user["id"]))
    if board_user is None:
        raise HTTPException(status_code=401, detail="게시판 사용자 정보가 없습니다")
    if board_user.is_active is False or board_user.is_deleted:
        raise HTTPException(status_code=403, detail="커뮤니티 이용이 제한된 계정입니다")


def _post_to_dict(post: PostModel, user_id: int | None = None) -> dict:
    hot = sum(1 for vote in post.votes if vote.vote_type == DBVoteType.HOT)
    not_ = sum(1 for vote in post.votes if vote.vote_type == DBVoteType.NOT)
    comments_count = sum(1 for comment in post.comments if not comment.is_deleted)
    author_nickname = post.author.nickname if post.author else f"user{post.author_id}"
    is_free = post.post_type == DBPostType.FREE
    return {
        "id": post.id,
        "title": post.title,
        "content": post.content,
        "post_type": post.post_type.value if post.post_type else "free",
        "category": post.custom_category or (post.category_id or ""),
        "tags": [post.custom_category] if is_free and post.custom_category else [],
        "images": [],
        "author_id": post.author_id,
        "author_nickname": author_nickname,
        "views": post.view_count,
        "comments_count": comments_count,
        "hot_votes": hot,
        "not_votes": not_,
        # Totals cannot identify a caller's selection. Only the validated
        # account subject may select its own existing vote, including cold GETs.
        "user_vote": next((vote.vote_type.value for vote in post.votes
                           if user_id is not None and vote.user_id == user_id), None),
        "price": post.deal_price,
        "original_price": post.original_price,
        "url": post.deal_url,
        "created_at": post.created_at.isoformat() if post.created_at else "",
        "updated_at": post.updated_at.isoformat() if post.updated_at else "",
    }


def _comment_to_dict(comment: CommentModel) -> dict:
    author_nickname = comment.author.nickname if comment.author else f"user{comment.author_id}"
    return {
        "id": comment.id,
        "content": comment.content,
        "author_id": comment.author_id,
        "author_nickname": author_nickname,
        "parent_id": comment.parent_id,
        "created_at": comment.created_at.isoformat() if comment.created_at else "",
    }


@router.get("")
async def list_posts(
    post_type: str = Query(None, description="게시글 유형 (hotdeal, free, qna, tip)"),
    category: str = Query(None, description="카테고리"),
    sort: str = Query("recent", description="정렬 (recent, popular, comments)"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    q: str | None = Query(None, description="제목/내용 검색"),
    partition_pinned: bool = Query(False, description="핫딜 인기글을 일반 목록에서 분리"),
    user: dict | None = Depends(get_current_user),
):
    factory = _session_factory()
    with factory() as session:
        # SQLite's legacy transaction mode does not begin a transaction for
        # SELECT alone. Keep pins, totals, rows and relationship counts in the
        # same read snapshot, including concurrent votes/comments/deletions.
        session.execute(text("BEGIN"))
        query = session.query(PostModel).filter(PostModel.is_deleted.is_(False))
        if post_type:
            try:
                query = query.filter(PostModel.post_type == DBPostType(post_type))
            except ValueError:
                pass
        if category:
            query = query.filter(
                (PostModel.custom_category == category) | (PostModel.category_id == category)
            )

        search = (q or "").strip()
        if search:
            query = query.filter(
                PostModel.title.icontains(search, autoescape=True)
                | PostModel.content.icontains(search, autoescape=True)
            )

        partition = partition_pinned and post_type == "hotdeal" and not search
        if partition or (sort == "popular" and post_type == "hotdeal"):
            votes = (
                session.query(
                    VoteModel.post_id,
                    func.sum(case((VoteModel.vote_type == DBVoteType.HOT, 1), else_=0)).label("hot"),
                    func.sum(case((VoteModel.vote_type == DBVoteType.NOT, 1), else_=0)).label("not_"),
                )
                .group_by(VoteModel.post_id)
                .subquery()
            )
            query = query.outerjoin(votes, votes.c.post_id == PostModel.id)
            net_votes = func.coalesce(votes.c.hot, 0) - func.coalesce(votes.c.not_, 0)

        # Load only the bounded result rows' related data, avoiding one query
        # per post while retaining the existing serialized vote/comment fields.
        query = query.options(
            joinedload(PostModel.author),
            selectinload(PostModel.votes),
            selectinload(PostModel.comments),
        )
        pinned = []
        if partition:
            pinned = query.filter(votes.c.hot > 0).order_by(
                desc(net_votes), desc(PostModel.created_at), desc(PostModel.id)
            ).limit(3).all()
            if pinned:
                query = query.filter(PostModel.id.notin_([post.id for post in pinned]))

        total = query.count()
        if sort == "popular":
            popularity = net_votes if post_type == "hotdeal" else PostModel.view_count
            query = query.order_by(desc(popularity), desc(PostModel.created_at), desc(PostModel.id))
        elif sort == "comments":
            counts = (
                session.query(CommentModel.post_id, func.count(CommentModel.id).label("comment_count"))
                .filter(CommentModel.is_deleted.is_(False))
                .group_by(CommentModel.post_id)
                .subquery()
            )
            query = query.outerjoin(counts, counts.c.post_id == PostModel.id).order_by(
                desc(func.coalesce(counts.c.comment_count, 0)), desc(PostModel.created_at), desc(PostModel.id)
            )
        else:
            query = query.order_by(desc(PostModel.created_at), desc(PostModel.id))

        posts = query.offset((page - 1) * per_page).limit(per_page).all()
        return CommunityListResponse(
            data=[_post_to_dict(post, int(user["id"]) if user else None) for post in posts],
            pinned_posts=[_post_to_dict(post, int(user["id"]) if user else None) for post in pinned],
            meta=PaginationMeta(
                page=page,
                per_page=per_page,
                total=total,
                total_pages=math.ceil(total / per_page) if total else 0,
            ),
        )


@router.post("")
async def create_post(body: PostCreate, user: dict = Depends(require_auth)):
    if body.images:
        raise HTTPException(status_code=422, detail="커뮤니티 이미지 첨부 저장은 아직 지원되지 않습니다")

    factory = _session_factory()
    with factory() as session:
        _ensure_user(session, user)
        _raise_if_banned(session, user)
        try:
            post_type = DBPostType(body.post_type.value)
        except ValueError:
            post_type = DBPostType.FREE

        custom_category = body.category
        if post_type == DBPostType.FREE and body.tags:
            custom_category = next((str(tag).strip() for tag in body.tags if str(tag).strip()), None)

        post = PostModel(
            author_id=int(user["id"]),
            post_type=post_type,
            title=body.title,
            content=body.content,
            custom_category=custom_category,
            deal_price=body.price,
            original_price=body.original_price,
            deal_url=body.url,
        )
        session.add(post)
        session.commit()
        session.refresh(post)
        return ApiResponse(data=_post_to_dict(post, int(user["id"])))


@router.get("/{post_id}")
async def get_post(post_id: int, user: dict | None = Depends(get_current_user)):
    factory = _session_factory()
    with factory() as session:
        post = session.get(PostModel, post_id)
        if not post or post.is_deleted:
            raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다")
        post.view_count += 1
        session.commit()
        session.refresh(post)
        return ApiResponse(data=_post_to_dict(post, int(user["id"]) if user else None))


@router.put("/{post_id}")
async def update_post(post_id: int, body: PostUpdate, user: dict = Depends(require_auth)):
    factory = _session_factory()
    with factory() as session:
        post = session.get(PostModel, post_id)
        if not post or post.is_deleted:
            raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다")
        if post.author_id != int(user["id"]):
            raise HTTPException(status_code=403, detail="수정 권한이 없습니다")
        _ensure_user(session, user)
        _raise_if_banned(session, user)

        fields = body.model_fields_set
        if "title" in fields and body.title is not None:
            post.title = body.title
        if "content" in fields and body.content is not None:
            post.content = body.content
        if "category" in fields:
            post.custom_category = body.category
        if "tags" in fields and post.post_type == DBPostType.FREE:
            post.custom_category = next(
                (str(tag).strip() for tag in (body.tags or []) if str(tag).strip()),
                None,
            )
        if "price" in fields:
            post.deal_price = body.price
        if "original_price" in fields:
            post.original_price = body.original_price
        if "url" in fields:
            post.deal_url = body.url
        post.updated_at = datetime.utcnow()
        session.commit()
        session.refresh(post)
        return ApiResponse(data=_post_to_dict(post, int(user["id"])))


@router.delete("/{post_id}")
async def delete_post(post_id: int, user: dict = Depends(require_auth)):
    factory = _session_factory()
    with factory() as session:
        post = session.get(PostModel, post_id)
        if not post or post.is_deleted:
            raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다")
        if post.author_id != int(user["id"]) and user.get("role") not in ("admin", "moderator"):
            raise HTTPException(status_code=403, detail="삭제 권한이 없습니다")
        _ensure_user(session, user)
        _raise_if_banned(session, user)
        post.is_deleted = True
        post.updated_at = datetime.utcnow()
        session.commit()
        return ApiResponse(data={"id": post_id, "status": "deleted"})


@router.post("/{post_id}/comments")
async def create_comment(post_id: int, body: CommentCreate, user: dict = Depends(require_auth)):
    factory = _session_factory()
    with factory() as session:
        post = session.get(PostModel, post_id)
        if not post or post.is_deleted:
            raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다")
        _ensure_user(session, user)
        _raise_if_banned(session, user)
        if body.parent_id is not None:
            parent = session.get(CommentModel, body.parent_id)
            if parent is None or parent.post_id != post_id or parent.is_deleted:
                raise HTTPException(status_code=400, detail="유효하지 않은 부모 댓글입니다")
        comment = CommentModel(
            post_id=post_id,
            author_id=int(user["id"]),
            content=body.content,
            parent_id=body.parent_id,
        )
        session.add(comment)
        session.commit()
        session.refresh(comment)
        return ApiResponse(data=_comment_to_dict(comment))


@router.get("/{post_id}/comments")
async def list_comments(post_id: int):
    factory = _session_factory()
    with factory() as session:
        post = session.get(PostModel, post_id)
        if not post or post.is_deleted:
            raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다")
        comments = (
            session.query(CommentModel)
            .filter(CommentModel.post_id == post_id, CommentModel.is_deleted.is_(False))
            .order_by(CommentModel.created_at)
            .all()
        )
        return ApiResponse(data=[_comment_to_dict(comment) for comment in comments])


@router.post("/{post_id}/vote")
async def vote_post(post_id: int, body: VoteRequest, user: dict = Depends(require_auth)):
    if body.vote_type not in ("hot", "not"):
        raise HTTPException(status_code=400, detail="vote_type은 'hot' 또는 'not'이어야 합니다")

    factory = _session_factory()
    with factory() as session:
        post = session.get(PostModel, post_id)
        if not post or post.is_deleted:
            raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다")
        _ensure_user(session, user)
        _raise_if_banned(session, user)
        existing = session.query(VoteModel).filter(
            VoteModel.post_id == post_id,
            VoteModel.user_id == int(user["id"]),
        ).first()
        new_vote = DBVoteType.HOT if body.vote_type == "hot" else DBVoteType.NOT
        user_vote = body.vote_type
        if existing and existing.vote_type == new_vote:
            session.delete(existing)
            user_vote = None
        elif existing:
            existing.vote_type = new_vote
        else:
            session.add(VoteModel(post_id=post_id, user_id=int(user["id"]), vote_type=new_vote))
        session.commit()
        session.refresh(post)
        data = _post_to_dict(post)
        return ApiResponse(data={
            "post_id": post_id,
            "hot_votes": data["hot_votes"],
            "not_votes": data["not_votes"],
            "user_vote": user_vote,
        })


@router.get("/{post_id}/suggested-tier")
async def suggested_tier(post_id: int):
    factory = _session_factory()
    with factory() as session:
        post = session.get(PostModel, post_id)
        if not post or post.is_deleted:
            raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다")
        price = post.deal_price
        original = post.original_price

    if price and original and original > 0:
        ratio = price / original
        if ratio <= 0.3:
            tier = "ultra"
        elif ratio <= 0.5:
            tier = "great"
        elif ratio <= 0.7:
            tier = "good"
        else:
            tier = "wait"
    else:
        tier = "unknown"

    return ApiResponse(data={
        "post_id": post_id,
        "suggested_tier": tier,
        "price": price,
        "original_price": original,
        "discount_rate": round((1 - price / original) * 100, 1)
        if price and original and original > 0 else None,
    })
