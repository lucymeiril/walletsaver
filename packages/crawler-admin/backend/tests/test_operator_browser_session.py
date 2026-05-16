"""운영자 헤드풀 브라우저 세션 매니저 테스트.

실 Playwright를 띄우지 않고 ``browser_factory`` 주입으로 mock을 사용한다.
세션 생명주기 / 캡챠 폴링 인계 / 정책 노출 / 자원 정리를 검증한다.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import pytest

from pipeline.operator_browser_session import (
    OperatorBrowserSession,
    OperatorBrowserSessionManager,
    _BrowserHandles,
    _looks_like_captcha,
)


class _FakePage:
    def __init__(self, html_sequence: Optional[list[str]] = None):
        self._html_sequence = list(html_sequence) if html_sequence is not None else ["<html><body>ok</body></html>"]
        self.goto_calls: list[tuple[str, dict[str, Any]]] = []
        self.click_calls: list[str] = []
        self.fill_calls: list[tuple[str, str]] = []
        self.screenshot_calls = 0
        self.eval_calls: list[str] = []

    async def goto(self, url: str, **kwargs):
        self.goto_calls.append((url, kwargs))

    async def content(self) -> str:
        if len(self._html_sequence) == 1:
            return self._html_sequence[0]
        return self._html_sequence.pop(0)

    async def screenshot(self, **kwargs) -> bytes:
        self.screenshot_calls += 1
        return b"\x89PNG-fake"

    async def click(self, selector: str, **kwargs):
        self.click_calls.append(selector)

    async def fill(self, selector: str, value: str, **kwargs):
        self.fill_calls.append((selector, value))

    async def evaluate(self, expression: str):
        self.eval_calls.append(expression)
        return "ok"


class _FakeCloser:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True

    async def stop(self):
        self.closed = True


def _make_factory(page: _FakePage):
    closers = {"pw": _FakeCloser(), "browser": _FakeCloser(), "context": _FakeCloser()}

    async def factory(*, headless, user_data_dir, locale, user_agent):
        return _BrowserHandles(
            playwright=closers["pw"],
            browser=closers["browser"],
            context=closers["context"],
            page=page,
        )

    return factory, closers


def test_looks_like_captcha_detects_common_markers():
    assert _looks_like_captcha("<html>please solve CAPTCHA</html>") is True
    assert _looks_like_captcha("<div>reCAPTCHA challenge</div>") is True
    assert _looks_like_captcha("<p>사람인지 확인해주세요</p>") is True
    assert _looks_like_captcha("<html><body>normal page</body></html>") is False
    assert _looks_like_captcha("") is False


@pytest.mark.asyncio
async def test_manager_opens_session_navigates_and_exposes_html():
    page = _FakePage(html_sequence=["<html>product list</html>"])
    factory, closers = _make_factory(page)
    mgr = OperatorBrowserSessionManager(headless=True, browser_factory=factory)

    session = await mgr.open("https://example.com/sale")

    assert page.goto_calls == [("https://example.com/sale", {"wait_until": "domcontentloaded", "timeout": 30_000})]
    assert (await session.html()) == "<html>product list</html>"
    assert session.last_url == "https://example.com/sale"

    meta = session.to_meta()
    assert meta["session_id"].startswith("opbs-")
    assert meta["last_url"] == "https://example.com/sale"
    assert "policy_version" in meta

    await mgr.close_all()
    assert closers["context"].closed is True
    assert closers["browser"].closed is True
    assert closers["pw"].closed is True


@pytest.mark.asyncio
async def test_remote_control_click_fill_screenshot_and_evaluate():
    page = _FakePage()
    factory, _ = _make_factory(page)
    mgr = OperatorBrowserSessionManager(browser_factory=factory)
    session = await mgr.open()

    await session.click("#login-btn")
    await session.fill("input[name=email]", "operator@example.com")
    png = await session.screenshot()
    result = await session.evaluate("document.title")

    assert page.click_calls == ["#login-btn"]
    assert page.fill_calls == [("input[name=email]", "operator@example.com")]
    assert png == b"\x89PNG-fake"
    assert result == "ok"
    await mgr.close_all()


@pytest.mark.asyncio
async def test_wait_until_captcha_resolved_returns_true_after_operator_solves():
    # 처음엔 캡챠 페이지, 두 번째 폴링에서 정상 페이지로 바뀜.
    page = _FakePage(html_sequence=[
        "<html>solve CAPTCHA please</html>",
        "<html>normal content</html>",
    ])
    factory, _ = _make_factory(page)
    mgr = OperatorBrowserSessionManager(browser_factory=factory)
    session = await mgr.open()

    ok = await session.wait_until_captcha_resolved(timeout_seconds=3.0, poll_interval_seconds=0.01)
    assert ok is True
    assert session.captcha_handoffs == 1
    await mgr.close_all()


@pytest.mark.asyncio
async def test_wait_until_captcha_resolved_times_out_when_never_solved():
    page = _FakePage(html_sequence=["<html>CAPTCHA persists</html>"])
    factory, _ = _make_factory(page)
    mgr = OperatorBrowserSessionManager(browser_factory=factory)
    session = await mgr.open()

    ok = await session.wait_until_captcha_resolved(timeout_seconds=0.2, poll_interval_seconds=0.05)
    assert ok is False
    await mgr.close_all()


@pytest.mark.asyncio
async def test_wait_returns_true_immediately_when_no_captcha():
    page = _FakePage(html_sequence=["<html>clean page</html>"])
    factory, _ = _make_factory(page)
    mgr = OperatorBrowserSessionManager(browser_factory=factory)
    session = await mgr.open()

    ok = await session.wait_until_captcha_resolved(timeout_seconds=1.0, poll_interval_seconds=0.01)
    assert ok is True
    assert session.captcha_handoffs == 0
    await mgr.close_all()


@pytest.mark.asyncio
async def test_get_and_close_individual_session():
    page = _FakePage()
    factory, closers = _make_factory(page)
    mgr = OperatorBrowserSessionManager(browser_factory=factory)
    session = await mgr.open()

    same = mgr.get(session.session_id)
    assert same is session

    listing = mgr.list_sessions()
    assert len(listing) == 1
    assert listing[0]["session_id"] == session.session_id

    await mgr.close(session.session_id)
    with pytest.raises(KeyError):
        mgr.get(session.session_id)


@pytest.mark.asyncio
async def test_closed_session_rejects_further_operations():
    page = _FakePage()
    factory, _ = _make_factory(page)
    mgr = OperatorBrowserSessionManager(browser_factory=factory)
    session = await mgr.open()
    await mgr.close(session.session_id)

    with pytest.raises(RuntimeError):
        await session.html()
    with pytest.raises(RuntimeError):
        await session.click("#x")


@pytest.mark.asyncio
async def test_manager_exposes_operator_workbench_policy():
    mgr = OperatorBrowserSessionManager(browser_factory=_make_factory(_FakePage())[0])
    policy = mgr.policy

    # 운영자 정책상 자동 시도/스텔스/챌린지 풀이/사람 인계는 허용.
    assert policy["automated_captcha_attempt"] is True
    assert policy["automation_flag_hiding_allowed"] is True
    assert policy["challenge_solver_libraries_allowed"] is True
    assert policy["human_handoff_required_on_auto_failure"] is True
    # 변하지 않는 금지선.
    assert policy["third_party_credential_automation"] is False
    assert policy["bypass_code_in_live_web_backend"] is False


@pytest.mark.asyncio
async def test_open_url_failure_cleans_up_session():
    """페이지 진입 실패 시 자원이 누수되지 않는다."""

    class _BadPage(_FakePage):
        async def goto(self, url, **kwargs):
            raise RuntimeError("network down")

    bad_page = _BadPage()
    factory, closers = _make_factory(bad_page)
    mgr = OperatorBrowserSessionManager(browser_factory=factory)

    with pytest.raises(RuntimeError, match="network down"):
        await mgr.open("https://example.com/will-fail")

    assert mgr.list_sessions() == []
    assert closers["context"].closed is True
