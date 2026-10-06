"""인증 시스템 종합 테스트"""
import json
import os
import sys
import pytest
from datetime import timedelta
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.auth_service import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
    create_token_pair,
    ACCESS_TOKEN_EXPIRE_MINUTES,
)
from services.oauth_service import (
    get_oauth_login_url, get_oauth_redirect_uri, OAuthConfig, OAuthUserInfo,
    generate_oauth_state, validate_oauth_state, OAUTH_STATE_TTL,
)


@pytest.fixture
def oauth_store(tmp_path):
    from services.account_database import AccountDatabase
    from services.user_storage import PublicUserStore
    db = AccountDatabase(tmp_path / "oauth-accounts.sqlite")
    yield PublicUserStore(db)
    db.close()


# ── 비밀번호 해싱 테스트 ──────────────────────────────────────────

class TestPasswordHashing:
    def test_hash_password_returns_hash(self):
        hashed = hash_password("TestPass1")
        assert hashed != "TestPass1"
        assert hashed.startswith("$2b$")

    def test_verify_correct_password(self):
        hashed = hash_password("MySecure1")
        assert verify_password("MySecure1", hashed) is True

    def test_verify_wrong_password(self):
        hashed = hash_password("MySecure1")
        assert verify_password("WrongPass1", hashed) is False

    def test_different_hashes_for_same_password(self):
        h1 = hash_password("SamePass1")
        h2 = hash_password("SamePass1")
        assert h1 != h2  # bcrypt uses random salt


# ── JWT 토큰 생성/디코딩 테스트 ──────────────────────────────────

class TestJWTTokens:
    def test_create_and_decode_access_token(self):
        data = {"sub": "1", "email": "test@example.com", "role": "user"}
        token = create_access_token(data)
        payload = decode_token(token)
        assert payload is not None
        assert payload["sub"] == "1"
        assert payload["email"] == "test@example.com"
        assert payload["role"] == "user"
        assert payload["type"] == "access"

    def test_create_and_decode_refresh_token(self):
        data = {"sub": "2", "email": "user@example.com", "role": "admin"}
        token = create_refresh_token(data)
        payload = decode_token(token)
        assert payload is not None
        assert payload["sub"] == "2"
        assert payload["type"] == "refresh"

    def test_access_token_with_custom_expiry(self):
        data = {"sub": "1", "email": "a@b.com", "role": "user"}
        token = create_access_token(data, expires_delta=timedelta(hours=2))
        payload = decode_token(token)
        assert payload is not None

    def test_expired_token_returns_none(self):
        data = {"sub": "1", "email": "a@b.com", "role": "user"}
        token = create_access_token(data, expires_delta=timedelta(seconds=-1))
        payload = decode_token(token)
        assert payload is None

    def test_invalid_token_returns_none(self):
        assert decode_token("invalid.token.string") is None
        assert decode_token("") is None

    def test_tampered_token_returns_none(self):
        data = {"sub": "1", "email": "a@b.com", "role": "user"}
        token = create_access_token(data)
        tampered = token[:-5] + "XXXXX"
        assert decode_token(tampered) is None

    def test_create_token_pair(self):
        pair = create_token_pair(1, "user@test.com", "user")
        assert "access_token" in pair
        assert "refresh_token" in pair
        assert pair["token_type"] == "bearer"
        assert pair["expires_in"] == ACCESS_TOKEN_EXPIRE_MINUTES * 60

        access_payload = decode_token(pair["access_token"])
        assert access_payload["type"] == "access"

        refresh_payload = decode_token(pair["refresh_token"])
        assert refresh_payload["type"] == "refresh"


# ── Pydantic 스키마 검증 테스트 ──────────────────────────────────

