"""인증 시스템 종합 테스트"""
import sys
import os
import pytest
from datetime import timedelta
from unittest.mock import patch

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
from services.oauth_service import get_oauth_login_url, OAuthConfig


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


# ── API 라우트 통합 테스트 ───────────────────────────────────────

class TestAuthRoutes:
    @pytest.fixture(autouse=True)
    def reset_db(self):
        """각 테스트 전에 인메모리 DB 초기화"""
        import api.routes.auth as auth_module
        auth_module._users_db.clear()
        auth_module._next_id = 1
        yield

    @pytest.fixture
    def client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from api.routes.auth import router

        app = FastAPI()
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
    def test_google_login_url(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_CLIENT_ID", "google-client")
        monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "google-secret")
        url = get_oauth_login_url("google")
        assert "accounts.google.com" in url
        assert "response_type=code" in url

    def test_kakao_login_url(self, monkeypatch):
        monkeypatch.setenv("KAKAO_CLIENT_ID", "kakao-client")
        monkeypatch.setenv("KAKAO_CLIENT_SECRET", "kakao-secret")
        url = get_oauth_login_url("kakao")
        assert "kauth.kakao.com" in url

    def test_naver_login_url(self, monkeypatch):
        monkeypatch.setenv("NAVER_CLIENT_ID", "naver-client")
        monkeypatch.setenv("NAVER_CLIENT_SECRET", "naver-secret")
        url = get_oauth_login_url("naver")
        assert "nid.naver.com" in url

    def test_invalid_provider_raises(self):
        with pytest.raises(ValueError, match="지원하지 않는"):
            get_oauth_login_url("facebook")

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
    def client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from api.routes.auth import router

        app = FastAPI()
        app.include_router(router)
        return TestClient(app, follow_redirects=False)

    def test_oauth_login_redirect(self, client, monkeypatch):
        monkeypatch.setenv("GOOGLE_CLIENT_ID", "google-client")
        monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "google-secret")
        resp = client.get("/api/auth/oauth/google")
        assert resp.status_code == 307
        assert "accounts.google.com" in resp.headers["location"]

    def test_oauth_login_redirect_without_credentials_uses_demo_fallback(self, client, monkeypatch):
        monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
        monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
        resp = client.get("/api/auth/oauth/google")
        assert resp.status_code == 307
        assert "/auth/callback?demo=1&provider=google" in resp.headers["location"]

    def test_oauth_invalid_provider(self, client):
        resp = client.get("/api/auth/oauth/facebook")
        assert resp.status_code == 400
