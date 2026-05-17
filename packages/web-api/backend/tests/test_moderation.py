"""Moderation tests."""
from sqlalchemy.orm import Session

from storage.board_models import User, get_board_engine


def _register_login(client, email, name="U", pw="password1"):
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "display_name": name, "password": pw},
    )
    client.post("/api/v1/auth/login", json={"email": email, "password": pw})


def _promote(email, role="moderator"):
    engine = get_board_engine()
    with Session(engine) as db:
        u = db.query(User).filter(User.email == email).first()
        u.role = role
        db.commit()


def _create_post(client):
    return client.post(
        "/api/v1/boards/free/posts",
        data={"title": "T", "body_markdown": "B"},
    ).json()


def test_report_post(board_test_client):
    _register_login(board_test_client, "a@x.com")
    pid = _create_post(board_test_client)["id"]
    r = board_test_client.post(
        f"/api/v1/posts/{pid}/report", json={"reason": "스팸"}
    )
    assert r.status_code == 201
    assert r.json()["report_id"]


def test_list_reports_open(board_test_client):
    _register_login(board_test_client, "a@x.com")
    pid = _create_post(board_test_client)["id"]
    board_test_client.post(f"/api/v1/posts/{pid}/report", json={"reason": "스팸"})
    _promote("a@x.com")
    r = board_test_client.get("/api/v1/reports")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["target_id"] == pid


def test_resolve_report_dismiss(board_test_client):
    _register_login(board_test_client, "a@x.com")
    pid = _create_post(board_test_client)["id"]
    rid = board_test_client.post(
        f"/api/v1/posts/{pid}/report", json={"reason": "x"}
    ).json()["report_id"]
    _promote("a@x.com")
    r = board_test_client.post(
        f"/api/v1/reports/{rid}/resolve",
        json={"action": "dismiss", "note": "노이즈"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "dismissed"


def test_ban_user(board_test_client):
    _register_login(board_test_client, "a@x.com")
    _register_login(board_test_client, "b@x.com")
    # b is the bad user (currently logged in). Promote a to mod.
    _promote("a@x.com")
    # Lookup b's id
    engine = get_board_engine()
    with Session(engine) as db:
        bu = db.query(User).filter(User.email == "b@x.com").first()
        bid = bu.id
    # Log back in as a
    board_test_client.cookies.clear()
    board_test_client.post(
        "/api/v1/auth/login", json={"email": "a@x.com", "password": "password1"}
    )
    r = board_test_client.post(f"/api/v1/users/{bid}/ban")
    assert r.status_code == 200
    with Session(engine) as db:
        bu = db.get(User, bid)
        assert bu.banned_at is not None


def test_audit_log_after_action(board_test_client):
    _register_login(board_test_client, "a@x.com")
    _promote("a@x.com")
    board_test_client.cookies.clear()
    board_test_client.post(
        "/api/v1/auth/login", json={"email": "a@x.com", "password": "password1"}
    )
    # Create another user and ban
    board_test_client.post(
        "/api/v1/auth/register",
        json={"email": "c@x.com", "display_name": "C", "password": "password1"},
    )
    engine = get_board_engine()
    with Session(engine) as db:
        cid = db.query(User).filter(User.email == "c@x.com").first().id
    board_test_client.post(f"/api/v1/users/{cid}/ban")
    r = board_test_client.get("/api/v1/admin/audit")
    assert r.status_code == 200
    actions = [row["action"] for row in r.json()]
    assert "ban_user" in actions