class TestSchemaValidation:
    def test_valid_registration(self):
        from api.schemas.auth import UserRegister
        user = UserRegister(email="test@example.com", password="secure123", nickname="테스터")
        assert user.email == "test@example.com"
        assert user.nickname == "테스터"

    def test_invalid_email(self):
        from api.schemas.auth import UserRegister
        with pytest.raises(Exception):
            UserRegister(email="not-an-email", password="secure123", nickname="테스터")

    def test_short_password(self):
        from api.schemas.auth import UserRegister
        with pytest.raises(Exception):
            UserRegister(email="a@b.com", password="short1", nickname="테스터")

    def test_password_without_digit(self):
        from api.schemas.auth import UserRegister
        with pytest.raises(Exception):
            UserRegister(email="a@b.com", password="nodigitshere", nickname="테스터")

    def test_nickname_too_short(self):
        from api.schemas.auth import UserRegister
        with pytest.raises(Exception):
            UserRegister(email="a@b.com", password="secure123", nickname="X")

    def test_nickname_too_long(self):
        from api.schemas.auth import UserRegister
        with pytest.raises(Exception):
            UserRegister(email="a@b.com", password="secure123", nickname="A" * 21)

    def test_valid_login(self):
        from api.schemas.auth import UserLogin
        login = UserLogin(email="user@example.com", password="pass1234")
        assert login.email == "user@example.com"

    def test_token_refresh_schema(self):
        from api.schemas.auth import TokenRefresh
        tr = TokenRefresh(refresh_token="some.jwt.token")
        assert tr.refresh_token == "some.jwt.token"

    def test_oauth_callback_schema(self):
        from api.schemas.auth import OAuthCallback
        cb = OAuthCallback(code="auth_code_123")
        assert cb.code == "auth_code_123"
        assert cb.state is None

    def test_oauth_callback_with_state(self):
        from api.schemas.auth import OAuthCallback
        cb = OAuthCallback(code="code", state="random_state")
        assert cb.state == "random_state"


# ── API 라우트 통합 테스트 ────────────────────────────────────────

