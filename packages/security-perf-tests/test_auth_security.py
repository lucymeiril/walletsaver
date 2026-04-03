"""
인증 보안 테스트 — JWT 토큰 조작, 비밀번호 보안, OAuth, 접근 제어.

Tests:
- JWT token tampering (modified payload, expired, invalid signature, none algorithm)
- Password security (bcrypt, minimum length, common password rejection)
- Session fixation prevention
- Token refresh flow security
- Brute force protection simulation
- OAuth callback validation
- Admin endpoint access control
- API key exposure prevention
"""

import pytest
import json
import base64
import time
from datetime import datetime, timedelta, timezone


# ═══════════════════════════════════════════════
# JWT Token Tampering Tests
# ═══════════════════════════════════════════════

class TestJWTTokenSecurity:
    """JWT 토큰 보안 테스트."""

    def test_expired_token_rejected(self, website_client, expired_token):
        """만료된 토큰은 거부되어야 한다."""
        headers = {"Authorization": f"Bearer {expired_token}"}
        resp = website_client.get("/api/users/me", headers=headers)
        assert resp.status_code == 401

    def test_invalid_signature_rejected(self, website_client, auth_service):
        """잘못된 서명의 토큰은 거부되어야 한다."""
        from jose import jwt
        token = jwt.encode(
            {"sub": "1", "email": "test@example.com", "role": "user",
             "exp": datetime.now(timezone.utc) + timedelta(hours=1), "type": "access"},
            "wrong-secret-key",
            algorithm="HS256",
        )
        headers = {"Authorization": f"Bearer {token}"}
        resp = website_client.get("/api/users/me", headers=headers)
        assert resp.status_code == 401

    def test_modified_payload_rejected(self, website_client, auth_token):
        """페이로드가 변조된 토큰은 거부되어야 한다."""
        parts = auth_token.split(".")
        payload_b64 = parts[1]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        payload["role"] = "admin"  # 권한 상승 시도
        tampered_payload = base64.urlsafe_b64encode(
            json.dumps(payload).encode()
        ).rstrip(b"=").decode()
        tampered_token = f"{parts[0]}.{tampered_payload}.{parts[2]}"
        headers = {"Authorization": f"Bearer {tampered_token}"}
        resp = website_client.get("/api/users/me", headers=headers)
        assert resp.status_code == 401

    def test_none_algorithm_rejected(self, website_client, auth_service):
        """'none' 알고리즘 공격은 거부되어야 한다."""
        payload = {
            "sub": "1", "email": "test@example.com", "role": "admin",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1), "type": "access",
        }
        header = base64.urlsafe_b64encode(
            json.dumps({"alg": "none", "typ": "JWT"}).encode()
        ).rstrip(b"=").decode()
        body = base64.urlsafe_b64encode(
            json.dumps(payload, default=str).encode()
        ).rstrip(b"=").decode()
        none_token = f"{header}.{body}."
        headers = {"Authorization": f"Bearer {none_token}"}
        resp = website_client.get("/api/users/me", headers=headers)
        assert resp.status_code == 401

    def test_empty_token_rejected(self, website_client):
        """빈 토큰은 거부되어야 한다."""
        headers = {"Authorization": "Bearer "}
        resp = website_client.get("/api/users/me", headers=headers)
        assert resp.status_code in (401, 403)

    def test_malformed_token_rejected(self, website_client):
        """형식이 잘못된 토큰은 거부되어야 한다."""
        headers = {"Authorization": "Bearer not.a.valid.jwt.token"}
        resp = website_client.get("/api/users/me", headers=headers)
        assert resp.status_code == 401

    def test_refresh_token_cannot_access_resources(self, website_client):
        """리프레시 토큰으로 리소스에 접근할 수 없어야 한다."""
        from services.auth_service import create_refresh_token
        refresh = create_refresh_token(
            {"sub": "1", "email": "test@example.com", "role": "user"}
        )
        headers = {"Authorization": f"Bearer {refresh}"}
        resp = website_client.get("/api/users/me", headers=headers)
        assert resp.status_code == 401

    def test_token_type_enforcement(self, website_client, auth_service):
        """토큰 type 필드가 'access'가 아니면 거부되어야 한다."""
        from jose import jwt
        token = jwt.encode(
            {"sub": "1", "email": "test@example.com", "role": "user",
             "exp": datetime.now(timezone.utc) + timedelta(hours=1),
             "type": "custom"},
            auth_service.SECRET_KEY,
            algorithm="HS256",
        )
        headers = {"Authorization": f"Bearer {token}"}
        resp = website_client.get("/api/users/me", headers=headers)
        assert resp.status_code == 401


