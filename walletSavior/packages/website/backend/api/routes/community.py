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

import math
import copy
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException, Depends, Query
from api.schemas.common import ApiResponse, PaginationMeta
from api.schemas.community import PostCreate, PostUpdate, CommentCreate, VoteRequest
from api.middleware.auth import require_auth, get_current_user

router = APIRouter()

# 인메모리 저장소 (mock)
_posts_db: list[dict] = []
_comments_db: dict[int, list[dict]] = {}
_votes_db: dict[str, str] = {}  # "user_id:post_id" -> vote_type
_next_post_id = 100
_next_comment_id = 100
_initialized = False


def _ensure_init():
    """lazy init from mock data."""
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
            page=page,
            per_page=per_page,
            total=total,
            total_pages=math.ceil(total / per_page) if total > 0 else 0,
        ),
    )


@router.post("")
async def create_post(body: PostCreate, user: dict = Depends(require_auth)):
    """게시글 작성."""
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
    _ensure_init()
    post = next((p for p in _posts_db if p["id"] == post_id), None)
    if not post:
        raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다")
    post["views"] += 1
    return ApiResponse(data=post)


@router.put("/{post_id}")
async def update_post(post_id: int, body: PostUpdate, user: dict = Depends(require_auth)):
    """게시글 수정 (작성자만)."""
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
    _ensure_init()
    post = next((p for p in _posts_db if p["id"] == post_id), None)
    if not post:
        raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다")
    comments = _comments_db.get(post_id, [])
    return ApiResponse(data=comments)


@router.post("/{post_id}/vote")
async def vote_post(post_id: int, body: VoteRequest, user: dict = Depends(require_auth)):
    """핫딜 투표 (hot/not)."""
    _ensure_init()
    post = next((p for p in _posts_db if p["id"] == post_id), None)
    if not post:
        raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다")

    if body.vote_type not in ("hot", "not"):
        raise HTTPException(status_code=400, detail="vote_type은 'hot' 또는 'not'이어야 합니다")

    vote_key = f"{user['id']}:{post_id}"
    prev = _votes_db.get(vote_key)

    # 이전 투표 취소
    if prev == "hot":
        post["hot_votes"] -= 1
    elif prev == "not":
        post["not_votes"] -= 1

    # 같은 투표면 토글(취소)
    if prev == body.vote_type:
        _votes_db.pop(vote_key, None)
        return ApiResponse(data={
            "post_id": post_id,
            "hot_votes": post["hot_votes"],
            "not_votes": post["not_votes"],
            "user_vote": None,
        })

    # 새 투표 반영
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