class TestAuthRoutes:
    @pytest.fixture
    def account_db(self, tmp_path):
        """각 테스트는 실제 스키마의 임시 accounts.sqlite를 사용한다."""
        from services.account_database import AccountDatabase

        db = AccountDatabase(tmp_path / "accounts.sqlite")
        yield db
        db.close()

    @pytest.fixture
    def client(self, account_db):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from api.routes.auth import router

        app = FastAPI()
        app.state.storage = account_db
        app.include_router(router)
        return TestClient(app)

    def test_register_success(self, client):
        resp = client.post("/api/auth/register", json={
            "email": "new@example.com",
            "password": "password123",
            "nickname": "뉴유저",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    def test_register_duplicate_email(self, client):
        payload = {"email": "dup@example.com", "password": "password123", "nickname": "유저A"}
        client.post("/api/auth/register", json=payload)
        resp = client.post("/api/auth/register", json={
            "email": "dup@example.com", "password": "password456", "nickname": "유저B"
        })
        assert resp.status_code == 400
        assert "이미 등록된 이메일" in resp.json()["detail"]

    def test_register_duplicate_nickname(self, client):
        client.post("/api/auth/register", json={
            "email": "a@example.com", "password": "password123", "nickname": "같은닉네임"
        })
        resp = client.post("/api/auth/register", json={
            "email": "b@example.com", "password": "password123", "nickname": "같은닉네임"
        })
        assert resp.status_code == 400
        assert "닉네임" in resp.json()["detail"]

    def test_login_success(self, client):
        client.post("/api/auth/register", json={
            "email": "login@example.com", "password": "password123", "nickname": "로그인유저"
        })
        resp = client.post("/api/auth/login", json={
            "email": "login@example.com", "password": "password123"
        })
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    def test_login_wrong_password(self, client):
        client.post("/api/auth/register", json={
            "email": "wrong@example.com", "password": "password123", "nickname": "유저"
        })
        resp = client.post("/api/auth/login", json={
            "email": "wrong@example.com", "password": "wrongpass1"
        })
        assert resp.status_code == 401

    def test_login_nonexistent_user(self, client):
        resp = client.post("/api/auth/login", json={
            "email": "nobody@example.com", "password": "password123"
        })
        assert resp.status_code == 401

    def test_refresh_token_flow(self, client):
        reg = client.post("/api/auth/register", json={
            "email": "refresh@example.com", "password": "password123", "nickname": "리프레시유저"
        })
        refresh_token = reg.json()["refresh_token"]
        resp = client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    def test_refresh_with_invalid_token(self, client):
        resp = client.post("/api/auth/refresh", json={"refresh_token": "invalid.token"})
        assert resp.status_code == 401

    def test_refresh_with_access_token_fails(self, client):
        """액세스 토큰으로 리프레시 요청 시 거부"""
        reg = client.post("/api/auth/register", json={
            "email": "norefresh@example.com", "password": "password123", "nickname": "거부유저"
        })
        access_token = reg.json()["access_token"]
        resp = client.post("/api/auth/refresh", json={"refresh_token": access_token})
        assert resp.status_code == 401

    def test_register_invalid_password(self, client):
        resp = client.post("/api/auth/register", json={
            "email": "bad@example.com", "password": "short", "nickname": "유저"
        })
        assert resp.status_code == 422

    def test_me_requires_auth(self, client):
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401


# ── OAuth URL 생성 테스트 ────────────────────────────────────────

class TestOAuthURLGeneration:
    def test_google_login_url(self, monkeypatch, oauth_store):
        monkeypatch.setenv("GOOGLE_CLIENT_ID", "google-client")
        monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "google-secret")
        monkeypatch.setenv("OAUTH_REDIRECT_BASE", "http://localhost:8000/")
        url = get_oauth_login_url("google", "synthetic-browser", state_store=oauth_store)
        assert "accounts.google.com" in url
        assert "response_type=code" in url
        assert "redirect_uri=http%3A%2F%2Flocalhost%3A8000%2Fapi%2Fauth%2Foauth%2Fgoogle%2Fcallback" in url
        assert get_oauth_redirect_uri("google") == "http://localhost:8000/api/auth/oauth/google/callback"

    def test_google_credentials_can_load_from_downloaded_json(self, tmp_path, monkeypatch):
        credential_file = tmp_path / "google-client.json"
        credential_file.write_text(json.dumps({
            "web": {
                "client_id": "file-client",
                "client_secret": "file-secret",
            },
        }), encoding="utf-8")
        monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
        monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
        monkeypatch.setenv("GOOGLE_CLIENT_SECRET_FILE", str(credential_file))

        config = OAuthConfig.get("google")

        assert config["client_id"] == "file-client"
        assert config["client_secret"] == "file-secret"

    @pytest.mark.parametrize("provider", ["kakao", "naver", "facebook"])
    def test_retired_provider_cannot_start_or_build_callback(self, oauth_store, provider):
        with pytest.raises(ValueError, match="지원하지 않는"):
            get_oauth_login_url(provider, "synthetic-browser", state_store=oauth_store)
        with pytest.raises(ValueError, match="지원하지 않는"):
            get_oauth_redirect_uri(provider)

    def test_invalid_provider_raises(self, oauth_store):
        with pytest.raises(ValueError, match="지원하지 않는"):
            get_oauth_login_url("facebook", "synthetic-browser", state_store=oauth_store)

    def test_oauth_config_get(self):
        config = OAuthConfig.get("google")
        assert "client_id" in config
        assert "token_url" in config

    def test_oauth_config_invalid(self):
        with pytest.raises(ValueError):
            OAuthConfig.get("invalid_provider")


# ── OAuth 라우트 테스트 ──────────────────────────────────────────

class TestOAuthRoutes:
    @pytest.fixture
    def client(self, tmp_path):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from api.routes.auth import router
        from services.account_database import AccountDatabase

        app = FastAPI()
        db = AccountDatabase(tmp_path / "accounts.sqlite")
        app.state.storage = db
        app.include_router(router)
        with TestClient(app, follow_redirects=False) as client:
            yield client
        db.close()

    @pytest.fixture
    def provider(self, monkeypatch):
        # Only the provider calls are mocked; redirects, cookies, JWT and account
        # storage use the existing route and temporary real SQLite schema.
        monkeypatch.setenv("GOOGLE_CLIENT_ID", "synthetic-client")
        monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "synthetic-secret")
        exchange = AsyncMock(return_value={"access_token": "synthetic-provider-token"})
        info = AsyncMock(return_value=OAuthUserInfo(
            "google", "subject-one", "oauth@example.com", "OAuth User", email_verified=True,
        ))
        monkeypatch.setattr("api.routes.auth.exchange_code_for_token", exchange)
        monkeypatch.setattr("api.routes.auth.get_user_info", info)
        return exchange, info

    @staticmethod
    def begin(client):
        response = client.get("/api/auth/oauth/google")
        assert response.status_code == 307
        state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
        return state, response

    @staticmethod
    def callback(client, state, **params):
        return client.get("/api/auth/oauth/google/callback", params={"state": state, "code": "synthetic-code", **params})

    def test_oauth_login_redirect(self, client, monkeypatch):
        monkeypatch.setenv("GOOGLE_CLIENT_ID", "google-client")
        monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "google-secret")
        resp = client.get("/api/auth/oauth/google")
        assert resp.status_code == 307
        assert "accounts.google.com" in resp.headers["location"]

    def test_oauth_login_redirect_without_credentials_returns_config_error(self, client, monkeypatch):
        monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
        monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
        monkeypatch.delenv("GOOGLE_CLIENT_SECRET_FILE", raising=False)
        monkeypatch.setenv("GOOGLE_CLIENT_SECRET_FILE", "")
        resp = client.get("/api/auth/oauth/google")
        assert resp.status_code == 302
        assert "/auth/callback?error=oauth_config&provider=google" in resp.headers["location"]

    def test_oauth_invalid_provider(self, client):
        resp = client.get("/api/auth/oauth/facebook")
        assert resp.status_code == 400

    @pytest.mark.parametrize("provider", ["kakao", "naver", "facebook"])
    def test_retired_routes_reject_without_provider_or_account_creation(self, client, provider):
        assert client.get(f"/api/auth/oauth/{provider}").status_code == 400
        assert client.get(f"/api/auth/oauth/{provider}/callback", params={"code": "old", "state": "old"}).status_code == 400
        assert client.post("/api/auth/demo-login", params={"provider": provider}).status_code == 404

    def test_oauth_denial_redirects_to_frontend_instead_of_422(self, client, monkeypatch, provider):
        monkeypatch.setenv("FRONTEND_URL", "http://localhost:5173/")
        state, _ = self.begin(client)
        resp = self.callback(client, state, error="access_denied")
        assert resp.status_code == 302
        assert resp.headers["location"] == (
            "http://localhost:5173/auth/callback?error=oauth_denied&provider=google"
        )
        assert "oauth_browser_google" not in client.cookies
        assert "error=oauth_state" in self.callback(client, state).headers["location"]
        provider[0].assert_not_awaited()

    def test_oauth_bound_login_replay_and_logout(self, client, provider):
        state, start = self.begin(client)
        cookie = start.headers["set-cookie"]
        assert all(value in cookie for value in ["HttpOnly", "SameSite=lax", "Max-Age=600", "Path=/api/auth/oauth/google"])
        response = self.callback(client, state)
        assert response.status_code == 302 and "error=" not in response.headers["location"]
        assert "oauth_browser_google" not in client.cookies
        assert "access_token" in client.cookies and "refresh_token" in client.cookies
        me = client.get("/api/auth/me")
        assert me.status_code == 200 and me.json()["email"] == "oauth@example.com"
        assert "error=oauth_state" in self.callback(client, state).headers["location"]
        assert provider[0].await_count == 1
        assert client.get("/api/auth/me").status_code == 200  # failed OAuth keeps the valid session
        assert client.post("/api/auth/logout").status_code == 200
        assert client.get("/api/auth/me").status_code == 401
        assert "access_token" not in client.cookies and "refresh_token" not in client.cookies

    @pytest.mark.parametrize("mismatch", ["missing_cookie", "wrong_cookie", "wrong_provider", "missing_state"])
    def test_oauth_binding_mismatch_does_not_exchange(self, client, provider, mismatch):
        state, _ = self.begin(client)
        path = "/api/auth/oauth/google/callback"
        if mismatch == "missing_cookie":
            client.cookies.clear()
        elif mismatch == "wrong_cookie":
            client.cookies.clear()
            client.cookies.set("oauth_browser_google", "different-browser", path="/api/auth/oauth/google")
        elif mismatch == "wrong_provider":
            binding = client.cookies.get("oauth_browser_google")
            client.cookies.set("oauth_browser_kakao", binding, path="/api/auth/oauth/kakao")
            path = "/api/auth/oauth/kakao/callback"
        params = {"code": "synthetic-code"}
        if mismatch != "missing_state":
            params["state"] = state
        response = client.get(path, params=params)
        if mismatch == "wrong_provider":
            assert response.status_code == 400
        else:
            assert "error=oauth_state" in response.headers["location"]
        provider[0].assert_not_awaited()
        if mismatch not in {"missing_state", "wrong_provider"}:
            from services.user_storage import PublicUserStore
            assert validate_oauth_state(state, "google", "anything", state_store=PublicUserStore(client.app.state.storage)) is False

    def test_oauth_expiry_and_missing_code(self, client, provider, monkeypatch):
        monkeypatch.setattr("services.oauth_service.time.time", lambda: 1000)
        state, _ = self.begin(client)
        monkeypatch.setattr("services.oauth_service.time.time", lambda: 1000 + OAUTH_STATE_TTL)
        assert "error=oauth_state" in self.callback(client, state).headers["location"]
        state, _ = self.begin(client)
        response = client.get("/api/auth/oauth/google/callback", params={"state": state})
        assert "error=oauth_denied" in response.headers["location"]
        provider[0].assert_not_awaited()

    def test_oauth_pending_store_unavailable_fails_closed(self, client, provider, monkeypatch):
        from services.user_storage import PublicUserStore, PublicUserStoreError
        with monkeypatch.context() as failure:
            failure.setattr(PublicUserStore, "issue_oauth_state", lambda *a, **k: (_ for _ in ()).throw(PublicUserStoreError("oauth_state_store_unavailable")))
            response = client.get("/api/auth/oauth/google")
            assert response.status_code == 503
            assert "oauth_browser_google" not in client.cookies
        state, _ = self.begin(client)
        with monkeypatch.context() as failure:
            failure.setattr(PublicUserStore, "consume_oauth_state", lambda *a, **k: (_ for _ in ()).throw(PublicUserStoreError("oauth_state_store_unavailable")))
            response = self.callback(client, state)
            assert "error=oauth_failed" in response.headers["location"]
            assert "oauth_browser_google" not in client.cookies
        provider[0].assert_not_awaited()

    def test_oauth_missing_account_store_fails_closed(self, client, provider):
        state, _ = self.begin(client)
        del client.app.state.storage
        assert client.get("/api/auth/oauth/google").status_code == 503
        response = self.callback(client, state)
        assert "error=oauth_failed" in response.headers["location"]
        assert "oauth_browser_google" not in client.cookies
        provider[0].assert_not_awaited()

    def test_oauth_consume_commit_failure_prevents_exchange(self, client, provider, monkeypatch):
        from sqlalchemy.exc import OperationalError
        from services.user_storage import PublicUserStore
        state, _ = self.begin(client)
        binding = client.cookies.get("oauth_browser_google")
        session_class = client.app.state.storage.SessionLocal.session_factory.class_

        def failed_commit(session):
            raise OperationalError("synthetic commit", {}, Exception("synthetic unavailable"))

        with monkeypatch.context() as failure:
            failure.setattr(session_class, "commit", failed_commit)
            assert "error=oauth_failed" in self.callback(client, state).headers["location"]
        provider[0].assert_not_awaited()
        assert "oauth_browser_google" not in client.cookies
        # Failed commit rolls back consumption; recovering storage may accept
        # the original binding once, but no token was exchanged during failure.
        store = PublicUserStore(client.app.state.storage)
        assert validate_oauth_state(state, "google", binding, state_store=store) is True
        assert validate_oauth_state(state, "google", binding, state_store=store) is False

    def test_oauth_callback_on_independent_worker(self, client, provider):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from api.routes.auth import router
        from services.account_database import AccountDatabase
        state, _ = self.begin(client)
        app = FastAPI()
        db = AccountDatabase(client.app.state.storage.path)
        app.state.storage = db
        app.include_router(router)
        try:
            with TestClient(app, follow_redirects=False) as worker:
                worker.cookies.update(client.cookies)
                response = self.callback(worker, state)
                assert response.status_code == 302 and "error=" not in response.headers["location"]
                assert "oauth_browser_google" not in worker.cookies
                assert worker.get("/api/auth/me").status_code == 200
            assert "error=oauth_state" in self.callback(client, state).headers["location"]
            assert provider[0].await_count == 1
        finally:
            db.close()

    @pytest.mark.parametrize("failure", ["token", "provider", "identity", "exception"])
    def test_oauth_bad_provider_response_fails_closed(self, client, provider, failure):
        exchange, info = provider
        if failure == "token":
            exchange.return_value = {"access_token": None}
        elif failure == "provider":
            info.return_value.provider = "kakao"
        elif failure == "identity":
            info.return_value.provider_user_id = None
        else:
            exchange.side_effect = RuntimeError("synthetic provider failure")
        state, _ = self.begin(client)
        response = self.callback(client, state)
        assert "error=oauth_failed" in response.headers["location"]
        assert "oauth_browser_google" not in client.cookies
        assert client.get("/api/auth/me").status_code == 401

    def test_oauth_verified_email_collision_preserves_local_session(self, client, provider):
        registered = client.post("/api/auth/register", json={
            "email": "oauth@example.com", "password": "synthetic123", "nickname": "Local User",
        })
        assert registered.status_code == 201
        original = client.get("/api/auth/me").json()
        state, _ = self.begin(client)
        assert "error=oauth_link_required" in self.callback(client, state).headers["location"]
        assert client.get("/api/auth/me").json() == original
        from sqlalchemy import text
        with client.app.state.storage.SessionLocal() as session:
            assert session.execute(text("SELECT count(*) FROM users")).scalar_one() == 1
            assert session.execute(text("SELECT count(*) FROM oauth_accounts")).scalar_one() == 0

    def test_oauth_disabled_existing_link_does_not_issue_session(self, client, provider):
        from services.user_storage import PublicUserStore
        store = PublicUserStore(client.app.state.storage)
        user = store.upsert_oauth_user(provider="google", provider_user_id="subject-one", email=None,
                                      nickname="Disabled", profile_image_url=None)
        store.soft_delete(user["id"])
        state, _ = self.begin(client)
        assert "error=account_disabled" in self.callback(client, state).headers["location"]
        assert client.get("/api/auth/me").status_code == 401


