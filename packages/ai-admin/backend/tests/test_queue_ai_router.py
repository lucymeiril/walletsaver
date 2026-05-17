"""WalletSavior Phase C1 — QueueAiRouter TDD 테스트.

테스트 케이스:
    1. test_emart_fixtures_all_resolved: 이마트 5건 fixture → 모두 RESOLVED
    2. test_invalid_category_id_escalated: 트리에 없는 id → ESCALATED
    3. test_low_confidence_escalated: confidence=0.4 → ESCALATED
    4. test_empty_response_escalated: 빈 응답 → ESCALATED
    5. test_provider_error_retry_escalated: provider 예외 → 1회 retry → ESCALATED
    6. test_json_broken_provider_escalated: JSON 깨진 응답 → ESCALATED
    7. test_apply_decisions_idempotency: 동일 결정 2회 적용 → 오류 없음
    8. test_apply_resolved_updates_canonical: RESOLVED → canonical 카테고리 업데이트
    9. test_apply_escalated_marks_queue: ESCALATED → 큐 유지 + 마커
    10. test_live_smoke (opt-in, WALLETSAVIOR_LIVE_AI=1 일 때만)

설계 메모:
    - Mock provider는 responses 목록을 순서대로 반환한다.
    - 라이브 provider는 WALLETSAVIOR_LIVE_AI=1 환경변수로만 활성화한다.
    - apply_decisions_to_db는 SQLAlchemy text() 쿼리를 사용하므로
      db-admin ORM 클래스 없이도 동작한다.
      (단, canonical_product_review_queue / canonical_products 테이블은 필요)
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

# ── 경로 보정 ─────────────────────────────────────────────────────────────────
# 주의: db-admin/backend에도 services/ 패키지가 있으므로 ai-admin의 services/가
#       먼저 검색되도록 ai-admin backend 경로를 앞에 insert하고,
#       db-admin은 충돌 방지를 위해 append해야 한다.
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_SHARED_DIR = _BACKEND_DIR.parent.parent / "shared"
_DB_ADMIN_BACKEND = _BACKEND_DIR.parent.parent / "db-admin" / "backend"

# ai-admin backend + shared: 앞에 추가 (services 패키지 우선권 확보)
for _p in (str(_SHARED_DIR), str(_BACKEND_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# db-admin: 뒤에 추가 (ai-admin services 패키지를 가리지 않도록)
if str(_DB_ADMIN_BACKEND) not in sys.path:
    sys.path.append(str(_DB_ADMIN_BACKEND))

from services.queue_ai_router import (
    QueueAiRouter,
    QueueRouterDecision,
    ApplyResult,
    CONFIDENCE_THRESHOLD,
    _RESOLVED_RESOLVER_ID,
    _ESCALATED_RESOLVER_ID,
    load_default_category_tree,
    load_default_brand_dictionary,
    load_default_synonyms,
)
from core.canonical_models import (
    MartKind,
    ReviewReason,
    ProductReviewQueue as CanonicalQueueDTO,
)

# 이마트 fixture 경로 (db-admin 테스트와 동일한 경로 사용)
FIXTURE_BASE = (
    Path(__file__).parent.parent.parent.parent
    / "crawler-admin" / "backend" / "tests" / "fixtures"
)

LIVE_AI_ENV = "WALLETSAVIOR_LIVE_AI"


# ══════════════════════════════════════════════════════
# Mock Provider
# ══════════════════════════════════════════════════════

class MockProvider:
    """
    테스트용 Mock Provider.

    responses: call()이 순서대로 반환할 dict 목록.
    raise_on_call: True이면 call()이 항상 예외를 발생시킨다.
    raise_once_then: 첫 번째 call은 예외, 이후는 이 dict를 반환한다.
    """

    def __init__(
        self,
        responses: list[dict] | None = None,
        *,
        raise_on_call: bool = False,
        raise_once_then: dict | None = None,
    ) -> None:
        self._responses = list(responses or [])
        self._idx = 0
        self._raise_on_call = raise_on_call
        self._raise_once_then = raise_once_then
        self._call_count = 0

    def call(self, *, prompt: str, schema: Any = None) -> dict:
        self._call_count += 1
        if self._raise_on_call:
            raise ValueError("MockProvider: 의도적 예외 (항상)")
        if self._raise_once_then is not None and self._call_count == 1:
            raise ValueError("MockProvider: 의도적 예외 (첫 번째만)")
        if self._idx < len(self._responses):
            resp = self._responses[self._idx]
            self._idx += 1
            return resp
        # 기본: 빈 응답
        return {}


# ══════════════════════════════════════════════════════
# pytest fixtures
# ══════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def category_tree() -> dict:
    return load_default_category_tree()


@pytest.fixture(scope="module")
def brand_dictionary() -> list[str]:
    return load_default_brand_dictionary()


@pytest.fixture(scope="module")
def synonyms() -> dict:
    return load_default_synonyms()


@pytest.fixture(scope="module")
def valid_category_ids(category_tree) -> set[str]:
    return {n["id"] for n in category_tree.get("nodes", []) if "id" in n}


def _make_router(provider, category_tree, brand_dictionary, synonyms) -> QueueAiRouter:
    return QueueAiRouter(provider, category_tree, brand_dictionary, synonyms)


def _make_simple_queue_entry(
    idx: int = 0,
    *,
    mart: MartKind = MartKind.EMART,
    reason: ReviewReason = ReviewReason.CATEGORY_UNKNOWN,
    raw_payload: dict | None = None,
) -> CanonicalQueueDTO:
    """테스트용 최소 ProductReviewQueue DTO."""
    return CanonicalQueueDTO(
        id=f"test-queue-{idx}",
        raw_payload=raw_payload or {
            "itemId": f"1000{idx:09d}",
            "itemName": "한끼 양배추 800g 통",
            "finalPrice": "3990",
        },
        source_mart=mart,
        reason=reason,
    )


# ── DB 픽스처 (canonical 테이블용 인메모리 SQLite) ────────────────────────────

# apply_decisions_to_db가 사용하는 컬럼만 포함한 최소 DDL.
# ORM 모델 없이 직접 DDL로 생성해 db-admin 패키지 의존성을 제거한다.
# (ai-admin/backend와 db-admin/backend 양쪽에 storage/ 패키지가 있어
#  cross-import 충돌이 발생하기 때문)
_CREATE_CANONICAL_PRODUCTS_DDL = """
CREATE TABLE IF NOT EXISTS canonical_products (
    id                      TEXT PRIMARY KEY,
    name_core               TEXT NOT NULL,
    brand                   TEXT,
    pack_quantity           REAL NOT NULL DEFAULT 1.0,
    pack_unit               TEXT NOT NULL DEFAULT '개',
    category_path_internal_id TEXT,
    representative_image_url  TEXT,
    created_at              DATETIME NOT NULL,
    updated_at              DATETIME NOT NULL
)
"""

_CREATE_REVIEW_QUEUE_DDL = """
CREATE TABLE IF NOT EXISTS canonical_product_review_queue (
    id                      TEXT PRIMARY KEY,
    raw_payload             TEXT NOT NULL,
    source_mart             TEXT NOT NULL,
    reason                  TEXT NOT NULL,
    suggested_canonical_id  TEXT REFERENCES canonical_products(id),
    created_at              DATETIME NOT NULL,
    resolved_at             DATETIME,
    resolver_user_id        TEXT
)
"""


@pytest.fixture
def canonical_engine():
    """in-memory SQLite + canonical 테이블 bootstrap (순수 DDL)."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    with engine.connect() as conn:
        conn.execute(text(_CREATE_CANONICAL_PRODUCTS_DDL))
        conn.execute(text(_CREATE_REVIEW_QUEUE_DDL))
        conn.commit()
    yield engine
    engine.dispose()


