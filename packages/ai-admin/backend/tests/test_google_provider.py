"""Google provider adapter tests without live network calls."""
from __future__ import annotations

import io
import sys
import types as py_types

import pytest

from core.contracts.ai_pipeline import ProviderKind
from core.contracts.control_plane import ProviderConfigContract
from providers.google_genai import (
    GoogleGenAIProvider,
    ProviderConfigurationError,
    ProviderResponseError,
    _extract_json_object,
)
from providers.secret_resolver import resolve_secret_alias


FAKE_GOOGLE_KEY = "AIza" + "1" * 25


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


def _install_fake_google_types(monkeypatch: pytest.MonkeyPatch) -> None:
    class GenerateContentConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            for key, value in kwargs.items():
                setattr(self, key, value)

    google_mod = py_types.ModuleType("google")
    genai_mod = py_types.ModuleType("google.genai")
    types_mod = py_types.ModuleType("google.genai.types")
    types_mod.GenerateContentConfig = GenerateContentConfig
    genai_mod.types = types_mod
    google_mod.genai = genai_mod
    monkeypatch.setitem(sys.modules, "google", google_mod)
    monkeypatch.setitem(sys.modules, "google.genai", genai_mod)
    monkeypatch.setitem(sys.modules, "google.genai.types", types_mod)


class _FakeResponse:
    text = '{"items":[{"raw_record_id":"hotdeal:tofu","canonical_name":"풀무원 두부 300g"}]}'
    usage_metadata = None


def test_call_retries_without_json_mode_when_google_model_rejects_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_google_types(monkeypatch)
    monkeypatch.setenv("GOOGLE_TEST_API_KEY", "fake-local-test-key")
    calls = []

    class FakeModels:
        def generate_content(self, *, model, contents, config):
            calls.append((model, contents, config.kwargs))
            if config.kwargs.get("response_mime_type") == "application/json":
                raise Exception(
                    "400 INVALID_ARGUMENT. JSON mode is not enabled for models/gemma-4-26b-a4b-it"
                )
            return _FakeResponse()

    provider = GoogleGenAIProvider(_config(default_model="gemini-compatible-name"))
    provider._client = py_types.SimpleNamespace(models=FakeModels())

    result = provider.call(
        prompt="Label hotdeal tofu/meat/mart prices. Return JSON.",
        schema={"type": "object"},
    )

    assert result["items"][0]["raw_record_id"] == "hotdeal:tofu"
    assert len(calls) == 2
    assert calls[0][2]["response_mime_type"] == "application/json"
    assert "response_mime_type" not in calls[1][2]
    assert "Return one valid JSON object only" in calls[1][1]


