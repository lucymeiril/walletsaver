"""
AI provider registry.

실제 Gemini/OpenAI/Ollama SDK 호출은 ai-admin backend adapter가 구현한다. shared는
provider 선택, capability 검증, secret alias 원칙만 고정하여 provider 교체와 로컬 모델
사용을 쉽게 만든다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .contracts.ai_pipeline import ProviderKind
from .contracts.control_plane import ProviderConfigContract


class AIProvider(Protocol):
    """ai-admin provider adapter가 구현해야 하는 호출 계약."""

    config: ProviderConfigContract

    def validate_config(self) -> None:
        """provider 설정이 호출 가능한지 검증한다."""

    def call(self, *, prompt: str, schema: dict[str, Any] | None = None) -> dict[str, Any]:
        """LLM 호출 결과를 JSON-serializable dict로 반환한다."""


@dataclass(frozen=True)
class ProviderCapabilities:
    """provider/model별 기능 메타데이터."""

    provider_kind: ProviderKind
    supports_json_mode: bool
    supports_local_execution: bool
    max_prompt_chars: int
    default_timeout_seconds: int = 60


@dataclass(frozen=True)
class ProviderModelCapability:
    """Operator-facing runtime capability metadata for one configured model."""

    provider_kind: ProviderKind
    model_name: str
    supports_json_mode: bool
    supports_local_execution: bool
    is_local: bool
    max_prompt_chars: int
    default_timeout_seconds: int
    availability_status: str = "configured"
    smoke_status: str = "not_run"
    input_token_limit: int | None = None
    output_token_limit: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_kind": self.provider_kind.value,
            "model_name": self.model_name,
            "supports_json_mode": self.supports_json_mode,
            "supports_local_execution": self.supports_local_execution,
            "is_local": self.is_local,
            "max_prompt_chars": self.max_prompt_chars,
            "default_timeout_seconds": self.default_timeout_seconds,
            "availability_status": self.availability_status,
            "smoke_status": self.smoke_status,
            "input_token_limit": self.input_token_limit,
            "output_token_limit": self.output_token_limit,
        }


DEFAULT_CAPABILITIES: dict[ProviderKind, ProviderCapabilities] = {
    ProviderKind.GEMINI: ProviderCapabilities(
        provider_kind=ProviderKind.GEMINI,
        supports_json_mode=True,
        supports_local_execution=False,
        max_prompt_chars=2000,
    ),
    ProviderKind.OPENAI_COMPATIBLE: ProviderCapabilities(
        provider_kind=ProviderKind.OPENAI_COMPATIBLE,
        supports_json_mode=True,
        supports_local_execution=False,
        max_prompt_chars=2000,
    ),
    ProviderKind.OLLAMA: ProviderCapabilities(
        provider_kind=ProviderKind.OLLAMA,
        supports_json_mode=False,
        supports_local_execution=True,
        max_prompt_chars=2000,
        default_timeout_seconds=120,
    ),
    ProviderKind.CUSTOM: ProviderCapabilities(
        provider_kind=ProviderKind.CUSTOM,
        supports_json_mode=False,
        supports_local_execution=False,
        max_prompt_chars=2000,
    ),
}


def model_supports_json_mode(provider_kind: ProviderKind, model_name: str) -> bool:
    """Return the JSON-mode request capability known before a live call."""

    base = DEFAULT_CAPABILITIES[provider_kind]
    if not base.supports_json_mode:
        return False
    if provider_kind == ProviderKind.GEMINI and "gemma" in model_name.lower():
        return False
    return True


def configured_model_capability(
    config: ProviderConfigContract,
    *,
    availability_status: str = "configured",
    smoke_status: str = "not_run",
    input_token_limit: int | None = None,
    output_token_limit: int | None = None,
) -> ProviderModelCapability:
    base = DEFAULT_CAPABILITIES[config.provider_kind]
    return ProviderModelCapability(
        provider_kind=config.provider_kind,
        model_name=config.default_model,
        supports_json_mode=model_supports_json_mode(
            config.provider_kind, config.default_model
        ),
        supports_local_execution=base.supports_local_execution,
        is_local=base.supports_local_execution,
        max_prompt_chars=base.max_prompt_chars,
        default_timeout_seconds=base.default_timeout_seconds,
        availability_status=availability_status,
        smoke_status=smoke_status,
        input_token_limit=input_token_limit,
        output_token_limit=output_token_limit,
    )


class ProviderRegistry:
    """provider 설정과 adapter factory를 관리한다."""

    def __init__(self) -> None:
        self._configs: dict[str, ProviderConfigContract] = {}
        self._factories: dict[ProviderKind, type[AIProvider]] = {}

    def register_factory(self, provider_kind: ProviderKind, factory: type[AIProvider]) -> None:
        self._factories[provider_kind] = factory

    def register_config(self, config: ProviderConfigContract) -> None:
        self._validate_secret_boundary(config)
        self._configs[config.provider_id] = config

    def get_config(self, provider_id: str) -> ProviderConfigContract:
        try:
            return self._configs[provider_id]
        except KeyError as exc:
            raise KeyError(f"AI provider is not registered: {provider_id}") from exc

    def list_enabled(self) -> list[ProviderConfigContract]:
        return [config for config in self._configs.values() if config.is_enabled]

    def capabilities(self, provider_id: str) -> ProviderCapabilities:
        config = self.get_config(provider_id)
        return DEFAULT_CAPABILITIES[config.provider_kind]

    def create(self, provider_id: str) -> AIProvider:
        config = self.get_config(provider_id)
        if not config.is_enabled:
            raise ValueError(f"AI provider is disabled: {provider_id}")
        try:
            factory = self._factories[config.provider_kind]
        except KeyError as exc:
            raise KeyError(f"No adapter factory registered for {config.provider_kind.value}") from exc
        provider = factory(config)  # type: ignore[call-arg]
        provider.validate_config()
        return provider

    def _validate_secret_boundary(self, config: ProviderConfigContract) -> None:
        if config.secret_alias and any(token in config.secret_alias.lower() for token in ("sk-", "key=", "bearer ")):
            raise ValueError("ProviderConfig.secret_alias must be an alias, not a secret value")