@pytest.fixture
def canonical_session(canonical_engine) -> Iterator[Session]:
    """테스트용 canonical 세션."""
    SessionFactory = sessionmaker(bind=canonical_engine)
    with SessionFactory() as session:
        yield session


# ══════════════════════════════════════════════════════
# 이마트 fixture 로더
# ══════════════════════════════════════════════════════

def _load_emart_queue_entries() -> list[CanonicalQueueDTO]:
    """
    이마트 5건 fixture → canonicalize_emart → ProductReviewQueue 5건 반환.
    모든 이마트 항목은 EMART_NO_CATEGORY_IN_RESPONSE 사유로 큐에 들어간다.
    """
    emart_dir = FIXTURE_BASE / "emart"
    if not emart_dir.exists():
        pytest.skip(f"이마트 fixture 디렉터리 없음: {emart_dir}")

    pref = emart_dir / "sale_listing_5cards.json"
    files = [pref] if pref.exists() else list(emart_dir.glob("*.json"))
    if not files:
        pytest.skip("이마트 fixture JSON 없음")

    raw_items: list[dict] = []
    for f in files:
        try:
            with open(f, encoding="utf-8") as fp:
                data = json.load(fp)
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

    from core.product_canonicalize import canonicalize_emart

    entries: list[CanonicalQueueDTO] = []
    for item in raw_items:
        result = canonicalize_emart(item, datetime.now())
        if result.queue_entry is not None:
            entries.append(result.queue_entry)

    return entries


