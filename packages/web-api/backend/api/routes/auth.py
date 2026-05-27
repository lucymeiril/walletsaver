"""인증 API 라우트"""
import os

from fastapi import APIRouter, HTTPException, Request, status
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
from fastapi.responses import JSONResponse, RedirectResponse

router = APIRouter(prefix="/api/auth", tags=["인증"])
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
_COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"

# 임시 인메모리 저장소 (DB 연결 전까지 사용)
_users_db: dict[str, dict] = {}
_next_id = 1


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


def _profile_from_payload(payload: dict) -> UserProfile:
    email = payload.get("email", "")
    user = _users_db.get(email) or {}
    return UserProfile(
        id=int(payload["sub"]),
        email=email,
        nickname=user.get("nickname") or email.split("@")[0] or "사용자",
        role=payload.get("role", "user"),
        created_at=user.get("created_at") or "",
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(data: UserRegister):
    """회원가입 — 이메일/비밀번호"""
    global _next_id

    if data.email in _users_db:
        raise HTTPException(status_code=400, detail="이미 등록된 이메일입니다")

    # 닉네임 중복 체크
    for user in _users_db.values():
        if user["nickname"] == data.nickname:
            raise HTTPException(status_code=400, detail="이미 사용 중인 닉네임입니다")

    user = {
        "id": _next_id,
        "email": data.email,
        "nickname": data.nickname,
        "hashed_password": hash_password(data.password),
        "role": "user",
    }
    _users_db[data.email] = user
    _next_id += 1

    tokens = create_token_pair(user["id"], user["email"], user["role"])
    response = JSONResponse(content=TokenResponse(**tokens).model_dump(), status_code=201)
    _set_auth_cookies(response, tokens)
    return response


@router.post("/login", response_model=TokenResponse)
async def login(data: UserLogin):
    """로그인 — 이메일/비밀번호"""
    user = _users_db.get(data.email)
    if not user or not verify_password(data.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다")

    tokens = create_token_pair(user["id"], user["email"], user["role"])
    response = JSONResponse(content=TokenResponse(**tokens).model_dump())
    _set_auth_cookies(response, tokens)
    return response


@router.post("/refresh", response_model=TokenResponse)
async def refresh(request: Request, data: TokenRefresh | None = None):
    """토큰 갱신"""
    refresh_token = data.refresh_token if data else request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=401, detail="유효하지 않은 리프레시 토큰입니다")
    payload = decode_token(refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="유효하지 않은 리프레시 토큰입니다")

    tokens = create_token_pair(int(payload["sub"]), payload["email"], payload["role"])
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
    """발표/로컬 검증용 데모 로그인 — 실제 OAuth 미설정 환경에서도 서버 쿠키를 발급한다."""
    global _next_id
    email = f"demo-{provider}@walletsavior.local"
    user = _users_db.get(email)
    if not user:
        user = {
            "id": _next_id,
            "email": email,
            "nickname": "발표용 데모 사용자",
            "hashed_password": None,
            "role": "user",
            "oauth_provider": provider,
        }
        _users_db[email] = user
        _next_id += 1
    tokens = create_token_pair(user["id"], user["email"], user["role"])
    response = JSONResponse(content={"success": True, "data": _profile_from_payload({"sub": str(user["id"]), "email": email, "role": "user"}).model_dump()})
    _set_auth_cookies(response, tokens)
    return response


@router.get("/oauth/{provider}")
async def oauth_login(provider: str):
    """OAuth 로그인 URL로 리다이렉트"""
    try:
        url = get_oauth_login_url(provider)
        return RedirectResponse(url=url)
    except ValueError as e:
        if "지원하지 않는 OAuth 공급자" in str(e):
            raise HTTPException(status_code=400, detail=str(e))
        return RedirectResponse(url=f"{FRONTEND_URL}/auth/callback?error=oauth_config&provider={provider}", status_code=302)


@router.get("/oauth/{provider}/callback")
async def oauth_callback(provider: str, code: str, state: str | None = None):
    """OAuth 콜백 처리"""
    global _next_id
    if not validate_oauth_state(state):
        return RedirectResponse(url=f"{FRONTEND_URL}/auth/callback?error=oauth_state", status_code=302)
    try:
        token_data = await exchange_code_for_token(provider, code)
        user_info = await get_user_info(provider, token_data["access_token"])

        # 기존 사용자 확인 또는 신규 생성
        user = _users_db.get(user_info.email)
        if not user:
            user = {
                "id": _next_id,
                "email": user_info.email,
                "nickname": user_info.nickname,
                "hashed_password": None,
                "role": "user",
                "oauth_provider": provider,
                "oauth_id": user_info.provider_user_id,
            }
            _users_db[user_info.email] = user
            _next_id += 1

        tokens = create_token_pair(user["id"], user["email"], user["role"])
        response = RedirectResponse(url=f"{FRONTEND_URL}/auth/callback", status_code=302)
        _set_auth_cookies(response, tokens)
        return response
    except Exception as e:
        return RedirectResponse(url=f"{FRONTEND_URL}/auth/callback?error=oauth_failed", status_code=302)


@router.get("/me", response_model=UserProfile)
async def get_me(request: Request):
    """현재 사용자 정보 — 쿠키/토큰이 없으면 정상적으로 미인증 처리."""
    token = request.cookies.get("access_token")
    auth_header = request.headers.get("authorization", "")
    if not token and auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1]
    payload = decode_token(token) if token else None
    if not payload or payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")
    return _profile_from_payload(payload)
