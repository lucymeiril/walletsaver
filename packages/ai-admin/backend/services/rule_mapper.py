"""§3-D rule_mapper — match-table-first, AI-fallback flow.

The non-conversational rule layer:

   1. Look up the raw_record's normalized signature in `ProductMatch` (the
      match table). If we find an *active* row → return it as `match_table_hit`.
   2. Otherwise hand the row to the `ModelRouter` (LLM or OSS stub) and return
      its decision as `ai_fallback`.

This module deliberately stays small. Heavy postcheck/gating happens elsewhere
(`postcheck_gate.py`); we only decide *which path* a row takes and emit a
monitoring counter the MatchMonitor panel can plot.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy.orm import Session

from core.contracts.control_plane import (  # type: ignore
    normalize_product_signature_key,
)
from storage.models import ProductMatch

from .model_router import ModelRequest, ModelResponse, ModelRouter, get_default_router


@dataclass
class RuleMapperResult:
    path: str  # "match_table_hit" | "ai_fallback"
    match: Optional[dict[str, Any]] = None
    ai_response: Optional[ModelResponse] = None
    signature_key: str = ""
    notes: str = ""


@dataclass
class RuleMapperStats:
    """Process-local counters for the MatchMonitor panel."""
    match_table_hits: int = 0
    ai_fallback_calls: int = 0
    ai_fallback_live: int = 0
    ai_fallback_oss: int = 0
    last_path_per_source: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_table_hits": self.match_table_hits,
            "ai_fallback_calls": self.ai_fallback_calls,
            "ai_fallback_live": self.ai_fallback_live,
            "ai_fallback_oss": self.ai_fallback_oss,
            "last_path_per_source": dict(self.last_path_per_source),
        }


_STATS = RuleMapperStats()
_STATS_LOCK = threading.Lock()


def get_stats() -> RuleMapperStats:
    return _STATS


def reset_stats() -> None:
    global _STATS
    _STATS = RuleMapperStats()


def record_rule_hit(source_name: str, raw_title: str = "") -> None:
    """Increment match_table_hits for a hit resolved outside map_row().

    Called by the AI ingestion pipeline's product_match_precheck() when it
    finds a human-approved ProductMatch without going through map_row() itself.
    Emits telemetry identical to a map_row match_table_hit so the MatchMonitor
    panel shows a unified counter.
    """
    with _STATS_LOCK:
        _STATS.match_table_hits += 1
        _STATS.last_path_per_source[source_name] = "rule_hit"


def map_row(
    session: Session,
    *,
    source_name: str,
    raw_title: str,
    raw_payload: Optional[dict[str, Any]] = None,
    router: Optional[ModelRouter] = None,
) -> RuleMapperResult:
    """Try match table first, AI fallback otherwise."""
    signature_key = normalize_product_signature_key(raw_title)
    hit = (
        session.query(ProductMatch)
        .filter(ProductMatch.source_name == source_name)
        .filter(ProductMatch.signature_key == signature_key)
        .filter(ProductMatch.is_active.is_(True))
        .order_by(ProductMatch.updated_at.desc())
        .first()
    )
    if hit is not None:
        with _STATS_LOCK:
            _STATS.match_table_hits += 1
            _STATS.last_path_per_source[source_name] = "match_table_hit"
        return RuleMapperResult(
            path="match_table_hit",
            match={
                "match_id": hit.match_id,
                "canonical_product_id": hit.canonical_product_id,
                "category_id": hit.category_id,
                "confidence": hit.confidence,
            },
            signature_key=signature_key,
        )

    router = router or get_default_router()
    request = ModelRequest(
        prompt=_build_classification_prompt(raw_title, source_name),
        schema={
            "type": "object",
            "properties": {
                "category_id": {"type": "string"},
                "confidence": {"type": "number"},
                "reason": {"type": "string"},
            },
            "required": ["category_id"],
        },
        call_purpose="rule_mapper.ai_fallback",
        meta={"source_name": source_name},
    )
    response = router.generate(request)
    with _STATS_LOCK:
        _STATS.ai_fallback_calls += 1
        if response.is_live:
            _STATS.ai_fallback_live += 1
        else:
            _STATS.ai_fallback_oss += 1
        _STATS.last_path_per_source[source_name] = "ai_fallback"
    return RuleMapperResult(
        path="ai_fallback",
        ai_response=response,
        signature_key=signature_key,
    )


def _build_classification_prompt(raw_title: str, source_name: str) -> str:
    return (
        "다음은 한국 마트 상품명입니다. WalletSavior 카테고리 트리에서 "
        "가장 적합한 category_id를 JSON으로 반환하세요.\n"
        f"source: {source_name}\nraw_title: {raw_title}"
    )
