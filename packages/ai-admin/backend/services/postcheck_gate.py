"""WalletSavior Phase C2 — 사후 검증 게이트 (PostcheckGate).

역할:
    C1 QueueAiRouter의 QueueRouterDecision을 4가지 게이트로 검증한다.
    4개 모두 통과해야 PASS → DB에 카테고리 확정.
    하나라도 실패하면 ESCALATE → escalation 큐로 이동.

게이트 설계 근거:
    Gate 1 TREE_VALID_ID:
        LLM이 환각으로 트리에 없는 id를 생성할 수 있다.
        C1에서도 걸러지지만 C2는 독립 방어선이다.

    Gate 2 CONFIDENCE_THRESHOLD:
        임계 0.7 — C1과 동일한 기준이지만 C2는 추가로 reasons 모호어 패널티를 적용한다.
        모호어 사전("아마", "추정", "것 같", "같습니다", "어쩌면", "불확실", "가능성"):
            LLM이 confidence=0.85를 보고해도 reason 문구에 모호어가 많으면
            실제 불확실도가 더 높다고 판단한다.
            패널티 = 모호어 등장 횟수 × 0.05 (상한 0.20).
            설계 이유: 과도한 패널티를 방지하면서 "아마 ... 인 것 같습니다" 같은
            2개 이상 모호어 문장은 반드시 임계 이하로 끌어내린다.

    Gate 3 SIBLING_CONSISTENCY:
        같은 canonical_id의 다른 마트 항목들이 이미 분류된 카테고리와 L1 대분류가
        충돌하면 의심 — "fresh_food 상품이 household로 분류?" 같은 케이스를 걸러낸다.
        비교 기준은 L1(level-1 조상): 트리를 역추적해 루트 노드 id를 구한다.
        다수파(majority) 기준: sibling 중 가장 많은 L1이 다수파.
        동수(tie)이면 아무것도 FAIL하지 않는다 (보수적 운영).

    Gate 4 PRICE_SANITY:
        |price - median| > 5 * MAD(median absolute deviation) → 이상가.
        MAD는 이상치에 강건한 산포 지표 (IQR보다 더 보수적).
        5σ 기준 선정 이유: 정상 상품 가격은 매우 높은 이상치 없이 분포하므로
        3σ는 정상 범위 과도 배제 가능성이 있고, 5σ는 명백한 이상가만 걸러낸다.
        표본 < 10이면 통계적으로 의미 없으므로 PASS.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any, Callable, Literal, Optional

# ── 경로 보정 ─────────────────────────────────────────────────────────────────
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_SHARED_DIR = _BACKEND_DIR.parent.parent / "shared"
for _p in (str(_BACKEND_DIR), str(_SHARED_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core.canonical_models import (  # noqa: E402
    PriceObservation,
    ProductReviewQueue,
)
from services.queue_ai_router import ApplyResult, QueueRouterDecision  # noqa: E402


# ══════════════════════════════════════════════════════
# 상수 · 설정
# ══════════════════════════════════════════════════════

CONFIDENCE_MIN: float = 0.7
"""임계 이하면 GATE_LOW_CONFIDENCE."""

VAGUE_PENALTY_PER_WORD: float = 0.05
"""모호어 1개당 패널티 (신뢰도에서 차감)."""

VAGUE_PENALTY_MAX: float = 0.20
"""모호어 패널티 상한."""

PRICE_OUTLIER_MAD_MULTIPLIER: float = 5.0
"""|price - median| > k * MAD이면 이상가. k=5."""

PRICE_MIN_SAMPLE_SIZE: int = 10
"""이 이하이면 통계 미신뢰 → Gate 4 PASS."""

_RESOLVER_POSTCHECK = "ai:postcheck_v1"

# 모호어 사전 (소문자 매칭)
_VAGUE_WORDS: tuple[str, ...] = (
    "아마",
    "추정",
    "것 같",
    "같습니다",
    "어쩌면",
    "불확실",
    "가능성",
    "인 것",
    "인듯",
    "인 듯",
    "unclear",
    "uncertain",
    "possibly",
    "probably",
    "maybe",
)


# ══════════════════════════════════════════════════════
# DTO
# ══════════════════════════════════════════════════════

@dataclass
class GateVerdict:
    """
    단일 QueueRouterDecision에 대한 C2 게이트 검증 결과.

    decision_id: 입력 QueueRouterDecision.queue_id
    verdict: PASS 또는 ESCALATE
    failed_gates: 실패한 게이트 reason 코드 목록 (PASS면 빈 리스트)
    diagnostics: 게이트별 측정값 (debug/audit용)
    final_category_node_id: PASS 시 확정 카테고리 id; ESCALATE 시 None
    confidence_after_gates: 모호어 패널티 적용 후 최종 신뢰도
    """

    decision_id: str
    verdict: Literal["PASS", "ESCALATE"]
    failed_gates: list[str] = field(default_factory=list)
    diagnostics: dict = field(default_factory=dict)
    final_category_node_id: Optional[str] = None
    confidence_after_gates: float = 0.0


# ══════════════════════════════════════════════════════
# 내부 유틸
# ══════════════════════════════════════════════════════

def _build_id_set(category_tree: dict) -> set[str]:
    """category_tree dict에서 모든 유효 노드 id를 추출."""
    return {n["id"] for n in category_tree.get("nodes", []) if "id" in n}


def _build_parent_map(category_tree: dict) -> dict[str, Optional[str]]:
    """id → parent_id 매핑 (루트는 None)."""
    return {
        n["id"]: n.get("parent_id") or None
        for n in category_tree.get("nodes", [])
        if "id" in n
    }


def _root_ancestor(node_id: str, parent_map: dict[str, Optional[str]]) -> str:
    """
    주어진 노드의 L1 조상(루트)을 반환한다.
    트리에 없는 노드이면 그대로 반환.
    """
    current = node_id
    seen: set[str] = set()
    while True:
        parent = parent_map.get(current)
        if parent is None:
            return current
        if parent in seen:
            return current  # 순환 방지
        seen.add(current)
        current = parent


def _count_vague_words(texts: list[str]) -> int:
    """reasons 목록에서 모호어 등장 총 횟수를 반환."""
    combined = " ".join(texts).lower()
    return sum(1 for w in _VAGUE_WORDS if w in combined)


def _majority_l1(l1_ids: list[str]) -> Optional[str]:
    """
    L1 id 목록에서 최다 빈도 항목을 반환한다.
    동수(tie)이면 None (보수적 운영 — 동수 충돌은 PASS).
    """
    if not l1_ids:
        return None
    from collections import Counter
    counts = Counter(l1_ids)
    top = counts.most_common(2)
    if len(top) == 1:
        return top[0][0]
    if top[0][1] > top[1][1]:
        return top[0][0]
    return None  # 동수 → 보수적으로 None (PASS)


def _mad(values: list[float]) -> float:
    """
    Median Absolute Deviation.
    MAD = median(|xi - median(x)|)
    """
    if not values:
        return 0.0
    m = median(values)
    deviations = [abs(v - m) for v in values]
    return median(deviations)


# ══════════════════════════════════════════════════════
# PostcheckGate
# ══════════════════════════════════════════════════════

class PostcheckGate:
    """
    C1 QueueRouterDecision을 4개 게이트로 검증하는 C2 사후 검증기.

    Args:
        category_tree: category_tree.yaml을 yaml.safe_load한 dict.
        price_stats_provider: (category_node_id: str) -> list[int]
            해당 카테고리의 PriceObservation.sale_price 목록.
            표본 < 10이면 빈 리스트 또는 10개 미만 목록 반환.
        sibling_provider: (canonical_id: str) -> list[str]
            해당 canonical_id로 묶인 다른 마트 항목의 현재 category_node_id 목록.
            첫 데이터이면 빈 리스트 반환.
        confidence_min: Gate 2의 신뢰도 하한선. 기본값은 CONFIDENCE_MIN(0.7).
            ThresholdCalibration DB에서 읽은 값으로 재정의 가능.
    """

    def __init__(
        self,
        category_tree: dict,
        price_stats_provider: Callable[[str], list[int]],
        sibling_provider: Callable[[str], list[str]],
        confidence_min: float = CONFIDENCE_MIN,
    ) -> None:
        self._category_tree = category_tree
        self._valid_ids: set[str] = _build_id_set(category_tree)
        self._parent_map: dict[str, Optional[str]] = _build_parent_map(category_tree)
        self._price_stats_provider = price_stats_provider
        self._sibling_provider = sibling_provider
        self._confidence_min = confidence_min

    @classmethod
    def create_with_thresholds(
        cls,
        session,
        category_tree: dict,
        price_stats_provider: Callable[[str], list[int]],
        sibling_provider: Callable[[str], list[str]],
    ) -> "PostcheckGate":
        """Factory that reads `confidence_min` from ThresholdCalibration DB.

        Falls back to CONFIDENCE_MIN if no calibrated value exists.
        """
        from services.threshold_calibrator import get_active_threshold, DEFAULT_CONFIDENCE_MIN
        confidence_min = get_active_threshold(session, "confidence_min", DEFAULT_CONFIDENCE_MIN)
        return cls(
            category_tree,
            price_stats_provider,
            sibling_provider,
            confidence_min=confidence_min,
        )

    # ── 개별 게이트 ───────────────────────────────────────────────────────

    def _gate1_tree_valid_id(
        self,
        decision: QueueRouterDecision,
        diag: dict,
    ) -> Optional[str]:
        """Gate 1: category_node_id가 트리에 실재하는지."""
        node_id = decision.category_node_id
        valid = bool(node_id and node_id in self._valid_ids)
        diag["tree_valid"] = valid
        diag["tree_node_id"] = node_id
        if not valid:
            return "GATE_TREE_INVALID_ID"
        return None

    def _gate2_confidence(
        self,
        decision: QueueRouterDecision,
        diag: dict,
    ) -> tuple[float, Optional[str]]:
        """
        Gate 2: 신뢰도 + 모호어 패널티.

        Returns:
            (confidence_after, fail_reason | None)
        """
        raw_conf = decision.confidence
        vague_count = _count_vague_words(decision.reasons)
        penalty = min(vague_count * VAGUE_PENALTY_PER_WORD, VAGUE_PENALTY_MAX)
        adjusted = raw_conf - penalty

        diag["confidence_raw"] = raw_conf
        diag["vague_word_count"] = vague_count
        diag["vague_penalty"] = penalty
        diag["confidence_adjusted"] = adjusted

        if adjusted < self._confidence_min:
            if vague_count > 0 and raw_conf >= self._confidence_min:
                return adjusted, "GATE_VAGUE_REASONING"
            return adjusted, "GATE_LOW_CONFIDENCE"
        return adjusted, None

    def _gate3_sibling_consistency(
        self,
        decision: QueueRouterDecision,
        queue_entry: ProductReviewQueue,
        diag: dict,
    ) -> Optional[str]:
        """Gate 3: sibling 카테고리 L1 다수파와 충돌하지 않는지."""
        canonical_id = queue_entry.suggested_canonical_id
        if not canonical_id:
            diag["sibling_majority"] = None
            diag["sibling_count"] = 0
            return None

        sibling_nodes: list[str] = self._sibling_provider(canonical_id)
        diag["sibling_count"] = len(sibling_nodes)

        if not sibling_nodes:
            diag["sibling_majority"] = None
            return None

        sibling_l1s = [_root_ancestor(sid, self._parent_map) for sid in sibling_nodes]
        majority = _majority_l1(sibling_l1s)
        diag["sibling_majority"] = majority

        if majority is None:
            return None  # 동수 → 보수적 PASS

        new_l1 = _root_ancestor(decision.category_node_id or "", self._parent_map)
        diag["new_l1"] = new_l1

        if new_l1 != majority:
            return "GATE_SIBLING_CATEGORY_CONFLICT"
        return None

    def _gate4_price_sanity(
        self,
        decision: QueueRouterDecision,
        observation: Optional[PriceObservation],
        diag: dict,
    ) -> Optional[str]:
        """Gate 4: 현재 관측 가격이 카테고리 통계 정상 범위 내인지."""
        if observation is None:
            diag["price_sanity_skipped"] = "no_observation"
            return None

        if not decision.category_node_id:
            diag["price_sanity_skipped"] = "no_category_node_id"
            return None

        prices: list[int] = self._price_stats_provider(decision.category_node_id)
        diag["price_sample_size"] = len(prices)

        if len(prices) < PRICE_MIN_SAMPLE_SIZE:
            diag["price_sanity_skipped"] = "insufficient_sample"
            return None

        price_median = median(prices)
        price_mad = _mad([float(p) for p in prices])
        observed = float(observation.sale_price)

        diag["price_median"] = price_median
        diag["price_mad"] = price_mad
        diag["price_observed"] = observed

        if price_mad == 0.0:
            # MAD=0: 모든 가격이 동일 → 현재 가격이 달라도 매우 큰 차이만 이상
            is_outlier = abs(observed - price_median) > price_median * 0.5
        else:
            is_outlier = abs(observed - price_median) > PRICE_OUTLIER_MAD_MULTIPLIER * price_mad

        diag["price_is_outlier"] = is_outlier

        if is_outlier:
            return "GATE_PRICE_OUTLIER"
        return None

    # ── 공개 API ──────────────────────────────────────────────────────────

    def check(
        self,
        decision: QueueRouterDecision,
        queue_entry: ProductReviewQueue,
        observation: Optional[PriceObservation] = None,
    ) -> GateVerdict:
        """
        단일 QueueRouterDecision을 4개 게이트로 검증한다.

        Args:
            decision: C1 QueueAiRouter의 결정.
            queue_entry: 대응하는 ProductReviewQueue 항목.
            observation: 가격 이상 탐지용 PriceObservation (없으면 Gate 4 PASS).

        Returns:
            GateVerdict (verdict = "PASS" | "ESCALATE").
        """
        diag: dict[str, Any] = {}
        failed: list[str] = []

        # Gate 1
        fail1 = self._gate1_tree_valid_id(decision, diag)
        if fail1:
            failed.append(fail1)

        # Gate 2
        conf_after, fail2 = self._gate2_confidence(decision, diag)
        if fail2:
            failed.append(fail2)

        # Gate 3
        fail3 = self._gate3_sibling_consistency(decision, queue_entry, diag)
        if fail3:
            failed.append(fail3)

        # Gate 4
        fail4 = self._gate4_price_sanity(decision, observation, diag)
        if fail4:
            failed.append(fail4)

        verdict: Literal["PASS", "ESCALATE"] = "PASS" if not failed else "ESCALATE"
        final_node = decision.category_node_id if verdict == "PASS" else None

        return GateVerdict(
            decision_id=decision.queue_id,
            verdict=verdict,
            failed_gates=failed,
            diagnostics=diag,
            final_category_node_id=final_node,
            confidence_after_gates=conf_after,
        )

    def check_batch(
        self,
        decisions: list[QueueRouterDecision],
        entries: list[ProductReviewQueue],
        observations: list[Optional[PriceObservation]],
    ) -> list[GateVerdict]:
        """배치 검증 — 순차 처리."""
        if len(decisions) != len(entries) or len(decisions) != len(observations):
            raise ValueError(
                f"decisions({len(decisions)}), entries({len(entries)}), "
                f"observations({len(observations)}) 길이가 달라야 함"
            )
        return [
            self.check(d, e, o)
            for d, e, o in zip(decisions, entries, observations)
        ]

    def apply_to_db(
        self,
        verdicts: list[GateVerdict],
        session: Any,
    ) -> ApplyResult:
        """
        GateVerdict 목록을 DB에 반영한다.

        PASS:
            - canonical_product_review_queue.resolved_at = now
            - canonical_product_review_queue.resolver_user_id = "ai:postcheck_v1"
            - canonical_products.category_path_internal_id = final_category_node_id

        ESCALATE:
            - resolved_at 유지 (None)
            - attributes JSON의 escalation_reasons[]에 failed_gates append
            - attributes JSON의 last_ai_decision에 diagnostics 보존
            - escalation_reasons 컬럼이 있으면 직접 갱신 (없으면 attributes JSON에)

        멱등:
            같은 verdict를 두 번 apply해도 오류 없음.
            PASS를 두 번 → resolved_at 갱신만.
            ESCALATE를 두 번 → escalation_reasons 중복 없이 추가.
        """
        from sqlalchemy import text  # 이미 sqlalchemy 의존성 있음

        result = ApplyResult()
        now = datetime.now()

        for verdict in verdicts:
            try:
                row = session.execute(
                    text(
                        "SELECT id, suggested_canonical_id, attributes "
                        "FROM canonical_product_review_queue WHERE id = :id"
                    ),
                    {"id": verdict.decision_id},
                ).fetchone()

                if row is None:
                    result.skipped_count += 1
                    continue

                _qid, suggested_canonical_id, raw_attrs = row[0], row[1], row[2]

                if verdict.verdict == "PASS":
                    session.execute(
                        text(
                            "UPDATE canonical_product_review_queue "
                            "SET resolved_at = :now, resolver_user_id = :uid "
                            "WHERE id = :id"
                        ),
                        {"now": now, "uid": _RESOLVER_POSTCHECK, "id": verdict.decision_id},
                    )
                    if suggested_canonical_id and verdict.final_category_node_id:
                        session.execute(
                            text(
                                "UPDATE canonical_products "
                                "SET category_path_internal_id = :cat_id, updated_at = :now "
                                "WHERE id = :id"
                            ),
                            {
                                "cat_id": verdict.final_category_node_id,
                                "now": now,
                                "id": suggested_canonical_id,
                            },
                        )
                    result.resolved_count += 1

                else:  # ESCALATE
                    # attributes JSON 파싱 (없으면 빈 dict)
                    try:
                        attrs: dict = json.loads(raw_attrs) if raw_attrs else {}
                    except (json.JSONDecodeError, TypeError):
                        attrs = {}

                    # escalation_reasons 중복 없이 append
                    existing: list[str] = attrs.get("escalation_reasons", [])
                    for reason in verdict.failed_gates:
                        if reason not in existing:
                            existing.append(reason)
                    attrs["escalation_reasons"] = existing
                    attrs["last_ai_decision"] = verdict.diagnostics

                    session.execute(
                        text(
                            "UPDATE canonical_product_review_queue "
                            "SET attributes = :attrs "
                            "WHERE id = :id"
                        ),
                        {
                            "attrs": json.dumps(attrs, ensure_ascii=False),
                            "id": verdict.decision_id,
                        },
                    )
                    result.escalated_count += 1

            except Exception as exc:
                result.errors.append(
                    {
                        "decision_id": verdict.decision_id,
                        "error": type(exc).__name__,
                        "message": str(exc)[:300],
                    }
                )

        return result
