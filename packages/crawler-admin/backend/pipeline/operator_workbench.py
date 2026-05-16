"""Operator source workbench persistence for public/saved crawler evidence.

This module stores operator-provided public page/source artifacts and source
registrations. It does not solve CAPTCHA, use credentials, bypass WAF/access
controls, or add stealth behavior.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


WORKBENCH_SCHEMA = "operator_source_workbench.v1"
SAFETY_POLICY = {
    "public_pages_only": True,
    "persistent_local_profile_allowed": True,
    "human_saved_source_import_allowed": True,
    "automated_captcha_solving": False,
    "credential_automation": False,
    "waf_or_access_control_bypass": False,
    "stealth_evasion": False,
}

_NETWORK_EVENT_FIELDS = {
    "url",
    "method",
    "status_code",
    "content_type",
    "bytes",
    "resource_type",
    "started_at",
    "ended_at",
    "duration_ms",
}


class OperatorWorkbenchStore:
    """File-backed operator source capture and registration store."""

    def __init__(self, base_dir: str | Path | None = None) -> None:
        default_dir = Path(__file__).resolve().parent.parent / "data" / "operator_source_workbench"
        self.base_dir = Path(base_dir or os.getenv("OPERATOR_SOURCE_WORKBENCH_DIR", str(default_dir)))

    def save_capture(
        self,
        *,
        crawler_name: str,
        source_name: str,
        schema_type: str,
        source_url: str | None,
        artifact_text: str,
        artifact_type: str = "html",
        operator_notes: str | None = None,
        network_events: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        capture_id = f"capture-{_utc_stamp()}-{uuid.uuid4().hex[:8]}"
        capture_dir = self.base_dir / "captures" / _safe_name(source_name) / capture_id
        capture_dir.mkdir(parents=True, exist_ok=True)
        suffix = _artifact_suffix(artifact_type)
        artifact_path = capture_dir / f"source{suffix}"
        artifact_path.write_text(artifact_text, encoding="utf-8")

        metadata = {
            "schema": WORKBENCH_SCHEMA,
            "capture_id": capture_id,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "crawler_name": crawler_name,
            "source_name": source_name,
            "schema_type": schema_type,
            "source_url": source_url,
            "artifact": {
                "path": str(artifact_path),
                "type": artifact_type,
                "sha1": _hash_text(artifact_text),
                "bytes": len(artifact_text.encode("utf-8")),
                "origin": "operator_supplied_saved_source",
            },
            "network_events": [_scrub_network_event(event) for event in (network_events or [])],
            "operator_notes": operator_notes,
            "source_health": {
                "collection_status": "captured_with_evidence",
                "evidence_artifact_path": str(artifact_path),
                "live_network_default": "disabled",
                "source_health_metadata": {
                    "evidence_mode": "operator_saved_source_import",
                    "feeds": ["crawler-admin", "ai-admin", "db-admin"],
                },
            },
            "safety_policy": SAFETY_POLICY,
        }
        metadata_path = capture_dir / "capture.json"
        metadata["artifact"]["metadata_path"] = str(metadata_path)
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return metadata

    def register_source(
        self,
        *,
        crawler_name: str,
        source_name: str,
        schema_type: str,
        source_url: str,
        cadence_cron: str | None = None,
        evidence_artifact_path: str | None = None,
        operator_notes: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        source_id = _safe_name(source_name)
        source_path = self.base_dir / "sources" / f"{source_id}.json"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc).isoformat()
        existing = _read_json(source_path)
        registration = {
            "schema": WORKBENCH_SCHEMA,
            "source_id": source_id,
            "registered_at": existing.get("registered_at", now),
            "updated_at": now,
            "crawler_name": crawler_name,
            "source_name": source_name,
            "schema_type": schema_type,
            "source_url": source_url,
            "cadence_cron": cadence_cron,
            "enabled": False,
            "operator_notes": operator_notes,
            "tags": tags or [],
            "evidence_artifact_path": evidence_artifact_path,
            "source_health": {
                "collection_status": "registered_unverified",
                "live_network_default": "disabled",
                "evidence_artifact_path": evidence_artifact_path,
                "source_health_metadata": {
                    "needs_operator_review": True,
                    "feeds": ["crawler-admin", "ai-admin", "db-admin"],
                    "next_action": "attach_saved_source_or_run_bounded_capture",
                },
            },
            "safety_policy": SAFETY_POLICY,
        }
        source_path.write_text(json.dumps(registration, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return registration

    def list_sources(self) -> list[dict[str, Any]]:
        sources_dir = self.base_dir / "sources"
        if not sources_dir.exists():
            return []
        return [
            data
            for path in sorted(sources_dir.glob("*.json"))
            if (data := _read_json(path))
        ]


def _artifact_suffix(artifact_type: str) -> str:
    normalized = artifact_type.lower().strip(".")
    return {
        "html": ".html",
        "source_html": ".html",
        "json": ".json",
        "text": ".txt",
        "txt": ".txt",
        "har": ".json",
    }.get(normalized, ".txt")


def _scrub_network_event(event: dict[str, Any]) -> dict[str, Any]:
    return {field: event.get(field) for field in _NETWORK_EVENT_FIELDS if field in event}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _safe_name(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value.strip())
    return safe or "source"


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _hash_text(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]