def test_call_is_utf8_safe_when_stdout_starts_as_ascii(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_google_types(monkeypatch)
    monkeypatch.setenv("GOOGLE_TEST_API_KEY", "fake-local-test-key")
    ascii_stdout = io.TextIOWrapper(io.BytesIO(), encoding="ascii", errors="strict")
    monkeypatch.setattr(sys, "stdout", ascii_stdout)
    calls = []

    class FakeModels:
        def generate_content(self, *, model, contents, config):
            print(contents)
            calls.append((model, contents, config.kwargs))
            return _FakeResponse()

    provider = GoogleGenAIProvider(_config(default_model="gemini-2.5-flash"))
    provider._client = py_types.SimpleNamespace(models=FakeModels())

    result = provider.call(
        prompt="이마트 상품 라벨링: 친환경 대추방울토마토 600g/팩",
        schema={"type": "object"},
    )

    assert result["items"][0]["raw_record_id"] == "hotdeal:tofu"
    assert "\\uc774\\ub9c8\\ud2b8" in calls[0][1]
    assert calls[0][1].encode("ascii")
    assert sys.stdout.encoding.lower().replace("_", "-") == "utf-8"


def test_call_sends_ascii_safe_korean_prompt_when_sdk_transport_encodes_ascii(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_google_types(monkeypatch)
    monkeypatch.setenv("GOOGLE_TEST_API_KEY", "fake-local-test-key")
    calls = []

    class FakeModels:
        def generate_content(self, *, model, contents, config):
            contents.encode("ascii")
            calls.append((model, contents, config.kwargs))
            return _FakeResponse()

    provider = GoogleGenAIProvider(_config(default_model="gemini-2.5-flash"))
    provider._client = py_types.SimpleNamespace(models=FakeModels())

    result = provider.call(
        prompt="이마트 상품 라벨링: 친환경 대추방울토마토 600g/팩",
        schema={"type": "object"},
    )

    assert result["items"][0]["raw_record_id"] == "hotdeal:tofu"
    assert calls[0][1].startswith("Transport note:")
    assert "\\uce5c\\ud658\\uacbd" in calls[0][1]
    assert "친환경" not in calls[0][1]


def test_call_error_detail_includes_sanitized_cause_location(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_google_types(monkeypatch)
    monkeypatch.setenv("GOOGLE_TEST_API_KEY", "fake-local-test-key")

    class FakeModels:
        def generate_content(self, *, model, contents, config):
            raise UnicodeEncodeError("ascii", "상품명", 0, 3, "ordinal not in range(128)")

    provider = GoogleGenAIProvider(_config(default_model="gemini-2.5-flash"))
    provider._client = py_types.SimpleNamespace(models=FakeModels())

    with pytest.raises(ProviderResponseError) as exc_info:
        provider.call(prompt="Label E-Mart Korean records")

    detail = exc_info.value.to_detail()
    assert detail["cause"]["class"] == "UnicodeEncodeError"
    assert detail["cause"]["location"]["function"] == "generate_content"
    assert detail["cause"]["location"]["file"] == "test_google_provider.py"
    assert "AIza" not in detail["cause"]["message"]


def test_call_falls_back_without_json_mode_when_json_mode_returns_malformed_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_google_types(monkeypatch)
    monkeypatch.setenv("GOOGLE_TEST_API_KEY", "fake-local-test-key")
    calls = []

    class BadJsonModeResponse:
        text = "```json\n{\"items\": [}\n```"
        usage_metadata = None

    class GoodFallbackResponse:
        text = '{"items":[{"raw_record_id":"hotdeal:shrimp","category_id":"seafood.frozen"}]}'
        usage_metadata = None

    class FakeModels:
        def generate_content(self, *, model, contents, config):
            calls.append((model, contents, config.kwargs))
            if config.kwargs.get("response_mime_type") == "application/json":
                return BadJsonModeResponse()
            return GoodFallbackResponse()

    provider = GoogleGenAIProvider(_config(default_model="gemini-2.5-flash"))
    provider._client = py_types.SimpleNamespace(models=FakeModels())

    result = provider.call(prompt="Label frozen shrimp records.", schema={"type": "object"})

    assert result["items"][0]["raw_record_id"] == "hotdeal:shrimp"
    assert len(calls) == 2
    assert calls[0][2]["response_mime_type"] == "application/json"
    assert "response_mime_type" not in calls[1][2]
    assert "Return one valid JSON object only" in calls[1][1]


def test_call_reports_sanitized_error_when_json_mode_and_fallback_are_malformed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_google_types(monkeypatch)
    monkeypatch.setenv("GOOGLE_TEST_API_KEY", "fake-local-test-key")
    calls = []

    class BadJsonResponse:
        text = f"```json\n{{\"items\": [}}\n``` api_key={FAKE_GOOGLE_KEY}"
        usage_metadata = None

    class FakeModels:
        def generate_content(self, *, model, contents, config):
            calls.append((model, contents, config.kwargs))
            return BadJsonResponse()

    provider = GoogleGenAIProvider(_config(default_model="gemini-2.5-flash"))
    provider._client = py_types.SimpleNamespace(models=FakeModels())

    with pytest.raises(ProviderResponseError) as exc_info:
        provider.call(prompt="Label realistic E-Mart records.")

    message = str(exc_info.value)
    assert len(calls) == 2
    assert "malformed JSON" in message
    assert "fallback" in message
    assert "AIza" not in message
    assert "api_key" not in message


def test_call_skips_json_mode_for_gemma_model(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_google_types(monkeypatch)
    monkeypatch.setenv("GOOGLE_TEST_API_KEY", "fake-local-test-key")
    calls = []

    class FakeModels:
        def generate_content(self, *, model, contents, config):
            calls.append((model, contents, config.kwargs))
            return _FakeResponse()

    provider = GoogleGenAIProvider(_config(default_model="gemma-4-26b-a4b-it"))
    provider._client = py_types.SimpleNamespace(models=FakeModels())

    provider.call(prompt="Label tofu/meat mart hotdeal records.", schema={"type": "object"})

    assert len(calls) == 1
    assert calls[0][0] == "gemma-4-26b-a4b-it"
    assert "response_mime_type" not in calls[0][2]
    assert "Return one valid JSON object only" in calls[0][1]


def test_call_reports_sanitized_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_google_types(monkeypatch)
    monkeypatch.setenv("GOOGLE_TEST_API_KEY", "fake-local-test-key")

    class FakeModels:
        def generate_content(self, *, model, contents, config):
            raise Exception(f"quota failed api_key={FAKE_GOOGLE_KEY}")

    provider = GoogleGenAIProvider(_config(default_model="gemini-2.5-flash"))
    provider._client = py_types.SimpleNamespace(models=FakeModels())

    with pytest.raises(ProviderResponseError) as exc_info:
        provider.call(prompt="Label tofu/meat mart hotdeal records.")

    detail = exc_info.value.to_detail()
    assert detail["provider_id"] == "google-dev"
    assert detail["model"] == "gemini-2.5-flash"
    assert "AIza" not in detail["message"]


def test_call_marks_timeout_retryable_not_model_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_google_types(monkeypatch)
    monkeypatch.setenv("GOOGLE_TEST_API_KEY", "fake-local-test-key")

    class FakeModels:
        def generate_content(self, *, model, contents, config):
            raise TimeoutError("request timed out after 90 seconds")

    provider = GoogleGenAIProvider(_config(default_model="gemma-4-26b-a4b-it"))
    provider._client = py_types.SimpleNamespace(models=FakeModels())

    with pytest.raises(ProviderResponseError) as exc_info:
        provider.call(prompt="Label tofu/meat mart hotdeal records.")

    detail = exc_info.value.to_detail()
    assert detail["error"] == "provider_timeout_retryable"
    assert detail["model"] == "gemma-4-26b-a4b-it"


def test_call_marks_not_found_as_model_configuration_issue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_google_types(monkeypatch)
    monkeypatch.setenv("GOOGLE_TEST_API_KEY", "fake-local-test-key")

    class FakeModels:
        def generate_content(self, *, model, contents, config):
            raise Exception("404 NOT_FOUND model gemma-3-27b-it was not found")

    provider = GoogleGenAIProvider(_config(default_model="gemma-3-27b-it"))
    provider._client = py_types.SimpleNamespace(models=FakeModels())

    with pytest.raises(ProviderResponseError) as exc_info:
        provider.call(prompt="Label tofu/meat mart hotdeal records.")

    detail = exc_info.value.to_detail()
    assert detail["error"] == "model_not_found"
    assert detail["model"] == "gemma-3-27b-it"


def test_call_rejects_malformed_json_without_leaking_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_google_types(monkeypatch)
    monkeypatch.setenv("GOOGLE_TEST_API_KEY", "fake-local-test-key")

    class BadJsonResponse:
        text = f"```json\n{{\"items\": [}}\n``` api_key={FAKE_GOOGLE_KEY}"
        usage_metadata = None

    class FakeModels:
        def generate_content(self, *, model, contents, config):
            return BadJsonResponse()

    provider = GoogleGenAIProvider(_config(default_model="gemini-2.5-flash"))
    provider._client = py_types.SimpleNamespace(models=FakeModels())

    with pytest.raises(ProviderResponseError) as exc_info:
        provider.call(prompt="Label realistic E-Mart records.")

    message = str(exc_info.value)
    assert "malformed JSON" in message
    assert "AIza" not in message
    assert "api_key" not in message


def test_list_models_returns_live_sdk_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_TEST_API_KEY", "fake-local-test-key")

    class FakeModel:
        name = "models/gemma-4-26b-a4b-it"
        display_name = "Gemma 3"
        supported_actions = ["generateContent"]
        input_token_limit = 8192
        output_token_limit = 2048

    class FakeModels:
        def list(self):
            return [FakeModel()]

    provider = GoogleGenAIProvider(_config(default_model="gemma-4-26b-a4b-it"))
    provider._client = py_types.SimpleNamespace(models=FakeModels())

    body = provider.list_models()

    assert body["discovery_status"] == "available"
    assert body["discovery_source"] == "live_sdk"
    assert body["quota_status"] == "not_reported"
    model = body["models"][0]
    assert model["name"] == "gemma-4-26b-a4b-it"
    assert model["api_name"] == "models/gemma-4-26b-a4b-it"
    assert model["supports_json_mode"] is False
    assert model["source"] == "live_sdk"


def test_list_models_reports_sanitized_quota_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOOGLE_TEST_API_KEY", "fake-local-test-key")

    class FakeModels:
        def list(self):
            raise Exception(f"429 quota exhausted api_key={FAKE_GOOGLE_KEY}")

    provider = GoogleGenAIProvider(_config(default_model="gemini-2.5-flash"))
    provider._client = py_types.SimpleNamespace(models=FakeModels())

    with pytest.raises(ProviderResponseError) as exc_info:
        provider.list_models()

    detail = exc_info.value.to_detail()
    assert detail["error"] == "quota_limited"
    assert "AIza" not in detail["message"]
    assert "api_key" in detail["message"]
