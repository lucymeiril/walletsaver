"""커뮤니티 관련 스키마"""
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class PostType(str, Enum):
    HOTDEAL = "hotdeal"
    FREE = "free"
    QNA = "qna"
    TIP = "tip"


class PostCreate(BaseModel):
    title: str
    content: str
    post_type: PostType = PostType.FREE
    category: Optional[str] = None
    tags: Optional[list[str]] = None
    price: Optional[float] = None
    original_price: Optional[float] = None
    url: Optional[str] = None
    images: Optional[list[str]] = None


class PostUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[list[str]] = None
    price: Optional[float] = None
    original_price: Optional[float] = None
    url: Optional[str] = None


class CommentCreate(BaseModel):
    content: str
    parent_id: Optional[int] = None


class VoteRequest(BaseModel):
    vote_type: str  # "hot" or "not"


class PostResponse(BaseModel):
    id: int
    title: str
    content: str
    post_type: str
    category: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    author_id: int
    author_nickname: str
    views: int = 0
    comments_count: int = 0
    hot_votes: int = 0
    not_votes: int = 0
    price: Optional[float] = None
    original_price: Optional[float] = None
    url: Optional[str] = None
    images: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str


class CommentResponse(BaseModel):
    id: int
    content: str
    author_id: int
    author_nickname: str
    parent_id: Optional[int] = None
    created_at: str
