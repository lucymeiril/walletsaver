"""Board, post, comment, image, and report API routes."""
from __future__ import annotations

import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from services.auth import get_current_user, require_mod, require_user
from services.snapshot_repo import SnapshotRepo
from storage.board_models import (
    Board,
    BoardCategory,
    Comment,
    ModerationLog,
    Post,
    PostImage,
    Report,
    User,
    get_board_db,
)

router = APIRouter(tags=["board"])


_IMAGE_ROOT = Path(__file__).resolve().parent.parent.parent / "var" / "board_images"


def _image_root() -> Path:
    env = os.environ.get("WALLETSAVIOR_BOARD_IMAGE_DIR")
    return Path(env) if env else _IMAGE_ROOT


def _now() -> str:
    return datetime.utcnow().isoformat()


# ---------- Pydantic schemas ----------


class BoardOut(BaseModel):
    slug: str
    name: str
    description: Optional[str] = None
    category_count: int = 0


class CategoryOut(BaseModel):
    id: str
    board_slug: str
    name: str
    slug: str


class UserOut(BaseModel):
    id: str
    display_name: str
    role: str


class GradeSummary(BaseModel):
    p10: Optional[float] = None
    p50: Optional[float] = None
    label: str
    sufficient: bool


class PostImageOut(BaseModel):
    id: str
    ord: int
    image_url: str
    alt: Optional[str] = None


class CommentOut(BaseModel):
    id: str
    user: UserOut
    body: str
    verdict: str
    created_at: str
    hidden_at: Optional[str] = None


class PostSummaryOut(BaseModel):
    id: str
    board_slug: str
    title: str
    user: UserOut
    category_id: Optional[str] = None
    freeform_category: Optional[str] = None
    deal_price: Optional[float] = None
    canonical_id: Optional[str] = None
    created_at: str
    comment_count: int = 0
    hidden_at: Optional[str] = None


class PostDetailOut(PostSummaryOut):
    body_markdown: str
    images: list[PostImageOut] = []
    comments: list[CommentOut] = []
    grade_summary: Optional[GradeSummary] = None
    mart_name: Optional[str] = None
    deal_url: Optional[str] = None


class PaginatedPosts(BaseModel):
    total: int
    page: int
    page_size: int
    total_pages: int
    items: list[PostSummaryOut]


