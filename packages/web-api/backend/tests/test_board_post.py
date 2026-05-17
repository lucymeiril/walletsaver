"""Board post tests."""


def _login(client, email="bob@example.com", name="Bob", pw="password1"):
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "display_name": name, "password": pw},
    )
    client.post(
        "/api/v1/auth/login", json={"email": email, "password": pw}
    )


def _create_post(client, slug="free", title="Hello", body="Body text", **kw):
    data = {"title": title, "body_markdown": body}
    data.update(kw)
    return client.post(f"/api/v1/boards/{slug}/posts", data=data)


def test_create_post_requires_auth(board_test_client):
    r = _create_post(board_test_client)
    assert r.status_code == 401


def test_create_post(board_test_client):
    _login(board_test_client)
    r = _create_post(board_test_client)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["title"] == "Hello"
    assert body["comments"] == []
    assert body["board_slug"] == "free"


def test_get_post(board_test_client):
    _login(board_test_client)
    r = _create_post(board_test_client)
    pid = r.json()["id"]
    r2 = board_test_client.get(f"/api/v1/posts/{pid}")
    assert r2.status_code == 200
    assert r2.json()["body_markdown"] == "Body text"
    assert r2.json()["comments"] == []


def test_get_post_with_canonical_id(board_test_client):
    _login(board_test_client)
    r = _create_post(
        board_test_client,
        slug="hotdeal",
        title="두부 핫딜",
        body="요기",
        canonical_id="prod_tofu_001",
        deal_price="1400",
    )
    pid = r.json()["id"]
    r2 = board_test_client.get(f"/api/v1/posts/{pid}")
    j = r2.json()
    assert j["grade_summary"] is not None
    assert j["grade_summary"]["p10"] == 1500.0
    assert j["grade_summary"]["p50"] == 2200.0


def test_update_post_own(board_test_client):
    _login(board_test_client)
    r = _create_post(board_test_client)
    pid = r.json()["id"]
    r2 = board_test_client.patch(
        f"/api/v1/posts/{pid}", json={"title": "Updated"}
    )
    assert r2.status_code == 200
    assert r2.json()["title"] == "Updated"


def test_update_post_other_user(board_test_client):
    _login(board_test_client)
    pid = _create_post(board_test_client).json()["id"]
    board_test_client.post("/api/v1/auth/logout")
    board_test_client.cookies.clear()
    _login(board_test_client, email="eve@example.com", name="Eve")
    r2 = board_test_client.patch(
        f"/api/v1/posts/{pid}", json={"title": "Hacked"}
    )
    assert r2.status_code == 403


def test_delete_post_own(board_test_client):
    _login(board_test_client)
    pid = _create_post(board_test_client).json()["id"]
    r = board_test_client.delete(f"/api/v1/posts/{pid}")
    assert r.status_code == 200
    # public can no longer see it
    board_test_client.post("/api/v1/auth/logout")
    board_test_client.cookies.clear()
    r2 = board_test_client.get(f"/api/v1/posts/{pid}")
    assert r2.status_code == 404


def test_freeform_category(board_test_client):
    _login(board_test_client)
    r = _create_post(board_test_client, freeform_category="새카테고리")
    assert r.status_code == 201
    assert r.json()["freeform_category"] == "새카테고리"


def test_verdict_summary_empty(board_test_client):
    _login(board_test_client)
    pid = _create_post(board_test_client).json()["id"]
    r = board_test_client.get(f"/api/v1/posts/{pid}/verdict-summary")
    assert r.status_code == 200
    assert r.json() == {"hot_deal": 0, "not_hot_deal": 0, "neutral": 0}
