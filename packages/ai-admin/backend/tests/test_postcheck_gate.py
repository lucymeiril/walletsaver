"""WalletSavior Phase C2 — PostcheckGate TDD 테스트.

테스트 케이스:
    1.  test_pass_all_gates: 4개 게이트 모두 통과 → PASS
    2.  test_gate1_invalid_tree_id: 트리에 없는 id → ESCALATE(GATE_TREE_INVALID_ID)
    3.  test_gate2_low_confidence: confidence=0.5 → ESCALATE(GATE_LOW_CONFIDENCE)
    4.  test_gate2_vague_reasoning: confidence=0.8 + 모호어 → 패널티로 < 0.7 → ESCALATE(GATE_VAGUE_REASONING)
    5.  test_gate3_sibling_conflict: 새 분류 L1 ≠ sibling 다수파 L1 → ESCALATE(GATE_SIBLING_CATEGORY_CONFLICT)
    6.  test_gate3_no_sibling_pass: sibling 없음(첫 데이터) → PASS
    7.  test_gate3_tie_pass: sibling 동수 → 보수적 PASS
    8.  test_gate4_price_outlier: 가격 1,000,000원 + median 3000 + mad 500 → ESCALATE
    9.  test_gate4_insufficient_sample: 표본 < 10 → Gate4 PASS
    10. test_gate4_no_observation: observation=None → Gate4 PASS
    11. test_multiple_gates_fail: Gate1+Gate2 동시 실패 → ESCALATE(2개 reason)
    12. test_apply_to_db_pass: PASS verdict → DB resolved_at 업데이트 + canonical 카테고리 업데이트
    13. test_apply_to_db_escalate: ESCALATE verdict → resolved_at None 유지 + attributes JSON
    14. test_apply_to_db_idempotency: 동일 verdict 2회 apply → 오류 없음
    15. test_apply_to_db_nonexistent: 없는 queue_id → skipped
    16. test_4mart_fixture_pass: 4마트 fixture → 게이트 통과 회귀 확인
    17. test_check_batch: check_batch 배치 API 동작 확인
    18. test_diagnostics_keys: diagnostics에 필수 키 포함 확인

설계:
    - price_stats_provider / sibling_provider는 명시적 lambda mock 사용.
    - PriceObservation은 canonical_models에서 import해 실제 DTO로 생성.
    - DB는 in-memory SQLite (ai-admin 패키지 독립).
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Optional

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

# ── 경로 보정 ─────────────────────────────────────────────────────────────────
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_SHARED_DIR = _BACKEND_DIR.parent.parent / "shared"
for _p in (str(_SHARED_DIR), str(_BACKEND_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import yaml

from services.queue_ai_router import (
    QueueRouterDecision,
    ApplyResult,
    load_default_category_tree,
)
from services.postcheck_gate import (
    GateVerdict,
    PostcheckGate,
    CONFIDENCE_MIN,
    VAGUE_PENALTY_PER_WORD,
    _RESOLVER_POSTCHECK,
)
from core.canonical_models import (
    MartKind,
    ReviewReason,
    ProductReviewQueue as CanonicalQueueDTO,
    PriceObservation,
    UnitPriceBasis,
)


# ══════════════════════════════════════════════════════
# Fixtures — 공통
# ══════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def category_tree() -> dict:
    return load_default_category_tree()


@pytest.fixture(scope="module")
def valid_ids(category_tree) -> set[str]:
    return {n["id"] for n in category_tree.get("nodes", []) if "id" in n}


def _no_op_price_provider(node_id: str) -> list[int]:
    """표본 없음 → Gate4 PASS."""
    return []


def _no_op_sibling_provider(canonical_id: str) -> list[str]:
    """sibling 없음 → Gate3 PASS."""
    return []


def _make_gate(
    category_tree: dict,
    *,
    price_provider=None,
    sibling_provider=None,
) -> PostcheckGate:
    return PostcheckGate(
        category_tree=category_tree,
        price_stats_provider=price_provider or _no_op_price_provider,
        sibling_provider=sibling_provider or _no_op_sibling_provider,
    )


def _make_decision(
    queue_id: str = "q-001",
    *,
    category_node_id: Optional[str] = "cabbage",
    confidence: float = 0.85,
    reasons: Optional[list[str]] = None,
    decision: str = "RESOLVED",
) -> QueueRouterDecision:
    return QueueRouterDecision(
        queue_id=queue_id,
        decision=decision,  # type: ignore[arg-type]
        category_node_id=category_node_id,
        brand=None,
        name_core_refined="양배추",
        confidence=confidence,
        reasons=reasons if reasons is not None else ["신선식품 엽채류 양배추 분류"],
        raw_ai_response={"category_node_id": category_node_id, "confidence": confidence},
        elapsed_ms=100,
    )


def _make_queue_entry(
    queue_id: str = "q-001",
    *,
    mart: MartKind = MartKind.EMART,
    suggested_canonical_id: Optional[str] = None,
) -> CanonicalQueueDTO:
    return CanonicalQueueDTO(
        id=queue_id,
        raw_payload={"itemName": "양배추 800g", "finalPrice": "2990"},
        source_mart=mart,
        reason=ReviewReason.CATEGORY_UNKNOWN,
        suggested_canonical_id=suggested_canonical_id,
    )


def _make_observation(
    sale_price: int,
    canonical_id: str = "canon-001",
    mart: MartKind = MartKind.EMART,
) -> PriceObservation:
    return PriceObservation(
        id=f"obs-{sale_price}",
        canonical_id=canonical_id,
        mart=mart,
        sale_price=sale_price,
        on_sale=False,
        unit_price_basis=UnitPriceBasis.PER_100G,
        raw_payload_hash="a" * 40,
    )


# ══════════════════════════════════════════════════════
# DB 픽스처 (in-memory SQLite)
# ══════════════════════════════════════════════════════

_CREATE_CANONICAL_PRODUCTS_DDL = """
CREATE TABLE IF NOT EXISTS canonical_products (
    id                          TEXT PRIMARY KEY,
    name_core                   TEXT NOT NULL,
    brand                       TEXT,
    pack_quantity               REAL NOT NULL DEFAULT 1.0,
    pack_unit                   TEXT NOT NULL DEFAULT '개',
    category_path_internal_id   TEXT,
    representative_image_url    TEXT,
    created_at                  DATETIME NOT NULL,
    updated_at                  DATETIME NOT NULL
)
"""

_CREATE_REVIEW_QUEUE_DDL = """
CREATE TABLE IF NOT EXISTS canonical_product_review_queue (
    id                      TEXT PRIMARY KEY,
    raw_payload             TEXT NOT NULL,
    source_mart             TEXT NOT NULL,
    reason                  TEXT NOT NULL,
    suggested_canonical_id  TEXT REFERENCES canonical_products(id),
    attributes              TEXT,
    created_at              DATETIME NOT NULL,
    resolved_at             DATETIME,
    resolver_user_id        TEXT
)
"""


@pytest.fixture
def db_engine():
    engine = create_engine("sqlite:///:memory:", echo=False)
    with engine.connect() as conn:
        conn.execute(text(_CREATE_CANONICAL_PRODUCTS_DDL))
        conn.execute(text(_CREATE_REVIEW_QUEUE_DDL))
        conn.commit()
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine) -> Iterator[Session]:
    SessionFactory = sessionmaker(bind=db_engine)
    with SessionFactory() as session:
        yield session


def _seed_queue_and_canonical(
    session: Session,
    *,
    queue_id: str,
    canonical_id: Optional[str] = None,
    mart: str = "EMART",
) -> None:
    """테스트용 canonical_products + queue 행 삽입."""
    if canonical_id:
        session.execute(
            text(
                "INSERT OR IGNORE INTO canonical_products "
                "(id, name_core, pack_quantity, pack_unit, created_at, updated_at) "
                "VALUES (:id, :name, 1.0, '개', :ca, :ua)"
            ),
            {"id": canonical_id, "name": "테스트상품", "ca": datetime.now(), "ua": datetime.now()},
        )
    session.execute(
        text(
            "INSERT OR IGNORE INTO canonical_product_review_queue "
            "(id, raw_payload, source_mart, reason, suggested_canonical_id, created_at) "
            "VALUES (:id, :raw, :mart, :reason, :cid, :ca)"
        ),
        {
            "id": queue_id,
            "raw": json.dumps({"itemName": "양배추"}),
            "mart": mart,
            "reason": "CATEGORY_UNKNOWN",
            "cid": canonical_id,
            "ca": datetime.now(),
        },
    )
    session.flush()


# ══════════════════════════════════════════════════════
# 테스트 1: 모든 게이트 통과 → PASS
# ══════════════════════════════════════════════════════

def test_pass_all_gates(category_tree):
    """
    트리 valid + confidence 0.85 + sibling 일치 + 가격 정상 → PASS.
    diagnostics에 게이트별 측정값 포함.
    """
    # price_stats_provider: 정상 가격 분포 (median≈3000, mad≈200)
    normal_prices = [2700, 2800, 2900, 3000, 3100, 3200, 3000, 2950, 3050, 2850]

    gate = _make_gate(
        category_tree,
        price_provider=lambda nid: normal_prices,
        sibling_provider=lambda cid: ["cabbage", "cabbage", "leaf_vegetable"],
    )
    decision = _make_decision("q-pass-001", category_node_id="cabbage", confidence=0.85)
    entry = _make_queue_entry("q-pass-001", suggested_canonical_id="canon-001")
    obs = _make_observation(sale_price=2990, canonical_id="canon-001")

    verdict = gate.check(decision, entry, obs)

    assert verdict.verdict == "PASS"
    assert verdict.failed_gates == []
    assert verdict.final_category_node_id == "cabbage"
    assert verdict.confidence_after_gates >= CONFIDENCE_MIN

    # diagnostics 필수 키 확인
    diag = verdict.diagnostics
    assert "tree_valid" in diag
    assert "confidence_raw" in diag
    assert "vague_penalty" in diag
    assert diag["tree_valid"] is True


# ══════════════════════════════════════════════════════
# 테스트 2: Gate 1 실패 — 트리에 없는 id
# ══════════════════════════════════════════════════════

def test_gate1_invalid_tree_id(category_tree):
    """fake/id → ESCALATE, GATE_TREE_INVALID_ID."""
    gate = _make_gate(category_tree)
    decision = _make_decision("q-gate1-001", category_node_id="fake/id/hallucinated")
    entry = _make_queue_entry("q-gate1-001")

    verdict = gate.check(decision, entry, None)

    assert verdict.verdict == "ESCALATE"
    assert "GATE_TREE_INVALID_ID" in verdict.failed_gates
    assert verdict.final_category_node_id is None
    assert verdict.diagnostics["tree_valid"] is False


def test_gate1_none_category_node_id(category_tree):
    """category_node_id=None → ESCALATE, GATE_TREE_INVALID_ID."""
    gate = _make_gate(category_tree)
    decision = _make_decision("q-gate1-002", category_node_id=None)
    entry = _make_queue_entry("q-gate1-002")

    verdict = gate.check(decision, entry, None)

    assert verdict.verdict == "ESCALATE"
    assert "GATE_TREE_INVALID_ID" in verdict.failed_gates


# ══════════════════════════════════════════════════════
# 테스트 3: Gate 2 실패 — 낮은 신뢰도
# ══════════════════════════════════════════════════════

def test_gate2_low_confidence(category_tree):
    """confidence=0.5 → ESCALATE(GATE_LOW_CONFIDENCE)."""
    gate = _make_gate(category_tree)
    decision = _make_decision("q-gate2-low", confidence=0.5)
    entry = _make_queue_entry("q-gate2-low")

    verdict = gate.check(decision, entry, None)

    assert verdict.verdict == "ESCALATE"
    assert "GATE_LOW_CONFIDENCE" in verdict.failed_gates
    assert verdict.diagnostics["confidence_raw"] == 0.5
    assert verdict.confidence_after_gates < CONFIDENCE_MIN


# ══════════════════════════════════════════════════════
# 테스트 4: Gate 2 실패 — 모호어 패널티
# ══════════════════════════════════════════════════════

def test_gate2_vague_reasoning(category_tree):
    """
    confidence=0.8 + 모호어 2개("아마", "인 것 같습니다") → 패널티 0.10 → adjusted=0.70 미만 → ESCALATE.

    계산: penalty = 2 * 0.05 = 0.10, adjusted = 0.80 - 0.10 = 0.70.
    0.70은 임계와 같으므로 < 0.70 조건을 맞추려면 3개 모호어를 사용해야 한다.
    여기서는 3개 모호어("아마", "인 것", "추정")를 사용:
    penalty = 3 * 0.05 = 0.15, adjusted = 0.80 - 0.15 = 0.65 < 0.70 → ESCALATE.
    """
    gate = _make_gate(category_tree)
    decision = _make_decision(
        "q-gate2-vague",
        confidence=0.8,
        reasons=["아마 양배추인 것 같습니다. 추정 기반 분류."],
    )
    entry = _make_queue_entry("q-gate2-vague")

    verdict = gate.check(decision, entry, None)

    assert verdict.verdict == "ESCALATE"
    # vague_penalty가 적용되어 임계 이하로 떨어져야 함
    assert verdict.diagnostics["vague_word_count"] >= 2
    assert verdict.diagnostics["vague_penalty"] > 0
    assert verdict.confidence_after_gates < CONFIDENCE_MIN
    # 원래 confidence는 임계 이상이지만 패널티로 실패
    assert verdict.diagnostics["confidence_raw"] >= CONFIDENCE_MIN


def test_gate2_vague_reason_code(category_tree):
    """모호어 패널티로 실패 시 GATE_VAGUE_REASONING 이유 코드 반환."""
    gate = _make_gate(category_tree)
    decision = _make_decision(
        "q-gate2-vague-code",
        confidence=0.8,
        reasons=["아마 양배추인 것 같습니다. 추정 기반 분류."],
    )
    entry = _make_queue_entry("q-gate2-vague-code")
    verdict = gate.check(decision, entry, None)
    assert "GATE_VAGUE_REASONING" in verdict.failed_gates


# ══════════════════════════════════════════════════════
# 테스트 5: Gate 3 실패 — sibling 카테고리 충돌
# ══════════════════════════════════════════════════════

def test_gate3_sibling_conflict(category_tree):
    """
    새 분류 "bath_tissue"(household L1) vs sibling 다수 "cabbage"(fresh_food L1) → ESCALATE.
    """
    def sibling_provider(cid: str) -> list[str]:
        return ["cabbage", "cabbage", "leaf_vegetable", "vegetable"]  # L1=fresh_food

    gate = _make_gate(category_tree, sibling_provider=sibling_provider)
    decision = _make_decision(
        "q-gate3-001",
        category_node_id="bath_tissue",  # L1=household
        confidence=0.85,
    )
    entry = _make_queue_entry("q-gate3-001", suggested_canonical_id="canon-sibling-001")

    verdict = gate.check(decision, entry, None)

    assert verdict.verdict == "ESCALATE"
    assert "GATE_SIBLING_CATEGORY_CONFLICT" in verdict.failed_gates
    diag = verdict.diagnostics
    assert diag["sibling_majority"] == "fresh_food"
    assert diag["new_l1"] == "household"


def test_gate3_no_sibling_pass(category_tree):
    """sibling 없음(라이브 첫 데이터) → Gate3 PASS."""
    gate = _make_gate(category_tree, sibling_provider=lambda cid: [])
    decision = _make_decision("q-gate3-empty", category_node_id="cabbage", confidence=0.85)
    entry = _make_queue_entry("q-gate3-empty", suggested_canonical_id="canon-new-001")

    verdict = gate.check(decision, entry, None)

    assert verdict.verdict == "PASS"
    assert "GATE_SIBLING_CATEGORY_CONFLICT" not in verdict.failed_gates
    assert verdict.diagnostics["sibling_count"] == 0


def test_gate3_tie_pass(category_tree):
    """sibling 동수 tie → 보수적 PASS (충돌 없음)."""
    def sibling_provider(cid: str) -> list[str]:
        # fresh_food 2개 vs household 2개 → 동수
        return ["cabbage", "vegetable", "bath_tissue", "sanitary"]

    gate = _make_gate(category_tree, sibling_provider=sibling_provider)
    decision = _make_decision("q-gate3-tie", category_node_id="kitchen_towel", confidence=0.85)
    entry = _make_queue_entry("q-gate3-tie", suggested_canonical_id="canon-tie-001")

    verdict = gate.check(decision, entry, None)

    # 동수이면 majority=None → PASS
    assert "GATE_SIBLING_CATEGORY_CONFLICT" not in verdict.failed_gates


def test_gate3_no_canonical_id_pass(category_tree):
    """suggested_canonical_id=None이면 sibling 조회 불가 → Gate3 PASS."""
    gate = _make_gate(category_tree, sibling_provider=lambda cid: ["cabbage"] * 5)
    decision = _make_decision("q-gate3-no-cid", category_node_id="bath_tissue", confidence=0.85)
    entry = _make_queue_entry("q-gate3-no-cid", suggested_canonical_id=None)

    verdict = gate.check(decision, entry, None)

    assert "GATE_SIBLING_CATEGORY_CONFLICT" not in verdict.failed_gates


# ══════════════════════════════════════════════════════
# 테스트 6: Gate 4 실패 — 가격 이상치
# ══════════════════════════════════════════════════════

def test_gate4_price_outlier(category_tree):
    """
    가격 1,000,000원 + median 3000 + mad 500 → ESCALATE(GATE_PRICE_OUTLIER).

    |1,000,000 - 3,000| = 997,000 >> 5 * 500 = 2,500 → outlier.
    """
    # 10개 이상 표본으로 median≈3000, mad≈약500인 분포
    prices = [2500, 2700, 2800, 2900, 3000, 3100, 3200, 3300, 3400, 3500]

    gate = _make_gate(category_tree, price_provider=lambda nid: prices)
    decision = _make_decision("q-gate4-outlier", category_node_id="cabbage", confidence=0.85)
    entry = _make_queue_entry("q-gate4-outlier")
    obs = _make_observation(sale_price=1_000_000)  # 명백한 이상가

    verdict = gate.check(decision, entry, obs)

    assert verdict.verdict == "ESCALATE"
    assert "GATE_PRICE_OUTLIER" in verdict.failed_gates
    diag = verdict.diagnostics
    assert diag["price_observed"] == 1_000_000
    assert diag["price_is_outlier"] is True
    assert "price_median" in diag
    assert "price_mad" in diag


def test_gate4_normal_price_pass(category_tree):
    """가격이 정상 범위 내 → Gate4 PASS."""
    prices = [2500, 2700, 2800, 2900, 3000, 3100, 3200, 3300, 3400, 3500]

    gate = _make_gate(category_tree, price_provider=lambda nid: prices)
    decision = _make_decision("q-gate4-normal", category_node_id="cabbage", confidence=0.85)
    entry = _make_queue_entry("q-gate4-normal")
    obs = _make_observation(sale_price=2990)

    verdict = gate.check(decision, entry, obs)

    assert "GATE_PRICE_OUTLIER" not in verdict.failed_gates
    assert verdict.diagnostics.get("price_is_outlier") is False


def test_gate4_insufficient_sample(category_tree):
    """표본 < 10 → Gate4 PASS (통계 미신뢰)."""
    small_sample = [3000, 3100, 3200]  # 3개 < 10

    gate = _make_gate(category_tree, price_provider=lambda nid: small_sample)
    decision = _make_decision("q-gate4-small-sample", category_node_id="cabbage", confidence=0.85)
    entry = _make_queue_entry("q-gate4-small-sample")
    obs = _make_observation(sale_price=999_999)  # 이상가지만 표본 부족

    verdict = gate.check(decision, entry, obs)

    assert "GATE_PRICE_OUTLIER" not in verdict.failed_gates
    assert verdict.diagnostics.get("price_sanity_skipped") == "insufficient_sample"


def test_gate4_no_observation_pass(category_tree):
    """observation=None → Gate4 PASS."""
    prices = [3000] * 15

    gate = _make_gate(category_tree, price_provider=lambda nid: prices)
    decision = _make_decision("q-gate4-no-obs", category_node_id="cabbage", confidence=0.85)
    entry = _make_queue_entry("q-gate4-no-obs")

    verdict = gate.check(decision, entry, None)

    assert "GATE_PRICE_OUTLIER" not in verdict.failed_gates
    assert verdict.diagnostics.get("price_sanity_skipped") == "no_observation"


# ══════════════════════════════════════════════════════
# 테스트 7: 복합 실패 — 여러 게이트 동시 실패
# ══════════════════════════════════════════════════════

def test_multiple_gates_fail(category_tree):
    """
    Gate1(invalid id) + Gate2(low confidence) 동시 실패.
    failed_gates에 2개 이유 코드 포함.
    """
    gate = _make_gate(category_tree)
    decision = _make_decision(
        "q-multi-fail",
        category_node_id="nonexistent_id_xyz",
        confidence=0.3,
    )
    entry = _make_queue_entry("q-multi-fail")

    verdict = gate.check(decision, entry, None)

    assert verdict.verdict == "ESCALATE"
    assert "GATE_TREE_INVALID_ID" in verdict.failed_gates
    assert "GATE_LOW_CONFIDENCE" in verdict.failed_gates
    assert len(verdict.failed_gates) >= 2


# ══════════════════════════════════════════════════════
# 테스트 8: check_batch
# ══════════════════════════════════════════════════════

def test_check_batch(category_tree):
    """check_batch는 decisions와 같은 수의 verdicts를 반환한다."""
    normal_prices = [2700, 2800, 2900, 3000, 3100, 3200, 3000, 2950, 3050, 2850]
    gate = _make_gate(category_tree, price_provider=lambda nid: normal_prices)

    decisions = [
        _make_decision(f"q-batch-{i}", category_node_id="cabbage", confidence=0.85)
        for i in range(3)
    ]
    entries = [_make_queue_entry(f"q-batch-{i}") for i in range(3)]
    observations = [_make_observation(2990) for _ in range(3)]

    verdicts = gate.check_batch(decisions, entries, observations)

    assert len(verdicts) == 3
    assert all(v.verdict == "PASS" for v in verdicts)


def test_check_batch_length_mismatch(category_tree):
    """decisions/entries/observations 길이 불일치 → ValueError."""
    gate = _make_gate(category_tree)
    decisions = [_make_decision("q-1")]
    entries = [_make_queue_entry("q-1"), _make_queue_entry("q-2")]
    observations = [None]

    with pytest.raises(ValueError, match="길이가 달라야"):
        gate.check_batch(decisions, entries, observations)


# ══════════════════════════════════════════════════════
# 테스트 9: apply_to_db — PASS → DB 업데이트
# ══════════════════════════════════════════════════════

def test_apply_to_db_pass(db_session, category_tree):
    """
    PASS verdict → resolved_at 설정 + canonical 카테고리 업데이트.
    resolver_user_id = "ai:postcheck_v1".
    """
    session = db_session
    queue_id = "q-apply-pass-001"
    canonical_id = "c" * 40

    _seed_queue_and_canonical(session, queue_id=queue_id, canonical_id=canonical_id)

    gate = _make_gate(category_tree)
    verdict = GateVerdict(
        decision_id=queue_id,
        verdict="PASS",
        failed_gates=[],
        diagnostics={"tree_valid": True},
        final_category_node_id="cabbage",
        confidence_after_gates=0.85,
    )

    result = gate.apply_to_db([verdict], session)

    assert result.resolved_count == 1
    assert result.escalated_count == 0
    assert result.errors == []

    # resolved_at 설정 확인
    row = session.execute(
        text("SELECT resolved_at, resolver_user_id FROM canonical_product_review_queue WHERE id = :id"),
        {"id": queue_id},
    ).fetchone()
    assert row[0] is not None, "resolved_at이 설정되어야 함"
    assert row[1] == _RESOLVER_POSTCHECK

    # canonical 카테고리 업데이트 확인
    cat_row = session.execute(
        text("SELECT category_path_internal_id FROM canonical_products WHERE id = :id"),
        {"id": canonical_id},
    ).fetchone()
    assert cat_row[0] == "cabbage"


# ══════════════════════════════════════════════════════
# 테스트 10: apply_to_db — ESCALATE → attributes JSON 갱신
# ══════════════════════════════════════════════════════

def test_apply_to_db_escalate(db_session, category_tree):
    """
    ESCALATE verdict → resolved_at=None 유지 + attributes.escalation_reasons + last_ai_decision.
    """
    session = db_session
    queue_id = "q-apply-escalate-001"

    _seed_queue_and_canonical(session, queue_id=queue_id)

    gate = _make_gate(category_tree)
    verdict = GateVerdict(
        decision_id=queue_id,
        verdict="ESCALATE",
        failed_gates=["GATE_TREE_INVALID_ID", "GATE_LOW_CONFIDENCE"],
        diagnostics={"tree_valid": False, "confidence_raw": 0.5},
        final_category_node_id=None,
        confidence_after_gates=0.5,
    )

    result = gate.apply_to_db([verdict], session)

    assert result.escalated_count == 1
    assert result.resolved_count == 0
    assert result.errors == []

    row = session.execute(
        text("SELECT resolved_at, attributes FROM canonical_product_review_queue WHERE id = :id"),
        {"id": queue_id},
    ).fetchone()

    assert row[0] is None, "ESCALATE 시 resolved_at은 None이어야 함"

    attrs = json.loads(row[1])
    assert "GATE_TREE_INVALID_ID" in attrs["escalation_reasons"]
    assert "GATE_LOW_CONFIDENCE" in attrs["escalation_reasons"]
    assert "last_ai_decision" in attrs


# ══════════════════════════════════════════════════════
# 테스트 11: apply_to_db 멱등성
# ══════════════════════════════════════════════════════

def test_apply_to_db_idempotency(db_session, category_tree):
    """같은 PASS verdict를 두 번 apply해도 오류 없음 (resolved_at 갱신만)."""
    session = db_session
    queue_id = "q-idempotent-001"
    canonical_id = "d" * 40

    _seed_queue_and_canonical(session, queue_id=queue_id, canonical_id=canonical_id)

    gate = _make_gate(category_tree)
    verdict = GateVerdict(
        decision_id=queue_id,
        verdict="PASS",
        failed_gates=[],
        diagnostics={},
        final_category_node_id="egg",
        confidence_after_gates=0.9,
    )

    r1 = gate.apply_to_db([verdict], session)
    r2 = gate.apply_to_db([verdict], session)

    assert r1.errors == []
    assert r2.errors == []
    assert r1.resolved_count == 1
    assert r2.resolved_count == 1


def test_apply_to_db_escalate_idempotency(db_session, category_tree):
    """ESCALATE를 두 번 apply해도 escalation_reasons 중복 없음."""
    session = db_session
    queue_id = "q-escalate-idem-001"

    _seed_queue_and_canonical(session, queue_id=queue_id)

    gate = _make_gate(category_tree)
    verdict = GateVerdict(
        decision_id=queue_id,
        verdict="ESCALATE",
        failed_gates=["GATE_PRICE_OUTLIER"],
        diagnostics={"price_is_outlier": True},
        final_category_node_id=None,
        confidence_after_gates=0.85,
    )

    gate.apply_to_db([verdict], session)
    gate.apply_to_db([verdict], session)  # 두 번째 적용

    row = session.execute(
        text("SELECT attributes FROM canonical_product_review_queue WHERE id = :id"),
        {"id": queue_id},
    ).fetchone()
    attrs = json.loads(row[0])
    # 중복 없이 1개만 있어야 함
    assert attrs["escalation_reasons"].count("GATE_PRICE_OUTLIER") == 1


def test_apply_to_db_nonexistent_queue(db_session, category_tree):
    """존재하지 않는 queue_id → skipped_count 증가, 오류 없음."""
    gate = _make_gate(category_tree)
    verdict = GateVerdict(
        decision_id="nonexistent-queue-xyz",
        verdict="PASS",
        failed_gates=[],
        diagnostics={},
        final_category_node_id="cabbage",
        confidence_after_gates=0.9,
    )

    result = gate.apply_to_db([verdict], db_session)

    assert result.skipped_count == 1
    assert result.resolved_count == 0
    assert result.errors == []


# ══════════════════════════════════════════════════════
# 테스트 12: diagnostics 필수 키 확인
# ══════════════════════════════════════════════════════

def test_diagnostics_keys_present(category_tree):
    """PASS/ESCALATE 모두 diagnostics에 게이트별 측정값 포함."""
    normal_prices = [2700, 2800, 2900, 3000, 3100, 3200, 3000, 2950, 3050, 2850]
    gate = _make_gate(
        category_tree,
        price_provider=lambda nid: normal_prices,
        sibling_provider=lambda cid: ["cabbage", "leaf_vegetable"],
    )
    decision = _make_decision("q-diag-001", category_node_id="cabbage", confidence=0.85)
    entry = _make_queue_entry("q-diag-001", suggested_canonical_id="canon-diag-001")
    obs = _make_observation(2990)

    verdict = gate.check(decision, entry, obs)
    diag = verdict.diagnostics

    required_keys = [
        "tree_valid", "tree_node_id",
        "confidence_raw", "vague_word_count", "vague_penalty", "confidence_adjusted",
        "sibling_count",
        "price_sample_size",
    ]
    for key in required_keys:
        assert key in diag, f"diagnostics에 '{key}' 키 누락"


# ══════════════════════════════════════════════════════
# 테스트 13: 4마트 fixture 회귀
# ══════════════════════════════════════════════════════

def test_4mart_fixture_all_pass(category_tree):
    """
    이마트·홈플러스·롯데마트·코스트코 4마트 대표 상품 각 1건씩
    유효한 결정으로 게이트 통과 확인.

    각 마트에서 대표 상품:
        EMART: 양배추 → cabbage (가격대 ~3000원)
        HOMEPLUS: 계란 → egg (가격대 ~5000원)
        LOTTEMART: 두부 → tofu (가격대 ~2000원)
        COSTCO: 화장지 → bath_tissue (가격대 ~30000원)

    price_stats_provider는 카테고리별 명시적 mock — 각 카테고리에 맞는 가격 분포 반환.
    """
    # 카테고리별 명시적 가격 통계 mock (각 카테고리에 적합한 분포)
    category_price_map: dict[str, list[int]] = {
        "cabbage":     [2500, 2700, 2800, 2900, 2990, 3000, 3100, 3200, 3300, 3400],
        "egg":         [4500, 4700, 4800, 4900, 4990, 5000, 5100, 5200, 5300, 5400],
        "tofu":        [1700, 1800, 1900, 1990, 2000, 2100, 2200, 2300, 2400, 2500],
        "bath_tissue": [27000, 28000, 29000, 29900, 30000, 31000, 32000, 33000, 34000, 35000],
    }

    def price_provider(nid: str) -> list[int]:
        return category_price_map.get(nid, [])

    gate = _make_gate(
        category_tree,
        price_provider=price_provider,
        sibling_provider=lambda cid: [],  # 첫 데이터 → Gate3 PASS
    )

    fixtures = [
        (MartKind.EMART,     "cabbage",    2990,  "이마트 양배추"),
        (MartKind.HOMEPLUS,  "egg",        4990,  "홈플러스 계란"),
        (MartKind.LOTTEMART, "tofu",       1990,  "롯데마트 두부"),
        (MartKind.COSTCO,    "bath_tissue", 29900, "코스트코 화장지"),
    ]

    for mart, cat_node, price, label in fixtures:
        qid = f"q-4mart-{mart.value}"
        decision = _make_decision(qid, category_node_id=cat_node, confidence=0.88)
        entry = _make_queue_entry(qid, mart=mart, suggested_canonical_id=f"canon-{mart.value}")
        obs = _make_observation(sale_price=price, mart=mart)

        verdict = gate.check(decision, entry, obs)

        assert verdict.verdict == "PASS", (
            f"{label}({cat_node}) 게이트 실패: {verdict.failed_gates}"
        )
        assert verdict.final_category_node_id == cat_node


def test_emart_fixture_from_file(category_tree):
    """
    이마트 fixture 파일 존재 시 — Queue 엔트리 생성 후 PostcheckGate PASS 회귀.
    fixture 없으면 skip.
    """
    fixture_path = (
        Path(__file__).resolve().parents[3]
        / "crawler-admin" / "backend" / "tests" / "fixtures" / "emart"
    )
    if not fixture_path.exists():
        pytest.skip(f"이마트 fixture 없음: {fixture_path}")

    import json as _json
    files = list(fixture_path.glob("*.json"))
    if not files:
        pytest.skip("이마트 fixture JSON 없음")

    raw_items: list[dict] = []
    for f in files[:1]:
        try:
            with open(f, encoding="utf-8") as fp:
                data = _json.load(fp)
            queries = (
                data.get("props", {})
                    .get("pageProps", {})
                    .get("dehydratedState", {})
                    .get("queries", [])
            )
            for q in queries:
                for area in q.get("state", {}).get("data", {}).get("areaList", []):
                    raw_items.extend(area.get("dataList", []))
        except Exception:
            pass

    if not raw_items:
        pytest.skip("이마트 fixture item 없음")

    # 이마트 fixture 가격은 다양하므로 통계 없음(표본 부족) → Gate4 PASS.
    # 가짜 단일 통계로 우격다짐 통과 금지 — 명시적으로 표본 없음 반환.
    gate = _make_gate(category_tree, price_provider=lambda nid: [])

    from core.product_canonicalize import canonicalize_emart  # type: ignore

    for item in raw_items[:3]:
        result = canonicalize_emart(item, datetime.now())
        if result.queue_entry is None:
            continue

        qe = result.queue_entry
        decision = _make_decision(
            qe.id,
            category_node_id="cabbage",
            confidence=0.88,
        )
        obs = _make_observation(int(str(item.get("finalPrice", "3000")).replace(",", "") or 3000))
        verdict = gate.check(decision, qe, obs)

        # fixture를 유효한 결정으로 처리 시 반드시 PASS이어야 함
        assert verdict.verdict == "PASS", f"fixture {qe.id} FAIL: {verdict.failed_gates}"
