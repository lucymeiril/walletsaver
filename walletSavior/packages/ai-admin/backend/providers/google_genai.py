"""Google GenAI SDK adapter.

The DB stores only ``ProviderConfig.secret_alias``. The actual API key is
resolved from local ``.env`` files or process environment under that alias. This
file must never log or return the resolved secret value.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.contracts.control_plane import ProviderConfigContract

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
    ) -> None:
        super().__init__(message)
        self.provider_id = provider_id
        self.model = model

    def to_detail(self) -> dict[str, Any]:
        return {
            "error": "provider_response_error",
            "provider_id": self.provider_id,
            "model": self.model,
            "message": str(self),
        }


_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)
_JSON_MODE_UNSUPPORTED_MARKERS = (
    "json mode is not enabled",
    "response_mime_type",
    "response mime type",
    "application/json",
    "response_schema",
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


def _is_json_mode_unsupported_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _JSON_MODE_UNSUPPORTED_MARKERS) and (
        "not enabled" in text
        or "unsupported" in text
        or "invalid_argument" in text
        or "400" in text
    )


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
        parsed = json.loads(match.group(0))
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "supported_actions": self.supported_actions or [],
            "input_token_limit": self.input_token_limit,
            "output_token_limit": self.output_token_limit,
        }


class GoogleGenAIProvider:
    """Minimal Google GenAI SDK provider for schema-first data refinement."""

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
        self._api_key()
        if self.config.provider_kind.value != "gemini":
            raise ProviderConfigurationError("GoogleGenAIProvider requires gemini kind")
        if not self.config.default_model:
            raise ProviderConfigurationError("default_model is required")

    def call(self, *, prompt: str, schema: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call Google GenAI once and parse a JSON object response."""
        self.validate_config()
        client = self._get_client()
        try:
            from google.genai import types
        except ImportError as exc:
            raise ProviderConfigurationError(
                "google-genai package is not installed"
            ) from exc

        config_kwargs: dict[str, Any] = {"temperature": 0.1}
        use_json_mode = "gemma" not in self.config.default_model.lower()
        if use_json_mode:
            config_kwargs["response_mime_type"] = "application/json"
        # The SDK accepts response_schema for selected schema dialects, but it is
        # stricter than JSON Schema and changes across releases. We only request
        # JSON mode for models that accept it and validate the returned object in
        # our own pipeline layer.
        try:
            response = client.models.generate_content(
                model=self.config.default_model,
                contents=prompt if use_json_mode else _json_only_prompt(prompt),
                config=types.GenerateContentConfig(**config_kwargs),
            )
        except Exception as exc:
            if not use_json_mode or not _is_json_mode_unsupported_error(exc):
                message = _sanitize_provider_error(str(exc))
                raise ProviderResponseError(
                    f"Google GenAI provider call failed: {message}",
                    provider_id=self.config.provider_id,
                    model=self.config.default_model,
                ) from exc
            try:
                response = client.models.generate_content(
                    model=self.config.default_model,
                    contents=_json_only_prompt(prompt),
                    config=types.GenerateContentConfig(temperature=0.1),
                )
            except Exception as retry_exc:
                message = _sanitize_provider_error(str(retry_exc))
                raise ProviderResponseError(
                    f"Google GenAI provider fallback failed: {message}",
                    provider_id=self.config.provider_id,
                    model=self.config.default_model,
                ) from retry_exc
        text = getattr(response, "text", "") or ""
        try:
            parsed = _extract_json_object(text)
        except ProviderResponseError as exc:
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

    def list_models(self) -> dict[str, Any]:
        """Return SDK-visible model metadata.

        Google GenAI does not expose remaining daily quota through this SDK call,
        so the response states that explicitly instead of inventing a value.
        """
        self.validate_config()
        models = []
        for model in self._get_client().models.list():
            models.append(
                ModelInfo(
                    name=getattr(model, "name", ""),
                    display_name=getattr(model, "display_name", None),
                    supported_actions=list(getattr(model, "supported_actions", []) or []),
                    input_token_limit=getattr(model, "input_token_limit", None),
                    output_token_limit=getattr(model, "output_token_limit", None),
                ).to_dict()
            )
        return {
            "provider_id": self.config.provider_id,
            "default_model": self.config.default_model,
            "models": models,
            "quota_remaining_available": False,
            "quota_note": "Google GenAI SDK model listing does not include remaining daily request quota.",
        }
