"""Google AI Studio live smoke harness tests.

These tests use fakes unless WALLET_SAVIOR_LIVE_AI_SMOKE=1 and a GOOGLE_API_KEY
alias is configured, so default test runs do not consume Google AI Studio quota.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

import services.aistudio_live_smoke as smoke_module
from providers.google_genai import ProviderResponseError
from services.aistudio_live_smoke import (
    DEFAULT_MODEL,
    DEFAULT_SECRET_ALIAS,
    LIVE_SMOKE_ENV,
    build_provider_config,
    run_aistudio_live_smoke,
)
from providers.secret_resolver import resolve_secret_alias


FAKE_GOOGLE_KEY = "AIza" + "1" * 30
FAKE_GOOGLE_KEY_ALT = "AIza" + "0" * 30
FAKE_OPENAI_KEY = "sk-live" + "1" * 12


class _FailingProvider:
    def call(self, **_kwargs):
        raise AssertionError("provider must not be called")


def test_default_model_prefers_higher_quota_configured_choice() -> None:
    config = build_provider_config()

    assert DEFAULT_MODEL == "gemini-3.1-flash-lite-preview"
    assert config.default_model == "gemini-3.1-flash-lite-preview"
    assert config.default_model != "gemini-2.5-flash-lite"


def test_non_live_default_skips_without_provider_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(LIVE_SMOKE_ENV, raising=False)
    config = build_provider_config(secret_alias="MAY_EXIST_BUT_NOT_USED")

    result = run_aistudio_live_smoke(config=config, provider=_FailingProvider())

    assert result["status"] == "SKIPPED"
    assert result["live_call_attempted"] is False
    assert result["live_call_succeeded"] is False
    assert result["key_present"] is False
    assert result["env_paths_checked"]
    assert result["env_path_with_alias"] is None
    assert "live opt-in missing" in result["skip_reason"]
    assert LIVE_SMOKE_ENV in result["skip_reason"]


def test_non_live_reports_backend_env_key_readiness_without_secret_leakage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = FAKE_GOOGLE_KEY
    fake_backend_dir = tmp_path / "packages" / "ai-admin" / "backend"
    fake_backend_dir.mkdir(parents=True)
    backend_dotenv = fake_backend_dir / ".env"
    repo_dotenv = tmp_path / ".env"
    backend_dotenv.write_text(f"GOOGLE_TEST_SMOKE_KEY={secret}\n", encoding="utf-8")
    repo_dotenv.write_text(f"GOOGLE_TEST_SMOKE_KEY={FAKE_GOOGLE_KEY_ALT}\n", encoding="utf-8")
    monkeypatch.delenv(LIVE_SMOKE_ENV, raising=False)
    monkeypatch.delenv("GOOGLE_TEST_SMOKE_KEY", raising=False)

    result = run_aistudio_live_smoke(
        config=build_provider_config(secret_alias="GOOGLE_TEST_SMOKE_KEY"),
        env_paths=(backend_dotenv, repo_dotenv),
        provider=_FailingProvider(),
    )

    serialized = str(result)
    assert result["status"] == "SKIPPED"
    assert result["live_call_attempted"] is False
    assert result["key_present"] is True
    assert result["env_paths_checked"] == [str(backend_dotenv), str(repo_dotenv)]
    assert result["env_path_with_alias"] == str(backend_dotenv)
    assert "live opt-in missing" in result["skip_reason"]
    assert secret not in serialized
    assert "AIza" not in serialized


def test_live_enabled_no_key_is_blocked_not_passed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(LIVE_SMOKE_ENV, "1")
    monkeypatch.delenv("GOOGLE_SMOKE_MISSING_KEY", raising=False)
    config = build_provider_config(secret_alias="GOOGLE_SMOKE_MISSING_KEY")

    result = run_aistudio_live_smoke(config=config, provider=_FailingProvider())

    assert result["status"] == "BLOCKED"
    assert result["live_call_attempted"] is False
    assert result["live_call_succeeded"] is False
    assert result["key_present"] is False
    assert result["env_path_with_alias"] is None
    assert "key missing" in result["skip_reason"]
    assert "GOOGLE_SMOKE_MISSING_KEY" in result["skip_reason"]


def test_provider_disabled_skip_reason_is_distinct(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(LIVE_SMOKE_ENV, "1")
    config = build_provider_config()
    config.is_enabled = False

    result = run_aistudio_live_smoke(config=config, provider=_FailingProvider())

    assert result["status"] == "BLOCKED"
    assert result["skip_reason"] == "provider disabled; no live provider call attempted"
    assert result["live_call_attempted"] is False


def test_alias_resolution_failure_is_distinct_and_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = FAKE_GOOGLE_KEY
    monkeypatch.setenv(LIVE_SMOKE_ENV, "1")

    def raise_with_secret(_path: Path) -> dict[str, str]:
        raise OSError(f"cannot read dotenv api_key={secret} Authorization Bearer {FAKE_OPENAI_KEY}")

    monkeypatch.setattr(smoke_module, "_parse_env_file", raise_with_secret)

    result = run_aistudio_live_smoke(
        config=build_provider_config(secret_alias="GOOGLE_TEST_SMOKE_KEY"),
        env_paths=(Path("backend.env"),),
        provider=_FailingProvider(),
    )

    serialized = str(result)
    assert result["status"] == "BLOCKED"
    assert "alias resolution failed" in result["skip_reason"]
    assert result["live_call_attempted"] is False
    assert secret not in serialized
    assert "AIza" not in serialized
    assert FAKE_OPENAI_KEY not in serialized
    assert "Bearer [REDACTED]" in serialized


def test_metadata_redacts_secret_from_success_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = FAKE_GOOGLE_KEY
    dotenv = tmp_path / ".env"
    dotenv.write_text(f"GOOGLE_TEST_SMOKE_KEY={secret}\n", encoding="utf-8")
    monkeypatch.setenv(LIVE_SMOKE_ENV, "1")

    class SecretEchoProvider:
        def call(self, **_kwargs):
            return {
                "ok": True,
                "purpose": "wallet_savior_ai_studio_smoke",
                "debug": f"api_key={secret}",
            }

    result = run_aistudio_live_smoke(
        config=build_provider_config(secret_alias="GOOGLE_TEST_SMOKE_KEY"),
        env_paths=(dotenv,),
        provider=SecretEchoProvider(),
    )

    serialized = str(result)
    assert result["status"] == "PASSED"
    assert result["live_call_attempted"] is True
    assert result["live_call_succeeded"] is True
    assert result["parsed_shape"]["keys"] == ["debug", "ok", "purpose"]
    assert secret not in serialized
    assert "[REDACTED]" in result["response_excerpt"]


def test_provider_error_is_visible_but_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = FAKE_GOOGLE_KEY
    dotenv = tmp_path / ".env"
    dotenv.write_text(f"GOOGLE_TEST_SMOKE_KEY={secret}\n", encoding="utf-8")
    monkeypatch.setenv(LIVE_SMOKE_ENV, "1")

    class ErrorProvider:
        def call(self, **_kwargs):
            raise ProviderResponseError(
                f"quota exhausted api_key={secret}",
                provider_id="google-aistudio-live-smoke",
                model="gemini-test",
                error_kind="quota_limited",
            )

    result = run_aistudio_live_smoke(
        config=build_provider_config(model="gemini-test", secret_alias="GOOGLE_TEST_SMOKE_KEY"),
        env_paths=(dotenv,),
        provider=ErrorProvider(),
    )

    serialized = str(result)
    assert result["status"] == "FAILED"
    assert result["live_call_attempted"] is True
    assert result["live_call_succeeded"] is False
    assert result["error"]["error"] == "quota_limited"
    assert "quota exhausted" in result["error"]["message"]
    assert secret not in serialized
    assert "AIza" not in serialized


@pytest.mark.skipif(
    os.getenv(LIVE_SMOKE_ENV) != "1" or not resolve_secret_alias(DEFAULT_SECRET_ALIAS),
    reason=f"Set {LIVE_SMOKE_ENV}=1 and {DEFAULT_SECRET_ALIAS} to consume one live Google AI Studio smoke call.",
)
def test_opt_in_live_google_aistudio_smoke() -> None:
    result = run_aistudio_live_smoke()

    assert result["live_call_attempted"] is True
    assert result["status"] == "PASSED", result
    assert result["live_call_succeeded"] is True
    assert result["parsed_shape"]["type"] == "object"