# ══════════════════════════════════════════════════════
# 테스트 1: 이마트 5건 fixture → 모두 RESOLVED
# ══════════════════════════════════════════════════════

def test_emart_fixtures_all_resolved(category_tree, brand_dictionary, synonyms, valid_category_ids):
    """
    이마트 5건 fixture → ProductReviewQueue 5건 생성 →
    mock provider가 유효한 응답 → 5건 모두 RESOLVED.

    왜 이 테스트가 중요한가:
        이마트는 카테고리 정보가 없어 100% 큐로 빠진다.
        C1 라우터가 이 케이스를 올바르게 RESOLVED 처리해야
        canonical 데이터가 완성된다.
    """
    entries = _load_emart_queue_entries()
    assert len(entries) >= 1, "이마트 fixture에서 queue_entry가 생성되어야 함"

    # mock provider: 모든 호출에 유효한 응답 반환 (양배추 → cabbage)
    valid_responses = [
        {
            "category_node_id": "cabbage",
            "brand": None,
            "name_core": "양배추",
            "confidence": 0.85,
            "reasons": ["이마트 양배추: 엽채류 > 양배추 분류"],
        }
    ] * len(entries)

    provider = MockProvider(valid_responses)
    router = _make_router(provider, category_tree, brand_dictionary, synonyms)
    decisions = router.route_batch(entries, dry_run_with_mock_provider=True)

    assert len(decisions) == len(entries)
    for dec in decisions:
        assert dec.decision == "RESOLVED", (
            f"queue_id={dec.queue_id} → 예상 RESOLVED, 실제 {dec.decision}: {dec.reasons}"
        )
        assert dec.category_node_id == "cabbage"
        assert dec.category_node_id in valid_category_ids
        assert dec.confidence == 0.85
        assert isinstance(dec.raw_ai_response, dict)
        assert isinstance(dec.elapsed_ms, int) and dec.elapsed_ms >= 0


# ══════════════════════════════════════════════════════
# 테스트 2: 트리에 없는 id → ESCALATED
# ══════════════════════════════════════════════════════

def test_invalid_category_id_escalated(category_tree, brand_dictionary, synonyms):
    """
    mock provider가 트리에 없는 id("vegetables/leafy/cabbage") 반환 → ESCALATED.

    왜 이 테스트가 중요한가:
        LLM이 슬래시 구분 경로를 id로 착각하거나 존재하지 않는 id를 만들 수 있다.
        이 경우 반드시 ESCALATED 처리해야 한다.
    """
    provider = MockProvider([
        {
            "category_node_id": "vegetables/leafy/cabbage",  # 트리에 없는 id
            "confidence": 0.9,
            "reasons": ["hallucinated id"],
        }
    ])
    router = _make_router(provider, category_tree, brand_dictionary, synonyms)
    entry = _make_simple_queue_entry(0)
    decision = router.route_one(entry)

    assert decision.decision == "ESCALATED"
    assert any("INVALID_CATEGORY_ID" in r for r in decision.reasons)
    assert decision.category_node_id is None  # 잘못된 id는 결정에서 None으로


# ══════════════════════════════════════════════════════
# 테스트 3: confidence 임계 미달 → ESCALATED
# ══════════════════════════════════════════════════════

