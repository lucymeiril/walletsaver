"""Opt-in Google AI Studio live smoke harness.

Default execution is offline and never consumes provider quota. A live provider
call is attempted only when WALLET_SAVIOR_LIVE_AI_SMOKE=1 and the configured
secret alias resolves to a local key value.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

BACKEND_DIR = Path(__file__).resolve().parents[1]
SHARED_DIR = BACKEND_DIR.parent.parent / "shared"
for import_path in (BACKEND_DIR, SHARED_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from core.contracts.ai_pipeline import ProviderKind
from core.contracts.control_plane import ProviderConfigContract
from providers.google_genai import (
    GoogleGenAIProvider,
    ProviderConfigurationError,
    ProviderResponseError,
    _sanitize_provider_error,
)
from providers.secret_resolver import DEFAULT_ENV_PATHS, _parse_env_file, resolve_secret_alias

LIVE_SMOKE_ENV = "WALLET_SAVIOR_LIVE_AI_SMOKE"
DEFAULT_PROVIDER_ID = "google-aistudio-live-smoke"
DEFAULT_MODEL = "gemini-3.1-flash-lite-preview"
DEFAULT_SECRET_ALIAS = "GOOGLE_API_KEY"
SMOKE_PROMPT = (
    'Return exactly this JSON object and no prose: '
    '{"ok": true, "purpose": "wallet_savior_ai_studio_smoke"}'
)
SMOKE_SCHEMA = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "purpose": {"type": "string"},
    },
    "required": ["ok", "purpose"],
}


_SECRET_VALUE_PATTERNS = (
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"(?i)(api[_-]?key|key|token|authorization)(\s*[=:]\s*)['\"]?[^'\"\s,;}]+"),
)
_BEARER_TOKEN_RE = re.compile(r"(?i)\bbearer\s+[0-9A-Za-z_\-\.]{8,}")


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _live_enabled(env: dict[str, str] | None = None) -> bool:
    values = env if env is not None else os.environ
    return values.get(LIVE_SMOKE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _sanitize_text(value: Any) -> str:
    text = _sanitize_provider_error(str(value))
    text = _BEARER_TOKEN_RE.sub("Bearer [REDACTED]", text)
    for pattern in _SECRET_VALUE_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def _safe_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _safe_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_safe_json(v) for v in value]
    if isinstance(value, str):
        return _sanitize_text(value)
    return value


def _excerpt(value: Any, limit: int = 240) -> str:
    text = json.dumps(_safe_json(value), ensure_ascii=False, sort_keys=True)
    if len(text) > limit:
        return text[: limit - 1] + "…"
    return text


def _shape(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"type": type(value).__name__}
    return {
        "type": "object",
        "keys": sorted(str(key) for key in value.keys()),
        "field_types": {str(key): type(field_value).__name__ for key, field_value in value.items()},
    }


def _base_result(config: ProviderConfigContract) -> dict[str, Any]:
    return {
        "status": "SKIPPED",
        "provider": config.provider_id,
        "provider_kind": config.provider_kind.value,
        "model": config.default_model,
        "secret_alias": config.secret_alias or DEFAULT_SECRET_ALIAS,
        "live_gate_env": LIVE_SMOKE_ENV,
        "live_call_attempted": False,
        "live_call_succeeded": False,
        "key_present": False,
        "env_paths_checked": [],
        "env_path_with_alias": None,
        "skip_reason": None,
        "response_excerpt": None,
        "parsed_shape": None,
        "latency_ms": None,
        "timestamp": _utc_timestamp(),
    }


def build_provider_config(
    *,
    provider_id: str = DEFAULT_PROVIDER_ID,
    model: str = DEFAULT_MODEL,
    secret_alias: str = DEFAULT_SECRET_ALIAS,
) -> ProviderConfigContract:
    return ProviderConfigContract(
        provider_id=provider_id,
        provider_kind=ProviderKind.GEMINI,
        display_name="Google AI Studio Live Smoke",
        default_model=model,
        secret_alias=secret_alias or DEFAULT_SECRET_ALIAS,
        is_enabled=True,
        max_concurrent_jobs=1,
        min_request_interval_seconds=1.0,
    )


def _secret_readiness(
    alias: str,
    *,
    env: dict[str, str] | None = None,
    env_paths: Iterable[Path] | None = None,
) -> dict[str, Any]:
    paths = tuple(Path(path) for path in (env_paths if env_paths is not None else DEFAULT_ENV_PATHS))
    readiness: dict[str, Any] = {
        "key_present": False,
        "env_paths_checked": [str(path) for path in paths],
        "env_path_with_alias": None,
    }

    for path in paths:
        value = _parse_env_file(path).get(alias)
        if value:
            readiness["key_present"] = True
            readiness["env_path_with_alias"] = str(path)
            return readiness

    env_values = env if env is not None else os.environ
    if env_values.get(alias):
        readiness["key_present"] = True
    return readiness


def run_aistudio_live_smoke(
    *,
    config: ProviderConfigContract | None = None,
    env: dict[str, str] | None = None,
    env_paths: Iterable[Path] | None = None,
    provider: GoogleGenAIProvider | None = None,
) -> dict[str, Any]:
    """Return explicit live-smoke metadata without leaking credential values."""
    config = config or build_provider_config()
    result = _base_result(config)
    env_paths_tuple = tuple(Path(path) for path in env_paths) if env_paths is not None else None

    if config.provider_kind != ProviderKind.GEMINI:
        result["status"] = "BLOCKED"
        result["skip_reason"] = "Google AI Studio smoke requires a gemini provider config"
        return _safe_json(result)

    alias = config.secret_alias or DEFAULT_SECRET_ALIAS
    try:
        result.update(_secret_readiness(alias, env=env, env_paths=env_paths_tuple))
    except Exception as exc:
        result["status"] = "BLOCKED"
        result["skip_reason"] = f"alias resolution failed for {alias}: {_sanitize_text(exc)}"
        return _safe_json(result)

    if not config.is_enabled:
        result["status"] = "BLOCKED"
        result["skip_reason"] = "provider disabled; no live provider call attempted"
        return _safe_json(result)

    if not _live_enabled(env):
        result["skip_reason"] = f"live opt-in missing ({LIVE_SMOKE_ENV}=1 not set); no live provider call attempted"
        return _safe_json(result)

    if not result["key_present"]:
        result["status"] = "BLOCKED"
        result["skip_reason"] = f"key missing for alias {alias}; live Google AI Studio smoke was not run"
        return _safe_json(result)

    try:
        secret_value = (
            env.get(alias)
            if env is not None and env.get(alias)
            else resolve_secret_alias(alias, env_paths_tuple)
        )
    except Exception as exc:
        result["status"] = "BLOCKED"
        result["skip_reason"] = f"alias resolution failed for {alias}: {_sanitize_text(exc)}"
        return _safe_json(result)

    if not secret_value:
        result["status"] = "BLOCKED"
        result["key_present"] = False
        result["skip_reason"] = f"key missing for alias {alias}; live Google AI Studio smoke was not run"
        return _safe_json(result)

    adapter = provider or GoogleGenAIProvider(config, env_paths=env_paths_tuple)
    result["status"] = "RUNNING"
    result["live_call_attempted"] = True
    start = time.perf_counter()
    try:
        parsed = adapter.call(prompt=SMOKE_PROMPT, schema=SMOKE_SCHEMA)
    except (ProviderConfigurationError, ProviderResponseError) as exc:
        result["status"] = "FAILED"
        result["live_call_succeeded"] = False
        result["error"] = _safe_json(exc.to_detail() if hasattr(exc, "to_detail") else str(exc))
    except Exception as exc:
        result["status"] = "FAILED"
        result["live_call_succeeded"] = False
        result["error"] = {
            "error": "unexpected_live_smoke_error",
            "message": _sanitize_text(exc),
        }
    else:
        result["status"] = "PASSED"
        result["live_call_succeeded"] = True
        result["response_excerpt"] = _excerpt(parsed)
        result["parsed_shape"] = _shape(parsed)
    finally:
        result["latency_ms"] = round((time.perf_counter() - start) * 1000, 2)
        result["timestamp"] = _utc_timestamp()

    return _safe_json(result)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Opt-in Google AI Studio live smoke harness")
    parser.add_argument("--provider-id", default=os.getenv("AISTUDIO_SMOKE_PROVIDER_ID", DEFAULT_PROVIDER_ID))
    parser.add_argument("--model", default=os.getenv("AISTUDIO_SMOKE_MODEL", DEFAULT_MODEL))
    parser.add_argument("--secret-alias", default=os.getenv("AISTUDIO_SMOKE_SECRET_ALIAS", DEFAULT_SECRET_ALIAS))
    parser.add_argument("--output-json", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    config = build_provider_config(
        provider_id=args.provider_id,
        model=args.model,
        secret_alias=args.secret_alias,
    )
    result = run_aistudio_live_smoke(config=config)
    serialized = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output_json:
        args.output_json.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    if result["status"] == "PASSED":
        return 0
    if result["status"] == "SKIPPED":
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
