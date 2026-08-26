"""Authentication API backed by web-api's server-owned accounts SQLite."""
import os

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse

from api.schemas.auth import UserLogin, UserProfile, UserRegister, TokenRefresh, TokenResponse
from services.auth_service import create_token_pair, decode_token, hash_password, verify_password
from services.oauth_service import (
    exchange_code_for_token,
    get_oauth_login_url,
    get_user_info,
    validate_oauth_state,
)
from services.user_storage import PublicUserStore, PublicUserStoreError

router = APIRouter(prefix="/api/auth", tags=["인증"])
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
_COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"


def _store(request: Request) -> PublicUserStore:
    try:
        return PublicUserStore(request.app.state.storage)
    except PublicUserStoreError as exc:
        raise HTTPException(status_code=503, detail="회원 데이터 저장소를 사용할 수 없습니다") from exc


def _is_active(user: dict | None) -> bool:
    return bool(user and user.get("is_active") and not user.get("is_deleted"))


def _profile(user: dict) -> UserProfile:
    return UserProfile(
        id=int(user["id"]),
        email=user["email"],
        nickname=user["nickname"],
        role=user.get("role") or "user",
        created_at=user.get("created_at") or "",
    )


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


def _user_from_token(request: Request, token: str | None, token_type: str) -> dict | None:
    payload = decode_token(token) if token else None
    if not payload or payload.get("type") != token_type:
        return None
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        return None
    user = _store(request).get_by_id(user_id)
    return user if _is_active(user) else None


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(request: Request, data: UserRegister):
    """회원가입 — accounts.sqlite users 테이블에 실제 계정을 생성한다."""
    store = _store(request)
    try:
        user = store.create_password_user(
            email=str(data.email),
            nickname=data.nickname,
            hashed_password=hash_password(data.password),
        )
    except PublicUserStoreError as exc:
        if str(exc) == "email_exists":
            raise HTTPException(status_code=400, detail="이미 등록된 이메일입니다") from exc
        if str(exc) == "nickname_exists":
            raise HTTPException(status_code=400, detail="이미 사용 중인 닉네임입니다") from exc
        raise

    tokens = create_token_pair(user["id"], user["email"], user["role"])
    response = JSONResponse(content=TokenResponse(**tokens).model_dump(), status_code=201)
    _set_auth_cookies(response, tokens)
    return response


@router.post("/login", response_model=TokenResponse)
async def login(request: Request, data: UserLogin):
    """로그인 — 영구 계정과 비밀번호를 검증한다."""
    user = _store(request).get_by_email(str(data.email), include_password=True)
    if (
        not _is_active(user)
        or not user.get("hashed_password")
        or not verify_password(data.password, user["hashed_password"])
    ):
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다")

    tokens = create_token_pair(user["id"], user["email"], user["role"])
    response = JSONResponse(content=TokenResponse(**tokens).model_dump())
    _set_auth_cookies(response, tokens)
    return response


@router.post("/refresh", response_model=TokenResponse)
async def refresh(request: Request, data: TokenRefresh | None = None):
    """토큰 갱신 — 토큰의 user id를 accounts.sqlite에서 다시 확인한다."""
    refresh_token = data.refresh_token if data else request.cookies.get("refresh_token")
    user = _user_from_token(request, refresh_token, "refresh")
    if user is None:
        raise HTTPException(status_code=401, detail="유효하지 않은 리프레시 토큰입니다")

    tokens = create_token_pair(user["id"], user["email"], user["role"])
    response = JSONResponse(content=TokenResponse(**tokens).model_dump())
    _set_auth_cookies(response, tokens)
    return response


@router.post("/logout")
async def logout():
    response = JSONResponse(content={"success": True, "data": {"message": "로그아웃 되었습니다"}})
    _clear_auth_cookies(response)
    return response


@router.post("/demo-login")
async def demo_login(request: Request, provider: str = "google"):
    """로컬 발표용 기능. 명시적으로 ENABLE_DEMO_LOGIN=true인 환경에서만 허용한다."""
    if os.getenv("ENABLE_DEMO_LOGIN", "false").strip().lower() not in {"1", "true", "yes"}:
        raise HTTPException(status_code=404, detail="찾을 수 없습니다")
    if provider not in {"google", "kakao", "naver"}:
        raise HTTPException(status_code=400, detail="지원하지 않는 데모 공급자입니다")

    user = _store(request).ensure_demo_user(
        email=f"demo-{provider}@walletsavior.local",
        nickname="발표용 데모 사용자",
    )
    if not _is_active(user):
        raise HTTPException(status_code=403, detail="비활성화된 계정입니다")
    tokens = create_token_pair(user["id"], user["email"], user["role"])
    response = JSONResponse(content={"success": True, "data": _profile(user).model_dump()})
    _set_auth_cookies(response, tokens)
    return response


@router.get("/oauth/{provider}")
async def oauth_login(provider: str):
    """OAuth 로그인 URL로 리다이렉트."""
    try:
        return RedirectResponse(url=get_oauth_login_url(provider))
    except ValueError as exc:
        if "지원하지 않는 OAuth 공급자" in str(exc):
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse(
            url=f"{FRONTEND_URL}/auth/callback?error=oauth_config&provider={provider}",
            status_code=302,
        )


@router.get("/oauth/{provider}/callback")
async def oauth_callback(request: Request, provider: str, code: str, state: str | None = None):
    """OAuth 콜백 — OAuth 계정과 accounts.sqlite 사용자를 연결한다."""
    if not validate_oauth_state(state):
        return RedirectResponse(url=f"{FRONTEND_URL}/auth/callback?error=oauth_state", status_code=302)
    try:
        token_data = await exchange_code_for_token(provider, code)
        info = await get_user_info(provider, token_data["access_token"])
        user = _store(request).upsert_oauth_user(
            provider=provider,
            provider_user_id=info.provider_user_id,
            email=info.email,
            nickname=info.nickname,
            profile_image_url=info.profile_image,
        )
        if not _is_active(user):
            return RedirectResponse(
                url=f"{FRONTEND_URL}/auth/callback?error=account_disabled",
                status_code=302,
            )
        tokens = create_token_pair(user["id"], user["email"], user["role"])
        response = RedirectResponse(url=f"{FRONTEND_URL}/auth/callback", status_code=302)
        _set_auth_cookies(response, tokens)
        return response
    except PublicUserStoreError:
        return RedirectResponse(url=f"{FRONTEND_URL}/auth/callback?error=oauth_failed", status_code=302)
    except Exception:
        return RedirectResponse(url=f"{FRONTEND_URL}/auth/callback?error=oauth_failed", status_code=302)


@router.get("/me", response_model=UserProfile)
async def get_me(request: Request):
    """현재 사용자 정보 — JWT id를 accounts.sqlite users 테이블에서 재검증한다."""
    token = request.cookies.get("access_token")
    auth_header = request.headers.get("authorization", "")
    if not token and auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1]
    user = _user_from_token(request, token, "access")
    if user is None:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")
    return _profile(user)