class TestOAuthIdentityStorage:
    @pytest.fixture
    def store(self, tmp_path):
        from services.account_database import AccountDatabase
        from services.user_storage import PublicUserStore
        db = AccountDatabase(tmp_path / "accounts.sqlite")
        yield PublicUserStore(db)
        db.close()

    @staticmethod
    def upsert(store, **changes):
        values = dict(provider="google", provider_user_id="subject-one", email="claimed@example.com",
                      nickname="Synthetic OAuth", profile_image_url=None)
        values.update(changes)
        return store.upsert_oauth_user(**values)

    @pytest.mark.parametrize("verified", [False, None, "true", 1])
    def test_oauth_unverified_email_never_links_or_owns_local_contact(self, store, verified):
        local = store.create_password_user(email="claimed@example.com", nickname="Local", hashed_password="synthetic-hash")
        oauth = self.upsert(store, email_verified=verified, profile_image_url="https://example.invalid/synthetic.png")
        assert oauth["id"] != local["id"]
        assert oauth["email"].endswith("@oauth.walletsavior.local")
        assert store.get_by_id(local["id"]) == local
        assert store.get_by_email("claimed@example.com")["id"] == local["id"]

    def test_oauth_explicit_provider_link_survives_changed_or_missing_email(self, store):
        linked = self.upsert(store, email_verified=True)
        local = store.create_password_user(email="local@example.com", nickname="Local", hashed_password="synthetic-hash")
        for email, verified in [("local@example.com", True), ("invalid", True), (None, False)]:
            current = self.upsert(store, email=email, email_verified=verified)
            assert current["id"] == linked["id"] and current["email"] == "claimed@example.com"
        assert store.get_by_id(local["id"]) == local

    def test_oauth_verified_email_cannot_link_another_provider_identity(self, store):
        from services.user_storage import PublicUserStoreError
        linked = self.upsert(store, email_verified=True)
        for changes in [{"provider_user_id": "other-subject"}, {"provider": "kakao"}]:
            with pytest.raises(PublicUserStoreError, match="oauth_email_conflict"):
                self.upsert(store, email_verified=True, **changes)
        assert store.get_by_id(linked["id"]) == linked

    @pytest.mark.parametrize("identity", [None, True, 12, "", " ", " subject "])
    def test_oauth_invalid_subject_cannot_create_account(self, store, identity):
        from services.user_storage import PublicUserStoreError
        with pytest.raises(PublicUserStoreError, match="oauth_identity_invalid"):
            self.upsert(store, provider_user_id=identity)
        assert store.get_by_email("claimed@example.com") is None

    def test_oauth_missing_email_has_provider_scoped_identity(self, store):
        first = self.upsert(store, email=None, email_verified=True)
        repeated = self.upsert(store, email=None)
        another = self.upsert(store, provider="kakao", email=None)
        assert first["id"] == repeated["id"] != another["id"]
        assert first["email"] != another["email"]

    def test_oauth_invalid_verified_email_fails_closed(self, store):
        from services.user_storage import PublicUserStoreError
        with pytest.raises(PublicUserStoreError, match="oauth_email_invalid"):
            self.upsert(store, email="not-an-email", email_verified=True)


