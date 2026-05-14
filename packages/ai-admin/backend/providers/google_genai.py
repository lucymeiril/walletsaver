"""Google GenAI SDK adapter.

The DB stores only ``ProviderConfig.secret_alias``. The actual API key is
resolved from local ``.env`` files or process environment under that alias. This
file must never log or return the resolved secret value.
"""
from __future__ import annotations

import json
import re
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.ai_providers import model_supports_json_mode
from core.contracts.control_plane import ProviderConfigContract
from runtime import configure_utf8_runtime

from .secret_resolver import env_setup_hint, resolve_secret_alias


class ProviderConfigurationError(ValueError):
    """Provider config or local secret setup is invalid."""


class ProviderResponseError(ValueError):
    """Provider call failed safely or returned an invalid JSON shape."""

    def __init__(
        self,
        message: str,
        *,
        provider_id: str | None = None,
        model: str | None = None,
        invalid_rows: list[dict[str, Any]] | None = None,
        error_kind: str = "provider_response_error",
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.provider_id = provider_id
        self.model = model
        self.invalid_rows = invalid_rows or []
        self.error_kind = error_kind
        self.cause = cause

    def __str__(self) -> str:
        return _sanitize_provider_error(super().__str__())

    def to_detail(self) -> dict[str, Any]:
        detail = {
            "error": self.error_kind,
            "provider_id": self.provider_id,
            "model": self.model,
            "message": str(self),
        }
        if self.invalid_rows:
            detail["invalid_rows"] = self.invalid_rows
        if self.cause is not None:
            detail["cause"] = _safe_exception_detail(self.cause)
        return detail


_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)
_JSON_MODE_UNSUPPORTED_MARKERS = (
    "json mode is not enabled",
    "response_mime_type",
    "response mime type",
    "application/json",
    "response_schema",
)
_QUOTA_ERROR_MARKERS = (
    "quota",
    "rate limit",
    "rate_limit",
    "resource_exhausted",
    "too many requests",
    "429",
)
_TIMEOUT_ERROR_MARKERS = (
    "timeout",
    "timed out",
    "deadline",
    "deadline_exceeded",
)
_NOT_FOUND_ERROR_MARKERS = (
    "not_found",
    "not found",
    "404",
    "model was not found",
)
_STATIC_GOOGLE_MODEL_NAMES = (
    ("gemini-2.5-flash", "Gemini 2.5 Flash"),
    ("gemini-2.5-flash-lite", "Gemini 2.5 Flash Lite"),
    ("gemini-3.1-flash-lite-preview", "Gemini 3.1 Flash Lite Preview"),
    ("gemini-3.1-pro-preview", "Gemini 3.1 Pro Preview"),
    ("gemini-3-flash-preview", "Gemini 3 Flash Preview"),
    ("gemini-2.0-flash", "Gemini 2.0 Flash"),
    ("gemini-2.0-flash-lite", "Gemini 2.0 Flash Lite"),
    ("gemini-1.5-flash", "Gemini 1.5 Flash"),
    ("gemini-1.5-pro", "Gemini 1.5 Pro"),
    ("gemma-4-31b-it", "Gemma 4 31B IT"),
    ("gemma-4-26b-a4b-it", "Gemma 4 26B A4B IT"),
)


def _sanitize_provider_error(message: str) -> str:
    """Keep provider diagnostics useful without exposing common API-key shapes."""
    sanitized = re.sub(r"AIza[0-9A-Za-z_\-]{20,}", "[REDACTED_API_KEY]", message)
    sanitized = re.sub(
        r"(?i)(api[_-]?key|key|token|authorization)(\s*[=:]\s*)['\"]?[^'\"\s,;}]+",
        r"\1\2[REDACTED]",
        sanitized,
    )
    return sanitized.strip()


