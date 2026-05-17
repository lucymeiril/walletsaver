"""SQLAlchemy models and engine factory for the board database."""
from __future__ import annotations

import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Integer,
    String,
    Float,
    Text,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship


_DEFAULT_DB = Path(__file__).resolve().parent / "board.sqlite"


def _now() -> str:
    return datetime.utcnow().isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "user"
    id = Column(String, primary_key=True, default=_uuid)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    display_name = Column(String, nullable=False)
    role = Column(
        String,
        nullable=False,
        default="user",
    )
    created_at = Column(String, default=_now)
    banned_at = Column(String, nullable=True)
    __table_args__ = (
        CheckConstraint("role IN ('user','moderator','admin')", name="ck_user_role"),
    )


class SessionRow(Base):
    __tablename__ = "session"
    token_hash = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("user.id"), nullable=False)
    expires_at = Column(String, nullable=False)


class Board(Base):
    __tablename__ = "board"
    slug = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)


class BoardCategory(Base):
    __tablename__ = "board_category"
    id = Column(String, primary_key=True, default=_uuid)
    board_slug = Column(String, ForeignKey("board.slug"), nullable=False)
    name = Column(String, nullable=False)
    slug = Column(String, nullable=False)


class Post(Base):
    __tablename__ = "post"
    id = Column(String, primary_key=True, default=_uuid)
    board_slug = Column(String, ForeignKey("board.slug"), nullable=False)
    category_id = Column(String, ForeignKey("board_category.id"), nullable=True)
    freeform_category = Column(String, nullable=True)
    user_id = Column(String, ForeignKey("user.id"), nullable=False)
    title = Column(String, nullable=False)
    body_markdown = Column(Text, nullable=False)
    canonical_id = Column(String, nullable=True)
    deal_price = Column(Float, nullable=True)
    mart_name = Column(String, nullable=True)
    deal_url = Column(String, nullable=True)
    created_at = Column(String, default=_now)
    updated_at = Column(String, default=_now)
    hidden_at = Column(String, nullable=True)
    hidden_reason = Column(String, nullable=True)

    images = relationship("PostImage", backref="post", cascade="all, delete-orphan")
    comments = relationship("Comment", backref="post", cascade="all, delete-orphan")


class PostImage(Base):
    __tablename__ = "post_image"
    id = Column(String, primary_key=True, default=_uuid)
    post_id = Column(String, ForeignKey("post.id"), nullable=False)
    ord = Column(Integer, default=0)
    image_path = Column(String, nullable=False)
    alt = Column(String, nullable=True)


class Comment(Base):
    __tablename__ = "comment"
    id = Column(String, primary_key=True, default=_uuid)
    post_id = Column(String, ForeignKey("post.id"), nullable=False)
    user_id = Column(String, ForeignKey("user.id"), nullable=False)
    body = Column(Text, nullable=False)
    verdict = Column(String, default="neutral", nullable=False)
    created_at = Column(String, default=_now)
    hidden_at = Column(String, nullable=True)
    __table_args__ = (
        CheckConstraint(
            "verdict IN ('hot_deal','not_hot_deal','neutral')",
            name="ck_comment_verdict",
        ),
    )


class Report(Base):
    __tablename__ = "report"
    id = Column(String, primary_key=True, default=_uuid)
    target_kind = Column(String, nullable=False)
    target_id = Column(String, nullable=False)
    reporter_user_id = Column(String, ForeignKey("user.id"), nullable=False)
    reason = Column(Text, nullable=True)
    status = Column(String, default="open", nullable=False)
    created_at = Column(String, default=_now)
    resolved_by_user_id = Column(String, ForeignKey("user.id"), nullable=True)
    resolved_at = Column(String, nullable=True)
    __table_args__ = (
        CheckConstraint(
            "target_kind IN ('post','comment')", name="ck_report_target_kind"
        ),
        CheckConstraint(
            "status IN ('open','resolved','dismissed')", name="ck_report_status"
        ),
    )


class ModerationLog(Base):
    __tablename__ = "moderation_log"
    id = Column(String, primary_key=True, default=_uuid)
    action = Column(String, nullable=False)
    target_kind = Column(String, nullable=True)
    target_id = Column(String, nullable=True)
    actor_user_id = Column(String, ForeignKey("user.id"), nullable=True)
    note = Column(Text, nullable=True)
    created_at = Column(String, default=_now)


_engine_cache: dict[str, object] = {}


def get_board_db_path() -> str:
    env = os.environ.get("WALLETSAVIOR_BOARD_DB")
    if env:
        return env
    return str(_DEFAULT_DB)


def get_board_engine(db_path: Optional[str] = None):
    path = db_path or get_board_db_path()
    cached = _engine_cache.get(path)
    if cached is not None:
        return cached
    if path == ":memory:":
        url = "sqlite://"
    else:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{path}"
    engine = create_engine(
        url,
        connect_args={"check_same_thread": False},
        future=True,
    )

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(engine)
    _seed_if_empty(engine)
    _engine_cache[path] = engine
    return engine


def reset_engine_cache():
    _engine_cache.clear()


def _seed_if_empty(engine):
    with Session(engine) as db:
        existing = db.query(Board).count()
        if existing > 0:
            return
        hotdeal = Board(slug="hotdeal", name="핫딜 게시판", description="할인/특가 공유")
        free = Board(slug="free", name="자유 게시판", description="자유롭게 이야기")
        db.add_all([hotdeal, free])
        db.flush()
        cats = [
            BoardCategory(id=_uuid(), board_slug="hotdeal", name="식품", slug="food"),
            BoardCategory(id=_uuid(), board_slug="hotdeal", name="생활/가전", slug="home"),
            BoardCategory(id=_uuid(), board_slug="hotdeal", name="기타", slug="etc"),
            BoardCategory(id=_uuid(), board_slug="free", name="잡담", slug="chat"),
            BoardCategory(id=_uuid(), board_slug="free", name="질문", slug="qna"),
        ]
        db.add_all(cats)
        db.commit()


def get_board_db():
    engine = get_board_engine()
    db = Session(engine)
    try:
        yield db
    finally:
        db.close()