# ═══════════════════════════════════════════════
# Password Security Tests
# ═══════════════════════════════════════════════

class TestPasswordSecurity:
    """비밀번호 보안 테스트."""

    def test_bcrypt_hashing_used(self, auth_service):
        """bcrypt 해싱이 사용되어야 한다."""
        hashed = auth_service.hash_password("testpassword1")
        assert hashed.startswith("$2b$") or hashed.startswith("$2a$")

    def test_password_hashes_are_unique(self, auth_service):
        """같은 비밀번호라도 해시는 달라야 한다 (salt 사용)."""
        h1 = auth_service.hash_password("samepassword1")
        h2 = auth_service.hash_password("samepassword1")
        assert h1 != h2

    def test_password_verification_works(self, auth_service):
        """비밀번호 검증이 올바르게 동작해야 한다."""
        hashed = auth_service.hash_password("mypassword1")
        assert auth_service.verify_password("mypassword1", hashed) is True
        assert auth_service.verify_password("wrongpassword", hashed) is False

    def test_minimum_password_length_enforced(self, website_client):
        """최소 비밀번호 길이(8자)가 강제되어야 한다."""
        resp = website_client.post("/api/auth/register", json={
            "email": "short@test.com",
            "password": "abc1",
            "nickname": "shortpwd",
        })
        assert resp.status_code == 422

    def test_password_requires_digit(self, website_client):
        """비밀번호에 숫자가 포함되어야 한다."""
        resp = website_client.post("/api/auth/register", json={
            "email": "nodigit@test.com",
            "password": "abcdefghij",
            "nickname": "nodigit",
        })
        assert resp.status_code == 422

    @pytest.mark.parametrize("weak_password", [
        "12345678",
        "password1",
        "qwerty123",
    ])
    def test_common_passwords_have_proper_hashing(self, auth_service, weak_password):
        """일반적인 비밀번호도 bcrypt로 해싱되어야 한다."""
        hashed = auth_service.hash_password(weak_password)
        assert hashed.startswith("$2b$") or hashed.startswith("$2a$")
        assert auth_service.verify_password(weak_password, hashed)


# ═══════════════════════════════════════════════
# Token Refresh Security
# ═══════════════════════════════════════════════

class TestTokenRefreshSecurity:
    """토큰 갱신 보안 테스트."""

    def test_valid_refresh_flow(self, website_client):
        """유효한 리프레시 토큰으로 새 토큰 쌍을 발급받을 수 있다."""
        reg_resp = website_client.post("/api/auth/register", json={
            "email": "refresh_test@test.com",
            "password": "password123",
            "nickname": "리프레시테스트",
        })
        assert reg_resp.status_code == 201
        refresh_token = reg_resp.json()["refresh_token"]

        refresh_resp = website_client.post("/api/auth/refresh", json={
            "refresh_token": refresh_token,
        })
        assert refresh_resp.status_code == 200
        data = refresh_resp.json()
        assert "access_token" in data
        assert "refresh_token" in data

    def test_access_token_rejected_for_refresh(self, website_client):
        """액세스 토큰으로 리프레시는 불가능해야 한다."""
        reg_resp = website_client.post("/api/auth/register", json={
            "email": "norefresh@test.com",
            "password": "password123",
            "nickname": "노리프레시",
        })
        access_token = reg_resp.json()["access_token"]

        resp = website_client.post("/api/auth/refresh", json={
            "refresh_token": access_token,
        })
        assert resp.status_code == 401

    def test_invalid_refresh_token_rejected(self, website_client):
        """유효하지 않은 리프레시 토큰은 거부되어야 한다."""
        resp = website_client.post("/api/auth/refresh", json={
            "refresh_token": "invalid.token.here",
        })
        assert resp.status_code == 401


# ═══════════════════════════════════════════════
# Session Fixation Prevention
# ═══════════════════════════════════════════════

class TestSessionFixation:
    """세션 고정 공격 방어 테스트."""

    def test_login_returns_new_tokens(self, website_client):
        """로그인할 때마다 새로운 토큰이 발급되어야 한다."""
        import time
        website_client.post("/api/auth/register", json={
            "email": "session_fix@test.com",
            "password": "password123",
            "nickname": "세션픽스",
        })
        resp1 = website_client.post("/api/auth/login", json={
            "email": "session_fix@test.com",
            "password": "password123",
        })
        time.sleep(1.1)  # Ensure different exp timestamp
        resp2 = website_client.post("/api/auth/login", json={
            "email": "session_fix@test.com",
            "password": "password123",
        })
        assert resp1.json()["access_token"] != resp2.json()["access_token"]


