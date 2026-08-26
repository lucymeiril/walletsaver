"""Independent SQLite storage for web users and the community board.

Community writes must never touch the product/catalog source DB. Public account
identity lives in the same ``community_users`` table as post ownership so a
server restart can never recycle an in-memory user id onto somebody else's
persistent posts.
"""
from __future__ import annotations

import enum
import os
from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, scoped_session, sessionmaker


_DEFAULT_DB = Path(__file__).resolve().parent.parent / "storage" / "board.sqlite"


class Base(DeclarativeBase):
    pass


class PostType(str, enum.Enum):
    HOTDEAL = "hotdeal"
    FREE = "free"
    QNA = "qna"
    TIP = "tip"


class VoteType(str, enum.Enum):
    HOT = "hot"
    NOT = "not"


class User(Base):
    __tablename__ = "community_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    nickname: Mapped[str] = mapped_column(String(100), nullable=False)
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    oauth_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    oauth_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    profile_image_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    preferences_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    posts: Mapped[list["Post"]] = relationship(back_populates="author")
    comments: Mapped[list["Comment"]] = relationship(back_populates="author")


class Post(Base):
    __tablename__ = "community_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("community_users.id"), nullable=False, index=True)
    post_type: Mapped[PostType] = mapped_column(
        SAEnum(PostType, values_callable=lambda values: [item.value for item in values], name="community_post_type"),
        nullable=False,
        default=PostType.FREE,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    custom_category: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    category_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    deal_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    original_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    deal_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    author: Mapped[User] = relationship(back_populates="posts")
    comments: Mapped[list["Comment"]] = relationship(
        back_populates="post", cascade="all, delete-orphan"
    )
    votes: Mapped[list["Vote"]] = relationship(
        back_populates="post", cascade="all, delete-orphan"
    )


class Comment(Base):
    __tablename__ = "community_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("community_posts.id", ondelete="CASCADE"), nullable=False, index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("community_users.id"), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("community_comments.id"), nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    post: Mapped[Post] = relationship(back_populates="comments")
    author: Mapped[User] = relationship(back_populates="comments")


class Vote(Base):
    __tablename__ = "community_votes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("community_posts.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("community_users.id"), nullable=False, index=True)
    vote_type: Mapped[VoteType] = mapped_column(
        SAEnum(VoteType, values_callable=lambda values: [item.value for item in values], name="community_vote_type"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    post: Mapped[Post] = relationship(back_populates="votes")

    __table_args__ = (
        UniqueConstraint("post_id", "user_id", name="uq_community_vote_post_user"),
    )


_engine = None
_SessionLocal = None


def get_board_db_path() -> Path:
    configured = os.getenv("WALLETSAVIOR_BOARD_DB")
    return Path(configured).resolve() if configured else _DEFAULT_DB.resolve()


def _ensure_auth_columns(engine) -> None:
    """Upgrade older local community_users tables without discarding board data."""
    with engine.begin() as connection:
        columns = {
            row[1]
            for row in connection.execute(text("PRAGMA table_info(community_users)"))
        }
        additions = {
            "hashed_password": "hashed_password VARCHAR(255)",
            "role": "role VARCHAR(32) NOT NULL DEFAULT 'user'",
            "oauth_provider": "oauth_provider VARCHAR(32)",
            "oauth_id": "oauth_id VARCHAR(255)",
            "bio": "bio TEXT",
            "profile_image_url": "profile_image_url VARCHAR(1000)",
            "preferences_json": "preferences_json TEXT",
            "updated_at": "updated_at DATETIME",
            "deleted_at": "deleted_at DATETIME",
        }
        for name, definition in additions.items():
            if name not in columns:
                connection.execute(text(f"ALTER TABLE community_users ADD COLUMN {definition}"))


def get_board_engine():
    global _engine, _SessionLocal
    if _engine is not None:
        return _engine

    path = get_board_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    _engine = create_engine(
        f"sqlite:///{path.as_posix()}",
        connect_args={"timeout": 30, "check_same_thread": False},
        pool_pre_ping=True,
    )

    @event.listens_for(_engine, "connect")
    def _set_pragmas(dbapi_connection, _):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

    with _engine.begin() as connection:
        connection.execute(text("PRAGMA journal_mode=WAL"))

    Base.metadata.create_all(_engine)
    _ensure_auth_columns(_engine)
    _SessionLocal = scoped_session(sessionmaker(bind=_engine, expire_on_commit=False))
    return _engine


def get_board_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        get_board_engine()
    return _SessionLocal


def reset_board_engine() -> None:
    global _engine, _SessionLocal
    if _SessionLocal is not None:
        _SessionLocal.remove()
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
