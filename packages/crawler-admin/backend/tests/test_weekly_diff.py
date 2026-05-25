"""test_weekly_diff.py — 주간 diff 서비스 테스트.

테스트 시드:
    - previous window: 10건 (emart, source_record_key sku-01 ~ sku-10)
    - current  window:  8건 (sku-01~08) + 신규 sku-11
      → 사라짐: sku-09, sku-10  (2건)
      → 신규:   sku-11          (1건)
      → 가격 변동: sku-01 (1000 → 1200, +20%)

커버리지:
    - compute_weekly_diff 정확성 (사라짐/신규/유지/가격변동)
    - alert 적재 후 GET /weekly/alerts 정상 응답
    - resolve 후 status=open에서 빠짐
    - 같은 window 재실행 멱등 (alert 중복 적재 X)
    - 빈 데이터 / 한 쪽만 비어있는 경우
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

# ── sys.path 설정 ──────────────────────────────────────────────────────────
_backend = Path(__file__).resolve().parents[1]
_shared = _backend.parent.parent / "shared"
for _p in (_backend, _shared):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from services.weekly_diff import (
    AlertDisappearedSkuModel,
    AlertSkuBase,
    WeeklyDiffReport,
    compute_weekly_diff,
    persist_alerts,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

_T_PREV_SINCE = datetime(2025, 1, 1, 0, 0, 0)
_T_PREV_UNTIL = datetime(2025, 1, 8, 0, 0, 0)
_T_CURR_SINCE = _T_PREV_UNTIL
_T_CURR_UNTIL = datetime(2025, 1, 15, 0, 0, 0)
_MART = "emart"


def _make_engine():
    """인메모리 SQLite 엔진 + raw_crawl_records + alert_disappeared_skus 테이블 생성."""
    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # 모든 세션이 동일 in-memory DB 공유
    )

    # raw_crawl_records 테이블 생성 (ai-admin 모델 없이 직접 DDL)
    with engine.connect() as conn:
        conn.execute(text(
            """
            CREATE TABLE raw_crawl_records (
                raw_record_id    TEXT PRIMARY KEY,
                batch_id         TEXT NOT NULL,
                source_name      TEXT NOT NULL,
                source_record_key TEXT,
                source_url       TEXT,
                raw_title        TEXT NOT NULL,
                raw_price        INTEGER,
                raw_payload      TEXT DEFAULT '{}',
                crawled_at       DATETIME NOT NULL
            )
            """
        ))
        conn.commit()

    # alert_disappeared_skus 테이블 생성
    AlertSkuBase.metadata.create_all(engine, checkfirst=True)

    return engine


def _insert_record(session: Session, *, rid: str, source_name: str, key: str,
                   title: str, price: int, crawled_at: datetime):
    session.execute(text(
        """
        INSERT INTO raw_crawl_records
            (raw_record_id, batch_id, source_name, source_record_key, raw_title, raw_price, crawled_at)
        VALUES
            (:rid, 'batch-test', :source_name, :key, :title, :price, :crawled_at)
        """
    ), {"rid": rid, "source_name": source_name, "key": key, "title": title,
        "price": price, "crawled_at": crawled_at})


@pytest.fixture
def engine():
    return _make_engine()


@pytest.fixture
def session(engine):
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    sess = SessionLocal()
    yield sess
    sess.close()


def _seed_standard(session: Session):
    """표준 시드: previous 10건, current 8+1건 (사라짐 2, 신규 1, 가격변동 1)."""
    prev_mid = datetime(2025, 1, 4, 12, 0, 0)
    curr_mid = datetime(2025, 1, 11, 12, 0, 0)

    # previous window — sku-01 ~ sku-10
    for i in range(1, 11):
        key = f"sku-{i:02d}"
        price = 1000 + i * 100
        # sku-01은 가격 변동 시드 — current에서 1200이 됨
        _insert_record(session, rid=f"prev-{key}", source_name=_MART,
                       key=key, title=f"상품{i}", price=price, crawled_at=prev_mid)

    # current window — sku-01 ~ sku-08 + sku-11(신규)
    # sku-01: 가격 변동 1100 → 1200
    for i in list(range(1, 9)) + [11]:
        key = f"sku-{i:02d}"
        if i == 1:
            price = 1200   # 가격 변동 (old: 1100)
        elif i == 11:
            price = 500    # 신규
        else:
            price = 1000 + i * 100
        _insert_record(session, rid=f"curr-{key}", source_name=_MART,
                       key=key, title=f"상품{i}", price=price, crawled_at=curr_mid)

    session.commit()


# ─────────────────────────────────────────────────────────────────────────────
# 1. compute_weekly_diff 정확성
# ─────────────────────────────────────────────────────────────────────────────

def test_compute_diff_disappeared(session):
    _seed_standard(session)
    report = compute_weekly_diff(session, mart=_MART, since=_T_CURR_SINCE, until=_T_CURR_UNTIL)

    disappeared_keys = {d["source_record_key"] for d in report.disappeared}
    assert disappeared_keys == {"sku-09", "sku-10"}, f"사라진 SKU 불일치: {disappeared_keys}"


def test_compute_diff_new_skus(session):
    _seed_standard(session)
    report = compute_weekly_diff(session, mart=_MART, since=_T_CURR_SINCE, until=_T_CURR_UNTIL)

    new_keys = {s["source_record_key"] for s in report.new_skus}
    assert new_keys == {"sku-11"}, f"신규 SKU 불일치: {new_keys}"


def test_compute_diff_retained_count(session):
    _seed_standard(session)
    report = compute_weekly_diff(session, mart=_MART, since=_T_CURR_SINCE, until=_T_CURR_UNTIL)

    # sku-01 ~ sku-08 = 8건 유지
    assert report.retained_count == 8, f"유지 count 불일치: {report.retained_count}"


def test_compute_diff_price_changes(session):
    _seed_standard(session)
    report = compute_weekly_diff(session, mart=_MART, since=_T_CURR_SINCE, until=_T_CURR_UNTIL)

    price_keys = {c["source_record_key"] for c in report.price_changes}
    assert "sku-01" in price_keys, f"가격변동 키 누락: {price_keys}"

    change = next(c for c in report.price_changes if c["source_record_key"] == "sku-01")
    assert change["old_price"] == 1100   # prev: 1000 + 1*100 = 1100
    assert change["new_price"] == 1200


def test_compute_diff_report_structure(session):
    _seed_standard(session)
    report = compute_weekly_diff(session, mart=_MART, since=_T_CURR_SINCE, until=_T_CURR_UNTIL)

    assert report.mart == _MART
    assert report.previous_window == (_T_PREV_SINCE, _T_PREV_UNTIL)
    assert report.current_window == (_T_CURR_SINCE, _T_CURR_UNTIL)

    d = report.to_dict()
    assert d["mart"] == _MART
    assert d["disappeared_count"] == 2
    assert d["new_skus_count"] == 1
    assert d["retained_count"] == 8


# ─────────────────────────────────────────────────────────────────────────────
# 2. alert 적재 + API 조회
# ─────────────────────────────────────────────────────────────────────────────

def test_persist_alerts_inserts_rows(session):
    _seed_standard(session)
    report = compute_weekly_diff(session, mart=_MART, since=_T_CURR_SINCE, until=_T_CURR_UNTIL)
    inserted = persist_alerts(session, report)
    session.commit()

    assert inserted == 2  # sku-09, sku-10

    # DB 확인
    rows = session.query(AlertDisappearedSkuModel).filter_by(mart=_MART).all()
    keys = {r.source_record_key for r in rows}
    assert keys == {"sku-09", "sku-10"}


def test_alerts_resolved_at_is_none_by_default(session):
    _seed_standard(session)
    report = compute_weekly_diff(session, mart=_MART, since=_T_CURR_SINCE, until=_T_CURR_UNTIL)
    persist_alerts(session, report)
    session.commit()

    rows = session.query(AlertDisappearedSkuModel).filter_by(mart=_MART).all()
    for row in rows:
        assert row.resolved_at is None


# ─────────────────────────────────────────────────────────────────────────────
# 3. FastAPI 엔드포인트 테스트 (TestClient + 세션 오버라이드)
# ─────────────────────────────────────────────────────────────────────────────

def _make_test_app(shared_session: Session):
    """weekly 라우터만 포함한 최소 FastAPI 앱. 인증 미적용."""
    from fastapi import FastAPI
    import api.routes.weekly as weekly_mod

    app = FastAPI()

    # 세션 팩토리를 테스트용으로 패치
    weekly_mod._engine = shared_session.bind
    weekly_mod._SessionLocal = sessionmaker(
        bind=shared_session.bind, autoflush=False, autocommit=False
    )

    app.include_router(weekly_mod.router)
    return app


def test_api_get_alerts_returns_open(engine):
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    sess = SessionLocal()

    _seed_standard(sess)
    report = compute_weekly_diff(sess, mart=_MART, since=_T_CURR_SINCE, until=_T_CURR_UNTIL)
    persist_alerts(sess, report)
    sess.commit()

    app = _make_test_app(sess)
    client = TestClient(app)

    resp = client.get("/api/weekly/alerts?status=open")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    keys = {d["source_record_key"] for d in data}
    assert keys == {"sku-09", "sku-10"}
    for d in data:
        assert d["status"] == "open"
        assert d["resolved_at"] is None

    sess.close()


def test_api_resolve_alert(engine):
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    sess = SessionLocal()

    _seed_standard(sess)
    report = compute_weekly_diff(sess, mart=_MART, since=_T_CURR_SINCE, until=_T_CURR_UNTIL)
    persist_alerts(sess, report)
    sess.commit()

    # alert id 조회
    alert = sess.query(AlertDisappearedSkuModel).filter_by(source_record_key="sku-09").first()
    assert alert is not None
    alert_id = alert.id

    app = _make_test_app(sess)
    client = TestClient(app)

    resp = client.post(f"/api/weekly/alerts/{alert_id}/resolve")
    assert resp.status_code == 200
    assert resp.json()["status"] == "resolved"

    # open 목록에서 빠졌는지 확인
    resp2 = client.get("/api/weekly/alerts?status=open")
    assert resp2.status_code == 200
    open_keys = {d["source_record_key"] for d in resp2.json()}
    assert "sku-09" not in open_keys
    assert "sku-10" in open_keys

    sess.close()


def test_api_resolve_then_not_in_open(engine):
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    sess = SessionLocal()

    _seed_standard(sess)
    report = compute_weekly_diff(sess, mart=_MART, since=_T_CURR_SINCE, until=_T_CURR_UNTIL)
    persist_alerts(sess, report)
    sess.commit()

    rows = sess.query(AlertDisappearedSkuModel).all()
    app = _make_test_app(sess)
    client = TestClient(app)

    # 모든 alert resolve
    for row in rows:
        resp = client.post(f"/api/weekly/alerts/{row.id}/resolve")
        assert resp.status_code == 200

    # open 이제 0건
    resp = client.get("/api/weekly/alerts?status=open")
    assert resp.status_code == 200
    assert resp.json() == []

    sess.close()


# ─────────────────────────────────────────────────────────────────────────────
# 4. 멱등 테스트 — 같은 window 재실행 시 alert 중복 적재 X
# ─────────────────────────────────────────────────────────────────────────────

def test_persist_alerts_idempotent(session):
    _seed_standard(session)
    report = compute_weekly_diff(session, mart=_MART, since=_T_CURR_SINCE, until=_T_CURR_UNTIL)

    inserted1 = persist_alerts(session, report)
    session.commit()
    inserted2 = persist_alerts(session, report)
    session.commit()
    inserted3 = persist_alerts(session, report)
    session.commit()

    assert inserted1 == 2
    assert inserted2 == 0, "재실행 시 중복 삽입 없어야 함"
    assert inserted3 == 0, "3번째도 중복 없어야 함"

    total_rows = session.query(AlertDisappearedSkuModel).filter_by(mart=_MART).count()
    assert total_rows == 2


def test_persist_alerts_idempotent_after_partial_resolve(session):
    _seed_standard(session)
    report = compute_weekly_diff(session, mart=_MART, since=_T_CURR_SINCE, until=_T_CURR_UNTIL)

    persist_alerts(session, report)
    session.commit()

    # sku-09만 resolve
    alert = session.query(AlertDisappearedSkuModel).filter_by(source_record_key="sku-09").first()
    alert.resolved_at = datetime(2025, 1, 16, 0, 0, 0)
    session.commit()

    # 재실행 — sku-09는 resolved 됐으니 재삽입 가능, sku-10은 open이므로 중복 안 됨
    inserted2 = persist_alerts(session, report)
    session.commit()

    assert inserted2 == 1  # sku-09 재삽입
    total_open = session.query(AlertDisappearedSkuModel).filter(
        AlertDisappearedSkuModel.mart == _MART,
        AlertDisappearedSkuModel.resolved_at.is_(None),
    ).count()
    assert total_open == 2  # sku-10 (기존 open) + sku-09 (새로 open)


# ─────────────────────────────────────────────────────────────────────────────
# 5. 엣지 케이스 — 빈 데이터 / 한 쪽만 비어있는 경우
# ─────────────────────────────────────────────────────────────────────────────

def test_compute_diff_both_empty(session):
    # 레코드 없음
    report = compute_weekly_diff(session, mart=_MART, since=_T_CURR_SINCE, until=_T_CURR_UNTIL)
    assert report.disappeared == []
    assert report.new_skus == []
    assert report.retained_count == 0
    assert report.price_changes == []


def test_compute_diff_only_current_has_data(session):
    """current window에만 데이터 — 모두 신규, 사라짐 0."""
    curr_mid = datetime(2025, 1, 11, 12, 0, 0)
    for i in range(1, 4):
        _insert_record(session, rid=f"c-{i}", source_name=_MART,
                       key=f"sku-{i:02d}", title=f"상품{i}", price=1000,
                       crawled_at=curr_mid)
    session.commit()

    report = compute_weekly_diff(session, mart=_MART, since=_T_CURR_SINCE, until=_T_CURR_UNTIL)
    assert report.disappeared == []
    assert len(report.new_skus) == 3
    assert report.retained_count == 0


def test_compute_diff_only_previous_has_data(session):
    """previous window에만 데이터 — 모두 사라짐, 신규 0."""
    prev_mid = datetime(2025, 1, 4, 12, 0, 0)
    for i in range(1, 4):
        _insert_record(session, rid=f"p-{i}", source_name=_MART,
                       key=f"sku-{i:02d}", title=f"상품{i}", price=1000,
                       crawled_at=prev_mid)
    session.commit()

    report = compute_weekly_diff(session, mart=_MART, since=_T_CURR_SINCE, until=_T_CURR_UNTIL)
    assert len(report.disappeared) == 3
    assert report.new_skus == []
    assert report.retained_count == 0


def test_persist_alerts_empty_report(session):
    """사라진 SKU가 없는 리포트 → 0 삽입."""
    report = WeeklyDiffReport(
        mart=_MART,
        previous_window=(_T_PREV_SINCE, _T_PREV_UNTIL),
        current_window=(_T_CURR_SINCE, _T_CURR_UNTIL),
        disappeared=[],
        new_skus=[],
        retained_count=5,
        price_changes=[],
    )
    inserted = persist_alerts(session, report)
    session.commit()
    assert inserted == 0
    assert session.query(AlertDisappearedSkuModel).count() == 0


def test_compute_diff_ignores_null_source_record_key(session):
    """source_record_key가 NULL인 레코드는 diff에서 제외."""
    curr_mid = datetime(2025, 1, 11, 12, 0, 0)
    # NULL key 레코드
    session.execute(text(
        """
        INSERT INTO raw_crawl_records
            (raw_record_id, batch_id, source_name, source_record_key, raw_title, raw_price, crawled_at)
        VALUES
            ('null-key-rec', 'batch-test', :mart, NULL, '제목없음', 999, :ts)
        """
    ), {"mart": _MART, "ts": curr_mid})
    session.commit()

    report = compute_weekly_diff(session, mart=_MART, since=_T_CURR_SINCE, until=_T_CURR_UNTIL)
    # NULL key는 신규에 포함되면 안 됨
    assert all(s["source_record_key"] is not None for s in report.new_skus)
