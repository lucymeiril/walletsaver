"""Auth route tests."""


def _register(client, email="alice@example.com", name="Alice", pw="password1"):
    return client.post(
        "/api/v1/auth/register",
        json={"email": email, "display_name": name, "password": pw},
    )


def test_register_success(board_test_client):
    r = _register(board_test_client)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email"] == "alice@example.com"
    assert body["role"] == "user"
    assert body["user_id"]


def test_register_duplicate_email(board_test_client):
    _register(board_test_client)
    r = _register(board_test_client)
    assert r.status_code == 409


def test_login_success(board_test_client):
    _register(board_test_client)
    r = board_test_client.post(
        "/api/v1/auth/login",
        json={"email": "alice@example.com", "password": "password1"},
    )
    assert r.status_code == 200, r.text
    assert "ws_session" in r.cookies


def test_login_wrong_password(board_test_client):
    _register(board_test_client)
    r = board_test_client.post(
        "/api/v1/auth/login",
        json={"email": "alice@example.com", "password": "wrong"},
    )
    assert r.status_code == 401


def test_me_with_session(board_test_client):
    _register(board_test_client)
    board_test_client.post(
        "/api/v1/auth/login",
        json={"email": "alice@example.com", "password": "password1"},
    )
    r = board_test_client.get("/api/v1/auth/me")
    assert r.status_code == 200
    assert r.json()["email"] == "alice@example.com"


def test_me_no_session(board_test_client):
    r = board_test_client.get("/api/v1/auth/me")
    assert r.status_code == 401


def test_logout(board_test_client):
    _register(board_test_client)
    board_test_client.post(
        "/api/v1/auth/login",
        json={"email": "alice@example.com", "password": "password1"},
    )
    r = board_test_client.post("/api/v1/auth/logout")
    assert r.status_code == 200
    # cookie cleared on client
    board_test_client.cookies.clear()
    r2 = board_test_client.get("/api/v1/auth/me")
    assert r2.status_code == 401