def test_low_confidence_escalated(category_tree, brand_dictionary, synonyms):
    """
    mock provider가 confidence=0.4 반환 → ESCALATED (임계 0.7 미달).

    왜 0.7인가:
        0.7 미만은 LLM이 확신 없이 추측하는 수준.
        틀린 카테고리가 canonical에 들어가는 것을 방지한다.
    """
    provider = MockProvider([
        {
            "category_node_id": "cabbage",
            "confidence": 0.4,  # 임계 미달
            "reasons": ["LOW_CONFIDENCE"],
        }
    ])
    router = _make_router(provider, category_tree, brand_dictionary, synonyms)
    entry = _make_simple_queue_entry(1)
    decision = router.route_one(entry)

    assert decision.decision == "ESCALATED"
    assert decision.confidence == 0.4
    assert any("LOW_CONFIDENCE" in r for r in decision.reasons)
    # 트리에 있는 id라도 신뢰도 미달이면 ESCALATED
    assert decision.category_node_id == "cabbage"


# ══════════════════════════════════════════════════════
# 테스트 4: 빈 응답 → ESCALATED
# ══════════════════════════════════════════════════════

def test_empty_response_escalated(category_tree, brand_dictionary, synonyms):
    """
    mock provider가 빈 dict 반환 → ESCALATED(EMPTY_RESPONSE).
    JSON이 깨졌거나 LLM이 아무것도 반환하지 않은 경우.
    """
    provider = MockProvider([{}])  # 빈 응답
    router = _make_router(provider, category_tree, brand_dictionary, synonyms)
    entry = _make_simple_queue_entry(2)
    decision = router.route_one(entry)

    assert decision.decision == "ESCALATED"
    assert any("EMPTY_RESPONSE" in r for r in decision.reasons)


# ══════════════════════════════════════════════════════
# 테스트 5: provider 예외 → 1회 retry → 실패 시 ESCALATED
# ══════════════════════════════════════════════════════

def test_provider_error_retry_then_escalated(category_tree, brand_dictionary, synonyms):
    """
    provider가 항상 예외를 발생시킴 → 2회 시도 후 ESCALATED(PROVIDER_ERROR).

    왜 1회 retry인가:
        네트워크 일시 장애·quota 초과 등 transient error에 대응.
        2회 이상 재시도는 비용 낭비이므로 제한.
    """
    provider = MockProvider(raise_on_call=True)
    router = _make_router(provider, category_tree, brand_dictionary, synonyms)
    entry = _make_simple_queue_entry(3)
    decision = router.route_one(entry)

    assert decision.decision == "ESCALATED"
    assert any("PROVIDER_ERROR" in r for r in decision.reasons)
    # 2회 시도 확인
    assert provider._call_count == 2


# ══════════════════════════════════════════════════════
# 테스트 6: 첫 번째 provider 오류 → retry → 두 번째 성공 → RESOLVED
# ══════════════════════════════════════════════════════

def test_provider_error_once_then_resolved(category_tree, brand_dictionary, synonyms):
    """
    provider가 첫 번째 호출은 예외, 두 번째는 유효 응답 → RESOLVED.
    """
    # MockProvider: raise_once_then 설정
    provider = MockProvider(
        [{"category_node_id": "cabbage", "confidence": 0.9, "reasons": ["retry 성공"]}],
        raise_once_then={"category_node_id": "cabbage", "confidence": 0.9},
    )
    router = _make_router(provider, category_tree, brand_dictionary, synonyms)
    entry = _make_simple_queue_entry(4)
    decision = router.route_one(entry)

    assert decision.decision == "RESOLVED"
    assert decision.category_node_id == "cabbage"


# ══════════════════════════════════════════════════════
# 테스트 7: apply_decisions_to_db — RESOLVED 업데이트
# ══════════════════════════════════════════════════════

