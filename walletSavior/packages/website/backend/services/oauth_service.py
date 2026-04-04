"""OAuth 서비스 — Google, Kakao, Naver OAuth 2.0 처리"""
import httpx
import os
import secrets
from typing import Optional
from dataclasses import dataclass


@dataclass
class OAuthUserInfo:
    """OAuth 공급자로부터 받은 사용자 정보"""
    provider: str
    provider_user_id: str
    email: str
    nickname: str
    profile_image: Optional[str] = None


class OAuthConfig:
    """OAuth 공급자별 설정"""

    GOOGLE = {
        "client_id": os.getenv("GOOGLE_CLIENT_ID", ""),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", ""),
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "userinfo_url": "https://www.googleapis.com/oauth2/v2/userinfo",
        "scope": "openid email profile",
    }

    KAKAO = {
        "client_id": os.getenv("KAKAO_CLIENT_ID", ""),
        "client_secret": os.getenv("KAKAO_CLIENT_SECRET", ""),
        "auth_url": "https://kauth.kakao.com/oauth/authorize",
        "token_url": "https://kauth.kakao.com/oauth/token",
        "userinfo_url": "https://kapi.kakao.com/v2/user/me",
        "scope": "profile_nickname account_email",
    }

    NAVER = {
        "client_id": os.getenv("NAVER_CLIENT_ID", ""),
        "client_secret": os.getenv("NAVER_CLIENT_SECRET", ""),
        "auth_url": "https://nid.naver.com/oauth2.0/authorize",
        "token_url": "https://nid.naver.com/oauth2.0/token",
        "userinfo_url": "https://openapi.naver.com/v1/nid/me",
        "scope": "",
    }

    @classmethod
    def get(cls, provider: str) -> dict:
        configs = {
            "google": cls.GOOGLE,
            "kakao": cls.KAKAO,
            "naver": cls.NAVER,
        }
        config = configs.get(provider)
        if not config:
            raise ValueError(f"지원하지 않는 OAuth 공급자: {provider}")
        return config


REDIRECT_BASE = os.getenv("OAUTH_REDIRECT_BASE", "http://localhost:8000")

# In-memory OAuth state store for CSRF protection (TTL: 10 minutes)
_oauth_states: dict[str, float] = {}
_OAUTH_STATE_TTL = 600  # seconds


def _cleanup_expired_states():
    """Remove expired OAuth state tokens."""
    import time
    now = time.time()
    expired = [k for k, v in _oauth_states.items() if now - v > _OAUTH_STATE_TTL]
    for k in expired:
        _oauth_states.pop(k, None)


def generate_oauth_state() -> str:
    """Generate a cryptographic random state token for CSRF protection."""
    _cleanup_expired_states()
    import time
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = time.time()
    return state


def validate_oauth_state(state: str | None) -> bool:
    """Validate and consume an OAuth state token. Returns False if invalid/expired."""
    if not state:
        return False
    import time
    ts = _oauth_states.pop(state, None)
    if ts is None:
        return False
    if time.time() - ts > _OAUTH_STATE_TTL:
        return False
    return True


def get_oauth_login_url(provider: str) -> str:
    """OAuth 로그인 URL 생성 (with CSRF state parameter)"""
    config = OAuthConfig.get(provider)
    state = generate_oauth_state()
    params = {
        "client_id": config["client_id"],
        "redirect_uri": f"{REDIRECT_BASE}/api/auth/oauth/{provider}/callback",
        "response_type": "code",
        "scope": config["scope"],
        "state": state,
    }
    query = "&".join(f"{k}={v}" for k, v in params.items() if v)
    return f"{config['auth_url']}?{query}"


async def exchange_code_for_token(provider: str, code: str) -> dict:
    """인가 코드를 액세스 토큰으로 교환"""
    config = OAuthConfig.get(provider)
    async with httpx.AsyncClient() as client:
        response = await client.post(
            config["token_url"],
            data={
                "grant_type": "authorization_code",
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
                "code": code,
                "redirect_uri": f"{REDIRECT_BASE}/api/auth/oauth/{provider}/callback",
            },
        )
        response.raise_for_status()
        return response.json()


async def get_user_info(provider: str, access_token: str) -> OAuthUserInfo:
    """OAuth 공급자로부터 사용자 정보 조회"""
    config = OAuthConfig.get(provider)
    headers = {"Authorization": f"Bearer {access_token}"}

    async with httpx.AsyncClient() as client:
        response = await client.get(config["userinfo_url"], headers=headers)
        response.raise_for_status()
        data = response.json()

    if provider == "google":
        return OAuthUserInfo(
            provider="google",
            provider_user_id=str(data["id"]),
            email=data["email"],
            nickname=data.get("name", data["email"].split("@")[0]),
            profile_image=data.get("picture"),
        )
    elif provider == "kakao":
        account = data.get("kakao_account", {})
        profile = account.get("profile", {})
        return OAuthUserInfo(
            provider="kakao",
            provider_user_id=str(data["id"]),
            email=account.get("email", ""),
            nickname=profile.get("nickname", f"kakao_{data['id']}"),
            profile_image=profile.get("profile_image_url"),
        )
    elif provider == "naver":
        info = data.get("response", {})
        return OAuthUserInfo(
            provider="naver",
            provider_user_id=info["id"],
            email=info.get("email", ""),
            nickname=info.get("nickname", f"naver_{info['id']}"),
            profile_image=info.get("profile_image"),
        )
    else:
        raise ValueError(f"지원하지 않는 OAuth 공급자: {provider}")