class CommentReq(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    verdict: str = "neutral"


class ReportReq(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=1000)


class PostPatchReq(BaseModel):
    title: Optional[str] = None
    body_markdown: Optional[str] = None
    deal_price: Optional[float] = None
    mart_name: Optional[str] = None
    deal_url: Optional[str] = None


# ---------- Helpers ----------


def _user_out(u: User) -> UserOut:
    return UserOut(id=u.id, display_name=u.display_name, role=u.role)


def _image_url(post_id: str, filename: str) -> str:
    return f"/api/v1/images/{post_id}/{filename}"


def _post_to_summary(db: Session, p: Post) -> PostSummaryOut:
    u = db.get(User, p.user_id)
    comment_count = (
        db.query(func.count(Comment.id))
        .filter(Comment.post_id == p.id, Comment.hidden_at.is_(None))
        .scalar()
        or 0
    )
    return PostSummaryOut(
        id=p.id,
        board_slug=p.board_slug,
        title=p.title,
        user=_user_out(u) if u else UserOut(id="", display_name="(deleted)", role="user"),
        category_id=p.category_id,
        freeform_category=p.freeform_category,
        deal_price=p.deal_price,
        canonical_id=p.canonical_id,
        created_at=p.created_at,
        comment_count=int(comment_count),
        hidden_at=p.hidden_at,
    )


def _grade_summary(canonical_id: str) -> Optional[GradeSummary]:
    try:
        repo = SnapshotRepo()
        grade = repo.grade_by_id(canonical_id)
        if grade is None:
            return None
        if not grade.sufficient or grade.p10 is None:
            label = "INSUFFICIENT_DATA"
        else:
            label = "AVAILABLE"
        return GradeSummary(
            p10=grade.p10, p50=grade.p50, label=label, sufficient=grade.sufficient
        )
    except Exception:
        return None


# ---------- Board / category routes ----------


@router.get("/boards", response_model=list[BoardOut])
def list_boards(db: Session = Depends(get_board_db)):
    rows = db.query(Board).all()
    out = []
    for b in rows:
        cnt = (
            db.query(func.count(BoardCategory.id))
            .filter(BoardCategory.board_slug == b.slug)
            .scalar()
            or 0
        )
        out.append(
            BoardOut(slug=b.slug, name=b.name, description=b.description, category_count=int(cnt))
        )
    return out


@router.get("/boards/{slug}/categories", response_model=list[CategoryOut])
def list_categories(slug: str, db: Session = Depends(get_board_db)):
    if not db.get(Board, slug):
        raise HTTPException(404, "board_not_found")
    cats = db.query(BoardCategory).filter(BoardCategory.board_slug == slug).all()
    return [CategoryOut(id=c.id, board_slug=c.board_slug, name=c.name, slug=c.slug) for c in cats]


# ---------- Post list ----------


@router.get("/boards/{slug}/posts", response_model=PaginatedPosts)
def list_posts(
    slug: str,
    category: Optional[str] = None,
    q: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort: str = "recent",
    db: Session = Depends(get_board_db),
    user: Optional[User] = Depends(get_current_user),
):
    if not db.get(Board, slug):
        raise HTTPException(404, "board_not_found")

    qry = db.query(Post).filter(Post.board_slug == slug)
    if not user or user.role not in ("moderator", "admin"):
        qry = qry.filter(Post.hidden_at.is_(None))

    if category:
        cat = (
            db.query(BoardCategory)
            .filter(
                BoardCategory.board_slug == slug, BoardCategory.slug == category
            )
            .first()
        )
        if cat:
            qry = qry.filter(Post.category_id == cat.id)
    if q:
        like = f"%{q}%"
        qry = qry.filter((Post.title.like(like)) | (Post.body_markdown.like(like)))

    total = qry.count()

    if sort == "comments":
        # subquery comment count
        sub = (
            db.query(Comment.post_id, func.count(Comment.id).label("cnt"))
            .filter(Comment.hidden_at.is_(None))
            .group_by(Comment.post_id)
            .subquery()
        )
        qry = (
            qry.outerjoin(sub, sub.c.post_id == Post.id)
            .order_by(desc(func.coalesce(sub.c.cnt, 0)), desc(Post.created_at))
        )
    elif sort == "popular":
        qry = qry.order_by(desc(Post.created_at))
    else:
        qry = qry.order_by(desc(Post.created_at))

    rows = qry.offset((page - 1) * page_size).limit(page_size).all()
    items = [_post_to_summary(db, p) for p in rows]
    total_pages = (total + page_size - 1) // page_size if total else 0
    return PaginatedPosts(
        total=total, page=page, page_size=page_size, total_pages=total_pages, items=items
    )


# ---------- Create post (multipart) ----------


@router.post("/boards/{slug}/posts", response_model=PostDetailOut, status_code=201)
async def create_post(
    slug: str,
    title: str = Form(...),
    body_markdown: str = Form(...),
    category_id: Optional[str] = Form(None),
    freeform_category: Optional[str] = Form(None),
    canonical_id: Optional[str] = Form(None),
    deal_price: Optional[float] = Form(None),
    mart_name: Optional[str] = Form(None),
    deal_url: Optional[str] = Form(None),
    images: list[UploadFile] = File(default_factory=list),
    db: Session = Depends(get_board_db),
    user: User = Depends(require_user),
):
    if not db.get(Board, slug):
        raise HTTPException(404, "board_not_found")
    if category_id:
        if not db.get(BoardCategory, category_id):
            raise HTTPException(400, "category_not_found")
    post_id = str(uuid.uuid4())
    post = Post(
        id=post_id,
        board_slug=slug,
        category_id=category_id or None,
        freeform_category=freeform_category or None,
        user_id=user.id,
        title=title,
        body_markdown=body_markdown,
        canonical_id=canonical_id or None,
        deal_price=deal_price,
        mart_name=mart_name or None,
        deal_url=deal_url or None,
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(post)
    db.flush()

    saved_imgs: list[PostImage] = []
    if images:
        root = _image_root() / post_id
        root.mkdir(parents=True, exist_ok=True)
        for idx, up in enumerate(images):
            if not up or not up.filename:
                continue
            ext = Path(up.filename).suffix.lower()
            safe_name = f"{idx:03d}_{uuid.uuid4().hex[:8]}{ext}"
            dest = root / safe_name
            content = await up.read()
            dest.write_bytes(content)
            img = PostImage(
                id=str(uuid.uuid4()),
                post_id=post_id,
                ord=idx,
                image_path=safe_name,
                alt=None,
            )
            db.add(img)
            saved_imgs.append(img)
    db.commit()
    db.refresh(post)
    return _post_to_detail(db, post)


def _post_to_detail(db: Session, p: Post) -> PostDetailOut:
    summary = _post_to_summary(db, p)
    imgs = (
        db.query(PostImage)
        .filter(PostImage.post_id == p.id)
        .order_by(PostImage.ord)
        .all()
    )
    image_outs = [
        PostImageOut(
            id=i.id, ord=i.ord, image_url=_image_url(p.id, i.image_path), alt=i.alt
        )
        for i in imgs
    ]
    comments = (
        db.query(Comment)
        .filter(Comment.post_id == p.id)
        .order_by(Comment.created_at)
        .all()
    )
    com_outs = []
    for c in comments:
        cu = db.get(User, c.user_id)
        com_outs.append(
            CommentOut(
                id=c.id,
                user=_user_out(cu)
                if cu
                else UserOut(id="", display_name="(deleted)", role="user"),
                body=c.body if not c.hidden_at else "(숨김 처리됨)",
                verdict=c.verdict,
                created_at=c.created_at,
                hidden_at=c.hidden_at,
            )
        )
    grade = _grade_summary(p.canonical_id) if p.canonical_id else None
    return PostDetailOut(
        **summary.model_dump(),
        body_markdown=p.body_markdown,
        images=image_outs,
        comments=com_outs,
        grade_summary=grade,
        mart_name=p.mart_name,
        deal_url=p.deal_url,
    )


@router.get("/posts/{post_id}", response_model=PostDetailOut)
def get_post(
    post_id: str,
    db: Session = Depends(get_board_db),
    user: Optional[User] = Depends(get_current_user),
):
    p = db.get(Post, post_id)
    if not p:
        raise HTTPException(404, "post_not_found")
    if p.hidden_at and (not user or user.role not in ("moderator", "admin")):
        raise HTTPException(404, "post_not_found")
    return _post_to_detail(db, p)


@router.patch("/posts/{post_id}", response_model=PostDetailOut)
def update_post(
    post_id: str,
    body: PostPatchReq,
    db: Session = Depends(get_board_db),
    user: User = Depends(require_user),
):
    p = db.get(Post, post_id)
    if not p or p.hidden_at:
        raise HTTPException(404, "post_not_found")
    if p.user_id != user.id and user.role not in ("moderator", "admin"):
        raise HTTPException(403, "forbidden")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(p, k, v)
    p.updated_at = _now()
    db.commit()
    db.refresh(p)
    return _post_to_detail(db, p)


@router.delete("/posts/{post_id}")
def delete_post(
    post_id: str,
    db: Session = Depends(get_board_db),
    user: User = Depends(require_user),
):
    p = db.get(Post, post_id)
    if not p:
        raise HTTPException(404, "post_not_found")
    if p.user_id != user.id and user.role not in ("moderator", "admin"):
        raise HTTPException(403, "forbidden")
    p.hidden_at = _now()
    p.hidden_reason = "deleted_by_owner" if p.user_id == user.id else "deleted_by_mod"
    db.add(
        ModerationLog(
            action="delete_post",
            target_kind="post",
            target_id=p.id,
            actor_user_id=user.id,
            note=p.hidden_reason,
            created_at=_now(),
        )
    )
    db.commit()
    return {"ok": True}


# ---------- Comments ----------


@router.post("/posts/{post_id}/comments", response_model=CommentOut, status_code=201)
def add_comment(
    post_id: str,
    body: CommentReq,
    db: Session = Depends(get_board_db),
    user: User = Depends(require_user),
):
    p = db.get(Post, post_id)
    if not p or p.hidden_at:
        raise HTTPException(404, "post_not_found")
    if body.verdict not in ("hot_deal", "not_hot_deal", "neutral"):
        raise HTTPException(400, "invalid_verdict")
    c = Comment(
        post_id=post_id,
        user_id=user.id,
        body=body.body,
        verdict=body.verdict,
        created_at=_now(),
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return CommentOut(
        id=c.id,
        user=_user_out(user),
        body=c.body,
        verdict=c.verdict,
        created_at=c.created_at,
        hidden_at=None,
    )


@router.patch("/comments/{comment_id}", response_model=CommentOut)
def hide_comment(
    comment_id: str,
    db: Session = Depends(get_board_db),
    user: User = Depends(require_mod),
):
    c = db.get(Comment, comment_id)
    if not c:
        raise HTTPException(404, "comment_not_found")
    c.hidden_at = _now()
    db.add(
        ModerationLog(
            action="hide_comment",
            target_kind="comment",
            target_id=c.id,
            actor_user_id=user.id,
            created_at=_now(),
        )
    )
    db.commit()
    cu = db.get(User, c.user_id)
    return CommentOut(
        id=c.id,
        user=_user_out(cu)
        if cu
        else UserOut(id="", display_name="(deleted)", role="user"),
        body="(숨김 처리됨)",
        verdict=c.verdict,
        created_at=c.created_at,
        hidden_at=c.hidden_at,
    )


@router.get("/posts/{post_id}/verdict-summary")
def verdict_summary(post_id: str, db: Session = Depends(get_board_db)):
    p = db.get(Post, post_id)
    if not p:
        raise HTTPException(404, "post_not_found")
    out = {"hot_deal": 0, "not_hot_deal": 0, "neutral": 0}
    rows = (
        db.query(Comment.verdict, func.count(Comment.id))
        .filter(Comment.post_id == post_id, Comment.hidden_at.is_(None))
        .group_by(Comment.verdict)
        .all()
    )
    for v, n in rows:
        if v in out:
            out[v] = int(n)
    return out


# ---------- Reports ----------


@router.post("/posts/{post_id}/report", status_code=201)
def report_post(
    post_id: str,
    body: ReportReq,
    db: Session = Depends(get_board_db),
    user: User = Depends(require_user),
):
    p = db.get(Post, post_id)
    if not p:
        raise HTTPException(404, "post_not_found")
    r = Report(
        target_kind="post",
        target_id=post_id,
        reporter_user_id=user.id,
        reason=body.reason,
        status="open",
        created_at=_now(),
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return {"report_id": r.id}


@router.post("/comments/{comment_id}/report", status_code=201)
def report_comment(
    comment_id: str,
    body: ReportReq,
    db: Session = Depends(get_board_db),
    user: User = Depends(require_user),
):
    c = db.get(Comment, comment_id)
    if not c:
        raise HTTPException(404, "comment_not_found")
    r = Report(
        target_kind="comment",
        target_id=comment_id,
        reporter_user_id=user.id,
        reason=body.reason,
        status="open",
        created_at=_now(),
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return {"report_id": r.id}


# ---------- Image serving ----------


@router.get("/images/{post_id}/{filename}")
def serve_image(post_id: str, filename: str):
    # Basic safety: no path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400, "invalid_filename")
    p = _image_root() / post_id / filename
    if not p.exists() or not p.is_file():
        raise HTTPException(404, "image_not_found")
    return FileResponse(str(p))