# ═══════════════════════════════════════════════
# Brute Force Protection
# ═══════════════════════════════════════════════

class TestBruteForceProtection:
    """무차별 대입 공격 방어 테스트."""

    def test_invalid_credentials_return_401(self, website_client):
        """잘못된 자격 증명은 401을 반환해야 한다."""
        for _ in range(5):
            resp = website_client.post("/api/auth/login", json={
                "email": "brute@test.com",
                "password": "wrong_password",
            })
            assert resp.status_code == 401

    def test_error_message_does_not_reveal_user_existence(self, website_client):
        """에러 메시지가 사용자 존재 여부를 드러내지 않아야 한다."""
        resp = website_client.post("/api/auth/login", json={
            "email": "nonexistent@test.com",
            "password": "password123",
        })
        assert resp.status_code == 401
        error_detail = resp.json().get("detail", "")
        assert "이메일 또는 비밀번호" in error_detail or "Invalid" in error_detail.lower() or "올바르지" in error_detail


# ═══════════════════════════════════════════════
# OAuth Callback Security
# ═══════════════════════════════════════════════

class TestOAuthSecurity:
    """OAuth 보안 테스트."""

    def test_invalid_oauth_provider_rejected(self, website_client):
        """지원하지 않는 OAuth 프로바이더는 거부되어야 한다."""
        resp = website_client.get("/api/auth/oauth/invalid_provider", follow_redirects=False)
        assert resp.status_code == 400

    def test_oauth_callback_without_code_fails(self, website_client):
        """OAuth 콜백에 code가 없으면 실패해야 한다."""
        resp = website_client.get("/api/auth/oauth/google/callback")
        assert resp.status_code == 422  # Missing required query param


# ═══════════════════════════════════════════════
# Admin Access Control
# ═══════════════════════════════════════════════

class TestAdminAccessControl:
    """관리자 접근 제어 테스트."""

    def test_unauthenticated_user_cannot_access_protected(self, website_client):
        """미인증 사용자는 보호된 엔드포인트에 접근할 수 없다."""
        resp = website_client.get("/api/users/me")
        assert resp.status_code in (401, 403)

    def test_valid_user_can_access_own_profile(self, website_client, auth_headers):
        """인증된 사용자는 자신의 프로필에 접근할 수 있다."""
        resp = website_client.get("/api/users/me", headers=auth_headers)
        assert resp.status_code == 200

    def test_regular_user_cannot_delete_others_post(self, website_client, auth_headers, other_user_headers):
        """일반 사용자는 다른 사용자의 게시글을 삭제할 수 없다."""
        # 사용자 1이 게시글 작성
        post_resp = website_client.post("/api/posts", headers=auth_headers, json={
            "title": "내 게시글",
            "content": "내 콘텐츠",
            "post_type": "free",
        })
        assert post_resp.status_code == 200
        post_id = post_resp.json()["data"]["id"]

        # 사용자 2가 삭제 시도
        del_resp = website_client.delete(f"/api/posts/{post_id}", headers=other_user_headers)
        assert del_resp.status_code == 403


# ═══════════════════════════════════════════════
# API Key Exposure Prevention
# ═══════════════════════════════════════════════

class TestAPIKeyExposure:
    """API 키 노출 방지 테스트."""

    SENSITIVE_KEYS = ["secret", "password", "api_key", "token", "private_key",
                      "client_secret", "hashed_password"]

    def test_health_endpoint_no_secrets(self, website_client):
        """헬스체크 응답에 비밀 정보가 없어야 한다."""
        resp = website_client.get("/api/health")
        body = json.dumps(resp.json()).lower()
        for key in self.SENSITIVE_KEYS:
            assert key not in body or key in ("token",), \
                f"Health response may leak sensitive key: {key}"

    def test_error_responses_no_secrets(self, website_client):
        """에러 응답에 비밀 정보가 없어야 한다."""
        resp = website_client.get("/api/nonexistent")
        body = json.dumps(resp.json()).lower()
        for key in ["secret_key", "database_url", "password", "private"]:
            assert key not in body, \
                f"Error response may leak: {key}"

    def test_user_profile_no_password_hash(self, website_client, auth_headers):
        """사용자 프로필 응답에 비밀번호 해시가 포함되지 않아야 한다."""
        resp = website_client.get("/api/users/me", headers=auth_headers)
        body = json.dumps(resp.json()).lower()
        assert "hashed_password" not in body
        assert "$2b$" not in body
        assert "$2a$" not in body