class TestOAuthProviderClaims:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("provider,payload,verified", [
        ("google", {"id": "google-sub", "email": "claim@example.com", "verified_email": True}, True),
        ("google", {"id": "google-sub", "email": "claim@example.com", "verified_email": "true"}, False),
        ("google", {"id": "google-sub"}, False),
    ])
    async def test_oauth_email_verification_requires_literal_provider_evidence(self, monkeypatch, provider, payload, verified):
        import httpx
        from services.oauth_service import get_user_info
        monkeypatch.setattr(OAuthConfig, "get", lambda _: {"userinfo_url": "https://example.invalid/userinfo"})
        response = httpx.Response(200, json=payload, request=httpx.Request("GET", "https://example.invalid/userinfo"))
        with patch("services.oauth_service.httpx.AsyncClient") as http:
            http.return_value.__aenter__.return_value.get = AsyncMock(return_value=response)
            info = await get_user_info(provider, "synthetic-token")
        assert info.email_verified is verified
        assert info.provider_user_id == "google-sub"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("payload", [{}, {"id": None}, {"id": True}, {"id": ""}])
    async def test_oauth_missing_provider_subject_is_not_an_identity(self, monkeypatch, payload):
        import httpx
        from services.oauth_service import get_user_info
        monkeypatch.setattr(OAuthConfig, "get", lambda _: {"userinfo_url": "https://example.invalid/userinfo"})
        response = httpx.Response(200, json=payload, request=httpx.Request("GET", "https://example.invalid/userinfo"))
        with patch("services.oauth_service.httpx.AsyncClient") as http:
            http.return_value.__aenter__.return_value.get = AsyncMock(return_value=response)
            with pytest.raises(ValueError, match="provider user id"):
                await get_user_info("google", "synthetic-token")


