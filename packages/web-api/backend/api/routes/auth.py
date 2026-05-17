"""Auth API routes — register/login/logout/me."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from services.auth import (
    SESSION_COOKIE,
    create_session,
    delete_session,
    get_current_user,
    hash_password,
    verify_password,
)
from storage.board_models import User, get_board_db

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterReq(BaseModel):
    email: str = Field(min_length=3, max_length=128)
    display_name: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=6, max_length=128)


class LoginReq(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    user_id: str
    email: str
    display_name: str
    role: str


def _user_out(u: User) -> UserOut:
    return UserOut(
        user_id=u.id, email=u.email, display_name=u.display_name, role=u.role
    )


@router.post("/register", status_code=201, response_model=UserOut)
def register(body: RegisterReq, db: Session = Depends(get_board_db)):
    existing = db.query(User).filter(User.email == str(body.email).lower().strip()).first()
    if existing:
        raise HTTPException(status_code=409, detail="email_already_exists")
    user = User(
        email=str(body.email).lower().strip(),
        password_hash=hash_password(body.password),
        display_name=body.display_name,
        role="user",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _user_out(user)


@router.post("/login", response_model=UserOut)
def login(body: LoginReq, response: Response, db: Session = Depends(get_board_db)):
    user = db.query(User).filter(User.email == str(body.email).lower().strip()).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid_credentials")
    if user.banned_at:
        raise HTTPException(status_code=403, detail="user_banned")
    token = create_session(db, user.id)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24,
        path="/",
    )
    return _user_out(user)


from fastapi import Request  # noqa: E402


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_board_db)):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        delete_session(db, token)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: User | None = Depends(get_current_user)):
    if user is None:
        raise HTTPException(status_code=401, detail="auth_required")
    return _user_out(user)
