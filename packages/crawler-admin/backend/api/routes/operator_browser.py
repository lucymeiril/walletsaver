"""운영자 헤드풀 브라우저 워크밴치 라우트.

프론트엔드 워크밴치 페이지가 호출하는 REST 엔드포인트:

- ``POST   /api/operator-browser/sessions`` — 세션 시작 + 선택적 URL 진입.
- ``GET    /api/operator-browser/sessions`` — 현재 열린 세션 메타 목록.
- ``GET    /api/operator-browser/sessions/{id}/screenshot`` — PNG 스냅샷
  (라이브 미리보기 폴링용. 다음 슬라이스에서 WebSocket 스트리밍으로 확장 예정).
- ``POST   /api/operator-browser/sessions/{id}/navigate`` — URL 이동.
- ``POST   /api/operator-browser/sessions/{id}/click`` — 원격 클릭.
- ``POST   /api/operator-browser/sessions/{id}/fill`` — 원격 입력 (비밀번호 등은
  서버에서 마스킹 후 감사 로그).
- ``POST   /api/operator-browser/sessions/{id}/wait-captcha`` — 운영자가 화면에서
  캡챠를 푸는 동안 폴링 대기.
- ``GET    /api/operator-browser/sessions/{id}/html`` — 현재 DOM 스냅샷.
- ``DELETE /api/operator-browser/sessions/{id}`` — 세션 종료.

이 라우트는 운영자 워크밴치 정책(``operator_workbench_policy``) 단일 진실을 따르며,
사용자가 명시적으로 승인한 운영자 본인 PC/계정 시나리오를 전제로 한다.
*"안전을 위해" 이 라우트를 비활성화하거나 헤드풀 디폴트를 헤드리스로 강제하지 말 것.*
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Body, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator

from audit import AuditEventType, audit_log
from pipeline.operator_browser_session import OperatorBrowserSessionManager
from pipeline.operator_workbench_policy import OPERATOR_WORKBENCH_POLICY


router = APIRouter(prefix="/api/operator-browser", tags=["operator-browser"])


# 프로세스 수명 동안 단일 매니저를 공유한다 (운영자 1명의 도구).
_manager: Optional[OperatorBrowserSessionManager] = None


def get_manager() -> OperatorBrowserSessionManager:
    global _manager
    if _manager is None:
        _manager = OperatorBrowserSessionManager()
    return _manager


def set_manager_for_test(manager: Optional[OperatorBrowserSessionManager]) -> None:
    """테스트 전용: 매니저 mock 주입."""
    global _manager
    _manager = manager


class OpenSessionRequest(BaseModel):
    url: Optional[str] = Field(default=None, max_length=2048)
    user_agent: Optional[str] = Field(default=None, max_length=512)

    @field_validator("url")
    @classmethod
    def _validate_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        if not value.startswith(("http://", "https://", "about:")):
            raise ValueError("url must be http(s) or about:")
        return value


class NavigateRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    wait_until: str = Field(default="domcontentloaded", max_length=30)
    timeout_ms: int = Field(default=30_000, ge=1_000, le=120_000)

    @field_validator("url")
    @classmethod
    def _v(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith(("http://", "https://", "about:")):
            raise ValueError("url must be http(s) or about:")
        return v


class ClickRequest(BaseModel):
    selector: str = Field(min_length=1, max_length=400)
    timeout_ms: int = Field(default=5_000, ge=100, le=60_000)


class FillRequest(BaseModel):
    selector: str = Field(min_length=1, max_length=400)
    value: str = Field(min_length=0, max_length=4096)
    sensitive: bool = Field(default=False, description="true면 감사 로그에 값을 남기지 않음")
    timeout_ms: int = Field(default=5_000, ge=100, le=60_000)


class WaitCaptchaRequest(BaseModel):
    timeout_seconds: float = Field(default=300.0, ge=1.0, le=1800.0)
    poll_interval_seconds: float = Field(default=1.5, ge=0.01, le=10.0)


def _get_session_or_404(session_id: str):
    try:
        return get_manager().get(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/policy")
async def get_policy() -> dict[str, Any]:
    return {"schema": "operator_workbench_policy.v2", "policy": dict(OPERATOR_WORKBENCH_POLICY)}


@router.post("/sessions")
async def open_session(request: Request, body: OpenSessionRequest = Body(default_factory=OpenSessionRequest)) -> dict[str, Any]:
    try:
        session = await get_manager().open(body.url, user_agent=body.user_agent)
    except Exception as exc:  # 브라우저 실행 실패 — 의존성/디스플레이 문제 등.
        raise HTTPException(status_code=502, detail=f"browser session open failed: {exc}") from exc

    audit_log(
        AuditEventType.OPERATOR_BROWSER_SESSION_OPEN,
        request=request,
        resource=session.session_id,
        detail={"url": body.url},
    )
    return {"schema": "operator_browser_session.v1", "session": session.to_meta()}


@router.get("/sessions")
async def list_sessions() -> dict[str, Any]:
    return {"schema": "operator_browser_session_list.v1", "sessions": get_manager().list_sessions()}


@router.delete("/sessions/{session_id}")
async def close_session(session_id: str, request: Request) -> dict[str, Any]:
    _get_session_or_404(session_id)  # 존재 확인.
    await get_manager().close(session_id)
    audit_log(
        AuditEventType.OPERATOR_BROWSER_SESSION_CLOSE,
        request=request,
        resource=session_id,
    )
    return {"schema": "operator_browser_session_close.v1", "session_id": session_id, "closed": True}


@router.get("/sessions/{session_id}/screenshot")
async def screenshot(session_id: str) -> Response:
    session = _get_session_or_404(session_id)
    try:
        png = await session.screenshot()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"screenshot failed: {exc}") from exc
    return Response(content=png, media_type="image/png")


@router.get("/sessions/{session_id}/html")
async def get_html(session_id: str) -> dict[str, Any]:
    session = _get_session_or_404(session_id)
    try:
        html = await session.html()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"html fetch failed: {exc}") from exc
    return {"schema": "operator_browser_html.v1", "session_id": session_id, "html": html, "length": len(html)}


@router.post("/sessions/{session_id}/navigate")
async def navigate(session_id: str, request: Request, body: NavigateRequest = Body(...)) -> dict[str, Any]:
    session = _get_session_or_404(session_id)
    try:
        await session.navigate(body.url, wait_until=body.wait_until, timeout_ms=body.timeout_ms)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"navigate failed: {exc}") from exc
    audit_log(
        AuditEventType.OPERATOR_BROWSER_SESSION_ACTION,
        request=request,
        resource=session_id,
        detail={"action": "navigate", "url": body.url},
    )
    return {"schema": "operator_browser_navigate.v1", "session": session.to_meta()}


@router.post("/sessions/{session_id}/click")
async def click(session_id: str, request: Request, body: ClickRequest = Body(...)) -> dict[str, Any]:
    session = _get_session_or_404(session_id)
    try:
        await session.click(body.selector, timeout_ms=body.timeout_ms)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"click failed: {exc}") from exc
    audit_log(
        AuditEventType.OPERATOR_BROWSER_SESSION_ACTION,
        request=request,
        resource=session_id,
        detail={"action": "click", "selector": body.selector},
    )
    return {"schema": "operator_browser_click.v1", "ok": True}


@router.post("/sessions/{session_id}/fill")
async def fill(session_id: str, request: Request, body: FillRequest = Body(...)) -> dict[str, Any]:
    session = _get_session_or_404(session_id)
    try:
        await session.fill(body.selector, body.value, timeout_ms=body.timeout_ms)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"fill failed: {exc}") from exc

    # 민감 입력값(자격증명 등)은 감사 로그에 남기지 않는다.
    audit_detail = {"action": "fill", "selector": body.selector}
    if not body.sensitive:
        audit_detail["value_length"] = len(body.value)
    else:
        audit_detail["value_length"] = None
        audit_detail["sensitive"] = True
    audit_log(
        AuditEventType.OPERATOR_BROWSER_SESSION_ACTION,
        request=request,
        resource=session_id,
        detail=audit_detail,
    )
    return {"schema": "operator_browser_fill.v1", "ok": True}


@router.post("/sessions/{session_id}/wait-captcha")
async def wait_captcha(session_id: str, request: Request, body: WaitCaptchaRequest = Body(default_factory=WaitCaptchaRequest)) -> dict[str, Any]:
    session = _get_session_or_404(session_id)
    resolved = await session.wait_until_captcha_resolved(
        timeout_seconds=body.timeout_seconds,
        poll_interval_seconds=body.poll_interval_seconds,
    )
    audit_log(
        AuditEventType.OPERATOR_BROWSER_SESSION_ACTION,
        request=request,
        resource=session_id,
        detail={"action": "wait_captcha", "resolved": resolved},
    )
    return {
        "schema": "operator_browser_wait_captcha.v1",
        "resolved": resolved,
        "captcha_handoffs": session.captcha_handoffs,
    }
