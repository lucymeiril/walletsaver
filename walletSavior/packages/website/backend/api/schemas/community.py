"""커뮤니티 관련 스키마"""
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class PostType(str, Enum):
    HOTDEAL = "hotdeal"
    FREE = "free"
    QNA = "qna"
    TIP = "tip"


class PostCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1, max_length=50_000)
    post_type: PostType = PostType.FREE
    category: Optional[str] = Field(None, max_length=50)
    price: Optional[float] = Field(None, ge=0, le=100_000_000)
    original_price: Optional[float] = None
    url: Optional[str] = Field(None, max_length=2048)
    images: Optional[list[str]] = Field(None, max_length=10)


class PostUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    content: Optional[str] = Field(None, max_length=50_000)
    category: Optional[str] = Field(None, max_length=50)
    price: Optional[float] = Field(None, ge=0, le=100_000_000)
    url: Optional[str] = Field(None, max_length=2048)


class CommentCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=5_000)
    parent_id: Optional[int] = None


class VoteRequest(BaseModel):
    vote_type: str  # "hot" or "not"


class PostResponse(BaseModel):
    id: int
    title: str
    content: str
    post_type: str
    category: Optional[str] = None
    author_id: int
    author_nickname: str
    views: int = 0
    comments_count: int = 0
    hot_votes: int = 0
    not_votes: int = 0
    price: Optional[float] = None
    original_price: Optional[float] = None
    url: Optional[str] = None
    created_at: str
    updated_at: str


class CommentResponse(BaseModel):
    id: int
    content: str
    author_id: int
    author_nickname: str
    parent_id: Optional[int] = None
    created_at: str
