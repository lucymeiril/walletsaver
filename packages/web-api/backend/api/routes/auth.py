"""인증 API 라우트 — 공개 회원 계정은 board SQLite에 영구 저장한다."""
import os

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse

from api.schemas.auth import (
    UserRegister, UserLogin, TokenResponse, TokenRefresh, UserProfile
)
from services.auth_service import (
    hash_password, verify_password, create_token_pair, decode_token
)
from services.board_storage import User, get_board_session_factory
from services.oauth_service import (
    get_oauth_login_url, exchange_code_for_token, get_user_info,
    validate_oauth_state,
)

router = APIRouter(prefix="/api/auth", tags=["인증"])
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
_COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"


def _set_auth_cookies(response, tokens: dict) -> None:
    response.set_cookie(
        key="access_token",
        value=tokens["access_token"],
        httponly=True,
        secure=_COOKIE_SECURE,
        samesite="lax",
        path="/",
        max_age=tokens["expires_in"],
    )
    response.set_cookie(
        key="refresh_token",
        value=tokens["refresh_token"],
        httponly=True,
        secure=_COOKIE_SECURE,
        samesite="lax",
        path="/api/auth",
        max_age=7 * 24 * 3600,
    )


def _clear_auth_cookies(response) -> None:
    response.delete_cookie(key="access_token", path="/")
    response.delete_cookie(key="refresh_token", path="/api/auth")


def _profile_from_user(user: User) -> UserProfile:
    return UserProfile(
        id=int(user.id),
        email=user.email,
        nickname=user.nickname,
        role=user.role or "user",
        created_at=user.created_at.isoformat() if user.created_at else "",
    )


def _active_user_by_id(user_id: int) -> User | None:
    factory = get_board_session_factory()
    with factory() as session:
        user = session.get(User, int(user_id))
        if not user or user.is_deleted or user.is_active is False:
            return None
        session.expunge(user)
        return user


def _active_user_from_payload(payload: dict | None, token_type: str) -> User | None:
    if not payload or payload.get("type") != token_type:
        return None
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        return None
    return _active_user_by_id(user_id)


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(data: UserRegister):
    """회원가입 — 이메일/비밀번호를 영구 저장한다."""
    email = str(data.email).strip().lower()
    nickname = data.nickname.strip()
    factory = get_board_session_factory()
    with factory() as session:
        if session.query(User).filter(User.email == email).first():
            raise HTTPException(status_code=400, detail="이미 등록된 이메일입니다")
        if session.query(User).filter(User.nickname == nickname, User.is_deleted.is_(False)).first():
            raise HTTPException(status_code=400, detail="이미 사용 중인 닉네임입니다")

        user = User(
            email=email,
            nickname=nickname,
            hashed_password=hash_password(data.password),
            role="user",
            is_active=True,
            is_deleted=False,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        tokens = create_token_pair(user.id, user.email, user.role)

    response = JSONResponse(content=TokenResponse(**tokens).model_dump(), status_code=201)
    _set_auth_cookies(response, tokens)
    return response


@router.post("/login", response_model=TokenResponse)
async def login(data: UserLogin):
    """로그인 — 저장된 계정과 비밀번호를 검증한다."""
    email = str(data.email).strip().lower()
    factory = get_board_session_factory()
    with factory() as session:
        user = session.query(User).filter(User.email == email).first()
        if (
            not user
            or user.is_deleted
            or user.is_active is False
            or not user.hashed_password
            or not verify_password(data.password, user.hashed_password)
        ):
            raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다")
        tokens = create_token_pair(user.id, user.email, user.role or "user")

    response = JSONResponse(content=TokenResponse(**tokens).model_dump())
    _set_auth_cookies(response, tokens)
    return response


@router.post("/refresh", response_model=TokenResponse)
async def refresh(request: Request, data: TokenRefresh | None = None):
    """토큰 갱신 — DB에서 계정 상태를 다시 확인한다."""
    refresh_token = data.refresh_token if data else request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=401, detail="유효하지 않은 리프레시 토큰입니다")
    user = _active_user_from_payload(decode_token(refresh_token), "refresh")
    if user is None:
        raise HTTPException(status_code=401, detail="유효하지 않은 리프레시 토큰입니다")

    tokens = create_token_pair(user.id, user.email, user.role or "user")
    response = JSONResponse(content=TokenResponse(**tokens).model_dump())
    _set_auth_cookies(response, tokens)
    return response


@router.post("/logout")
async def logout():
    response = JSONResponse(content={"success": True, "data": {"message": "로그아웃 되었습니다"}})
    _clear_auth_cookies(response)
    return response


