"""Operator source workbench API.

The workbench accepts public/saved source artifacts and source registrations
for crawler-admin -> AI-admin -> DB-admin evidence flow. It never automates
CAPTCHA solving, credential use, WAF/access-control bypass, or stealth evasion.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from audit import AuditEventType, audit_log
from crawlers.registry.registry import CrawlerRegistry
from pipeline.operator_workbench import OperatorWorkbenchStore, SAFETY_POLICY
from pipeline.source_runs import SourceRunPipeline, SourceRunStore, load_source_input_artifact


router = APIRouter(prefix="/api/source-workbench", tags=["source-workbench"])

_NAME_RE = re.compile(r"^[a-zA-Z0-9_\-\.]+$")
_registry: CrawlerRegistry | None = None


class SourceCaptureRequest(BaseModel):
    crawler_name: str = Field(min_length=1, max_length=100)
    source_name: Optional[str] = Field(default=None, max_length=120)
    schema_type: str = Field(default="source_raw", min_length=1, max_length=60)
    source_url: Optional[str] = Field(default=None, max_length=2048)
    source_input: Optional[str] = Field(default=None, max_length=2_000_000)
    source_input_path: Optional[str] = Field(default=None, max_length=1024)
    artifact_type: str = Field(default="html", max_length=30)
    operator_notes: Optional[str] = Field(default=None, max_length=2000)
    network_events: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    run_capture: bool = True
    force_full: bool = False

    @field_validator("crawler_name", "source_name")
    @classmethod
    def validate_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        if not _NAME_RE.match(value):
            raise ValueError("name must contain only alphanumeric, dash, underscore, or dot")
        return value

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        value = value.strip()
        if not value.startswith(("http://", "https://")):
            raise ValueError("source_url must be http(s)")
        return value


class SourceRegistrationRequest(BaseModel):
    crawler_name: str = Field(min_length=1, max_length=100)
    source_name: str = Field(min_length=1, max_length=120)
    schema_type: str = Field(default="source_raw", min_length=1, max_length=60)
    source_url: str = Field(min_length=1, max_length=2048)
    cadence_cron: Optional[str] = Field(default=None, max_length=100)
    evidence_artifact_path: Optional[str] = Field(default=None, max_length=1024)
    operator_notes: Optional[str] = Field(default=None, max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("crawler_name", "source_name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not _NAME_RE.match(value):
            raise ValueError("name must contain only alphanumeric, dash, underscore, or dot")
        return value

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str) -> str:
        value = value.strip()
        if not value.startswith(("http://", "https://")):
            raise ValueError("source_url must be http(s)")
        return value


def _get_registry() -> CrawlerRegistry:
    global _registry
    if _registry is None:
        crawlers_dir = Path(__file__).resolve().parent.parent.parent / "crawlers"
        _registry = CrawlerRegistry(crawlers_dir=crawlers_dir)
        _registry.discover()
    return _registry


def _get_source_pipeline() -> SourceRunPipeline:
    return SourceRunPipeline(_get_registry(), store=SourceRunStore())


@router.post("/captures")
async def create_source_capture(request: Request, body: SourceCaptureRequest = Body(...)) -> dict[str, Any]:
    """Save operator source evidence and optionally run a no-DB AI handoff capture."""
    source_name = body.source_name or body.crawler_name
    source_input = body.source_input
    source_input_label = "request.source_input" if source_input is not None else None

    if source_input is None and body.source_input_path:
        try:
            source_input, source_input_label = load_source_input_artifact(body.source_input_path)
        except OSError as exc:
            raise HTTPException(status_code=400, detail=f"source_input_path could not be read: {exc}")

    if source_input is None and not body.source_url:
        raise HTTPException(status_code=422, detail="Provide source_input/source_input_path or source_url")

    capture = None
    run_source_input_path = body.source_input_path
    if source_input is not None:
        capture = OperatorWorkbenchStore().save_capture(
            crawler_name=body.crawler_name,
            source_name=source_name,
            schema_type=body.schema_type,
            source_url=body.source_url,
            artifact_text=source_input,
            artifact_type=body.artifact_type,
            operator_notes=body.operator_notes,
            network_events=body.network_events,
        )
        run_source_input_path = capture["artifact"]["path"]
        source_input_label = source_input_label or run_source_input_path

    result = None
    if body.run_capture:
        result_obj = await _get_source_pipeline().run_source_incremental(
            body.crawler_name,
            source_name=source_name,
            schema_type=body.schema_type,
            source_url=body.source_url,
            source_input_path=run_source_input_path if source_input is not None else None,
            source_input_label=source_input_label,
            force_full=body.force_full,
        )
        result = result_obj.to_dict()

    audit_log(
        AuditEventType.SOURCE_WORKBENCH_CAPTURE,
        request=request,
        resource=source_name,
        detail={"crawler_name": body.crawler_name, "run_capture": body.run_capture},
    )
    return {
        "schema": "operator_source_capture_response.v1",
        "capture": capture,
        "run": result,
        "safety_policy": SAFETY_POLICY,
    }


@router.post("/sources")
async def register_source(request: Request, body: SourceRegistrationRequest = Body(...)) -> dict[str, Any]:
    """Register a recurring public source candidate with evidence/health metadata only."""
    registration = OperatorWorkbenchStore().register_source(
        crawler_name=body.crawler_name,
        source_name=body.source_name,
        schema_type=body.schema_type,
        source_url=body.source_url,
        cadence_cron=body.cadence_cron,
        evidence_artifact_path=body.evidence_artifact_path,
        operator_notes=body.operator_notes,
        tags=body.tags,
    )
    audit_log(
        AuditEventType.SOURCE_WORKBENCH_REGISTER,
        request=request,
        resource=body.source_name,
        detail={"crawler_name": body.crawler_name, "cadence_cron": body.cadence_cron},
    )
    return registration


@router.get("/sources")
async def list_registered_sources() -> dict[str, Any]:
    """List operator-registered public source candidates."""
    return {
        "schema": "operator_source_registry.v1",
        "sources": OperatorWorkbenchStore().list_sources(),
        "safety_policy": SAFETY_POLICY,
    }
