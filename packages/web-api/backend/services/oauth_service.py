"""OAuth 서비스 — Google, Kakao, Naver OAuth 2.0 처리"""
import json
import hashlib
import os
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode
from typing import Optional
from dataclasses import dataclass

import httpx
from dotenv import load_dotenv


@dataclass
class OAuthUserInfo:
    """OAuth 공급자로부터 받은 사용자 정보"""
    provider: str
    provider_user_id: str
    email: str
    nickname: str
    profile_image: Optional[str] = None
    email_verified: bool = False


class OAuthConfig:
    """OAuth 공급자별 설정"""

    _PROVIDERS = {
        "google": {
            "client_id_env": "GOOGLE_CLIENT_ID",
            "client_secret_env": "GOOGLE_CLIENT_SECRET",
            "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_url": "https://oauth2.googleapis.com/token",
            "userinfo_url": "https://www.googleapis.com/oauth2/v2/userinfo",
            "scope": "openid email profile",
        },
        "kakao": {
            "client_id_env": "KAKAO_CLIENT_ID",
            "client_secret_env": "KAKAO_CLIENT_SECRET",
            "auth_url": "https://kauth.kakao.com/oauth/authorize",
            "token_url": "https://kauth.kakao.com/oauth/token",
            "userinfo_url": "https://kapi.kakao.com/v2/user/me",
            "scope": "profile_nickname account_email",
        },
        "naver": {
            "client_id_env": "NAVER_CLIENT_ID",
            "client_secret_env": "NAVER_CLIENT_SECRET",
            "auth_url": "https://nid.naver.com/oauth2.0/authorize",
            "token_url": "https://nid.naver.com/oauth2.0/token",
            "userinfo_url": "https://openapi.naver.com/v1/nid/me",
            "scope": "",
        },
    }

    @classmethod
    def get(cls, provider: str) -> dict:
        load_dotenv(Path(__file__).resolve().parent.parent / ".env")
        template = cls._PROVIDERS.get(provider)
        if not template:
            raise ValueError(f"지원하지 않는 OAuth 공급자: {provider}")
        client_id = os.getenv(template["client_id_env"], "").strip()
        client_secret = os.getenv(template["client_secret_env"], "").strip()
        if provider == "google" and (not client_id or not client_secret):
            file_client_id, file_client_secret = _google_credentials_from_file()
            client_id = client_id or file_client_id
            client_secret = client_secret or file_client_secret
        return {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_url": template["auth_url"],
            "token_url": template["token_url"],
            "userinfo_url": template["userinfo_url"],
            "scope": template["scope"],
        }


def _google_credentials_from_file() -> tuple[str, str]:
    """Load a downloaded Google OAuth JSON without copying its secret to .env."""
    configured_path = os.getenv("GOOGLE_CLIENT_SECRET_FILE", "").strip()
    if not configured_path:
        return "", ""
    path = Path(configured_path).expanduser()
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        config = payload.get("web") or payload.get("installed") or {}
        return (
            str(config.get("client_id") or "").strip(),
            str(config.get("client_secret") or "").strip(),
        )
    except (OSError, ValueError, TypeError):
        return "", ""


def _redirect_base() -> str:
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    return os.getenv("OAUTH_REDIRECT_BASE", "http://localhost:8000").strip().rstrip("/")


def get_oauth_redirect_uri(provider: str) -> str:
    """Return the one callback URI used by both authorization and token exchange."""
    if provider not in OAuthConfig._PROVIDERS:
        raise ValueError(f"지원하지 않는 OAuth 공급자: {provider}")
    return f"{_redirect_base()}/api/auth/oauth/{provider}/callback"


OAUTH_STATE_TTL = 600


def generate_oauth_state(provider: str, browser_binding: str, *, state_store) -> str:
    if provider not in OAuthConfig._PROVIDERS or not isinstance(browser_binding, str) or not browser_binding:
        raise ValueError("OAuth state requires a supported provider and browser binding")
    state = secrets.token_urlsafe(32)
    now = time.time()
    state_store.issue_oauth_state(
        state_digest=hashlib.sha256(state.encode()).hexdigest(), provider=provider,
        browser_digest=hashlib.sha256(browser_binding.encode()).hexdigest(),
        created_at=now, expires_at=now + OAUTH_STATE_TTL,
    )
    return state


def validate_oauth_state(state: str | None, provider: str, browser_binding: str | None, *, state_store) -> bool:
    if not isinstance(state, str) or not state:
        return False
    # Consume before any await/token exchange: denied, mismatched and expired
    # callbacks cannot replay an authorization across workers or restarts.
    entry = state_store.consume_oauth_state(hashlib.sha256(state.encode()).hexdigest())
    if entry is None or not isinstance(browser_binding, str) or not browser_binding:
        return False
    now = time.time()
    return (
        entry["provider"] == provider
        and entry["created_at"] <= now < entry["expires_at"]
        and secrets.compare_digest(entry["browser_digest"], hashlib.sha256(browser_binding.encode()).hexdigest())
    )


def get_oauth_login_url(provider: str, browser_binding: str, *, state_store) -> str:
    """OAuth 로그인 URL 생성"""
    config = OAuthConfig.get(provider)
    if not config["client_id"]:
        raise ValueError(f"{provider} OAuth client_id가 설정되지 않았습니다")
    if not config["client_secret"]:
        raise ValueError(f"{provider} OAuth client_secret이 설정되지 않았습니다")
    params = {
        "client_id": config["client_id"],
        "redirect_uri": get_oauth_redirect_uri(provider),
        "response_type": "code",
        "scope": config["scope"],
        "state": generate_oauth_state(provider, browser_binding, state_store=state_store),
    }
    if provider == "google":
        params["access_type"] = "offline"
        params["prompt"] = "consent"
    query = urlencode({k: v for k, v in params.items() if v})
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
                "redirect_uri": get_oauth_redirect_uri(provider),
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

    if not isinstance(data, dict):
        raise ValueError("Invalid OAuth userinfo response")

    if provider == "google":
        return OAuthUserInfo(
            provider="google",
            provider_user_id=_provider_user_id(data.get("id")),
            email=data.get("email") if isinstance(data.get("email"), str) else "",
            nickname=data.get("name") or "google 사용자",
            profile_image=data.get("picture"),
            email_verified=data.get("verified_email") is True,
        )
    elif provider == "kakao":
        account = data.get("kakao_account", {})
        profile = account.get("profile", {})
        return OAuthUserInfo(
            provider="kakao",
            provider_user_id=_provider_user_id(data.get("id")),
            email=account.get("email", ""),
            nickname=profile.get("nickname", f"kakao_{data['id']}"),
            profile_image=profile.get("profile_image_url"),
            email_verified=account.get("is_email_valid") is True and account.get("is_email_verified") is True,
        )
    elif provider == "naver":
        info = data.get("response", {})
        return OAuthUserInfo(
            provider="naver",
            provider_user_id=_provider_user_id(info.get("id")),
            email=info.get("email", ""),
            nickname=info.get("nickname", f"naver_{info['id']}"),
            profile_image=info.get("profile_image"),
        )
    else:
        raise ValueError(f"지원하지 않는 OAuth 공급자: {provider}")


def _provider_user_id(value) -> str:
    """Retain the explicit subject; never turn missing/bool values into identities."""
    if isinstance(value, bool) or not isinstance(value, (str, int)) or (isinstance(value, int) and value <= 0):
        raise ValueError("Missing or invalid OAuth provider user id")
    identity = str(value)
    if not identity.strip() or identity != identity.strip():
        raise ValueError("Missing or invalid OAuth provider user id")
    return identity
