"""Focused route regressions for the current web API runtime.

The public API must be testable without opening the repository's real catalog DB.
Community tests use temporary, physically separate account and board SQLite files.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.auth_service import create_token_pair
from services.user_storage import PublicUserStore


@pytest.fixture(autouse=True)
def isolated_board(tmp_path, monkeypatch):
    board_path = tmp_path / "board.sqlite"
    monkeypatch.setenv("WALLETSAVIOR_BOARD_DB", str(board_path))

    from services import board_storage

    board_storage.reset_board_engine()
    # The current board runtime creates only schema. Tests create their own data.
    board_storage.get_board_engine()
    yield board_path
    board_storage.reset_board_engine()


@pytest.fixture()
def account_db(tmp_path):
    from services.account_database import AccountDatabase

    db = AccountDatabase(tmp_path / "accounts.sqlite")
    yield db
    db.close()


@pytest.fixture()
def app(account_db):
    from api.app import create_app

    return create_app(storage=account_db)


@pytest.fixture()
def client(app):
    return TestClient(app)


def _identity(account_db, email: str, nickname: str) -> tuple[dict, dict[str, str]]:
    """Create a real persistent test account and its access-token header."""
    user = PublicUserStore(account_db).create_password_user(
        email=email,
        nickname=nickname,
        hashed_password="test-only-unused-password-hash",
    )
    tokens = create_token_pair(user["id"], user["email"], user["role"])
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    return user, headers


def test_health_uses_injected_storage_without_repository_db(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": "0.1.0",
        "catalog": "injected",
        "accounts": "ok",
    }


def test_community_database_is_physically_separate(isolated_board, client):
    response = client.get("/api/posts")
    assert response.status_code == 200
    assert isolated_board.is_file()

    with sqlite3.connect(isolated_board) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

    assert {
        "community_users",
        "community_posts",
        "community_comments",
        "community_votes",
    }.issubset(tables)
    # Product/catalog tables belong to the replaceable catalog snapshot, never the board file.
    assert "products" not in tables
    assert "matching_entries" not in tables
    assert "pending_ingestions" not in tables


def test_empty_board_is_readable_from_isolated_database(client):
    response = client.get("/api/posts")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"] == []
    assert body["meta"]["total"] == 0


def test_authenticated_community_crud_comment_and_vote_flow(client, account_db):
    user, headers = _identity(account_db, "community@example.com", "커뮤니티유저")

    created = client.post(
        "/api/posts",
        json={
            "title": "격리 게시판 테스트",
            "content": "board.sqlite에만 저장되어야 합니다.",
            "post_type": "free",
            "category": "test",
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    post = created.json()["data"]
    post_id = post["id"]
    assert post["author_id"] == user["id"]

    first_get = client.get(f"/api/posts/{post_id}")
    second_get = client.get(f"/api/posts/{post_id}")
    assert first_get.status_code == 200
    assert second_get.json()["data"]["views"] == first_get.json()["data"]["views"] + 1

    updated = client.put(
        f"/api/posts/{post_id}",
        json={"title": "수정된 격리 게시판 테스트"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["title"] == "수정된 격리 게시판 테스트"

    comment = client.post(
        f"/api/posts/{post_id}/comments",
        json={"content": "댓글도 board DB에 저장"},
        headers=headers,
    )
    assert comment.status_code == 200
    assert comment.json()["data"]["author_id"] == user["id"]

    voted = client.post(
        f"/api/posts/{post_id}/vote",
        json={"vote_type": "hot"},
        headers=headers,
    )
    assert voted.status_code == 200
    assert voted.json()["data"]["user_vote"] == "hot"
    assert voted.json()["data"]["hot_votes"] == 1

    toggled = client.post(
        f"/api/posts/{post_id}/vote",
        json={"vote_type": "hot"},
        headers=headers,
    )
    assert toggled.status_code == 200
    assert toggled.json()["data"]["user_vote"] is None
    assert toggled.json()["data"]["hot_votes"] == 0

    deleted = client.delete(f"/api/posts/{post_id}", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json()["data"]["status"] == "deleted"
    assert client.get(f"/api/posts/{post_id}").status_code == 404


def test_other_user_cannot_modify_or_delete_post(client, account_db):
    _, owner_headers = _identity(account_db, "owner@example.com", "글쓴이")
    _, other_headers = _identity(account_db, "other@example.com", "다른유저")

    created = client.post(
        "/api/posts",
        json={"title": "권한 테스트", "content": "owner only", "post_type": "free"},
        headers=owner_headers,
    )
    assert created.status_code == 200
    post_id = created.json()["data"]["id"]

    update = client.put(
        f"/api/posts/{post_id}",
        json={"title": "남의 글 수정"},
        headers=other_headers,
    )
    delete = client.delete(f"/api/posts/{post_id}", headers=other_headers)

    assert update.status_code == 403
    assert delete.status_code == 403


def test_comment_and_vote_require_authentication(client):
    post_id = 1
    assert client.post(
        f"/api/posts/{post_id}/comments",
        json={"content": "anonymous"},
    ).status_code == 401
    assert client.post(
        f"/api/posts/{post_id}/vote",
        json={"vote_type": "hot"},
    ).status_code == 401