def _safe_exception_detail(exc: BaseException) -> dict[str, Any]:
    frames = traceback.extract_tb(exc.__traceback__)
    location = None
    if frames:
        frame = frames[-1]
        location = {
            "file": Path(frame.filename).name,
            "function": frame.name,
            "line": frame.lineno,
        }
    return {
        "class": exc.__class__.__name__,
        "message": _sanitize_provider_error(str(exc)),
        "location": location,
    }


def _sdk_transport_safe_text(text: str) -> str:
    """Return ASCII-only request text for SDK transports that inherit ASCII encoders."""
    try:
        text.encode("ascii")
        return text
    except UnicodeEncodeError:
        escaped = text.encode("ascii", "backslashreplace").decode("ascii")
        return (
            "Transport note: Non-ASCII product text below is encoded with "
            "Unicode escape sequences such as \\uD55C; interpret escapes as "
            "the original text.\n"
            f"{escaped}"
        )


def _is_json_mode_unsupported_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _JSON_MODE_UNSUPPORTED_MARKERS) and (
        "not enabled" in text
        or "unsupported" in text
        or "invalid_argument" in text
        or "400" in text
    )


def _is_quota_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _QUOTA_ERROR_MARKERS)


def _provider_error_kind(exc: Exception) -> str:
    text = str(exc).lower()
    if any(marker in text for marker in _NOT_FOUND_ERROR_MARKERS):
        return "model_not_found"
    if any(marker in text for marker in _QUOTA_ERROR_MARKERS):
        return "quota_limited"
    if any(marker in text for marker in _TIMEOUT_ERROR_MARKERS):
        return "provider_timeout_retryable"
    return "provider_response_error"


def _selectable_model_name(name: str) -> str:
    return name.removeprefix("models/").strip()


def _json_only_prompt(prompt: str) -> str:
    return (
        f"{prompt}\n\n"
        "Provider compatibility instruction: JSON response mode is unavailable for "
        "this model. Return one valid JSON object only, with no Markdown fences, "
        "no prose, and no trailing commentary. The JSON must match the shape above."
    )


