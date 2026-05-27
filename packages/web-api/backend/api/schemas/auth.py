"""인증 요청/응답 스키마"""
from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional
from enum import Enum


class OAuthProvider(str, Enum):
    GOOGLE = "google"
    KAKAO = "kakao"
    NAVER = "naver"


class UserRegister(BaseModel):
    email: EmailStr
    password: str
    nickname: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError("비밀번호는 8자 이상이어야 합니다")
        if not any(c.isdigit() for c in v):
            raise ValueError("비밀번호에 숫자가 포함되어야 합니다")
        return v

    @field_validator("nickname")
    @classmethod
    def validate_nickname(cls, v):
        if len(v) < 2 or len(v) > 20:
            raise ValueError("닉네임은 2-20자여야 합니다")
        return v


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class TokenRefresh(BaseModel):
    refresh_token: str


class UserProfile(BaseModel):
    id: int
    email: str
    nickname: str
    role: str
    created_at: str

    class Config:
        from_attributes = True


class OAuthCallback(BaseModel):
    code: str
    state: Optional[str] = None
