"""OAuth 서비스 — Google, Kakao, Naver OAuth 2.0 처리

중요: OAuthConfig는 env 변수를 lazy하게 읽는다.
main.py의 import 순서상 oauth_service가 config.py(load_dotenv)보다
먼저 import되므로, 클래스 body에서 os.getenv()하면 빈 문자열이 된다.
get() 호출 시점에는 dotenv가 이미 로드된 상태이므로 안전하다.
"""
import httpx
import os
import secrets
from typing import Optional
from dataclasses import dataclass
from urllib.parse import urlencode


@dataclass
class OAuthUserInfo:
    """OAuth 공급자로부터 받은 사용자 정보"""
    provider: str
    provider_user_id: str
    email: str
    nickname: str
    profile_image: Optional[str] = None


class OAuthConfig:
    """OAuth 공급자별 설정 — env 변수는 get() 호출 시 lazy 로드"""

    # 정적 설정만 클래스 body에 둔다 (env 변수 제외)
    _PROVIDERS = {
        "google": {
            "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_url": "https://oauth2.googleapis.com/token",
            "userinfo_url": "https://www.googleapis.com/oauth2/v2/userinfo",
            "scope": "openid email profile",
            "client_id_env": "GOOGLE_CLIENT_ID",
            "client_secret_env": "GOOGLE_CLIENT_SECRET",
        },
        "kakao": {
            "auth_url": "https://kauth.kakao.com/oauth/authorize",
            "token_url": "https://kauth.kakao.com/oauth/token",
            "userinfo_url": "https://kapi.kakao.com/v2/user/me",
            "scope": "profile_nickname account_email",
            "client_id_env": "KAKAO_CLIENT_ID",
            "client_secret_env": "KAKAO_CLIENT_SECRET",
        },
        "naver": {
            "auth_url": "https://nid.naver.com/oauth2.0/authorize",
            "token_url": "https://nid.naver.com/oauth2.0/token",
            "userinfo_url": "https://openapi.naver.com/v1/nid/me",
            "scope": "",
            "client_id_env": "NAVER_CLIENT_ID",
            "client_secret_env": "NAVER_CLIENT_SECRET",
        },
    }

    @classmethod
    def get(cls, provider: str) -> dict:
        """env 변수를 호출 시점에 읽어 반환 (lazy load)

        안전장치: config.py의 load_dotenv가 아직 실행되지 않았을 경우를 대비하여
        여기서도 한 번 더 load_dotenv를 호출한다 (이미 로드된 경우 no-op).
        """
        from pathlib import Path
        from dotenv import load_dotenv
        _env_path = Path(__file__).resolve().parent.parent / ".env"
        load_dotenv(_env_path)

        tmpl = cls._PROVIDERS.get(provider)
        if not tmpl:
            raise ValueError(f"지원하지 않는 OAuth 공급자: {provider}")
        return {
            "client_id": os.getenv(tmpl["client_id_env"], "").strip(),
            "client_secret": os.getenv(tmpl["client_secret_env"], "").strip(),
            "auth_url": tmpl["auth_url"],
            "token_url": tmpl["token_url"],
            "userinfo_url": tmpl["userinfo_url"],
            "scope": tmpl["scope"],
        }


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
    """OAuth 로그인 URL 생성 (with CSRF state parameter)

    urlencode를 사용하여 scope 공백, redirect_uri 슬래시 등을 안전하게 인코딩한다.
    """
    import logging
    _logger = logging.getLogger(__name__)

    config = OAuthConfig.get(provider)

    # ── 필수 값 검증 — client_id가 빈 문자열이면 즉시 에러 ──
    if not config["client_id"]:
        _logger.error(
            "OAuth client_id가 비어 있습니다. "
            "환경 변수 %s 를 확인하세요. (provider=%s)",
            OAuthConfig._PROVIDERS[provider]["client_id_env"], provider,
        )
        raise ValueError(
            f"OAuth {provider} client_id가 설정되지 않았습니다. "
            f".env 파일의 {OAuthConfig._PROVIDERS[provider]['client_id_env']} 값을 확인하세요."
        )
    if not config["client_secret"]:
        _logger.error(
            "OAuth client_secret이 비어 있습니다. "
            "환경 변수 %s 를 확인하세요. (provider=%s)",
            OAuthConfig._PROVIDERS[provider]["client_secret_env"], provider,
        )
        raise ValueError(
            f"OAuth {provider} client_secret이 설정되지 않았습니다. "
            f".env 파일의 {OAuthConfig._PROVIDERS[provider]['client_secret_env']} 값을 확인하세요."
        )

    redirect_base = os.getenv("OAUTH_REDIRECT_BASE", "http://localhost:8000")
    redirect_uri = f"{redirect_base}/api/auth/oauth/{provider}/callback"
    state = generate_oauth_state()

    params = {
        "client_id": config["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "state": state,
    }

    # scope가 있으면 추가 (naver는 scope가 빈 문자열)
    if config["scope"]:
        params["scope"] = config["scope"]

    # Google 전용 파라미터 — 리프레시 토큰 수신 + 동의 화면 강제 표시
    if provider == "google":
        params["access_type"] = "offline"
        params["prompt"] = "consent"

    _logger.info(
        "OAuth login URL 생성: provider=%s, redirect_uri=%s, client_id=%s…",
        provider, redirect_uri, config["client_id"][:20],
    )

    return f"{config['auth_url']}?{urlencode(params)}"


async def exchange_code_for_token(provider: str, code: str) -> dict:
    """인가 코드를 액세스 토큰으로 교환"""
    import logging
    _logger = logging.getLogger(__name__)

    config = OAuthConfig.get(provider)
    redirect_base = os.getenv("OAUTH_REDIRECT_BASE", "http://localhost:8000")
    redirect_uri = f"{redirect_base}/api/auth/oauth/{provider}/callback"

    _logger.info(
        "OAuth token exchange: provider=%s, redirect_uri=%s",
        provider, redirect_uri,
    )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                config["token_url"],
                data={
                    "grant_type": "authorization_code",
                    "client_id": config["client_id"],
                    "client_secret": config["client_secret"],
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
            )
            if response.status_code != 200:
                _logger.error(
                    "OAuth token exchange failed: status=%d, body=%s",
                    response.status_code, response.text,
                )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        _logger.error(
            "OAuth token exchange HTTP error: %s — response: %s",
            exc, exc.response.text if exc.response else "N/A",
        )
        raise ValueError(f"OAuth token exchange failed for {provider}: {exc}")
    except httpx.TimeoutException:
        raise ValueError(f"OAuth token exchange timed out for {provider}")
    except httpx.ConnectError:
        raise ValueError(f"OAuth token endpoint unreachable for {provider}")


async def get_user_info(provider: str, access_token: str) -> OAuthUserInfo:
    """OAuth 공급자로부터 사용자 정보 조회"""
    config = OAuthConfig.get(provider)
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(config["userinfo_url"], headers=headers)
            response.raise_for_status()
            data = response.json()
    except httpx.TimeoutException:
        raise ValueError(f"OAuth userinfo request timed out for {provider}")
    except httpx.ConnectError:
        raise ValueError(f"OAuth userinfo endpoint unreachable for {provider}")

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
