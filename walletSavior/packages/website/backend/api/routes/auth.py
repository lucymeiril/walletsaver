"""인증 API 라우트"""
import logging
from fastapi import APIRouter, HTTPException, status, Request
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
from fastapi.responses import RedirectResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["인증"])

# 임시 인메모리 저장소 (DB 연결 전까지 사용)
_users_db: dict[str, dict] = {}
_next_id = 1


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def register(request: Request, data: UserRegister):
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

    log_auth_event("register", user_id=user["id"], email=data.email,
                   ip=request.client.host if request.client else "unknown")

    tokens = create_token_pair(user["id"], user["email"], user["role"])
    return TokenResponse(**tokens)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(request: Request, data: UserLogin):
    """로그인 — 이메일/비밀번호"""
    user = _users_db.get(data.email)
    if not user or not verify_password(data.password, user["hashed_password"]):
        log_auth_event("login_failed", email=data.email,
                       ip=request.client.host if request.client else "unknown",
                       status="failed")
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다")

    log_auth_event("login", user_id=user["id"], email=data.email,
                   ip=request.client.host if request.client else "unknown")

    tokens = create_token_pair(user["id"], user["email"], user["role"])
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


@router.get("/oauth/{provider}")
async def oauth_login(provider: str):
    """OAuth 로그인 URL로 리다이렉트"""
    try:
        url = get_oauth_login_url(provider)
        return RedirectResponse(url=url)
    except ValueError:
        raise HTTPException(status_code=400, detail="지원하지 않는 OAuth 제공자입니다")


@router.get("/oauth/{provider}/callback")
async def oauth_callback(request: Request, provider: str, code: str, state: str | None = None):
    """OAuth 콜백 처리 — state 파라미터로 CSRF 방지"""
    global _next_id

    # CSRF state 검증
    if not validate_oauth_state(state):
        log_auth_event("oauth_csrf_failed",
                       ip=request.client.host if request.client else "unknown",
                       status="failed", provider=provider)
        raise HTTPException(status_code=400, detail="OAuth 인증 상태가 유효하지 않습니다. 다시 시도해주세요.")

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

        log_auth_event("oauth_callback", user_id=user["id"], email=user_info.email,
                       ip=request.client.host if request.client else "unknown",
                       provider=provider)

        tokens = create_token_pair(user["id"], user["email"], user["role"])
        # 프론트엔드로 리다이렉트 (토큰 전달)
        return RedirectResponse(
            url=f"http://localhost:5173/auth/callback?access_token={tokens['access_token']}&refresh_token={tokens['refresh_token']}"
        )
    except Exception as e:
        logger.error("OAuth callback failed for provider=%s: %s", provider, str(e), exc_info=True)
        log_auth_event("oauth_failed",
                       ip=request.client.host if request.client else "unknown",
                       status="failed", provider=provider, detail=str(e))
        raise HTTPException(status_code=400, detail="OAuth 인증에 실패했습니다. 다시 시도해주세요.")


@router.get("/me", response_model=UserProfile)
async def get_me():
    """현재 사용자 정보 (인증 필요 — 미들웨어 연동 후 구현)"""
    raise HTTPException(status_code=501, detail="인증 미들웨어 연동 후 구현 예정")