@router.post("/demo-login")
async def demo_login(provider: str = "google"):
    """명시적으로 호출할 때만 쓰는 로컬 데모 계정."""
    email = f"demo-{provider}@walletsavior.local"
    factory = get_board_session_factory()
    with factory() as session:
        user = session.query(User).filter(User.email == email).first()
        if not user:
            user = User(
                email=email,
                nickname="발표용 데모 사용자",
                hashed_password=None,
                role="user",
                oauth_provider=provider,
                is_active=True,
                is_deleted=False,
            )
            session.add(user)
            session.commit()
            session.refresh(user)
        elif user.is_deleted or user.is_active is False:
            raise HTTPException(status_code=403, detail="비활성화된 계정입니다")
        tokens = create_token_pair(user.id, user.email, user.role or "user")
        profile = _profile_from_user(user).model_dump()

    response = JSONResponse(content={"success": True, "data": profile})
    _set_auth_cookies(response, tokens)
    return response


@router.get("/oauth/{provider}")
async def oauth_login(provider: str):
    """OAuth 로그인 URL로 리다이렉트."""
    try:
        url = get_oauth_login_url(provider)
        return RedirectResponse(url=url)
    except ValueError as exc:
        if "지원하지 않는 OAuth 공급자" in str(exc):
            raise HTTPException(status_code=400, detail=str(exc))
        return RedirectResponse(
            url=f"{FRONTEND_URL}/auth/callback?error=oauth_config&provider={provider}",
            status_code=302,
        )


@router.get("/oauth/{provider}/callback")
async def oauth_callback(provider: str, code: str, state: str | None = None):
    """OAuth 콜백 처리 — 공급자 ID를 우선 키로 사용해 계정을 영구 저장한다."""
    if not validate_oauth_state(state):
        return RedirectResponse(url=f"{FRONTEND_URL}/auth/callback?error=oauth_state", status_code=302)
    try:
        token_data = await exchange_code_for_token(provider, code)
        user_info = await get_user_info(provider, token_data["access_token"])
        provider_id = str(user_info.provider_user_id)
        real_email = (user_info.email or "").strip().lower()
        # Some Kakao/Naver users do not grant e-mail. Keep a stable internal
        # identifier rather than inserting an empty/duplicate e-mail value.
        stored_email = real_email or f"{provider}-{provider_id}@oauth.walletsavior.local"

        factory = get_board_session_factory()
        with factory() as session:
            user = (
                session.query(User)
                .filter(User.oauth_provider == provider, User.oauth_id == provider_id)
                .first()
            )
            if user is None and real_email:
                user = session.query(User).filter(User.email == real_email).first()

            if not user:
                base_nickname = (user_info.nickname or "").strip() or f"{provider}_{provider_id}"
                nickname = base_nickname
                suffix = 2
                while session.query(User).filter(
                    User.nickname == nickname,
                    User.is_deleted.is_(False),
                ).first():
                    nickname = f"{base_nickname}_{suffix}"
                    suffix += 1
                user = User(
                    email=stored_email,
                    nickname=nickname,
                    hashed_password=None,
                    role="user",
                    oauth_provider=provider,
                    oauth_id=provider_id,
                    profile_image_url=user_info.profile_image,
                    is_active=True,
                    is_deleted=False,
                )
                session.add(user)
            else:
                if user.is_deleted or user.is_active is False:
                    return RedirectResponse(
                        url=f"{FRONTEND_URL}/auth/callback?error=account_disabled",
                        status_code=302,
                    )
                user.oauth_provider = provider
                user.oauth_id = provider_id
                if real_email and user.email.endswith("@oauth.walletsavior.local"):
                    email_owner = session.query(User).filter(
                        User.email == real_email,
                        User.id != user.id,
                    ).first()
                    if email_owner is None:
                        user.email = real_email
                if user_info.profile_image:
                    user.profile_image_url = user_info.profile_image
            session.commit()
            session.refresh(user)
            tokens = create_token_pair(user.id, user.email, user.role or "user")

        response = RedirectResponse(url=f"{FRONTEND_URL}/auth/callback", status_code=302)
        _set_auth_cookies(response, tokens)
        return response
    except Exception:
        return RedirectResponse(url=f"{FRONTEND_URL}/auth/callback?error=oauth_failed", status_code=302)


@router.get("/me", response_model=UserProfile)
async def get_me(request: Request):
    """현재 사용자 정보 — 토큰의 ID를 DB에서 다시 검증한다."""
    token = request.cookies.get("access_token")
    auth_header = request.headers.get("authorization", "")
    if not token and auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1]
    user = _active_user_from_payload(decode_token(token) if token else None, "access")
    if user is None:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")
    return _profile_from_user(user)
