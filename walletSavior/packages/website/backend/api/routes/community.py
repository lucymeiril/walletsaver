"""
커뮤니티 API — 게시글, 댓글, 투표.

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
import copy
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException, Depends, Query
from api.schemas.common import ApiResponse, PaginationMeta
from api.schemas.community import PostCreate, PostUpdate, CommentCreate, VoteRequest
from api.middleware.auth import require_auth, get_current_user

router = APIRouter()

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

    # 커뮤니티 초기 데이터가 없으면 mock 데이터로 시드
    try:
        _tmp_session = _SessionLocal()
        _post_count = _tmp_session.query(PostModel).count()
        if _post_count == 0:
            from api.mock_responses import MOCK_POSTS, MOCK_COMMENTS
            # 먼저 사용자 생성
            _authors = {}
            for p in MOCK_POSTS:
                aid = p["author_id"]
                if aid not in _authors:
                    existing = _tmp_session.get(UserModel, aid)
                    if not existing:
                        u = UserModel(
                            id=aid,
                            email=f"{p['author_nickname']}@seed.local",
                            nickname=p["author_nickname"],
                        )
                        _tmp_session.add(u)
                    _authors[aid] = True
            _tmp_session.commit()

            # 게시글 생성
            for p in MOCK_POSTS:
                try:
                    pt = DBPostType(p["post_type"])
                except ValueError:
                    pt = DBPostType.FREE
                post_obj = PostModel(
                    id=p["id"],
                    author_id=p["author_id"],
                    post_type=pt,
                    title=p["title"],
                    content=p["content"],
                    custom_category=p.get("category"),
                    deal_price=p.get("price"),
                    deal_url=p.get("url"),
                    view_count=p.get("views", 0),
                )
                _tmp_session.add(post_obj)
            _tmp_session.commit()

            # 댓글 생성
            for post_id, comments in MOCK_COMMENTS.items():
                for c in comments:
                    aid = c["author_id"]
                    if aid not in _authors:
                        existing = _tmp_session.get(UserModel, aid)
                        if not existing:
                            u = UserModel(
                                id=aid,
                                email=f"{c['author_nickname']}@seed.local",
                                nickname=c["author_nickname"],
                            )
                            _tmp_session.add(u)
                        _authors[aid] = True
                    _tmp_session.commit()
                    comment_obj = CommentModel(
                        id=c["id"],
                        post_id=post_id,
                        author_id=c["author_id"],
                        content=c["content"],
                        parent_id=c.get("parent_id"),
                    )
                    _tmp_session.add(comment_obj)
            _tmp_session.commit()
        _tmp_session.close()
    except Exception as _seed_err:
        import logging
        logging.warning(f"커뮤니티 시드 실패: {_seed_err}")

    _use_db = True
except Exception as _e:
    import logging
    logging.warning(f"커뮤니티 DB 연결 실패, mock 사용: {_e}")
    _use_db = False

# ── 인메모리 fallback ──
_posts_db: list[dict] = []
_comments_db: dict[int, list[dict]] = {}
_votes_db: dict[str, str] = {}
_next_post_id = 100
_next_comment_id = 100
_initialized = False


def _ensure_init():
    """lazy init from mock data (fallback)."""
    global _posts_db, _comments_db, _initialized, _next_post_id, _next_comment_id
    if _initialized:
        return
    from api.mock_responses import MOCK_POSTS, MOCK_COMMENTS
    _posts_db = copy.deepcopy(MOCK_POSTS)
    _comments_db = copy.deepcopy(MOCK_COMMENTS)
    _next_post_id = max((p["id"] for p in _posts_db), default=0) + 1
    all_cids = [c["id"] for cs in _comments_db.values() for c in cs]
    _next_comment_id = max(all_cids, default=0) + 1
    _initialized = True


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

            return ApiResponse(
                data=data,
                meta=PaginationMeta(
                    page=page, per_page=per_page, total=total,
                    total_pages=math.ceil(total / per_page) if total > 0 else 0,
                ),
            )

    # fallback: in-memory mock
    _ensure_init()
    results = list(_posts_db)
    if post_type:
        results = [p for p in results if p["post_type"] == post_type]
    if category:
        results = [p for p in results if p.get("category") == category]
    if sort == "popular":
        results.sort(key=lambda x: x["views"], reverse=True)
    elif sort == "comments":
        results.sort(key=lambda x: x["comments_count"], reverse=True)
    else:
        results.sort(key=lambda x: x["created_at"], reverse=True)

    total = len(results)
    start = (page - 1) * per_page
    paginated = results[start:start + per_page]
    return ApiResponse(
        data=paginated,
        meta=PaginationMeta(
            page=page, per_page=per_page, total=total,
            total_pages=math.ceil(total / per_page) if total > 0 else 0,
        ),
    )


@router.post("")
async def create_post(body: PostCreate, user: dict = Depends(require_auth)):
    """게시글 작성."""
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
            data = _post_to_dict(post)
            return ApiResponse(data=data)

    global _next_post_id
    _ensure_init()
    now = datetime.now().isoformat()
    post = {
        "id": _next_post_id,
        "title": body.title,
        "content": body.content,
        "post_type": body.post_type.value,
        "category": body.category,
        "author_id": user["id"],
        "author_nickname": user.get("nickname", user["email"].split("@")[0]),
        "views": 0,
        "comments_count": 0,
        "hot_votes": 0,
        "not_votes": 0,
        "price": body.price,
        "original_price": body.original_price,
        "url": body.url,
        "created_at": now,
        "updated_at": now,
    }
    _posts_db.insert(0, post)
    _next_post_id += 1
    return ApiResponse(data=post)


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

    _ensure_init()
    post = next((p for p in _posts_db if p["id"] == post_id), None)
    if not post:
        raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다")
    post["views"] += 1
    return ApiResponse(data=post)


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
            post.updated_at = datetime.utcnow()
            session.commit()
            session.refresh(post)
            return ApiResponse(data=_post_to_dict(post))

    _ensure_init()
    post = next((p for p in _posts_db if p["id"] == post_id), None)
    if not post:
        raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다")
    if post["author_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="수정 권한이 없습니다")
    if body.title is not None:
        post["title"] = body.title
    if body.content is not None:
        post["content"] = body.content
    if body.category is not None:
        post["category"] = body.category
    post["updated_at"] = datetime.now().isoformat()
    return ApiResponse(data=post)


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
            return ApiResponse(data={"id": post_id, "status": "deleted"})

    _ensure_init()
    post = next((p for p in _posts_db if p["id"] == post_id), None)
    if not post:
        raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다")
    if post["author_id"] != user["id"] and user.get("role") not in ("admin", "moderator"):
        raise HTTPException(status_code=403, detail="삭제 권한이 없습니다")
    _posts_db.remove(post)
    _comments_db.pop(post_id, None)
    return ApiResponse(data={"id": post_id, "status": "deleted"})


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

    global _next_comment_id
    _ensure_init()
    post = next((p for p in _posts_db if p["id"] == post_id), None)
    if not post:
        raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다")
    comment = {
        "id": _next_comment_id,
        "content": body.content,
        "author_id": user["id"],
        "author_nickname": user.get("nickname", user["email"].split("@")[0]),
        "parent_id": body.parent_id,
        "created_at": datetime.now().isoformat(),
    }
    _comments_db.setdefault(post_id, []).append(comment)
    post["comments_count"] += 1
    _next_comment_id += 1
    return ApiResponse(data=comment)


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

    _ensure_init()
    post = next((p for p in _posts_db if p["id"] == post_id), None)
    if not post:
        raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다")
    comments = _comments_db.get(post_id, [])
    return ApiResponse(data=comments)


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

    # fallback: in-memory
    _ensure_init()
    post = next((p for p in _posts_db if p["id"] == post_id), None)
    if not post:
        raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다")

    vote_key = f"{user['id']}:{post_id}"
    prev = _votes_db.get(vote_key)

    if prev == "hot":
        post["hot_votes"] -= 1
    elif prev == "not":
        post["not_votes"] -= 1

    if prev == body.vote_type:
        _votes_db.pop(vote_key, None)
        return ApiResponse(data={
            "post_id": post_id,
            "hot_votes": post["hot_votes"],
            "not_votes": post["not_votes"],
            "user_vote": None,
        })

    _votes_db[vote_key] = body.vote_type
    if body.vote_type == "hot":
        post["hot_votes"] += 1
    else:
        post["not_votes"] += 1

    return ApiResponse(data={
        "post_id": post_id,
        "hot_votes": post["hot_votes"],
        "not_votes": post["not_votes"],
        "user_vote": body.vote_type,
    })


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
        _ensure_init()
        post = next((p for p in _posts_db if p["id"] == post_id), None)
        if not post:
            raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다")
        price = post.get("price")
        orig = post.get("original_price")

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
