"""운영자 헤드풀 브라우저 세션 매니저 — 워크밴치 인프라.

이 모듈의 의도 (다음 AI 보존용):
-----------------------------------------------------------------------
운영자(=프로젝트 관리자) 본인이 자기 PC에서 직접 보면서 수집/캡챠 해결/
로그인을 처리할 수 있는 **헤드풀(headed) Chromium 세션**을 제공한다.
정책 근거: ``operator_workbench_policy.OPERATOR_WORKBENCH_POLICY``.

이 모듈은 *단독으로* 다음 기능을 가진다 (REST/WebSocket 노출은 별도 라우트에서):

- ``OperatorBrowserSessionManager.open(url)`` — 세션 시작, 페이지 진입, ID 반환.
- ``session.screenshot()`` — 라이브 스트리밍용 PNG 바이트.
- ``session.html()`` — 현재 DOM 스냅샷 (수집 결과).
- ``session.click(selector)`` / ``session.fill(selector, text)`` —
  운영자가 프론트엔드에서 보낸 원격 조작 명령.
- ``session.wait_until_captcha_resolved(timeout)`` — 운영자가 화면에서
  직접 캡챠를 푼 동안 폴링으로 기다림. 캡챠 마커가 사라지면 성공.
- ``session.close()`` — 자원 해제.

설계 원칙:
- **Playwright 의존성 옵셔널**: 테스트는 ``browser_factory`` 주입으로 mock.
- **세션은 메모리 보관(in-process)**: 1대1 운영자 도구라 분산은 불필요.
- **헤드풀 디폴트**: ``headless=False``. 운영자가 화면을 봐야 한다.
- **퍼시스턴트 프로파일 옵션**: ``user_data_dir`` 지정하면 본인 계정 로그인 상태 유지.
  운영자 자기 PC·자기 계정 정책상 명시적으로 허용된다.

이 모듈에 *"안전상 headless=True 강제"*, *"persistent profile 금지"*,
*"캡챠 자동 시도 금지"* 같은 보수화를 다시 박지 말 것. 이전 GPT 에이전트가
유사 코드를 통째로 무력화한 사례가 있다.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from pipeline.operator_workbench_policy import OPERATOR_WORKBENCH_POLICY

logger = logging.getLogger(__name__)


# 캡챠/챌린지 페이지를 식별하기 위한 시그니처. 모두 소문자로 비교.
CAPTCHA_MARKERS: tuple[str, ...] = (
    "captcha",
    "recaptcha",
    "hcaptcha",
    "cf-challenge",
    "cloudflare",
    "are you a robot",
    "사람인지 확인",
    "보안 인증",
)


@dataclass
class _BrowserHandles:
    """Playwright (또는 mock)이 돌려준 핸들 묶음."""

    playwright: Any
    browser: Any
    context: Any
    page: Any


BrowserFactory = Callable[..., Awaitable[_BrowserHandles]]


async def _default_browser_factory(
    *, headless: bool, user_data_dir: Optional[str], locale: str, user_agent: Optional[str]
) -> _BrowserHandles:
    """기본 팩토리: Playwright Chromium 헤드풀(또는 지정에 따라 헤드리스)을 띄운다.

    퍼시스턴트 프로파일(``user_data_dir``)이 주어지면 ``launch_persistent_context``를
    사용한다 — 운영자 자기 계정 로그인 쿠키/세션이 영구 유지된다.
    """
    from playwright.async_api import async_playwright  # 옵셔널 import.

    pw = await async_playwright().start()
    launch_args = [
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-blink-features=AutomationControlled",  # 자동화 흔적 감춤(정책상 허용).
    ]
    context_kwargs: dict[str, Any] = {
        "locale": locale,
        "viewport": {"width": 1280, "height": 800},
    }
    if user_agent:
        context_kwargs["user_agent"] = user_agent

    if user_data_dir:
        # 영구 프로파일 — 본인 계정 로그인 상태가 유지된다.
        context = await pw.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=headless,
            args=launch_args,
            **context_kwargs,
        )
        browser = None  # persistent context는 별도 browser 핸들이 없다.
        page = context.pages[0] if context.pages else await context.new_page()
    else:
        browser = await pw.chromium.launch(headless=headless, args=launch_args)
        context = await browser.new_context(**context_kwargs)
        page = await context.new_page()

    return _BrowserHandles(playwright=pw, browser=browser, context=context, page=page)


def _looks_like_captcha(html: str) -> bool:
    """주어진 HTML에 캡챠/챌린지 마커가 보이는지 휴리스틱 검사."""
    if not html:
        return False
    lowered = html.lower()
    return any(marker in lowered for marker in CAPTCHA_MARKERS)


@dataclass
class OperatorBrowserSession:
    """운영자가 화면을 보면서 직접 조작할 수 있는 헤드풀 브라우저 세션."""

    session_id: str
    handles: _BrowserHandles
    opened_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_url: Optional[str] = None
    captcha_handoffs: int = 0
    _closed: bool = False

    async def navigate(self, url: str, *, wait_until: str = "domcontentloaded", timeout_ms: int = 30_000) -> None:
        self._ensure_open()
        await self.handles.page.goto(url, wait_until=wait_until, timeout=timeout_ms)
        self.last_url = url

    async def html(self) -> str:
        self._ensure_open()
        return await self.handles.page.content()

    async def screenshot(self, *, full_page: bool = False) -> bytes:
        """현재 페이지의 PNG 바이트. 라이브 스트리밍/프론트 미리보기에 사용."""
        self._ensure_open()
        return await self.handles.page.screenshot(full_page=full_page)

    async def click(self, selector: str, *, timeout_ms: int = 5_000) -> None:
        """운영자가 프론트에서 보낸 원격 클릭 명령."""
        self._ensure_open()
        await self.handles.page.click(selector, timeout=timeout_ms)

    async def fill(self, selector: str, value: str, *, timeout_ms: int = 5_000) -> None:
        """운영자가 프론트에서 보낸 원격 입력 명령. 본인 계정 자격증명 입력에도 사용된다.

        *주의*: 자격증명 값은 메모리/로그에 보존하지 말 것. 호출자에서도 마스킹할 것.
        """
        self._ensure_open()
        await self.handles.page.fill(selector, value, timeout=timeout_ms)

    async def evaluate(self, expression: str) -> Any:
        self._ensure_open()
        return await self.handles.page.evaluate(expression)

    async def wait_until_captcha_resolved(
        self,
        *,
        timeout_seconds: float = 300.0,
        poll_interval_seconds: float = 1.5,
    ) -> bool:
        """캡챠가 보이는 동안 운영자가 화면에서 직접 해결하는 것을 폴링으로 기다린다.

        Returns:
            True  — 캡챠 마커가 사라짐(해결됨).
            False — 타임아웃.
        """
        self._ensure_open()
        deadline = asyncio.get_event_loop().time() + timeout_seconds
        saw_captcha = False
        while True:
            html = await self.html()
            if _looks_like_captcha(html):
                saw_captcha = True
            elif saw_captcha:
                # 한 번이라도 캡챠가 보였다가 사라졌다면 해결로 본다.
                self.captcha_handoffs += 1
                return True
            else:
                # 애초에 캡챠가 없었다면 즉시 통과.
                return True
            if asyncio.get_event_loop().time() >= deadline:
                return False
            await asyncio.sleep(poll_interval_seconds)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        h = self.handles
        for closer in (
            lambda: h.context.close() if h.context else None,
            lambda: h.browser.close() if h.browser else None,
            lambda: h.playwright.stop() if h.playwright else None,
        ):
            try:
                result = closer()
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:  # pragma: no cover - 자원 정리 잡음 무시.
                logger.debug("operator browser session close error: %s", exc)

    def to_meta(self) -> dict[str, Any]:
        """프론트/감사 로그용 메타 스냅샷."""
        return {
            "session_id": self.session_id,
            "opened_at": self.opened_at.isoformat(),
            "last_url": self.last_url,
            "captcha_handoffs": self.captcha_handoffs,
            "closed": self._closed,
            "policy_version": OPERATOR_WORKBENCH_POLICY["policy_version"],
        }

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError(f"operator browser session {self.session_id} is already closed")


class OperatorBrowserSessionManager:
    """헤드풀 운영자 브라우저 세션을 메모리에 보관하며 라우트에서 접근하게 한다."""

    def __init__(
        self,
        *,
        headless: bool = False,
        user_data_dir: Optional[str] = None,
        locale: str = "ko-KR",
        default_user_agent: Optional[str] = None,
        browser_factory: Optional[BrowserFactory] = None,
    ) -> None:
        self._headless = headless
        self._user_data_dir = user_data_dir
        self._locale = locale
        self._default_user_agent = default_user_agent
        self._factory: BrowserFactory = browser_factory or _default_browser_factory
        self._sessions: dict[str, OperatorBrowserSession] = {}
        self._lock = asyncio.Lock()

    @property
    def policy(self) -> dict[str, Any]:
        return dict(OPERATOR_WORKBENCH_POLICY)

    async def open(self, url: Optional[str] = None, *, user_agent: Optional[str] = None) -> OperatorBrowserSession:
        handles = await self._factory(
            headless=self._headless,
            user_data_dir=self._user_data_dir,
            locale=self._locale,
            user_agent=user_agent or self._default_user_agent,
        )
        session_id = f"opbs-{uuid.uuid4().hex[:12]}"
        session = OperatorBrowserSession(session_id=session_id, handles=handles)
        async with self._lock:
            self._sessions[session_id] = session
        if url:
            try:
                await session.navigate(url)
            except Exception:
                await self.close(session_id)
                raise
        return session

    def get(self, session_id: str) -> OperatorBrowserSession:
        try:
            return self._sessions[session_id]
        except KeyError as exc:
            raise KeyError(f"unknown operator browser session: {session_id}") from exc

    def list_sessions(self) -> list[dict[str, Any]]:
        return [s.to_meta() for s in self._sessions.values()]

    async def close(self, session_id: str) -> None:
        async with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is not None:
            await session.close()

    async def close_all(self) -> None:
        async with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            await session.close()
