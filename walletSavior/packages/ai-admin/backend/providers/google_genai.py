"""Google GenAI SDK adapter.

The DB stores only ``ProviderConfig.secret_alias``. The actual API key must be
present in the local process environment under that alias. This file must never
log or return the resolved secret value.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

from core.contracts.control_plane import ProviderConfigContract


class ProviderConfigurationError(ValueError):
    """Provider config or local secret setup is invalid."""


class ProviderResponseError(ValueError):
    """Provider responded, but not with the required JSON shape."""


_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


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

    def __init__(self, config: ProviderConfigContract) -> None:
        self.config = config
        self._client = None

    def _secret_alias(self) -> str:
        alias = self.config.secret_alias or "GOOGLE_API_KEY"
        if not re.fullmatch(r"[A-Z0-9_]+", alias):
            raise ProviderConfigurationError(
                "secret_alias must be an environment variable name"
            )
        return alias

    def _api_key(self) -> str:
        alias = self._secret_alias()
        value = os.getenv(alias)
        if not value:
            raise ProviderConfigurationError(
                f"missing API key environment variable for alias '{alias}'"
            )
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

        config_kwargs: dict[str, Any] = {
            "temperature": 0.1,
            "response_mime_type": "application/json",
        }
        # The SDK accepts response_schema for selected schema dialects, but it is
        # stricter than JSON Schema and changes across releases. We keep JSON
        # mode on and validate the returned object in our own pipeline layer.
        response = client.models.generate_content(
            model=self.config.default_model,
            contents=prompt,
            config=types.GenerateContentConfig(**config_kwargs),
        )
        text = getattr(response, "text", "") or ""
        parsed = _extract_json_object(text)
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