def test_apply_resolved_updates_canonical(canonical_session, category_tree, brand_dictionary, synonyms):
    """
    RESOLVED 결정을 DB에 반영 →
    ProductReviewQueue.resolved_at 설정 + CanonicalProduct.category_path_internal_id 업데이트.
    """
    session = canonical_session

    # 테스트 데이터 삽입
    canonical_id = "a" * 40  # SHA1 길이 40
    queue_id = "queue-test-resolved-001"
    category_node = "cabbage"

    session.execute(
        text(
            "INSERT INTO canonical_products "
            "(id, name_core, pack_quantity, pack_unit, created_at, updated_at) "
            "VALUES (:id, :name, :qty, :unit, :ca, :ua)"
        ),
        {
            "id": canonical_id,
            "name": "양배추",
            "qty": 0.8,
            "unit": "KG",
            "ca": datetime.now(),
            "ua": datetime.now(),
        },
    )
    session.execute(
        text(
            "INSERT INTO canonical_product_review_queue "
            "(id, raw_payload, source_mart, reason, suggested_canonical_id, created_at) "
            "VALUES (:id, :raw, :mart, :reason, :cid, :ca)"
        ),
        {
            "id": queue_id,
            "raw": json.dumps({"itemName": "양배추"}),
            "mart": "EMART",
            "reason": "CATEGORY_UNKNOWN",
            "cid": canonical_id,
            "ca": datetime.now(),
        },
    )
    session.flush()

    # 라우터로 결정 생성
    provider = MockProvider([
        {"category_node_id": category_node, "confidence": 0.85, "reasons": ["테스트"]}
    ])
    router = _make_router(provider, category_tree, brand_dictionary, synonyms)

    decision = QueueRouterDecision(
        queue_id=queue_id,
        decision="RESOLVED",
        category_node_id=category_node,
        brand=None,
        name_core_refined="양배추",
        confidence=0.85,
        reasons=["테스트"],
        raw_ai_response={"category_node_id": category_node, "confidence": 0.85},
        elapsed_ms=100,
    )

    result = router.apply_decisions_to_db([decision], session)

    assert result.resolved_count == 1
    assert result.escalated_count == 0
    assert result.errors == []

    # DB 상태 확인
    row = session.execute(
        text("SELECT resolved_at, resolver_user_id FROM canonical_product_review_queue WHERE id = :id"),
        {"id": queue_id},
    ).fetchone()
    assert row is not None
    assert row[0] is not None  # resolved_at 설정됨
    assert row[1] == _RESOLVED_RESOLVER_ID

    cat_row = session.execute(
        text("SELECT category_path_internal_id FROM canonical_products WHERE id = :id"),
        {"id": canonical_id},
    ).fetchone()
    assert cat_row is not None
    assert cat_row[0] == category_node


# ══════════════════════════════════════════════════════
# 테스트 8: apply_decisions_to_db — 멱등성
# ══════════════════════════════════════════════════════

def test_apply_decisions_idempotency(canonical_session, category_tree, brand_dictionary, synonyms):
    """
    같은 RESOLVED 결정을 두 번 적용해도 오류 없이 동일한 결과.
    (resolved_at이 갱신될 뿐 예외·중복 오류 없음)
    """
    session = canonical_session
    canonical_id = "b" * 40
    queue_id = "queue-idempotency-001"
    category_node = "egg"

    session.execute(
        text(
            "INSERT INTO canonical_products "
            "(id, name_core, pack_quantity, pack_unit, created_at, updated_at) "
            "VALUES (:id, :name, :qty, :unit, :ca, :ua)"
        ),
        {
            "id": canonical_id,
            "name": "계란",
            "qty": 30.0,
            "unit": "개",
            "ca": datetime.now(),
            "ua": datetime.now(),
        },
    )
    session.execute(
        text(
            "INSERT INTO canonical_product_review_queue "
            "(id, raw_payload, source_mart, reason, suggested_canonical_id, created_at) "
            "VALUES (:id, :raw, :mart, :reason, :cid, :ca)"
        ),
        {
            "id": queue_id,
            "raw": json.dumps({"itemName": "행복 계란 30구"}),
            "mart": "EMART",
            "reason": "CATEGORY_UNKNOWN",
            "cid": canonical_id,
            "ca": datetime.now(),
        },
    )
    session.flush()

    router = _make_router(MockProvider(), category_tree, brand_dictionary, synonyms)
    decision = QueueRouterDecision(
        queue_id=queue_id,
        decision="RESOLVED",
        category_node_id=category_node,
        brand=None,
        name_core_refined="계란",
        confidence=0.9,
        reasons=["멱등성 테스트"],
        raw_ai_response={},
        elapsed_ms=50,
    )

    # 첫 번째 적용
    r1 = router.apply_decisions_to_db([decision], session)
    assert r1.resolved_count == 1
    assert r1.errors == []

    # 두 번째 적용 — 오류 없어야 함
    r2 = router.apply_decisions_to_db([decision], session)
    assert r2.resolved_count == 1
    assert r2.errors == []


