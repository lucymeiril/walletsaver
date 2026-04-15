"""인증 API 라우트 — SQLAlchemy User/OAuthAccount 모델 기반"""
import logging
import os
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy import select
from api.schemas.auth import (
    UserRegister, UserLogin, TokenResponse, TokenRefresh, UserProfile
)
from services.auth_service import (
    hash_password, verify_password, create_token_pair, decode_token
)
from services.oauth_service import (
    get_oauth_login_url, exchange_code_for_token, get_user_info,
    validate_oauth_state,
)
from services.audit_logger import log_auth_event
from api.middleware.rate_limit import limiter
from api.middleware.auth import require_auth
from fastapi.responses import RedirectResponse
from services.db import managed_session
from storage.models import User, OAuthAccount, OAuthProvider

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["인증"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def register(request: Request, data: UserRegister):
    """회원가입 — 이메일/비밀번호"""
    with managed_session() as session:
        existing = session.execute(
            select(User).where(User.email == data.email)
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=400, detail="이미 등록된 이메일입니다")

        existing_nick = session.execute(
            select(User).where(User.nickname == data.nickname)
        ).scalar_one_or_none()
        if existing_nick:
            raise HTTPException(status_code=400, detail="이미 사용 중인 닉네임입니다")

        user = User(
            email=data.email,
            nickname=data.nickname,
            hashed_password=hash_password(data.password),
        )
        session.add(user)
        session.flush()

        log_auth_event("register", user_id=user.id, email=data.email,
                       ip=request.client.host if request.client else "unknown")

        tokens = create_token_pair(user.id, user.email, user.role.value)

    return TokenResponse(**tokens)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(request: Request, data: UserLogin):
    """로그인 — 이메일/비밀번호"""
    with managed_session() as session:
        user = session.execute(
            select(User).where(User.email == data.email)
        ).scalar_one_or_none()

        if not user or not user.hashed_password or not verify_password(data.password, user.hashed_password):
            log_auth_event("login_failed", email=data.email,
                           ip=request.client.host if request.client else "unknown",
                           status="failed")
            raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다")

        log_auth_event("login", user_id=user.id, email=data.email,
                       ip=request.client.host if request.client else "unknown")

        tokens = create_token_pair(user.id, user.email, user.role.value)

    return TokenResponse(**tokens)


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("5/minute")
async def refresh(request: Request, data: TokenRefresh):
    """토큰 갱신"""
    payload = decode_token(data.refresh_token)
    if not payload or payload.get("type") != "refresh":
        log_auth_event("token_refresh_failed",
                       ip=request.client.host if request.client else "unknown",
                       status="failed")
        raise HTTPException(status_code=401, detail="유효하지 않은 리프레시 토큰입니다")

    log_auth_event("token_refresh", user_id=int(payload["sub"]),
                   ip=request.client.host if request.client else "unknown")

    tokens = create_token_pair(int(payload["sub"]), payload["email"], payload["role"])
    return TokenResponse(**tokens)


@router.post("/logout")
async def logout():
    """로그아웃 — JWT는 클라이언트에서 토큰 삭제로 처리"""
    return {"message": "로그아웃 되었습니다"}


@router.get("/oauth/{provider}")
async def oauth_login(provider: str):
    """OAuth 로그인 URL로 리다이렉트"""
    try:
        url = get_oauth_login_url(provider)
        return RedirectResponse(url=url)
    except ValueError:
        raise HTTPException(status_code=400, detail="지원하지 않는 OAuth 제공자입니다")


def _resolve_unique_nickname(session, base_nickname: str, suffix: str) -> str:
    """닉네임 충돌 시 suffix를 붙여 고유 닉네임을 생성한다."""
    nickname = base_nickname
    if len(nickname) > 50:
        nickname = nickname[:50]
    existing = session.execute(
        select(User).where(User.nickname == nickname)
    ).scalar_one_or_none()
    if not existing:
        return nickname
    # 충돌 시 suffix 추가
    nickname = f"{base_nickname}_{suffix[:4]}"
    if len(nickname) > 50:
        nickname = nickname[:50]
    existing = session.execute(
        select(User).where(User.nickname == nickname)
    ).scalar_one_or_none()
    if not existing:
        return nickname
    # 극히 드문 2차 충돌 — 랜덤 4자리 추가
    import secrets
    return f"{base_nickname[:40]}_{secrets.token_hex(4)}"


@router.get("/oauth/{provider}/callback")
async def oauth_callback(request: Request, provider: str, code: str, state: str | None = None):
    """OAuth 콜백 처리 — state 파라미터로 CSRF 방지"""
    if not validate_oauth_state(state):
        log_auth_event("oauth_csrf_failed",
                       ip=request.client.host if request.client else "unknown",
                       status="failed", provider=provider)
        raise HTTPException(status_code=400, detail="OAuth 인증 상태가 유효하지 않습니다. 다시 시도해주세요.")

    try:
        token_data = await exchange_code_for_token(provider, code)
        user_info = await get_user_info(provider, token_data["access_token"])

        with managed_session() as session:
            oauth_account = session.execute(
                select(OAuthAccount).where(
                    OAuthAccount.provider == OAuthProvider(provider),
                    OAuthAccount.provider_user_id == user_info.provider_user_id,
                )
            ).scalar_one_or_none()

            if oauth_account:
                user = oauth_account.user
                # 토큰 갱신
                oauth_account.access_token = token_data.get("access_token")
                if token_data.get("refresh_token"):
                    oauth_account.refresh_token = token_data.get("refresh_token")
                if user_info.profile_image and user.profile_image != user_info.profile_image:
                    user.profile_image = user_info.profile_image
            else:
                user = session.execute(
                    select(User).where(User.email == user_info.email)
                ).scalar_one_or_none()
                if not user:
                    nickname = _resolve_unique_nickname(
                        session, user_info.nickname, user_info.provider_user_id
                    )
                    user = User(
                        email=user_info.email,
                        nickname=nickname,
                        profile_image=user_info.profile_image,
                    )
                    session.add(user)
                    session.flush()
                oauth_account = OAuthAccount(
                    user_id=user.id,
                    provider=OAuthProvider(provider),
                    provider_user_id=user_info.provider_user_id,
                    access_token=token_data.get("access_token"),
                    refresh_token=token_data.get("refresh_token"),
                )
                session.add(oauth_account)

            log_auth_event("oauth_callback", user_id=user.id, email=user_info.email,
                           ip=request.client.host if request.client else "unknown",
                           provider=provider)

            tokens = create_token_pair(user.id, user.email, user.role.value)

        frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
        return RedirectResponse(
            url=f"{frontend_url}/auth/callback?access_token={tokens['access_token']}&refresh_token={tokens['refresh_token']}"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("OAuth callback failed for provider=%s: %s", provider, str(e), exc_info=True)
        log_auth_event("oauth_failed",
                       ip=request.client.host if request.client else "unknown",
                       status="failed", provider=provider, detail=str(e))
        raise HTTPException(status_code=400, detail="OAuth 인증에 실패했습니다. 다시 시도해주세요.")


@router.get("/me", response_model=UserProfile)
async def get_me(user: dict = Depends(require_auth)):
    """현재 사용자 프로필 조회"""
    with managed_session() as session:
        db_user = session.execute(
            select(User).where(User.id == user["id"])
        ).scalar_one_or_none()
        if not db_user:
            raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")
        return UserProfile(
            id=db_user.id,
            email=db_user.email,
            nickname=db_user.nickname,
            role=db_user.role.value,
            created_at=db_user.created_at.isoformat(),
            profile_image=db_user.profile_image,
        )
