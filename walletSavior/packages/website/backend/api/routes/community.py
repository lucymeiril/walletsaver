"""
커뮤니티 API — 게시글, 댓글, 투표. DB 기반으로 동작.

엔드포인트:
    GET    /api/posts                    — 게시글 목록
    POST   /api/posts                    — 게시글 작성 (인증 필요)
    GET    /api/posts/{id}               — 게시글 상세
    PUT    /api/posts/{id}               — 게시글 수정 (작성자만)
    DELETE /api/posts/{id}               — 게시글 삭제 (작성자 또는 관리자)
    POST   /api/posts/{id}/comments      — 댓글 작성 (인증 필요)
    GET    /api/posts/{id}/comments      — 댓글 목록
    POST   /api/posts/{id}/vote          — 핫딜 투표 (인증 필요)
    GET    /api/posts/{id}/suggested-tier — 핫딜 적정가 제안
"""

import os
import sys
import math
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException, Depends, Query
from api.schemas.common import ApiResponse, PaginationMeta
from api.schemas.community import PostCreate, PostUpdate, CommentCreate, VoteRequest
from api.middleware.auth import require_auth, get_current_user
from api.utils.cache import TTLCache

router = APIRouter()

# TTL cache for post listings (30s)
_posts_list_cache = TTLCache(ttl_seconds=30, max_size=64)

# ── DB 연결 설정 ──
_db_admin_path = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..", "db-admin", "backend"
))
if _db_admin_path not in sys.path:
    sys.path.insert(0, _db_admin_path)

_db_engine = None
_SessionLocal = None
_use_db = False

