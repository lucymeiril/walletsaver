"""DB-admin ingestion boundary for AI-reviewed publish records."""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from providers.secret_resolver import DEFAULT_ENV_PATHS, resolve_secret_alias


READINESS_PATHS = (
    "/api/ingestions/stats",
    "/health",
    "/status",
    "/openapi.json",
)
MUTATION_PREFLIGHT_STATS_PATH = "/api/ingestions/stats"
MUTATION_PREFLIGHT_BACKUPS_PATH = "/api/admin/backups"
MUTATION_PREFLIGHT_BACKUP_CREATE_PATH = "/api/admin/backup"

_SECRET_VALUE_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|key|token|authorization)(\s*[=:]\s*)['\"]?[^'\"\s,;}]+"),
    re.compile(r"(?i)(x-api-key)(\s*[:=]\s*)['\"]?[^'\"\s,;}]+"),
)


def _resolve_local_env(alias: str, env_paths: tuple[Path, ...] | list[Path] | None = None) -> str | None:
    return resolve_secret_alias(alias, env_paths)


def _sanitize_text(value: Any, secret_value: str | None = None) -> str:
    text = str(value)
    if secret_value:
        text = text.replace(secret_value, "[REDACTED]")
    for pattern in _SECRET_VALUE_PATTERNS:
        text = pattern.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", text)
    return text


def _safe_error(exc: Exception, secret_value: str | None = None) -> dict[str, str]:
    return {
        "class": type(exc).__name__,
        "message": _sanitize_text(exc, secret_value),
    }


def _http_error_message(response: httpx.Response, context: str, secret_value: str | None = None) -> str:
    try:
        body = response.text or ""
    except Exception:
        body = ""
    return _sanitize_text(
        f"DB-admin returned HTTP {response.status_code} for {context}: {body[:240]}",
        secret_value,
    )


def _sanitize_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value)
    netloc = parsed.hostname or ""
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path.rstrip("/") or "/", "", ""))


def _request_base_url(value: str) -> str:
    parsed = urlsplit(value)
    netloc = parsed.hostname or ""
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path.rstrip("/"), "", ""))


def _join_url(base_url: str, path: str) -> str:
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def _readiness_base_result(base_url: str | None, api_key: str | None) -> dict[str, Any]:
    return {
        "status": "unexpected_error",
        "url": _sanitize_url(base_url),
        "key_present": bool(api_key),
        "endpoint": None,
        "latency_ms": None,
        "error": None,
    }


def resolve_db_admin_credentials(
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    env_paths: tuple[Path, ...] | list[Path] | None = None,
) -> tuple[str | None, str | None]:
    resolved_url = (base_url or _resolve_local_env("DB_ADMIN_URL", env_paths) or "").strip()
    resolved_key = api_key if api_key is not None else _resolve_local_env("DB_ADMIN_API_KEY", env_paths)
    return (resolved_url or None), (resolved_key or None)