def _extract_json_object(text: str) -> dict[str, Any]:
    """Extract one JSON object from SDK text output.

    Models sometimes wrap JSON in Markdown fences despite JSON-mode hints. This
    keeps parsing strict enough to fail loudly while still accepting fenced JSON.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        match = _JSON_OBJECT_RE.search(stripped)
        if not match:
            raise ProviderResponseError("provider response did not contain a JSON object")
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise ProviderResponseError(
                "provider response contained malformed JSON"
            ) from exc
    if not isinstance(parsed, dict):
        raise ProviderResponseError("provider response JSON must be an object")
    return parsed


@dataclass(frozen=True)
class ModelInfo:
    name: str
    display_name: str | None = None
    supported_actions: list[str] | None = None
    input_token_limit: int | None = None
    output_token_limit: int | None = None
    supports_json_mode: bool = False
    provider_kind: str = "gemini"
    is_local: bool = False
    availability_status: str = "listed"
    smoke_status: str = "not_run"
    source: str = "live_sdk"
    api_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        selectable_name = _selectable_model_name(self.name)
        return {
            "name": selectable_name,
            "model_name": selectable_name,
            "selectable_model_name": selectable_name,
            "api_name": self.api_name or self.name,
            "display_name": self.display_name,
            "supported_actions": self.supported_actions or [],
            "input_token_limit": self.input_token_limit,
            "output_token_limit": self.output_token_limit,
            "supports_json_mode": self.supports_json_mode,
            "provider_kind": self.provider_kind,
            "is_local": self.is_local,
            "availability_status": self.availability_status,
            "smoke_status": self.smoke_status,
            "source": self.source,
        }


class GoogleGenAIProvider:
    """Minimal Google GenAI SDK provider for schema-first data refinement."""

    provider_mode = "live"

    def __init__(
        self,
        config: ProviderConfigContract,
        env_paths: tuple[Path, ...] | list[Path] | None = None,
    ) -> None:
        self.config = config
        self._client = None
        self._env_paths = env_paths

    def _secret_alias(self) -> str:
        alias = self.config.secret_alias or "GOOGLE_API_KEY"
        if not re.fullmatch(r"[A-Z0-9_]+", alias):
            raise ProviderConfigurationError(
                "secret_alias must be an environment variable name"
            )
        return alias

    def _api_key(self) -> str:
        alias = self._secret_alias()
        value = resolve_secret_alias(alias, self._env_paths)
        if not value:
            raise ProviderConfigurationError(env_setup_hint(alias))
        return value

    def _get_client(self):
        if self._client is None:
            try:
                from google import genai
            except ImportError as exc:
                raise ProviderConfigurationError(
                    "google-genai package is not installed"
                ) from exc
            self._client = genai.Client(api_key=self._api_key())
        return self._client

    def validate_config(self) -> None:
        configure_utf8_runtime()
        self._api_key()
        if self.config.provider_kind.value != "gemini":
            raise ProviderConfigurationError("GoogleGenAIProvider requires gemini kind")
        if not self.config.default_model:
            raise ProviderConfigurationError("default_model is required")

    def call(self, *, prompt: str, schema: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call Google GenAI once and parse a JSON object response."""
        configure_utf8_runtime()
        self.validate_config()
        client = self._get_client()
        try:
            from google.genai import types
        except ImportError as exc:
            raise ProviderConfigurationError(
                "google-genai package is not installed"
            ) from exc

        config_kwargs: dict[str, Any] = {"temperature": 0.1}
        use_json_mode = model_supports_json_mode(
            self.config.provider_kind, self.config.default_model
        )
        if use_json_mode:
            config_kwargs["response_mime_type"] = "application/json"
        request_contents = _sdk_transport_safe_text(
            prompt if use_json_mode else _json_only_prompt(prompt)
        )
        # The SDK accepts response_schema for selected schema dialects, but it is
        # stricter than JSON Schema and changes across releases. We only request
        # JSON mode for models that accept it and validate the returned object in
        # our own pipeline layer.
        try:
            response = client.models.generate_content(
                model=self.config.default_model,
                contents=request_contents,
                config=types.GenerateContentConfig(**config_kwargs),
            )
        except Exception as exc:
            if not use_json_mode or not _is_json_mode_unsupported_error(exc):
                message = _sanitize_provider_error(str(exc))
                raise ProviderResponseError(
                    f"Google GenAI provider call failed: {message}",
                    provider_id=self.config.provider_id,
                    model=self.config.default_model,
                    error_kind=_provider_error_kind(exc),
                    cause=exc,
                ) from exc
            try:
                response = client.models.generate_content(
                    model=self.config.default_model,
                    contents=_sdk_transport_safe_text(_json_only_prompt(prompt)),
                    config=types.GenerateContentConfig(temperature=0.1),
                )
            except Exception as retry_exc:
                message = _sanitize_provider_error(str(retry_exc))
                raise ProviderResponseError(
                    f"Google GenAI provider fallback failed: {message}",
                    provider_id=self.config.provider_id,
                    model=self.config.default_model,
                    error_kind=_provider_error_kind(retry_exc),
                    cause=retry_exc,
                ) from retry_exc
        text = getattr(response, "text", "") or ""
        try:
            parsed = _extract_json_object(text)
        except ProviderResponseError as exc:
            if use_json_mode:
                try:
                    response = client.models.generate_content(
                        model=self.config.default_model,
                        contents=_sdk_transport_safe_text(_json_only_prompt(prompt)),
                        config=types.GenerateContentConfig(temperature=0.1),
                    )
                    parsed = _extract_json_object(getattr(response, "text", "") or "")
                except Exception as fallback_exc:
                    message = _sanitize_provider_error(str(fallback_exc))
                    raise ProviderResponseError(
                        f"{exc}; JSON-mode fallback also failed: {message}",
                        provider_id=self.config.provider_id,
                        model=self.config.default_model,
                        cause=fallback_exc,
                    ) from fallback_exc
            else:
                raise ProviderResponseError(
                    str(exc),
                    provider_id=self.config.provider_id,
                    model=self.config.default_model,
                ) from exc
        usage = getattr(response, "usage_metadata", None)
        if usage is not None:
            parsed.setdefault(
                "_usage",
                {
                    "prompt_token_count": getattr(usage, "prompt_token_count", None),
                    "candidates_token_count": getattr(
                        usage, "candidates_token_count", None
                    ),
                    "total_token_count": getattr(usage, "total_token_count", None),
                },
            )
        return parsed

    def _static_models(self, *, source: str, availability_status: str) -> list[dict[str, Any]]:
        names = list(_STATIC_GOOGLE_MODEL_NAMES)
        if self.config.default_model and all(
            _selectable_model_name(name) != self.config.default_model for name, _ in names
        ):
            names.insert(0, (self.config.default_model, "Configured default model"))
        return [
            ModelInfo(
                name=name,
                display_name=display_name,
                supported_actions=["generateContent"],
                supports_json_mode=model_supports_json_mode(
                    self.config.provider_kind, name
                ),
                provider_kind=self.config.provider_kind.value,
                is_local=False,
                availability_status=availability_status,
                source=source,
            ).to_dict()
            for name, display_name in names
        ]

    def static_model_listing(
        self,
        *,
        discovery_status: str,
        discovery_source: str = "static_fallback",
        error: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "provider_id": self.config.provider_id,
            "provider_kind": self.config.provider_kind.value,
            "default_model": self.config.default_model,
            "discovery_status": discovery_status,
            "discovery_source": discovery_source,
            "models": self._static_models(
                source=discovery_source, availability_status=discovery_status
            ),
            "error": error,
            "quota_remaining_available": False,
            "quota_status": "unknown",
            "quota_note": (
                "Remaining provider quota is not exposed by static model metadata. "
                "Run a smoke test only when quota use is acceptable."
            ),
        }

    def list_models(self) -> dict[str, Any]:
        """Return SDK-visible model metadata without exposing credentials."""
        configure_utf8_runtime()
        self.validate_config()
        models = []
        try:
            for model in self._get_client().models.list():
                raw_name = getattr(model, "name", "") or ""
                model_name = _selectable_model_name(raw_name)
                models.append(
                    ModelInfo(
                        name=model_name,
                        api_name=raw_name or model_name,
                        display_name=getattr(model, "display_name", None),
                        supported_actions=list(getattr(model, "supported_actions", []) or []),
                        input_token_limit=getattr(model, "input_token_limit", None),
                        output_token_limit=getattr(model, "output_token_limit", None),
                        supports_json_mode=model_supports_json_mode(
                            self.config.provider_kind, model_name
                        ),
                        provider_kind=self.config.provider_kind.value,
                        is_local=False,
                        source="live_sdk",
                    ).to_dict()
                )
        except Exception as exc:
            message = _sanitize_provider_error(str(exc))
            raise ProviderResponseError(
                f"Google GenAI model discovery failed: {message}",
                provider_id=self.config.provider_id,
                model=self.config.default_model,
                error_kind="quota_limited" if _is_quota_error(exc) else "model_discovery_error",
                cause=exc,
            ) from exc
        return {
            "provider_id": self.config.provider_id,
            "provider_kind": self.config.provider_kind.value,
            "default_model": self.config.default_model,
            "discovery_status": "available" if models else "unavailable",
            "discovery_source": "live_sdk",
            "models": models,
            "error": None,
            "quota_remaining_available": False,
            "quota_status": "not_reported",
            "quota_note": "Google GenAI SDK model listing does not include remaining daily request quota.",
        }
