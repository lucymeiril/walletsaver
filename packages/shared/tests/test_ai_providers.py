"""AI provider registry 테스트."""

import pytest

from shared.core.ai_providers import ProviderRegistry
from shared.core.contracts.ai_pipeline import ProviderKind
from shared.core.contracts.control_plane import ProviderConfigContract


class FakeProvider:
    def __init__(self, config: ProviderConfigContract):
        self.config = config

    def validate_config(self) -> None:
        if not self.config.default_model:
            raise ValueError("default_model required")

    def call(self, *, prompt: str, schema=None):
        return {"prompt": prompt, "schema": schema}


def make_config(provider_id: str = "gemini-main") -> ProviderConfigContract:
    return ProviderConfigContract(
        provider_id=provider_id,
        provider_kind=ProviderKind.GEMINI,
        display_name="Gemini Main",
        default_model="gemini-2.5-pro",
        secret_alias="GEMINI_API_KEY",
    )


def test_register_and_create_provider_from_factory():
    registry = ProviderRegistry()
    registry.register_factory(ProviderKind.GEMINI, FakeProvider)
    registry.register_config(make_config())

    provider = registry.create("gemini-main")

    assert provider.config.provider_id == "gemini-main"
    assert provider.call(prompt="hello") == {"prompt": "hello", "schema": None}


def test_disabled_provider_cannot_be_created():
    registry = ProviderRegistry()
    registry.register_factory(ProviderKind.GEMINI, FakeProvider)
    config = make_config().model_copy(update={"is_enabled": False})
    registry.register_config(config)

    with pytest.raises(ValueError, match="disabled"):
        registry.create("gemini-main")


def test_secret_alias_rejects_inline_secret_like_values():
    registry = ProviderRegistry()
    config = make_config().model_copy(update={"secret_alias": "sk-real-secret-should-not-be-here"})

    with pytest.raises(ValueError, match="alias"):
        registry.register_config(config)


def test_capabilities_expose_local_ollama_flag():
    registry = ProviderRegistry()
    registry.register_config(
        ProviderConfigContract(
            provider_id="ollama-local",
            provider_kind=ProviderKind.OLLAMA,
            display_name="Ollama Local",
            default_model="llama3.1",
            secret_alias=None,
        )
    )

    caps = registry.capabilities("ollama-local")

    assert caps.supports_local_execution is True
    assert caps.max_prompt_chars == 2000