async def check_db_admin_readiness(
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    env_paths: tuple[Path, ...] | list[Path] | None = None,
    paths: tuple[str, ...] | list[str] = READINESS_PATHS,
    client_factory: Any | None = None,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    """Check DB-admin connectivity/auth with GET-only requests and sanitized output."""
    raw_url, resolved_key = resolve_db_admin_credentials(base_url=base_url, api_key=api_key, env_paths=env_paths)
    resolved_url = (raw_url or "").rstrip("/")
    if resolved_url:
        resolved_url = _request_base_url(resolved_url)
    result = _readiness_base_result(resolved_url, resolved_key)

    if not resolved_url:
        result["status"] = "url_missing"
        return result
    if not resolved_key:
        result["status"] = "key_missing"
        return result

    headers = {"X-API-Key": resolved_key}
    factory = client_factory or httpx.AsyncClient
    start = time.perf_counter()
    missing_count = 0
    last_error: dict[str, str] | None = None

    try:
        async with factory(timeout=timeout_seconds) as client:
            for path in paths:
                request_url = _join_url(resolved_url, path)
                try:
                    response = await client.get(request_url, headers=headers)
                except httpx.RequestError as exc:
                    result["status"] = "server_unreachable"
                    result["endpoint"] = path
                    result["error"] = _safe_error(exc, resolved_key)
                    return result

                result["endpoint"] = path
                status_code = getattr(response, "status_code", None)
                if status_code in {401, 403}:
                    result["status"] = "auth_failed"
                    result["error"] = {
                        "class": "HTTPStatusError",
                        "message": f"DB-admin returned HTTP {status_code} for readiness endpoint",
                    }
                    return result
                if status_code in {404, 405}:
                    missing_count += 1
                    continue
                if status_code is not None and 200 <= status_code < 400:
                    result["status"] = "ready"
                    return result

                body = ""
                try:
                    body = getattr(response, "text", "") or ""
                except Exception:
                    body = ""
                last_error = {
                    "class": "HTTPStatusError",
                    "message": _sanitize_text(
                        f"DB-admin returned HTTP {status_code}: {body[:240]}",
                        resolved_key,
                    ),
                }
                break

        if missing_count == len(tuple(paths)):
            result["status"] = "endpoint_missing"
            result["error"] = {
                "class": "EndpointMissing",
                "message": "No configured read-only DB-admin readiness endpoint was found",
            }
        else:
            result["status"] = "unexpected_error"
            result["error"] = last_error
        return result
    except Exception as exc:
        result["status"] = "unexpected_error"
        result["error"] = _safe_error(exc, resolved_key)
        return result
    finally:
        result["latency_ms"] = round((time.perf_counter() - start) * 1000, 2)


def run_db_admin_readiness(**kwargs: Any) -> dict[str, Any]:
    return asyncio.run(check_db_admin_readiness(**kwargs))


def require_db_admin_ready(result: dict[str, Any]) -> None:
    if result.get("status") != "ready":
        raise RuntimeError(f"DB-admin readiness failed: {json.dumps(result, ensure_ascii=False, sort_keys=True)}")


def _preflight_base_result(readiness: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "status": "blocked",
        "ready_to_mutate": False,
        "readiness": readiness,
        "current_state": None,
        "snapshot": {
            "verified": False,
            "latest_backup": None,
            "list_endpoint": MUTATION_PREFLIGHT_BACKUPS_PATH,
            "create_endpoint": MUTATION_PREFLIGHT_BACKUP_CREATE_PATH,
            "rollback_path": "Restore the verified backup before retrying mart3 live DB mutation.",
        },
        "error": None,
    }


def _backup_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        rows = payload.get("backups", [])
    else:
        rows = payload
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


async def check_db_admin_mutation_preflight(
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    env_paths: tuple[Path, ...] | list[Path] | None = None,
    client_factory: Any | None = None,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    """GET-only fail-closed preflight for DB-admin live mutation readiness.

    This verifies connectivity/auth, captures a read-only state snapshot, and
    requires an existing DB-admin backup listing before any live submit/final
    approval should be forwarded. It never creates backups or mutates DB state.
    """
    readiness = await check_db_admin_readiness(
        base_url=base_url,
        api_key=api_key,
        env_paths=env_paths,
        paths=(MUTATION_PREFLIGHT_STATS_PATH, "/health", "/openapi.json"),
        client_factory=client_factory,
        timeout_seconds=timeout_seconds,
    )
    result = _preflight_base_result(readiness)
    if readiness.get("status") != "ready":
        result["error"] = {
            "class": "ReadinessBlocked",
            "message": f"DB-admin readiness status {readiness.get('status')}; no DB mutation may be attempted",
        }
        return result

    raw_url, resolved_key = resolve_db_admin_credentials(base_url=base_url, api_key=api_key, env_paths=env_paths)
    resolved_url = _request_base_url((raw_url or "").rstrip("/"))
    factory = client_factory or httpx.AsyncClient

    try:
        async with factory(timeout=timeout_seconds) as client:
            for field, path in (
                ("current_state", MUTATION_PREFLIGHT_STATS_PATH),
                ("snapshot", MUTATION_PREFLIGHT_BACKUPS_PATH),
            ):
                response = await client.get(_join_url(resolved_url, path), headers={"X-API-Key": resolved_key or ""})
                status_code = getattr(response, "status_code", None)
                if status_code in {401, 403}:
                    result["error"] = {
                        "class": "HTTPStatusError",
                        "message": f"DB-admin returned HTTP {status_code} for mutation preflight {path}",
                    }
                    return result
                if status_code is None or not (200 <= status_code < 400):
                    body = getattr(response, "text", "") or ""
                    result["error"] = {
                        "class": "HTTPStatusError",
                        "message": _sanitize_text(
                            f"DB-admin returned HTTP {status_code} for mutation preflight {path}: {body[:240]}",
                            resolved_key,
                        ),
                    }
                    return result
                try:
                    payload = response.json()
                except Exception:
                    payload = {}
                if field == "current_state":
                    result["current_state"] = payload
                else:
                    backups = _backup_rows(payload)
                    if not backups:
                        result["error"] = {
                            "class": "SnapshotMissing",
                            "message": (
                                "No DB-admin backup was listed; create/record a rollback snapshot before "
                                "mart3 live DB mutation"
                            ),
                        }
                        return result
                    result["snapshot"]["verified"] = True
                    result["snapshot"]["latest_backup"] = _sanitize_text(backups[0])
    except httpx.RequestError as exc:
        result["error"] = _safe_error(exc, resolved_key)
        return result
    except Exception as exc:
        result["error"] = _safe_error(exc, resolved_key)
        return result

    result["status"] = "ready"
    result["ready_to_mutate"] = True
    result["error"] = None
    return result


def build_db_admin_ingestion_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    item = copy.deepcopy(candidate["item"])
    raw_data = item.setdefault("raw_data", {})
    if isinstance(raw_data, dict):
        normalized_metadata = item.get("normalized_metadata") or raw_data.get("normalized") or raw_data.get("normalized_metadata")
        if isinstance(normalized_metadata, dict):
            raw_data.setdefault("normalized", normalized_metadata)
            raw_data.setdefault("normalized_metadata", normalized_metadata)
        rebuild_provenance = {
            "raw_record_id": candidate.get("raw_record_id") or item.get("raw_record_id"),
            "batch_id": candidate.get("batch_id"),
            "source_name": candidate.get("source_name"),
            "proposal_ids": list(candidate.get("proposal_ids") or []),
            "human_decision_ids": list(candidate.get("human_decision_ids") or []),
            "db_handoff_mode": candidate.get("db_handoff_mode"),
            "publication_kind": candidate.get("publication_kind") or item.get("publication_kind"),
        }
        raw_data["ai_review_publish_provenance"] = {
            key: value for key, value in rebuild_provenance.items() if value not in (None, [], "")
        }
        audit = item.setdefault("ai_review_audit", {})
        if isinstance(audit, dict):
            audit.setdefault("raw_record_id", rebuild_provenance["raw_record_id"])
            audit.setdefault("proposal_ids", rebuild_provenance["proposal_ids"])
            audit["human_decision_ids"] = rebuild_provenance["human_decision_ids"]
    return {
        "crawler_name": f"ai-admin:{candidate['source_name']}",
        "crawl_status": "success",
        "items": [item],
        "schema_type": "DiscountItem",
        "strategy_used": "ai_review_publish",
        "duration_seconds": 0,
        "errors": [],
        "source_url": item.get("source_url"),
    }


@dataclass(frozen=True)
class DBAdminAdapter:
    ingestion_url: str
    api_key: str
    timeout_seconds: float = 20.0

    @classmethod
    def from_env(
        cls,
        env_paths: tuple[Path, ...] | list[Path] | None = None,
    ) -> "DBAdminAdapter":
        resolved_url, resolved_key = resolve_db_admin_credentials(env_paths=env_paths)
        base_url = (resolved_url or "http://localhost:8002").rstrip("/")
        ingestion_url = os.getenv(
            "DB_ADMIN_INGESTION_URL",
            f"{base_url}/api/ingestions",
        ).rstrip("/")
        return cls(
            ingestion_url=ingestion_url,
            api_key=resolved_key or "",
        )

    def headers(self) -> dict[str, str]:
        if not self.api_key:
            raise ValueError(
                "DB_ADMIN_API_KEY is required to publish AI-reviewed records to DB-admin."
            )
        return {"X-API-Key": self.api_key}

    async def submit_ingestion(self, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                self.ingestion_url,
                json=payload,
                headers=self.headers(),
            )
            if response.status_code >= 400:
                raise RuntimeError(_http_error_message(response, "ingestion submit", self.api_key))
            return response.json()

    async def ai_safe_final_approve(
        self,
        ingestion_id: int | str,
        *,
        notes: str | None = None,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                f"{self.ingestion_url}/{ingestion_id}/ai-safe-final-approve",
                json={"action": "approve", "notes": notes},
                headers=self.headers(),
            )
            if response.status_code >= 400:
                raise RuntimeError(_http_error_message(response, "ai-safe final approve", self.api_key))
            return response.json()


async def submit_to_db_admin(payload: dict[str, Any]) -> dict[str, Any]:
    return await DBAdminAdapter.from_env().submit_ingestion(payload)


async def ai_safe_final_approve_db_admin(
    ingestion_id: int | str,
    *,
    notes: str | None = None,
) -> dict[str, Any]:
    return await DBAdminAdapter.from_env().ai_safe_final_approve(
        ingestion_id,
        notes=notes,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GET-only DB-admin connectivity/auth readiness check")
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    parser.add_argument("--env-file", action="append", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    env_paths = tuple(args.env_file) if args.env_file else DEFAULT_ENV_PATHS
    result = run_db_admin_readiness(env_paths=env_paths, timeout_seconds=args.timeout_seconds)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
