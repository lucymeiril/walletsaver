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
from providers.secret_resolver import resolve_secret_alias


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


def test_validate_config_accepts_dotenv_alias(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GOOGLE_TEST_API_KEY", raising=False)
    dotenv = tmp_path / ".env"
    dotenv.write_text('GOOGLE_TEST_API_KEY="fake-dotenv-test-key"\n', encoding="utf-8")

    provider = GoogleGenAIProvider(_config(), env_paths=[dotenv])

    provider.validate_config()


def test_dotenv_alias_takes_priority_over_process_env(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GOOGLE_TEST_API_KEY", "fake-process-test-key")
    dotenv = tmp_path / ".env"
    dotenv.write_text("GOOGLE_TEST_API_KEY=fake-dotenv-test-key\n", encoding="utf-8")

    assert resolve_secret_alias("GOOGLE_TEST_API_KEY", [dotenv]) == "fake-dotenv-test-key"


def test_missing_alias_error_names_alias_without_secret_value(tmp_path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("OTHER_GOOGLE_KEY=fake-dotenv-secret-value\n", encoding="utf-8")
    provider = GoogleGenAIProvider(_config(), env_paths=[dotenv])

    with pytest.raises(ProviderConfigurationError) as exc_info:
        provider.validate_config()

    message = str(exc_info.value)
    assert "GOOGLE_TEST_API_KEY" in message
    assert "fake-dotenv-secret-value" not in message


def test_rejects_secret_alias_that_is_not_env_name() -> None:
    provider = GoogleGenAIProvider(_config(secret_alias="not-a-valid-alias-name"))
    with pytest.raises(ProviderConfigurationError):
        provider.validate_config()
