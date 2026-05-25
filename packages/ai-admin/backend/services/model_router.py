"""§5-A/B Model Router — OSS LLM fallback.

Spec §14.7 forbids "safe-by-default fallback" sealing — when the primary key is
absent or the primary provider returns errors, the AI pipeline must still produce
*something* the operator can review. This module exposes a single interface that
all callers go through; concrete adapters (Google GenAI, OSS local) are pluggable.

Defaults:
    - `google-genai` (live) when `WALLETSAVIOR_AI_LIVE_FORCE=1` and key present.
    - `local-oss-stub` (offline rule-based escalation generator) otherwise.

The OSS stub is deliberately *not* a real model — per §5-A v5, we never claim OSS
parity without `ProviderCapability` benchmarks. It only generates schema-valid
escalation responses so the rest of the pipe stays alive in dev/offline modes.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol


@dataclass
class ModelRequest:
    prompt: str
    schema: Optional[dict[str, Any]] = None
    call_purpose: str = "classification"
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelResponse:
    text: str
    provider_id: str
    model_name: str
    is_live: bool
    raw: dict[str, Any] = field(default_factory=dict)
    fallback_reason: Optional[str] = None


class ModelAdapter(Protocol):
    provider_id: str
    model_name: str

    def is_available(self) -> bool: ...

    def generate(self, request: ModelRequest) -> ModelResponse: ...


class LocalOSSStubAdapter:
    """Offline fallback. Always available. Returns a schema-valid escalation."""

    provider_id = "local-oss-stub"
    model_name = "rule-based-escalation-v1"

    def is_available(self) -> bool:
        return True

    def generate(self, request: ModelRequest) -> ModelResponse:
        if request.schema and "category_id" in (request.schema.get("properties") or {}):
            payload = '{"category_id":"unknown","confidence":0.0,"reason":"oss-fallback: escalation"}'
        elif request.schema:
            # generic schema → minimal escalation
            payload = '{"escalation": true, "reason": "oss-fallback"}'
        else:
            payload = "ESCALATE"
        return ModelResponse(
            text=payload,
            provider_id=self.provider_id,
            model_name=self.model_name,
            is_live=False,
            raw={"adapter": "local-oss-stub", "prompt_len": len(request.prompt)},
            fallback_reason="primary provider unavailable",
        )


class GoogleGenAIAdapter:
    """Thin wrapper around the existing `providers.google_genai` module."""

    provider_id = "google-genai"

    def __init__(self, model_name: str = "gemini-2.0-flash") -> None:
        self.model_name = model_name

    def is_available(self) -> bool:
        # We treat the adapter as available whenever a key is resolvable. The
        # actual call may still fail; the router will catch and fall back.
        if os.environ.get("GOOGLE_API_KEY"):
            return True
        try:
            from providers.secret_resolver import resolve_secret_alias  # type: ignore
            return bool(resolve_secret_alias("GOOGLE_GENAI_KEY"))
        except Exception:
            return False

    def generate(self, request: ModelRequest) -> ModelResponse:
        # Defer the heavy import so unit tests don't require the SDK.
        from providers.google_genai import call_google_provider  # type: ignore

        result = call_google_provider(
            prompt=request.prompt,
            model_name=self.model_name,
            schema=request.schema,
        )
        return ModelResponse(
            text=result.get("text", ""),
            provider_id=self.provider_id,
            model_name=self.model_name,
            is_live=True,
            raw=result,
        )


class ModelRouter:
    """Try adapters in order, log the path, never crash the pipeline."""

    def __init__(self, adapters: Optional[list[ModelAdapter]] = None) -> None:
        if adapters is not None:
            self.adapters = adapters
        else:
            self.adapters = [GoogleGenAIAdapter(), LocalOSSStubAdapter()]

    def generate(self, request: ModelRequest) -> ModelResponse:
        last_error: Optional[Exception] = None
        for adapter in self.adapters:
            try:
                if not adapter.is_available():
                    continue
                return adapter.generate(request)
            except Exception as exc:
                last_error = exc
                continue
        # Every adapter failed (only possible if the stub is removed). Return a
        # synthetic escalation so the pipeline still moves.
        return ModelResponse(
            text='{"escalation": true, "reason": "all adapters failed"}',
            provider_id="none",
            model_name="none",
            is_live=False,
            fallback_reason=f"all adapters failed: {last_error}" if last_error else "no adapters",
        )


_DEFAULT_ROUTER: Optional[ModelRouter] = None


def get_default_router() -> ModelRouter:
    global _DEFAULT_ROUTER
    if _DEFAULT_ROUTER is None:
        _DEFAULT_ROUTER = ModelRouter()
    return _DEFAULT_ROUTER


def reset_default_router() -> None:
    global _DEFAULT_ROUTER
    _DEFAULT_ROUTER = None