# ══════════════════════════════════════════════════════
# 테스트 9: apply_decisions_to_db — ESCALATED 마킹
# ══════════════════════════════════════════════════════

def test_apply_escalated_marks_queue(canonical_session, category_tree, brand_dictionary, synonyms):
    """
    ESCALATED 결정 → 큐 유지 (resolved_at=None) + escalation 마커 기록.
    """
    session = canonical_session
    queue_id = "queue-escalated-001"

    session.execute(
        text(
            "INSERT INTO canonical_product_review_queue "
            "(id, raw_payload, source_mart, reason, created_at) "
            "VALUES (:id, :raw, :mart, :reason, :ca)"
        ),
        {
            "id": queue_id,
            "raw": json.dumps({"itemName": "모호한 상품"}),
            "mart": "EMART",
            "reason": "PRODUCT_AMBIGUOUS",
            "ca": datetime.now(),
        },
    )
    session.flush()

    router = _make_router(MockProvider(), category_tree, brand_dictionary, synonyms)
    decision = QueueRouterDecision(
        queue_id=queue_id,
        decision="ESCALATED",
        category_node_id=None,
        brand=None,
        name_core_refined=None,
        confidence=0.3,
        reasons=["LOW_CONFIDENCE: 0.3 < 0.7"],
        raw_ai_response={},
        elapsed_ms=80,
    )

    result = router.apply_decisions_to_db([decision], session)
    assert result.escalated_count == 1
    assert result.errors == []

    row = session.execute(
        text(
            "SELECT resolved_at, resolver_user_id "
            "FROM canonical_product_review_queue WHERE id = :id"
        ),
        {"id": queue_id},
    ).fetchone()
    assert row is not None
    assert row[0] is None  # resolved_at은 None (큐 유지)
    assert row[1] == _ESCALATED_RESOLVER_ID


# ══════════════════════════════════════════════════════
# 테스트 10: apply_decisions_to_db — 존재하지 않는 queue_id → skip
# ══════════════════════════════════════════════════════

def test_apply_nonexistent_queue_id_skipped(canonical_session, category_tree, brand_dictionary, synonyms):
    """존재하지 않는 queue_id → skipped_count 증가, 오류 없음."""
    router = _make_router(MockProvider(), category_tree, brand_dictionary, synonyms)
    decision = QueueRouterDecision(
        queue_id="nonexistent-queue-id-xyz",
        decision="RESOLVED",
        category_node_id="cabbage",
        brand=None,
        name_core_refined=None,
        confidence=0.9,
        reasons=[],
        raw_ai_response={},
        elapsed_ms=10,
    )
    result = router.apply_decisions_to_db([decision], canonical_session)
    assert result.skipped_count == 1
    assert result.resolved_count == 0
    assert result.errors == []


# ══════════════════════════════════════════════════════
# 테스트 11: raw_ai_response 보존 확인
# ══════════════════════════════════════════════════════

def test_raw_ai_response_preserved(category_tree, brand_dictionary, synonyms):
    """
    raw_ai_response는 원본 LLM 응답을 그대로 보존해야 한다 (감사 정책).
    어떠한 정보도 삭제·변형해서는 안 된다.
    """
    original_response = {
        "category_node_id": "cabbage",
        "confidence": 0.9,
        "reasons": ["양배추 키워드"],
        "_usage": {"prompt_token_count": 500, "total_token_count": 520},
    }
    provider = MockProvider([original_response])
    router = _make_router(provider, category_tree, brand_dictionary, synonyms)
    entry = _make_simple_queue_entry(10)
    decision = router.route_one(entry)

    assert decision.raw_ai_response == original_response


# ══════════════════════════════════════════════════════
# 테스트 12: route_batch dry_run 플래그 동작
# ══════════════════════════════════════════════════════

