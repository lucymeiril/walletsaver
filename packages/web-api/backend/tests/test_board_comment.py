"""Comment & verdict tests."""
from sqlalchemy.orm import Session

from storage.board_models import User, get_board_engine


def _register_login(client, email, name="U", pw="password1"):
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "display_name": name, "password": pw},
    )
    client.post("/api/v1/auth/login", json={"email": email, "password": pw})


def _create_post(client, slug="free"):
    return client.post(
        f"/api/v1/boards/{slug}/posts",
        data={"title": "T", "body_markdown": "B"},
    ).json()


def _promote(email, role="moderator"):
    engine = get_board_engine()
    with Session(engine) as db:
        u = db.query(User).filter(User.email == email).first()
        u.role = role
        db.commit()


def test_add_comment_with_verdict(board_test_client):
    _register_login(board_test_client, "a@x.com")
    pid = _create_post(board_test_client)["id"]
    r = board_test_client.post(
        f"/api/v1/posts/{pid}/comments",
        json={"body": "좋은 딜!", "verdict": "hot_deal"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["verdict"] == "hot_deal"


def test_verdict_summary_after_comments(board_test_client):
    _register_login(board_test_client, "a@x.com")
    pid = _create_post(board_test_client)["id"]
    board_test_client.post(
        f"/api/v1/posts/{pid}/comments",
        json={"body": "yes", "verdict": "hot_deal"},
    )
    board_test_client.post(
        f"/api/v1/posts/{pid}/comments",
        json={"body": "no", "verdict": "not_hot_deal"},
    )
    board_test_client.post(
        f"/api/v1/posts/{pid}/comments",
        json={"body": "meh", "verdict": "neutral"},
    )
    r = board_test_client.get(f"/api/v1/posts/{pid}/verdict-summary")
    assert r.json() == {"hot_deal": 1, "not_hot_deal": 1, "neutral": 1}


def test_mod_hide_comment(board_test_client):
    _register_login(board_test_client, "a@x.com")
    pid = _create_post(board_test_client)["id"]
    cid = board_test_client.post(
        f"/api/v1/posts/{pid}/comments",
        json={"body": "spam", "verdict": "neutral"},
    ).json()["id"]
    # Make user a moderator
    _promote("a@x.com", "moderator")
    r = board_test_client.patch(f"/api/v1/comments/{cid}")
    assert r.status_code == 200
    assert r.json()["hidden_at"] is not None


def test_non_mod_cannot_hide(board_test_client):
    _register_login(board_test_client, "a@x.com")
    pid = _create_post(board_test_client)["id"]
    cid = board_test_client.post(
        f"/api/v1/posts/{pid}/comments",
        json={"body": "x", "verdict": "neutral"},
    ).json()["id"]
    r = board_test_client.patch(f"/api/v1/comments/{cid}")
    assert r.status_code == 403