class TestOAuthState:
    def test_oauth_state_restart_and_concurrent_single_use(self, tmp_path):
        import subprocess
        from concurrent.futures import ThreadPoolExecutor
        from services.account_database import AccountDatabase
        from services.user_storage import PublicUserStore
        path = tmp_path / "restart-accounts.sqlite"
        # Issue in a process that exits completely; no dictionary survives.
        issue = """
import sys
from services.account_database import AccountDatabase
from services.user_storage import PublicUserStore
from services.oauth_service import generate_oauth_state
db = AccountDatabase(sys.argv[1])
print(generate_oauth_state('google', 'synthetic-browser', state_store=PublicUserStore(db)))
db.close()
"""
        state = subprocess.run([sys.executable, "-c", issue, str(path)],
                               capture_output=True, text=True, check=True).stdout.strip()
        assert len(state) >= 40
        dbs = [AccountDatabase(path), AccountDatabase(path)]
        stores = [PublicUserStore(db) for db in dbs]
        from threading import Barrier
        barrier = Barrier(2)

        def consume(store):
            barrier.wait(timeout=5)
            return validate_oauth_state(state, "google", "synthetic-browser", state_store=store)

        try:
            with ThreadPoolExecutor(max_workers=2) as workers:
                assert sorted(workers.map(consume, stores)) == [False, True]
        finally:
            for db in dbs:
                db.close()
        # A new process after the successful consume must also reject replay.
        replay = issue.replace('generate_oauth_state', 'validate_oauth_state').replace(
            "validate_oauth_state('google', 'synthetic-browser', state_store=PublicUserStore(db))",
            "validate_oauth_state(sys.stdin.read(), 'google', 'synthetic-browser', state_store=PublicUserStore(db))")
        assert subprocess.run([sys.executable, "-c", replay, str(path)], input=state,
                              capture_output=True, text=True, check=True).stdout.strip() == "False"

    @pytest.mark.parametrize("provider,binding", [("kakao", "browser-one"), ("google", "wrong"), ("google", None)])
    def test_oauth_mismatch_consumes_across_connections(self, oauth_store, provider, binding):
        from services.user_storage import PublicUserStore
        state = generate_oauth_state("google", "browser-one", state_store=oauth_store)
        other = PublicUserStore(oauth_store)
        assert validate_oauth_state(state, provider, binding, state_store=other) is False
        assert validate_oauth_state(state, "google", "browser-one", state_store=oauth_store) is False

    def test_oauth_expired_cleanup_hashes_and_clock_rollback(self, oauth_store, monkeypatch):
        from hashlib import sha256
        from sqlalchemy import text
        monkeypatch.setattr("services.oauth_service.time.time", lambda: 1000)
        old = generate_oauth_state("google", "browser-one", state_store=oauth_store)
        with oauth_store.SessionLocal() as session:
            row = dict(session.execute(text("SELECT * FROM oauth_pending_states")).mappings().one())
            assert row == {"state_digest": sha256(old.encode()).hexdigest(), "provider": "google",
                           "browser_digest": sha256(b"browser-one").hexdigest(), "created_at": 1000,
                           "expires_at": 1000 + OAUTH_STATE_TTL}
            assert session.execute(text("SELECT count(*) FROM users")).scalar_one() == 0
        monkeypatch.setattr("services.oauth_service.time.time", lambda: 1000 + OAUTH_STATE_TTL)
        assert validate_oauth_state(old, "google", "browser-one", state_store=oauth_store) is False
        stale = generate_oauth_state("google", "browser-one", state_store=oauth_store)
        monkeypatch.setattr("services.oauth_service.time.time", lambda: 1000 + 2 * OAUTH_STATE_TTL)
        new = generate_oauth_state("google", "browser-two", state_store=oauth_store)
        with oauth_store.SessionLocal() as session:
            assert session.execute(text("SELECT count(*) FROM oauth_pending_states")).scalar_one() == 1
        assert validate_oauth_state(stale, "google", "browser-one", state_store=oauth_store) is False
        monkeypatch.setattr("services.oauth_service.time.time", lambda: 1000 + 2 * OAUTH_STATE_TTL - 1)
        assert validate_oauth_state(new, "google", "browser-two", state_store=oauth_store) is False
        monkeypatch.setattr("services.oauth_service.time.time", lambda: 1000 + 2 * OAUTH_STATE_TTL)
        assert validate_oauth_state(new, "google", "browser-two", state_store=oauth_store) is False
        valid = generate_oauth_state("google", "browser-one", state_store=oauth_store)
        monkeypatch.setattr("services.oauth_service.time.time", lambda: 1000 + 3 * OAUTH_STATE_TTL - .01)
        assert validate_oauth_state(valid, "google", "browser-one", state_store=oauth_store) is True

    def test_oauth_no_cross_store_or_process_fallback(self, oauth_store, tmp_path):
        from services.account_database import AccountDatabase
        from services.user_storage import PublicUserStore
        state = generate_oauth_state("google", "browser-one", state_store=oauth_store)
        other_db = AccountDatabase(tmp_path / "unrelated-accounts.sqlite")
        try:
            assert validate_oauth_state(state, "google", "browser-one", state_store=PublicUserStore(other_db)) is False
            assert validate_oauth_state(state, "google", "browser-one", state_store=oauth_store) is True
        finally:
            other_db.close()
