"""Provider 설정 관리 라우트.

원칙:
    * 비밀값(secret value)은 절대 받지도, 반환하지도 않는다. `secret_alias`만 사용.
    * `ProviderConfigContract`로 검증하고, `ProviderRegistry`의 secret-boundary
      검사를 재사용해서 인라인-비밀로 보이는 alias 입력을 거절한다.
    * 응답 모델은 contract 그대로(=alias만 포함)이므로 secret leak이 구조적으로
      불가능하다.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.ai_providers import DEFAULT_CAPABILITIES, ProviderRegistry
from core.contracts.ai_pipeline import ProviderKind
from core.contracts.control_plane import ProviderConfigContract

from api.deps import get_db_session
from providers import GoogleGenAIProvider
from providers.google_genai import ProviderConfigurationError, ProviderResponseError
from storage.repositories import ProviderConfigRepository

router = APIRouter(prefix="/api/providers", tags=["providers"])


_INLINE_SECRET_TOKENS = ("sk-", "key=", "bearer ")


def _reject_inline_secret(alias: Optional[str]) -> None:
    """alias가 실제 비밀값처럼 보이면 거절한다. ProviderRegistry 검사와 동일 규칙."""
    if alias is None:
        return
    lowered = alias.lower()
    if any(token in lowered for token in _INLINE_SECRET_TOKENS):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="secret_alias must be an alias, not a secret value",
        )


def _capabilities_payload(kind: ProviderKind) -> dict:
    cap = DEFAULT_CAPABILITIES[kind]
    return {
        "provider_kind": cap.provider_kind.value,
        "supports_json_mode": cap.supports_json_mode,
        "supports_local_execution": cap.supports_local_execution,
        "max_prompt_chars": cap.max_prompt_chars,
        "default_timeout_seconds": cap.default_timeout_seconds,
    }


def _adapter_for_config(config: ProviderConfigContract):
    if config.provider_kind == ProviderKind.GEMINI:
        return GoogleGenAIProvider(config)
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"provider adapter not implemented: {config.provider_kind.value}",
    )


class EnabledPayload(BaseModel):
    is_enabled: bool = Field(..., description="활성/비활성 토글 값")


@router.get("")
def list_providers(session: Session = Depends(get_db_session)) -> dict:
    repo = ProviderConfigRepository(session)
    configs = repo.list()
    return {
        "providers": [c.model_dump(mode="json") for c in configs],
        "count": len(configs),
    }


@router.post("", status_code=status.HTTP_200_OK)
def upsert_provider(
    payload: ProviderConfigContract,
    session: Session = Depends(get_db_session),
) -> dict:
    _reject_inline_secret(payload.secret_alias)

    # ProviderRegistry의 secret-boundary 규칙을 한 번 더 호출해 일관성 유지.
    registry = ProviderRegistry()
    try:
        registry.register_config(payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    repo = ProviderConfigRepository(session)
    repo.save(payload)
    return payload.model_dump(mode="json")


@router.get("/{provider_id}")
def get_provider(
    provider_id: str,
    session: Session = Depends(get_db_session),
) -> dict:
    repo = ProviderConfigRepository(session)
    cfg = repo.get(provider_id)
    if cfg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="provider not found"
        )
    return cfg.model_dump(mode="json")


@router.post("/{provider_id}/enabled")
def set_provider_enabled(
    provider_id: str,
    payload: EnabledPayload,
    session: Session = Depends(get_db_session),
) -> dict:
    repo = ProviderConfigRepository(session)
    cfg = repo.get(provider_id)
    if cfg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="provider not found"
        )
    updated = cfg.model_copy(update={"is_enabled": payload.is_enabled})
    repo.save(updated)
    return updated.model_dump(mode="json")


@router.get("/{provider_id}/capabilities")
def get_provider_capabilities(
    provider_id: str,
    session: Session = Depends(get_db_session),
) -> dict:
    repo = ProviderConfigRepository(session)
    cfg = repo.get(provider_id)
    if cfg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="provider not found"
        )
    return {
        "provider_id": cfg.provider_id,
        "capabilities": _capabilities_payload(cfg.provider_kind),
    }


@router.get("/{provider_id}/models")
def list_provider_models(
    provider_id: str,
    session: Session = Depends(get_db_session),
) -> dict:
    repo = ProviderConfigRepository(session)
    cfg = repo.get(provider_id)
    if cfg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="provider not found"
        )
    try:
        adapter = _adapter_for_config(cfg)
        return adapter.list_models()
    except ProviderConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


class ProviderSmokePayload(BaseModel):
    prompt: str = Field(
        default='Return {"ok": true, "provider": "google"} as JSON.',
        max_length=500,
    )


@router.post("/{provider_id}/smoke-test")
def smoke_test_provider(
    provider_id: str,
    payload: ProviderSmokePayload,
    session: Session = Depends(get_db_session),
) -> dict:
    repo = ProviderConfigRepository(session)
    cfg = repo.get(provider_id)
    if cfg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="provider not found"
        )
    try:
        adapter = _adapter_for_config(cfg)
        result = adapter.call(prompt=payload.prompt)
    except ProviderConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ProviderResponseError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return {
        "provider_id": cfg.provider_id,
        "model": cfg.default_model,
        "result": result,
    }