try:
    from storage.models import (
        Base,
        Post as PostModel,
        PostImage as PostImageModel,
        Comment as CommentModel,
        Vote as VoteModel,
        User as UserModel,
        PostType as DBPostType,
        VoteType as DBVoteType,
    )
    from sqlalchemy import create_engine, func, desc
    from sqlalchemy.orm import sessionmaker

    _db_path = os.path.join(_db_admin_path, "walletguardian.db")
    _db_engine = create_engine(
        f"sqlite:///{_db_path}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(_db_engine)
    _SessionLocal = sessionmaker(bind=_db_engine)

    _use_db = True
except Exception as _e:
    import logging
    logging.warning(f"커뮤니티 DB 연결 실패: {_e}")
    _use_db = False


def _post_to_dict(post: "PostModel") -> dict:
    """SQLAlchemy Post → API dict."""
    hot = sum(1 for v in post.votes if v.vote_type == DBVoteType.HOT)
    not_ = sum(1 for v in post.votes if v.vote_type == DBVoteType.NOT)
    author_nickname = post.author.nickname if post.author else f"user{post.author_id}"
    return {
        "id": post.id,
        "title": post.title,
        "content": post.content,
        "post_type": post.post_type.value if post.post_type else "free",
        "category": post.custom_category or (post.category_id or ""),
        "author_id": post.author_id,
        "author_nickname": author_nickname,
        "views": post.view_count,
        "comments_count": len(post.comments),
        "hot_votes": hot,
        "not_votes": not_,
        "price": post.deal_price,
        "original_price": None,
        "url": post.deal_url,
        "images": [img.image_url for img in post.images] if post.images else [],
        "created_at": post.created_at.isoformat() if post.created_at else "",
        "updated_at": post.updated_at.isoformat() if post.updated_at else "",
    }


def _comment_to_dict(comment: "CommentModel") -> dict:
    """SQLAlchemy Comment → API dict."""
    author_nickname = comment.author.nickname if comment.author else f"user{comment.author_id}"
    return {
        "id": comment.id,
        "content": comment.content,
        "author_id": comment.author_id,
        "author_nickname": author_nickname,
        "parent_id": comment.parent_id,
        "created_at": comment.created_at.isoformat() if comment.created_at else "",
    }


def _ensure_user(session, user_id: int, email: str = "", nickname: str = ""):
    """사용자가 DB에 없으면 생성."""
    existing = session.get(UserModel, user_id)
    if not existing:
        if not nickname:
            nickname = email.split("@")[0] if email else f"user{user_id}"
        if not email:
            email = f"user{user_id}@temp.local"
        new_user = UserModel(
            id=user_id,
            email=email,
            nickname=nickname,
        )
        session.add(new_user)
        session.commit()


@router.get("")
async def list_posts(
    request: Request,
    post_type: str = Query(None, description="게시글 유형 (hotdeal, free, qna, tip)"),
    category: str = Query(None, description="카테고리"),
    sort: str = Query("recent", description="정렬 (recent, popular, comments)"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """게시글 목록."""
    if _use_db and _SessionLocal:
        cache_key = f"posts:{post_type}:{category}:{sort}:{page}:{per_page}"
        cached = _posts_list_cache.get(cache_key)
        if cached is not None:
            return cached

        with _SessionLocal() as session:
            stmt = session.query(PostModel).filter(PostModel.is_deleted == False)
            if post_type:
                try:
                    pt = DBPostType(post_type)
                    stmt = stmt.filter(PostModel.post_type == pt)
                except ValueError:
                    pass
            if category:
                stmt = stmt.filter(
                    (PostModel.custom_category == category) |
                    (PostModel.category_id == category)
                )
            if sort == "popular":
                stmt = stmt.order_by(desc(PostModel.view_count))
            elif sort == "comments":
                stmt = stmt.order_by(desc(PostModel.created_at))
            else:
                stmt = stmt.order_by(desc(PostModel.created_at))

            total = stmt.count()
            offset = (page - 1) * per_page
            posts = stmt.offset(offset).limit(per_page).all()
            data = [_post_to_dict(p) for p in posts]

            resp = ApiResponse(
                data=data,
                meta=PaginationMeta(
                    page=page, per_page=per_page, total=total,
                    total_pages=math.ceil(total / per_page) if total > 0 else 0,
                ),
            )
            _posts_list_cache.set(cache_key, resp)
            return resp

    # DB 미연결 시 빈 결과 반환
    return ApiResponse(
        data=[],
        meta=PaginationMeta(page=page, per_page=per_page, total=0, total_pages=0),
    )


@router.post("")
async def create_post(body: PostCreate, user: dict = Depends(get_current_user)):
    """게시글 작성 — 로그인 시 사용자 정보 사용, 비로그인 시 게스트로 작성."""
    if not user:
        user = {"id": 0, "email": "guest@wallet.local", "nickname": "게스트", "role": "guest"}
    if _use_db and _SessionLocal:
        with _SessionLocal() as session:
            _ensure_user(session, user["id"], user.get("email", ""), user.get("nickname", ""))
            try:
                pt = DBPostType(body.post_type.value)
            except ValueError:
                pt = DBPostType.FREE
            post = PostModel(
                author_id=user["id"],
                post_type=pt,
                title=body.title,
                content=body.content,
                custom_category=body.category,
                deal_price=body.price,
                deal_url=body.url,
            )
            session.add(post)
            session.commit()
            session.refresh(post)
            if body.images:
                for i, img_data in enumerate(body.images):
                    if isinstance(img_data, str) and img_data:
                        img = PostImageModel(
                            post_id=post.id,
                            image_url=img_data,
                            position=i,
                        )
                        session.add(img)
                session.commit()
                session.refresh(post)
            _posts_list_cache.clear()
            data = _post_to_dict(post)
            return ApiResponse(data=data)

    # DB 미연결 시 에러
    raise HTTPException(status_code=503, detail="DB 미연결")


@router.get("/{post_id}")
async def get_post(post_id: int):
    """게시글 상세 (조회수 증가)."""
    if _use_db and _SessionLocal:
        with _SessionLocal() as session:
            post = session.get(PostModel, post_id)
            if not post or post.is_deleted:
                raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다")
            post.view_count += 1
            session.commit()
            session.refresh(post)
            return ApiResponse(data=_post_to_dict(post))

    raise HTTPException(status_code=503, detail="DB 미연결")


@router.put("/{post_id}")
async def update_post(post_id: int, body: PostUpdate, user: dict = Depends(require_auth)):
    """게시글 수정 (작성자만)."""
    if _use_db and _SessionLocal:
        with _SessionLocal() as session:
            post = session.get(PostModel, post_id)
            if not post or post.is_deleted:
                raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다")
            if post.author_id != user["id"]:
                raise HTTPException(status_code=403, detail="수정 권한이 없습니다")
            if body.title is not None:
                post.title = body.title
            if body.content is not None:
                post.content = body.content
            if body.category is not None:
                post.custom_category = body.category
            if body.price is not None:
                post.deal_price = body.price
            if body.url is not None:
                post.deal_url = body.url
            post.updated_at = datetime.utcnow()
            session.commit()
            session.refresh(post)
            _posts_list_cache.clear()
            return ApiResponse(data=_post_to_dict(post))

    raise HTTPException(status_code=503, detail="DB 미연결")


@router.delete("/{post_id}")
async def delete_post(post_id: int, user: dict = Depends(require_auth)):
    """게시글 삭제 (작성자 또는 관리자)."""
    if _use_db and _SessionLocal:
        with _SessionLocal() as session:
            post = session.get(PostModel, post_id)
            if not post or post.is_deleted:
                raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다")
            if post.author_id != user["id"] and user.get("role") not in ("admin", "moderator"):
                raise HTTPException(status_code=403, detail="삭제 권한이 없습니다")
            post.is_deleted = True
            session.commit()
            _posts_list_cache.clear()
            return ApiResponse(data={"id": post_id, "status": "deleted"})

    raise HTTPException(status_code=503, detail="DB 미연결")


@router.post("/{post_id}/comments")
async def create_comment(post_id: int, body: CommentCreate, user: dict = Depends(require_auth)):
    """댓글 작성."""
    if _use_db and _SessionLocal:
        with _SessionLocal() as session:
            post = session.get(PostModel, post_id)
            if not post or post.is_deleted:
                raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다")
            _ensure_user(session, user["id"], user.get("email", ""), user.get("nickname", ""))
            comment = CommentModel(
                post_id=post_id,
                author_id=user["id"],
                content=body.content,
                parent_id=body.parent_id,
            )
            session.add(comment)
            session.commit()
            session.refresh(comment)
            return ApiResponse(data=_comment_to_dict(comment))

    raise HTTPException(status_code=503, detail="DB 미연결")


@router.get("/{post_id}/comments")
async def list_comments(post_id: int):
    """댓글 목록."""
    if _use_db and _SessionLocal:
        with _SessionLocal() as session:
            post = session.get(PostModel, post_id)
            if not post or post.is_deleted:
                raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다")
            comments = (
                session.query(CommentModel)
                .filter(CommentModel.post_id == post_id, CommentModel.is_deleted == False)
                .order_by(CommentModel.created_at)
                .all()
            )
            return ApiResponse(data=[_comment_to_dict(c) for c in comments])

    return ApiResponse(data=[])


@router.post("/{post_id}/vote")
async def vote_post(post_id: int, body: VoteRequest, user: dict = Depends(require_auth)):
    """핫딜 투표 (hot/not)."""
    if body.vote_type not in ("hot", "not"):
        raise HTTPException(status_code=400, detail="vote_type은 'hot' 또는 'not'이어야 합니다")

    if _use_db and _SessionLocal:
        with _SessionLocal() as session:
            post = session.get(PostModel, post_id)
            if not post or post.is_deleted:
                raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다")
            _ensure_user(session, user["id"], user.get("email", ""), user.get("nickname", ""))

            existing = (
                session.query(VoteModel)
                .filter(VoteModel.post_id == post_id, VoteModel.user_id == user["id"])
                .first()
            )

            new_vt = DBVoteType.HOT if body.vote_type == "hot" else DBVoteType.NOT

            if existing:
                if existing.vote_type == new_vt:
                    session.delete(existing)
                    session.commit()
                    session.refresh(post)
                    d = _post_to_dict(post)
                    return ApiResponse(data={
                        "post_id": post_id,
                        "hot_votes": d["hot_votes"],
                        "not_votes": d["not_votes"],
                        "user_vote": None,
                    })
                else:
                    existing.vote_type = new_vt
                    session.commit()
            else:
                vote = VoteModel(post_id=post_id, user_id=user["id"], vote_type=new_vt)
                session.add(vote)
                session.commit()

            session.refresh(post)
            d = _post_to_dict(post)
            return ApiResponse(data={
                "post_id": post_id,
                "hot_votes": d["hot_votes"],
                "not_votes": d["not_votes"],
                "user_vote": body.vote_type,
            })

    raise HTTPException(status_code=503, detail="DB 미연결")


@router.get("/{post_id}/suggested-tier")
async def suggested_tier(post_id: int):
    """핫딜 적정가 제안 (DB 기반)."""
    price = None
    orig = None

    if _use_db and _SessionLocal:
        with _SessionLocal() as session:
            post = session.get(PostModel, post_id)
            if not post or post.is_deleted:
                raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다")
            price = post.deal_price
            orig = None
    else:
        raise HTTPException(status_code=503, detail="DB 미연결")

    if price and orig and orig > 0:
        ratio = price / orig
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
        "original_price": orig,
        "discount_rate": round((1 - price / orig) * 100, 1) if price and orig and orig > 0 else None,
    })
