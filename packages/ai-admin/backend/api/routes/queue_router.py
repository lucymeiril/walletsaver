"""WalletSavior Phase C1 — ProductReviewQueue AI 라우터 FastAPI 엔드포인트.

엔드포인트:
    POST /api/queue-router/route-batch  : 큐 항목 목록을 LLM으로 분류
    POST /api/queue-router/route-one    : 단일 큐 항목 분류
    GET  /api/queue-router/status       : 라우터 상태 조회 (카테고리 트리 노드 수 등)

설계 원칙:
    - provider는 ai-admin의 GoogleGenAIProvider를 사용 (재구현 금지)
    - category_tree·brand_dictionary·synonyms는 YAML에서 로드 (캐싱)
    - 라이브 provider 호출은 WALLETSAVIOR_LIVE_AI=1 환경변수로 opt-in
    - 기본(WALLETSAVIOR_LIVE_AI 미설정)은 route 로직은 동작하지만 provider 미설정 시 오류
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import sys
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_SHARED_DIR = _BACKEND_DIR.parent.parent / "shared"
for _p in (str(_BACKEND_DIR), str(_SHARED_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from services.queue_ai_router import (
    QueueAiRouter,
    QueueRouterDecision,
    ApplyResult,
    load_default_category_tree,
    load_default_brand_dictionary,
    load_default_synonyms,
    _all_category_ids,
)

router = APIRouter(prefix="/api/queue-router", tags=["queue-ai-router"])

# 카테고리 트리·브랜드·동의어는 프로세스당 1회 로드 (모듈 수준 캐시)
_CATEGORY_TREE: dict | None = None
_BRAND_DICTIONARY: list[str] | None = None
_SYNONYMS: dict | None = None


def _get_category_tree() -> dict:
    global _CATEGORY_TREE
    if _CATEGORY_TREE is None:
        _CATEGORY_TREE = load_default_category_tree()
    return _CATEGORY_TREE


def _get_brand_dictionary() -> list[str]:
    global _BRAND_DICTIONARY
    if _BRAND_DICTIONARY is None:
        _BRAND_DICTIONARY = load_default_brand_dictionary()
    return _BRAND_DICTIONARY


def _get_synonyms() -> dict:
    global _SYNONYMS
    if _SYNONYMS is None:
        _SYNONYMS = load_default_synonyms()
    return _SYNONYMS


def _live_enabled() -> bool:
    return os.environ.get("WALLETSAVIOR_LIVE_AI", "").strip().lower() in {"1", "true", "yes", "on"}


def _build_provider():
    """
    GoogleGenAIProvider를 생성한다.
    WALLETSAVIOR_LIVE_AI=1 일 때만 실제 provider 사용.
    환경변수 미설정 시 provider 없음 오류를 명시적으로 반환한다.
    """
    if not _live_enabled():
        raise HTTPException(
            status_code=400,
            detail={
                "error": "live_provider_disabled",
                "message": (
                    "라이브 AI 호출은 WALLETSAVIOR_LIVE_AI=1 환경변수로 opt-in해야 합니다. "
                    "테스트용 dry-run에는 dry_run=true 파라미터를 사용하세요."
                ),
            },
        )
    from providers.google_genai import GoogleGenAIProvider
    from core.contracts.ai_pipeline import ProviderKind
    from core.contracts.control_plane import ProviderConfigContract

    config = ProviderConfigContract(
        provider_id="queue-ai-router",
        provider_kind=ProviderKind.GEMINI,
        display_name="Queue AI Router",
        default_model=os.environ.get("WALLETSAVIOR_AI_MODEL", "gemini-2.0-flash"),
        secret_alias=os.environ.get("WALLETSAVIOR_AI_SECRET_ALIAS", "GOOGLE_API_KEY"),
        is_enabled=True,
        max_concurrent_jobs=1,
        min_request_interval_seconds=1.0,
    )
    return GoogleGenAIProvider(config)


# ── Request / Response 모델 ──────────────────────────────────────────────────

class QueueEntryPayload(BaseModel):
    """API로 전달되는 단일 큐 항목 (Pydantic DTO)."""
    id: str
    raw_payload: dict
    source_mart: str
    reason: str
    suggested_canonical_id: Optional[str] = None


class RouteBatchRequest(BaseModel):
    entries: list[QueueEntryPayload] = Field(
        ..., max_length=100, description="최대 100건"
    )
    dry_run: bool = Field(
        default=False,
        description="True: provider 호출 안 함, False: 실제 AI 호출 (WALLETSAVIOR_LIVE_AI=1 필요)",
    )


class DecisionResponse(BaseModel):
    queue_id: str
    decision: str
    category_node_id: Optional[str] = None
    brand: Optional[str] = None
    name_core_refined: Optional[str] = None
    confidence: float
    reasons: list[str]
    elapsed_ms: int


class RouteBatchResponse(BaseModel):
    total: int
    resolved: int
    escalated: int
    decisions: list[DecisionResponse]


# ── 엔드포인트 ───────────────────────────────────────────────────────────────

def _entry_payload_to_dto(entry: QueueEntryPayload):
    """API payload → Pydantic DTO 변환 (core.canonical_models.ProductReviewQueue)."""
    from core.canonical_models import ProductReviewQueue, MartKind, ReviewReason
    from datetime import datetime

    return ProductReviewQueue(
        id=entry.id,
        raw_payload=entry.raw_payload,
        source_mart=MartKind(entry.source_mart),
        reason=ReviewReason(entry.reason),
        suggested_canonical_id=entry.suggested_canonical_id,
        created_at=datetime.now(),
    )


def _decision_to_response(d: QueueRouterDecision) -> DecisionResponse:
    return DecisionResponse(
        queue_id=d.queue_id,
        decision=d.decision,
        category_node_id=d.category_node_id,
        brand=d.brand,
        name_core_refined=d.name_core_refined,
        confidence=d.confidence,
        reasons=d.reasons,
        elapsed_ms=d.elapsed_ms,
    )


class _DryRunMockProvider:
    """dry_run=True일 때 사용하는 no-op mock provider."""

    def call(self, *, prompt: str, schema: Any = None) -> dict:
        return {
            "category_node_id": None,
            "brand": None,
            "name_core": None,
            "confidence": 0.0,
            "reasons": ["DRY_RUN: 실제 AI 호출 없음"],
        }


@router.post("/route-batch", response_model=RouteBatchResponse)
async def route_batch(req: RouteBatchRequest):
    """
    ProductReviewQueue 항목 목록을 LLM으로 분류한다.

    dry_run=true: provider 호출 없이 모든 항목을 ESCALATED(DRY_RUN) 처리.
    dry_run=false: WALLETSAVIOR_LIVE_AI=1 환경변수 필요. 실제 Gemini 호출.
    """
    if req.dry_run:
        provider = _DryRunMockProvider()
    else:
        provider = _build_provider()

    tree = _get_category_tree()
    brands = _get_brand_dictionary()
    synonyms = _get_synonyms()

    router_svc = QueueAiRouter(provider, tree, brands, synonyms)
    entries = [_entry_payload_to_dto(e) for e in req.entries]
    decisions = router_svc.route_batch(entries, dry_run_with_mock_provider=req.dry_run)

    resolved = sum(1 for d in decisions if d.decision == "RESOLVED")
    escalated = sum(1 for d in decisions if d.decision == "ESCALATED")

    return RouteBatchResponse(
        total=len(decisions),
        resolved=resolved,
        escalated=escalated,
        decisions=[_decision_to_response(d) for d in decisions],
    )


@router.post("/route-one", response_model=DecisionResponse)
async def route_one(entry: QueueEntryPayload, dry_run: bool = False):
    """단일 ProductReviewQueue 항목을 LLM으로 분류한다."""
    if dry_run:
        provider = _DryRunMockProvider()
    else:
        provider = _build_provider()

    tree = _get_category_tree()
    brands = _get_brand_dictionary()
    synonyms = _get_synonyms()

    router_svc = QueueAiRouter(provider, tree, brands, synonyms)
    dto = _entry_payload_to_dto(entry)
    decision = router_svc.route_one(dto)
    return _decision_to_response(decision)


@router.get("/status")
async def router_status():
    """라우터 상태 조회 (카테고리 트리 크기, 환경 설정 등)."""
    try:
        tree = _get_category_tree()
        valid_ids = _all_category_ids(tree)
        brands = _get_brand_dictionary()
        return {
            "status": "ok",
            "category_node_count": len(valid_ids),
            "brand_count": len(brands),
            "live_ai_enabled": _live_enabled(),
            "confidence_threshold": 0.7,
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc)[:200]}
