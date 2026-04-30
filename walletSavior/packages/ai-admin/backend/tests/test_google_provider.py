"""Google provider adapter tests without live network calls."""
from __future__ import annotations

import pytest

from core.contracts.ai_pipeline import ProviderKind
from core.contracts.control_plane import ProviderConfigContract
from providers.google_genai import (
    GoogleGenAIProvider,
    ProviderConfigurationError,
    _extract_json_object,
)


def _config(**overrides) -> ProviderConfigContract:
    data = {
        "provider_id": "google-dev",
        "provider_kind": ProviderKind.GEMINI,
        "display_name": "Google Dev",
        "default_model": "gemini-test",
        "secret_alias": "GOOGLE_TEST_API_KEY",
    }
    data.update(overrides)
    return ProviderConfigContract(**data)


def test_extract_json_object_accepts_fenced_json() -> None:
    assert _extract_json_object('```json\n{"ok": true}\n```') == {"ok": True}


def test_validate_config_requires_env_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_TEST_API_KEY", raising=False)
    provider = GoogleGenAIProvider(_config())
    with pytest.raises(ProviderConfigurationError):
        provider.validate_config()


def test_validate_config_accepts_env_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_TEST_API_KEY", "fake-local-test-key")
    provider = GoogleGenAIProvider(_config())
    provider.validate_config()


def test_rejects_secret_alias_that_is_not_env_name() -> None:
    provider = GoogleGenAIProvider(_config(secret_alias="not-a-valid-alias-name"))
    with pytest.raises(ProviderConfigurationError):
        provider.validate_config()