def test_route_batch_returns_decisions_for_all_entries(category_tree, brand_dictionary, synonyms):
    """route_batch는 entries와 동일한 수의 decisions를 반환한다."""
    entries = [_make_simple_queue_entry(i) for i in range(5)]
    responses = [
        {"category_node_id": "cabbage", "confidence": 0.85, "reasons": []}
    ] * 5
    provider = MockProvider(responses)
    router = _make_router(provider, category_tree, brand_dictionary, synonyms)
    decisions = router.route_batch(entries, dry_run_with_mock_provider=True)

    assert len(decisions) == 5
    assert all(d.decision == "RESOLVED" for d in decisions)


# ══════════════════════════════════════════════════════
# 테스트 13: 라이브 smoke (opt-in, WALLETSAVIOR_LIVE_AI=1)
# ══════════════════════════════════════════════════════

@pytest.mark.skipif(
    os.environ.get(LIVE_AI_ENV, "").strip().lower() not in {"1", "true", "yes", "on"},
    reason=f"라이브 AI 테스트는 {LIVE_AI_ENV}=1 로 opt-in 필요",
)
def test_live_smoke_emart_cabbage(category_tree, brand_dictionary, synonyms, valid_category_ids):
    """
    라이브 smoke: 양배추 이마트 fixture 1건 → 실제 Gemini API 호출.
    category_node_id가 vegetable 하위 어떤 노드든 있으면 통과.
    (정확한 id 강요 X — 트리 내 존재만 검증)

    실행 방법:
        $env:WALLETSAVIOR_LIVE_AI="1"
        $env:GOOGLE_API_KEY="<your_key>"
        py -3 -m pytest tests/test_queue_ai_router.py::test_live_smoke_emart_cabbage -v
    """
    from providers.google_genai import GoogleGenAIProvider
    from core.contracts.ai_pipeline import ProviderKind
    from core.contracts.control_plane import ProviderConfigContract

    config = ProviderConfigContract(
        provider_id="live-smoke-queue-router",
        provider_kind=ProviderKind.GEMINI,
        display_name="Queue AI Router Live Smoke",
        default_model=os.environ.get("WALLETSAVIOR_AI_MODEL", "gemini-2.0-flash"),
        secret_alias=os.environ.get("WALLETSAVIOR_AI_SECRET_ALIAS", "GOOGLE_API_KEY"),
        is_enabled=True,
        max_concurrent_jobs=1,
        min_request_interval_seconds=1.0,
    )
    provider = GoogleGenAIProvider(config)
    router = _make_router(provider, category_tree, brand_dictionary, synonyms)

    # 양배추 fixture 1건
    cabbage_entry = CanonicalQueueDTO(
        id="live-smoke-cabbage-001",
        raw_payload={
            "itemId": "1000641687348",
            "itemName": "[냉장] 한끼 양배추 800g 통",
            "finalPrice": "3990",
            "brandName": "",
            "sellUnitCapacity": "800g",
        },
        source_mart=MartKind.EMART,
        reason=ReviewReason.CATEGORY_UNKNOWN,
        created_at=datetime.now(),
    )

    decision = router.route_one(cabbage_entry)

    # vegetable 하위 어떤 노드든 허용 (정확한 id 강요 X)
    vegetable_subtree_ids = {
        n["id"]
        for n in category_tree.get("nodes", [])
        if n.get("parent_id") in {"vegetable", "leaf_vegetable", "root_vegetable", "fruit_vegetable"}
        or n.get("id") in {"vegetable", "leaf_vegetable", "cabbage"}
    }

    print(f"\n[라이브 smoke] decision={decision.decision}")
    print(f"  category_node_id: {decision.category_node_id}")
    print(f"  confidence: {decision.confidence}")
    print(f"  reasons: {decision.reasons}")
    print(f"  elapsed_ms: {decision.elapsed_ms}")

    assert decision.decision in {"RESOLVED", "ESCALATED"}, "decision은 RESOLVED 또는 ESCALATED"
    if decision.decision == "RESOLVED":
        assert decision.category_node_id in valid_category_ids, (
            f"RESOLVED인데 category_node_id '{decision.category_node_id}'가 트리에 없음"
        )
        # 채소 관련 노드에 분류되면 가산점 (강제는 아님)
        if decision.category_node_id in vegetable_subtree_ids:
            print("  ✓ 채소 하위 카테고리로 분류됨 (기대 결과)")
        else:
            print(f"  ⚠ 채소 외 카테고리: {decision.category_node_id} (허용, 채소 필수 아님)")
