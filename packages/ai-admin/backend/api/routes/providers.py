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

from core.ai_providers import (
    DEFAULT_CAPABILITIES,
    ProviderRegistry,
    configured_model_capability,
)
from core.contracts.ai_pipeline import ProviderKind
from core.contracts.control_plane import ProviderConfigContract

from api.deps import get_db_session
from providers import GoogleGenAIProvider
from providers.google_genai import ProviderConfigurationError, ProviderResponseError
from providers.secret_resolver import DEFAULT_ENV_PATHS, resolve_secret_alias
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
        "is_local": cap.supports_local_execution,
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


def _model_listing_with_capability(
    config: ProviderConfigContract,
    payload: dict,
    *,
    availability_status: str | None = None,
) -> dict:
    payload.setdefault(
        "default_model_capability",
        configured_model_capability(
            config,
            availability_status=availability_status
            or payload.get("discovery_status", "configured"),
            smoke_status="not_run",
        ).to_dict(),
    )
    return payload


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


@router.get("/setup-state")
def list_provider_setup_state(
    session: Session = Depends(get_db_session),
) -> dict:
    """Return local setup status without exposing secret values or calling providers."""
    repo = ProviderConfigRepository(session)
    configs = repo.list()
    states = []
    for cfg in configs:
        alias = cfg.secret_alias or ("GOOGLE_API_KEY" if cfg.provider_kind == ProviderKind.GEMINI else None)
        requires_secret = cfg.provider_kind == ProviderKind.GEMINI
        secret_resolved = bool(alias and resolve_secret_alias(alias))
        availability_status = (
            "ready"
            if cfg.is_enabled and (not requires_secret or secret_resolved)
            else "missing_secret"
            if requires_secret and not secret_resolved
            else "disabled"
            if not cfg.is_enabled
            else "configured"
        )
        model_capability = configured_model_capability(
            cfg,
            availability_status=availability_status,
            smoke_status="not_run",
        ).to_dict()
        live_actions = []
        if cfg.provider_kind == ProviderKind.GEMINI:
            live_actions = [
                f"/api/providers/{cfg.provider_id}/models",
                f"/api/providers/{cfg.provider_id}/smoke-test",
                "/api/ingest/raw-records/label",
            ]
        states.append(
            {
                "provider_id": cfg.provider_id,
                "provider_kind": cfg.provider_kind.value,
                "is_enabled": cfg.is_enabled,
                "secret_alias": alias,
                "requires_secret": requires_secret,
                "secret_resolved": secret_resolved,
                "env_locations": [str(path) for path in DEFAULT_ENV_PATHS],
                "offline_actions": [
                    "/api/providers",
                    f"/api/providers/{cfg.provider_id}/capabilities",
                    "/api/review/audit",
                    "/api/review/raw-records",
                    "/api/review/proposals/* review decisions",
                ],
                "live_actions": live_actions,
                "can_call_live": cfg.is_enabled and (not requires_secret or secret_resolved),
                "live_rate_limits": {
                    "min_request_interval_seconds": cfg.min_request_interval_seconds,
                    "max_provider_calls_per_minute": cfg.max_provider_calls_per_minute,
                    "max_provider_calls_per_day": cfg.max_provider_calls_per_day,
                    "provider_retry_max_attempts": cfg.provider_retry_max_attempts,
                    "provider_retry_min_delay_seconds": cfg.provider_retry_min_delay_seconds,
                    "provider_retry_max_delay_seconds": cfg.provider_retry_max_delay_seconds,
                },
                "model_capability": model_capability,
            }
        )
    return {"providers": states, "count": len(states)}


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
        "model_capability": configured_model_capability(cfg).to_dict(),
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
    adapter = _adapter_for_config(cfg)
    if not cfg.is_enabled:
        return _model_listing_with_capability(
            cfg,
            adapter.static_model_listing(
                discovery_status="unavailable",
                discovery_source="static_config",
                error={
                    "error": "provider_disabled",
                    "message": "provider is disabled; enable it before live discovery",
                },
            ),
            availability_status="disabled",
        )
    try:
        return _model_listing_with_capability(cfg, adapter.list_models())
    except ProviderConfigurationError as exc:
        return _model_listing_with_capability(
            cfg,
            adapter.static_model_listing(
                discovery_status="unavailable",
                discovery_source="static_config",
                error={"error": "configuration_unavailable", "message": str(exc)},
            ),
            availability_status="missing_secret",
        )
    except ProviderResponseError as exc:
        detail = exc.to_detail()
        discovery_status = (
            "quota_limited" if detail.get("error") == "quota_limited" else "error"
        )
        return _model_listing_with_capability(
            cfg,
            adapter.static_model_listing(
                discovery_status=discovery_status,
                discovery_source="static_fallback",
                error=detail,
            ),
        )


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
        "provider_mode": getattr(adapter, "provider_mode", "live"),
        "model_capability": configured_model_capability(
            cfg,
            availability_status="ready",
            smoke_status="passed",
        ).to_dict(),
        "result": result,
    }
