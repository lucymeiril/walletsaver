"""운영자 헤드풀 브라우저 라우트 통합 테스트.

실 Playwright 대신 ``OperatorBrowserSessionManager``에 mock 팩토리를 주입한
인스턴스를 만들어 ``set_manager_for_test``로 라우트에 꽂는다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.routes import operator_browser as routes
from pipeline.operator_browser_session import (
    OperatorBrowserSessionManager,
    _BrowserHandles,
)


class _FakePage:
    def __init__(self, html: str = "<html><body>ok</body></html>"):
        self._html = html
        self.calls: list[tuple[str, dict]] = []

    async def goto(self, url, **kwargs):
        self.calls.append(("goto", {"url": url, **kwargs}))

    async def content(self):
        return self._html

    async def screenshot(self, **kwargs):
        return b"\x89PNGdata"

    async def click(self, selector, **kwargs):
        self.calls.append(("click", {"selector": selector}))

    async def fill(self, selector, value, **kwargs):
        self.calls.append(("fill", {"selector": selector, "value": value}))


class _FakeCloser:
    async def close(self): ...
    async def stop(self): ...


@pytest.fixture
def page() -> _FakePage:
    return _FakePage()


@pytest.fixture
def client(monkeypatch, tmp_path: Path, page: _FakePage):
    async def factory(**kwargs):
        return _BrowserHandles(
            playwright=_FakeCloser(),
            browser=_FakeCloser(),
            context=_FakeCloser(),
            page=page,
        )

    monkeypatch.setenv("REQUIRE_AUTH", "false")
    monkeypatch.setenv("OPERATOR_SOURCE_WORKBENCH_DIR", str(tmp_path / "workbench"))
    monkeypatch.setenv("SOURCE_RUN_DIR", str(tmp_path / "source_runs"))
    app = create_app()
    manager = OperatorBrowserSessionManager(headless=True, browser_factory=factory)
    routes.set_manager_for_test(manager)
    yield TestClient(app)
    routes.set_manager_for_test(None)


def test_policy_endpoint_returns_operator_workbench_policy(client: TestClient):
    resp = client.get("/api/operator-browser/policy")
    assert resp.status_code == 200
    data = resp.json()
    assert data["policy"]["automated_captcha_attempt"] is True
    assert data["policy"]["human_handoff_required_on_auto_failure"] is True
    assert data["policy"]["bypass_code_in_live_web_backend"] is False


def test_open_navigate_screenshot_html_close_full_flow(client: TestClient, page: _FakePage):
    open_resp = client.post("/api/operator-browser/sessions", json={"url": "https://example.com/sale"})
    assert open_resp.status_code == 200
    session_id = open_resp.json()["session"]["session_id"]
    assert session_id.startswith("opbs-")
    assert page.calls[0][0] == "goto"

    list_resp = client.get("/api/operator-browser/sessions")
    assert list_resp.status_code == 200
    assert len(list_resp.json()["sessions"]) == 1

    nav_resp = client.post(
        f"/api/operator-browser/sessions/{session_id}/navigate",
        json={"url": "https://example.com/login"},
    )
    assert nav_resp.status_code == 200
    assert any(c[0] == "goto" and c[1]["url"] == "https://example.com/login" for c in page.calls)

    shot = client.get(f"/api/operator-browser/sessions/{session_id}/screenshot")
    assert shot.status_code == 200
    assert shot.headers["content-type"] == "image/png"
    assert shot.content.startswith(b"\x89PNG")

    html_resp = client.get(f"/api/operator-browser/sessions/{session_id}/html")
    assert html_resp.status_code == 200
    assert "<body>" in html_resp.json()["html"]

    close_resp = client.delete(f"/api/operator-browser/sessions/{session_id}")
    assert close_resp.status_code == 200
    assert client.get("/api/operator-browser/sessions").json()["sessions"] == []


def test_click_and_fill_remote_control(client: TestClient, page: _FakePage):
    sid = client.post("/api/operator-browser/sessions", json={}).json()["session"]["session_id"]

    cr = client.post(f"/api/operator-browser/sessions/{sid}/click", json={"selector": "#login"})
    assert cr.status_code == 200
    assert ("click", {"selector": "#login"}) in page.calls

    fr = client.post(
        f"/api/operator-browser/sessions/{sid}/fill",
        json={"selector": "input[name=pw]", "value": "secret123", "sensitive": True},
    )
    assert fr.status_code == 200
    assert ("fill", {"selector": "input[name=pw]", "value": "secret123"}) in page.calls


def test_unknown_session_returns_404(client: TestClient):
    r = client.get("/api/operator-browser/sessions/opbs-nonexistent/html")
    assert r.status_code == 404


def test_navigate_validates_scheme(client: TestClient):
    sid = client.post("/api/operator-browser/sessions", json={}).json()["session"]["session_id"]
    r = client.post(
        f"/api/operator-browser/sessions/{sid}/navigate",
        json={"url": "javascript:alert(1)"},
    )
    assert r.status_code == 422


def test_wait_captcha_returns_resolved_when_no_captcha(client: TestClient):
    sid = client.post("/api/operator-browser/sessions", json={}).json()["session"]["session_id"]
    r = client.post(
        f"/api/operator-browser/sessions/{sid}/wait-captcha",
        json={"timeout_seconds": 1.0, "poll_interval_seconds": 0.05},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["resolved"] is True
    assert body["captcha_handoffs"] == 0
