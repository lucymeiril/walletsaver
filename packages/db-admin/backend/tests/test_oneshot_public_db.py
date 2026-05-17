"""WalletSavior Phase D4 — 원샷 공개 DB 빌더 TDD 테스트.

시나리오:
    1 (정상):    4사 fixture → snapshot 생성 → canonical_product 행 수 == canonical_created.
    2 (멱등):    동일 입력 두 번 실행 → snapshot 동일 행 수.
    3 (분위수):  합성 PriceObservation 주입 → grade.p10 등 정확값 검증.
    4 (insufficient): 표본 1건 → INSUFFICIENT_DATA.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator, Optional

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

# ── 경로 보정 ─────────────────────────────────────────────────────────────────
_TESTS_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _TESTS_DIR.parent
_SHARED_DIR = _BACKEND_DIR.parent.parent / "shared"

for _p in (str(_SHARED_DIR), str(_BACKEND_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from services.oneshot_public_db import build_snapshot, SnapshotMeta  # noqa: E402
from core.price_grading import classify, compute_price_grade  # noqa: E402

FIXTURE_BASE = (
    Path(__file__).resolve().parents[3]
    / "crawler-admin" / "backend" / "tests" / "fixtures"
)


# ══════════════════════════════════════════════════════
# DDL — in-memory SQLite
# ══════════════════════════════════════════════════════

_DDL_LIST = [
    """
    CREATE TABLE IF NOT EXISTS canonical_category_nodes (
        id TEXT PRIMARY KEY,
        parent_id TEXT REFERENCES canonical_category_nodes(id),
        name_kr TEXT NOT NULL,
        name_slug TEXT NOT NULL,
        level INTEGER NOT NULL,
        path TEXT NOT NULL UNIQUE,
        display_order INTEGER DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS canonical_products (
        id TEXT PRIMARY KEY,
        brand TEXT,
        name_core TEXT NOT NULL,
        pack_quantity REAL NOT NULL DEFAULT 1.0,
        pack_unit TEXT NOT NULL DEFAULT '개',
        category_path_internal_id TEXT REFERENCES canonical_category_nodes(id),
        representative_image_url TEXT,
        created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS canonical_mart_sku_aliases (
        id TEXT PRIMARY KEY,
        canonical_id TEXT NOT NULL REFERENCES canonical_products(id),
        mart TEXT NOT NULL,
        mart_item_id TEXT NOT NULL,
        mart_item_name_raw TEXT NOT NULL,
        source_url TEXT,
        first_seen_at DATETIME NOT NULL,
        last_seen_at DATETIME NOT NULL,
        UNIQUE(mart, mart_item_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS canonical_price_observations (
        id TEXT PRIMARY KEY,
        canonical_id TEXT NOT NULL REFERENCES canonical_products(id),
        mart TEXT NOT NULL,
        regular_price INTEGER,
        sale_price INTEGER NOT NULL,
        on_sale INTEGER NOT NULL,
        discount_rate INTEGER,
        unit_price_normalized REAL,
        unit_price_basis TEXT NOT NULL DEFAULT 'unknown',
        observed_at DATETIME NOT NULL,
        source_url TEXT,
        raw_payload_hash TEXT NOT NULL,
        event_labels TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS canonical_product_review_queue (
        id TEXT PRIMARY KEY,
        raw_payload TEXT NOT NULL,
        source_mart TEXT NOT NULL,
        reason TEXT NOT NULL,
        suggested_canonical_id TEXT REFERENCES canonical_products(id),
        attributes TEXT,
        created_at DATETIME NOT NULL,
        resolved_at DATETIME,
        resolver_user_id TEXT
    )
    """,
]


def _bootstrap_engine() -> Any:
    engine = create_engine("sqlite:///:memory:", echo=False)
    with engine.connect() as conn:
        for ddl in _DDL_LIST:
            conn.execute(text(ddl))
        conn.commit()
    return engine


@pytest.fixture
def db_engine():
    engine = _bootstrap_engine()
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine) -> Iterator[Session]:
    factory = sessionmaker(bind=db_engine)
    with factory() as session:
        yield session


# ══════════════════════════════════════════════════════
# Mock 의존성
# ══════════════════════════════════════════════════════

@dataclass
class _FakeLivepassReport:
    total_input: int
    by_mart: dict
    canonical_created: int
    queue_initial: int
    ai_resolved: int
    ai_escalated: int
    gate_passed: int
    gate_escalated: int
    final_db_resolved: int
    final_db_pending: int
    escalation_reasons_distribution: dict
    elapsed_ms: dict
    mode: str
    ai_provider_kind: str


class _MockAiRouter:
    """no-op AI 라우터 (run_livepass 주입 시 미사용)."""
    pass


class _MockPostcheckGate:
    """no-op 게이트."""
    pass


def _make_mock_livepass_report(
    mart_payloads: dict,
    canonical_ids: list[str],
) -> _FakeLivepassReport:
    """테스트용 최소 LivepassReport 반환."""
    by_mart = {
        mart: {
            "input": len(items),
            "canonical_created": len(items),
            "queue_initial": len(items),
            "ai_resolved": len(items),
            "ai_escalated": 0,
            "gate_passed": len(items),
            "gate_escalated": 0,
            "final_db_rows": len(items),
        }
        for mart, items in mart_payloads.items()
    }
    total = sum(len(items) for items in mart_payloads.values())
    return _FakeLivepassReport(
        total_input=total,
        by_mart=by_mart,
        canonical_created=len(canonical_ids),
        queue_initial=total,
        ai_resolved=total,
        ai_escalated=0,
        gate_passed=total,
        gate_escalated=0,
        final_db_resolved=total,
        final_db_pending=0,
        escalation_reasons_distribution={},
        elapsed_ms={},
        mode="commit",
        ai_provider_kind="mock",
    )


def _insert_canonical_product(session: Any, cid: str, name: str = "테스트상품") -> None:
    """테스트용 CanonicalProduct 직접 삽입."""
    now = datetime.now().isoformat()
    session.execute(text(
        "INSERT OR IGNORE INTO canonical_products "
        "(id, brand, name_core, pack_quantity, pack_unit, created_at, updated_at) "
        "VALUES (:id, NULL, :name, 1.0, '개', :now, :now)"
    ), {"id": cid, "name": name, "now": now})


def _insert_price_obs(
    session: Any,
    cid: str,
    sale_price: int,
    unit_price: Optional[float] = None,
    obs_id: Optional[str] = None,
    observed_at: Optional[datetime] = None,
) -> None:
    """테스트용 PriceObservation 직접 삽입."""
    import hashlib
    if obs_id is None:
        obs_id = hashlib.sha1(f"{cid}:{sale_price}:{id(sale_price)}".encode()).hexdigest()[:64]
    if observed_at is None:
        observed_at = datetime.now()
    session.execute(text(
        "INSERT OR IGNORE INTO canonical_price_observations "
        "(id, canonical_id, mart, regular_price, sale_price, on_sale, "
        "unit_price_normalized, unit_price_basis, observed_at, raw_payload_hash) "
        "VALUES (:id, :cid, 'EMART', NULL, :price, 0, :unit, 'unknown', :obs_at, :hash)"
    ), {
        "id": obs_id,
        "cid": cid,
        "price": sale_price,
        "unit": unit_price,
        "obs_at": observed_at.isoformat(),
        "hash": obs_id,
    })


# ══════════════════════════════════════════════════════
# 시나리오 1: 정상 — 4사 fixture → snapshot 생성
# ══════════════════════════════════════════════════════

def test_scenario_1_normal_snapshot(tmp_path, db_session):
    """합성 canonical products → snapshot 생성 → canonical_product 행 수 일관성.

    (시나리오 1: 정상 흐름 — mock run_livepass + 합성 데이터)
    """
    n_products = 3
    canonical_ids = [f"a" * 39 + str(i) for i in range(n_products)]
    for cid in canonical_ids:
        _insert_canonical_product(db_session, cid, f"상품{cid[:4]}")
    db_session.flush()

    mart_payloads = {"emart": [{"name": f"item{i}"} for i in range(n_products)]}

    # mock run_livepass — DB를 건드리지 않고 report만 반환
    report = _make_mock_livepass_report(mart_payloads, canonical_ids)

    def mock_run_livepass(payloads, session, ai_router, gate, **kwargs):
        return report

    snapshot_path = tmp_path / "public_snapshot.sqlite"
    meta_json_path = tmp_path / "meta.json"

    meta = build_snapshot(
        mart_payloads=mart_payloads,
        working_session=db_session,
        ai_router=_MockAiRouter(),
        postcheck_gate=_MockPostcheckGate(),
        snapshot_path=snapshot_path,
        meta_json_path=meta_json_path,
        run_livepass=mock_run_livepass,
        window_months=6,
        ai_provider_kind="mock",
        write_files=True,
    )

    # 파일 생성 확인
    assert snapshot_path.exists(), "snapshot SQLite 파일이 생성돼야 함"
    assert meta_json_path.exists(), "meta JSON 파일이 생성돼야 함"

    # snapshot 행 수 확인
    conn = sqlite3.connect(str(snapshot_path))
    try:
        product_count = conn.execute("SELECT COUNT(*) FROM canonical_product").fetchone()[0]
        grade_count = conn.execute("SELECT COUNT(*) FROM price_grade").fetchone()[0]
    finally:
        conn.close()

    assert product_count == n_products, (
        f"canonical_product 행 수({product_count}) == 사전 삽입 수({n_products})"
    )
    assert grade_count == n_products, "모든 canonical에 대한 price_grade가 있어야 함"

    # meta JSON 내용 확인
    with open(meta_json_path, encoding="utf-8") as f:
        meta_dict = json.load(f)
    assert "generated_at" in meta_dict
    assert "window_months" in meta_dict
    assert meta_dict["total_canonical"] == n_products


# ══════════════════════════════════════════════════════
# 시나리오 2: 멱등성 — 두 번 실행 → 동일 행 수
# ══════════════════════════════════════════════════════

def test_scenario_2_idempotent(tmp_path):
    """동일 입력 두 번 실행 → snapshot canonical_product 행 수 동일."""
    n_products = 4
    canonical_ids = [f"b" * 39 + str(i) for i in range(n_products)]
    mart_payloads = {"homeplus": [{"name": f"hp{i}"} for i in range(n_products)]}

    def _run_once():
        engine = _bootstrap_engine()
        factory = sessionmaker(bind=engine)
        with factory() as session:
            for cid in canonical_ids:
                _insert_canonical_product(session, cid, f"홈플상품{cid[:4]}")
            session.flush()

            report = _make_mock_livepass_report(mart_payloads, canonical_ids)

            def mock_lp(payloads, sess, ai_router, gate, **kwargs):
                return report

            meta = build_snapshot(
                mart_payloads=mart_payloads,
                working_session=session,
                ai_router=_MockAiRouter(),
                postcheck_gate=_MockPostcheckGate(),
                snapshot_path=tmp_path / "snap.sqlite",
                meta_json_path=tmp_path / "meta.json",
                run_livepass=mock_lp,
                window_months=6,
                ai_provider_kind="mock",
                write_files=True,
            )
        engine.dispose()
        return meta

    meta1 = _run_once()
    meta2 = _run_once()

    # 두 번 실행 후 canonical 수 동일
    assert meta1.total_canonical == meta2.total_canonical == n_products

    # snapshot 파일의 행 수도 동일
    conn = sqlite3.connect(str(tmp_path / "snap.sqlite"))
    try:
        count = conn.execute("SELECT COUNT(*) FROM canonical_product").fetchone()[0]
    finally:
        conn.close()
    assert count == n_products, f"멱등성: 두 번 실행 후도 {n_products}건 유지"


# ══════════════════════════════════════════════════════
# 시나리오 3: 분위수 정확값
# ══════════════════════════════════════════════════════

def test_scenario_3_quantile_accuracy(tmp_path, db_session):
    """합성 PriceObservation 10건 → grade.p10 정확값 검증."""
    cid = "c" * 40

    # canonical product 삽입
    _insert_canonical_product(db_session, cid, "분위수테스트상품")

    # 가격 1000, 2000, ..., 10000 (10건)
    prices = [float(i * 1000) for i in range(1, 11)]
    obs_cutoff = datetime.now() - timedelta(days=10)  # 최근 10일

    for i, price in enumerate(prices):
        _insert_price_obs(
            db_session, cid,
            sale_price=int(price),
            unit_price=price,
            obs_id=f"obs-{cid[:4]}-{i:03d}",
            observed_at=obs_cutoff + timedelta(hours=i),
        )

    db_session.flush()

    mart_payloads = {"emart": [{"name": "분위수테스트"}]}
    report = _make_mock_livepass_report(mart_payloads, [cid])

    def mock_lp(payloads, sess, ai_router, gate, **kwargs):
        return report

    meta = build_snapshot(
        mart_payloads=mart_payloads,
        working_session=db_session,
        ai_router=_MockAiRouter(),
        postcheck_gate=_MockPostcheckGate(),
        snapshot_path=tmp_path / "snap3.sqlite",
        meta_json_path=tmp_path / "meta3.json",
        run_livepass=mock_lp,
        window_months=6,
        ai_provider_kind="mock",
        write_files=True,
    )

    conn = sqlite3.connect(str(tmp_path / "snap3.sqlite"))
    try:
        row = conn.execute(
            "SELECT p10, p25, p50, p75, sample_size, sufficient "
            "FROM price_grade WHERE canonical_id = ?", (cid,)
        ).fetchone()
    finally:
        conn.close()

    assert row is not None, f"canonical_id={cid}의 price_grade 행 없음"
    p10, p25, p50, p75, n, suf = row

    assert n == 10, f"sample_size={n}, expected 10"
    assert suf == 1, "sufficient=True 이어야 함"

    # P10: idx=0.1*9=0.9 → 1000 + 0.9*(2000-1000) = 1900.0
    assert abs(p10 - 1900.0) < 1.0, f"p10={p10}, expected 1900.0"
    # P50: idx=0.5*9=4.5 → 5000 + 0.5*(6000-5000) = 5500.0
    assert abs(p50 - 5500.0) < 1.0, f"p50={p50}, expected 5500.0"
    # P75: idx=0.75*9=6.75 → 7000 + 0.75*(8000-7000) = 7750.0
    assert abs(p75 - 7750.0) < 1.0, f"p75={p75}, expected 7750.0"


# ══════════════════════════════════════════════════════
# 시나리오 4: sufficient=False → INSUFFICIENT_DATA
# ══════════════════════════════════════════════════════

def test_scenario_4_insufficient_data(tmp_path, db_session):
    """PriceObservation 1건 → sufficient=False → classify INSUFFICIENT_DATA."""
    cid = "d" * 40

    _insert_canonical_product(db_session, cid, "표본부족상품")
    _insert_price_obs(
        db_session, cid,
        sale_price=5000,
        unit_price=5000.0,
        obs_id=f"single-obs-{cid[:4]}",
    )

    db_session.flush()

    mart_payloads = {"lottemart": [{"name": "단일표본"}]}
    report = _make_mock_livepass_report(mart_payloads, [cid])

    def mock_lp(payloads, sess, ai_router, gate, **kwargs):
        return report

    meta = build_snapshot(
        mart_payloads=mart_payloads,
        working_session=db_session,
        ai_router=_MockAiRouter(),
        postcheck_gate=_MockPostcheckGate(),
        snapshot_path=tmp_path / "snap4.sqlite",
        meta_json_path=tmp_path / "meta4.json",
        run_livepass=mock_lp,
        window_months=6,
        ai_provider_kind="mock",
        write_files=True,
    )

    conn = sqlite3.connect(str(tmp_path / "snap4.sqlite"))
    try:
        row = conn.execute(
            "SELECT p10, sufficient, sample_size FROM price_grade WHERE canonical_id = ?",
            (cid,),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None, "price_grade 행이 있어야 함"
    p10, suf, n = row
    assert n == 1, f"sample_size={n}, expected 1"
    assert suf == 0, f"sufficient={suf}, expected 0 (False)"
    assert p10 is None, f"p10={p10}, expected None (insufficient)"

    # meta에서도 insufficient 집계 확인
    assert meta.insufficient_grades >= 1

    # classify 검증 (PriceGrade 직접 생성)
    grade = compute_price_grade(cid, [5000.0])
    label = classify(5000.0, grade)
    assert label == "INSUFFICIENT_DATA", f"label={label}"


# ══════════════════════════════════════════════════════
# 추가: meta JSON 구조 검증
# ══════════════════════════════════════════════════════

def test_meta_json_structure(tmp_path, db_session):
    """meta JSON이 모든 필수 필드를 포함하는지 검증."""
    cid = "e" * 40
    _insert_canonical_product(db_session, cid, "메타테스트")
    db_session.flush()

    mart_payloads = {"costco": [{"name": "메타상품"}]}
    report = _make_mock_livepass_report(mart_payloads, [cid])

    def mock_lp(payloads, sess, ai_router, gate, **kwargs):
        return report

    meta = build_snapshot(
        mart_payloads=mart_payloads,
        working_session=db_session,
        ai_router=_MockAiRouter(),
        postcheck_gate=_MockPostcheckGate(),
        snapshot_path=tmp_path / "snap5.sqlite",
        meta_json_path=tmp_path / "meta5.json",
        run_livepass=mock_lp,
        window_months=3,
        ai_provider_kind="mock",
        write_files=True,
    )

    with open(tmp_path / "meta5.json", encoding="utf-8") as f:
        d = json.load(f)

    required_keys = [
        "generated_at", "window_months", "input_counts", "total_input",
        "livepass_pass_rate", "ai_provider_kind", "total_canonical",
        "sufficient_grades", "insufficient_grades", "grade_sample",
        "snapshot_path", "meta_json_path",
    ]
    for k in required_keys:
        assert k in d, f"meta JSON에 '{k}' 필드 없음"

    assert d["window_months"] == 3
    assert d["ai_provider_kind"] == "mock"
    assert d["total_canonical"] == 1


def test_snapshot_tables_exist(tmp_path, db_session):
    """snapshot SQLite에 4개 테이블이 모두 존재하는지 확인."""
    cid = "f" * 40
    _insert_canonical_product(db_session, cid, "테이블검증")
    db_session.flush()

    mart_payloads = {"emart": [{"name": "table_test"}]}
    report = _make_mock_livepass_report(mart_payloads, [cid])

    def mock_lp(p, s, r, g, **kw):
        return report

    build_snapshot(
        mart_payloads=mart_payloads,
        working_session=db_session,
        ai_router=_MockAiRouter(),
        postcheck_gate=_MockPostcheckGate(),
        snapshot_path=tmp_path / "snap6.sqlite",
        meta_json_path=tmp_path / "meta6.json",
        run_livepass=mock_lp,
        write_files=True,
    )

    conn = sqlite3.connect(str(tmp_path / "snap6.sqlite"))
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    finally:
        conn.close()

    assert "canonical_product" in tables
    assert "price_grade" in tables
    assert "category_node" in tables
    assert "mart_sku_alias" in tables
