"""Weekly diff contracts against the real db-admin price schema.

The regression suite must not recreate retired raw tables. Test data is stored
through db-admin's actual Product and DiscountHistory ORM models, which are the
same tables populated by approved crawler ingestions.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

_backend = Path(__file__).resolve().parents[1]
_shared = _backend.parent.parent / "shared"
_db_admin_backend = _backend.parent.parent / "db-admin" / "backend"

for _path in (_backend, _shared):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from services.weekly_diff import (
    AlertDisappearedSkuModel,
    AlertSkuBase,
    WeeklyDiffReport,
    compute_weekly_diff,
    persist_alerts,
)

# Add db-admin after crawler-admin imports so ``services`` continues to resolve
# to crawler-admin while ``storage.models`` resolves to the canonical working DB
# schema used by ingestion approval.
if str(_db_admin_backend) not in sys.path:
    sys.path.append(str(_db_admin_backend))

from storage.models import Category, DiscountHistory, Product, UnifiedCategory


_T_PREV_SINCE = datetime(2025, 1, 1)
_T_PREV_UNTIL = datetime(2025, 1, 8)
_T_CURR_SINCE = _T_PREV_UNTIL
_T_CURR_UNTIL = datetime(2025, 1, 15)
_MART = "emart"


def _make_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Use actual db-admin table objects; never hand-roll a substitute schema.
    for table in (
        Category.__table__,
        UnifiedCategory.__table__,
        Product.__table__,
        DiscountHistory.__table__,
    ):
        table.create(engine, checkfirst=True)
    AlertSkuBase.metadata.create_all(engine, checkfirst=True)
    return engine


@pytest.fixture
def engine():
    return _make_engine()


@pytest.fixture
def session(engine):
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    sess = SessionLocal()
    try:
        yield sess
    finally:
        sess.close()


def _product_for_key(session: Session, key: str, title: str) -> Product:
    product = (
        session.query(Product)
        .filter(Product.mart == _MART, Product.mart_native_code == key)
        .one_or_none()
    )
    if product is not None:
        return product

    product = Product(
        name=title,
        display_name=title,
        unit="개",
        source_type="mart_crawl",
        mart=_MART,
        mart_native_code=key,
        canon_hash=f"canon-{key}",
        is_active=True,
    )
    session.add(product)
    session.flush()
    return product


def _insert_observation(
    session: Session,
    *,
    key: str,
    title: str,
    price: int,
    crawled_at: datetime,
    raw_source_key: str | None = None,
) -> None:
    product = _product_for_key(session, key, title)
    source_key = key if raw_source_key is None else raw_source_key
    raw_data = {} if source_key == "" else {"source_record_key": source_key}
    session.add(
        DiscountHistory(
            product_id=product.id,
            price=price,
            original_price=None,
            discount_rate=None,
            source=_MART,
            source_url=f"https://example.test/{key}",
            crawled_at=crawled_at,
            raw_data=raw_data,
        )
    )


def _seed_standard(session: Session) -> None:
    prev_mid = datetime(2025, 1, 4, 12)
    curr_mid = datetime(2025, 1, 11, 12)

    for i in range(1, 11):
        key = f"sku-{i:02d}"
        _insert_observation(
            session,
            key=key,
            title=f"상품{i}",
            price=1000 + i * 100,
            crawled_at=prev_mid,
        )

    for i in [*range(1, 9), 11]:
        key = f"sku-{i:02d}"
        price = 1200 if i == 1 else 500 if i == 11 else 1000 + i * 100
        _insert_observation(
            session,
            key=key,
            title=f"상품{i}",
            price=price,
            crawled_at=curr_mid,
        )
    session.commit()


def test_compute_weekly_diff_against_discount_history(session):
    _seed_standard(session)

    report = compute_weekly_diff(
        session,
        mart=_MART,
        since=_T_CURR_SINCE,
        until=_T_CURR_UNTIL,
    )

    assert {row["source_record_key"] for row in report.disappeared} == {"sku-09", "sku-10"}
    assert {row["source_record_key"] for row in report.new_skus} == {"sku-11"}
    assert report.retained_count == 8
    change = next(row for row in report.price_changes if row["source_record_key"] == "sku-01")
    assert change["old_price"] == 1100
    assert change["new_price"] == 1200
    assert change["pct_change"] == pytest.approx(9.09, abs=0.01)

    payload = report.to_dict()
    assert payload["disappeared_count"] == 2
    assert payload["new_skus_count"] == 1
    assert payload["price_changes_count"] == 1


def test_latest_observation_wins_inside_each_window(session):
    _insert_observation(
        session,
        key="sku-01",
        title="상품1",
        price=1000,
        crawled_at=datetime(2025, 1, 4, 9),
    )
    _insert_observation(
        session,
        key="sku-01",
        title="상품1",
        price=1100,
        crawled_at=datetime(2025, 1, 6, 9),
    )
    _insert_observation(
        session,
        key="sku-01",
        title="상품1",
        price=1200,
        crawled_at=datetime(2025, 1, 10, 9),
    )
    _insert_observation(
        session,
        key="sku-01",
        title="상품1",
        price=1300,
        crawled_at=datetime(2025, 1, 13, 9),
    )
    session.commit()

    report = compute_weekly_diff(session, _MART, _T_CURR_SINCE, _T_CURR_UNTIL)

    assert report.retained_count == 1
    assert report.price_changes == [
        {
            "source_record_key": "sku-01",
            "old_price": 1100,
            "new_price": 1300,
            "pct_change": 18.18,
        }
    ]


def test_missing_raw_source_key_falls_back_to_real_product_identity(session):
    _insert_observation(
        session,
        key="native-42",
        raw_source_key="",
        title="fallback identity",
        price=1990,
        crawled_at=datetime(2025, 1, 11, 12),
    )
    session.commit()

    report = compute_weekly_diff(session, _MART, _T_CURR_SINCE, _T_CURR_UNTIL)

    assert [row["source_record_key"] for row in report.new_skus] == ["native-42"]


def test_other_mart_history_is_not_mixed(session):
    product = Product(
        name="홈플러스 상품",
        display_name="홈플러스 상품",
        unit="개",
        source_type="mart_crawl",
        mart="homeplus",
        mart_native_code="hp-1",
        canon_hash="canon-hp-1",
        is_active=True,
    )
    session.add(product)
    session.flush()
    session.add(
        DiscountHistory(
            product_id=product.id,
            price=3000,
            source="homeplus",
            crawled_at=datetime(2025, 1, 11, 12),
            raw_data={"source_record_key": "hp-1"},
        )
    )
    session.commit()

    report = compute_weekly_diff(session, _MART, _T_CURR_SINCE, _T_CURR_UNTIL)

    assert report.new_skus == []


def test_persist_alerts_is_idempotent_while_alert_is_open(session):
    _seed_standard(session)
    report = compute_weekly_diff(session, _MART, _T_CURR_SINCE, _T_CURR_UNTIL)

    assert persist_alerts(session, report) == 2
    session.commit()
    assert persist_alerts(session, report) == 0
    session.commit()

    assert session.query(AlertDisappearedSkuModel).count() == 2


def test_resolved_alert_can_be_detected_again(session):
    _seed_standard(session)
    report = compute_weekly_diff(session, _MART, _T_CURR_SINCE, _T_CURR_UNTIL)
    persist_alerts(session, report)
    session.commit()

    alert = (
        session.query(AlertDisappearedSkuModel)
        .filter_by(mart=_MART, source_record_key="sku-09")
        .one()
    )
    alert.resolved_at = datetime(2025, 1, 16)
    session.commit()

    assert persist_alerts(session, report) == 1
    session.commit()
    assert (
        session.query(AlertDisappearedSkuModel)
        .filter_by(mart=_MART, source_record_key="sku-09", resolved_at=None)
        .count()
        == 1
    )


def test_empty_windows_are_valid(session):
    report = compute_weekly_diff(session, _MART, _T_CURR_SINCE, _T_CURR_UNTIL)
    assert report.disappeared == []
    assert report.new_skus == []
    assert report.retained_count == 0
    assert report.price_changes == []


def test_empty_report_does_not_create_alert(session):
    report = WeeklyDiffReport(
        mart=_MART,
        previous_window=(_T_PREV_SINCE, _T_PREV_UNTIL),
        current_window=(_T_CURR_SINCE, _T_CURR_UNTIL),
    )
    assert persist_alerts(session, report) == 0
    assert session.query(AlertDisappearedSkuModel).count() == 0


def _make_test_app(engine):
    from fastapi import FastAPI
    import api.routes.weekly as weekly_mod

    weekly_mod._engine = engine
    weekly_mod._SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    app = FastAPI()
    app.include_router(weekly_mod.router)
    return app


def test_weekly_alert_api_lists_and_resolves(engine):
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with SessionLocal() as sess:
        _seed_standard(sess)
        report = compute_weekly_diff(sess, _MART, _T_CURR_SINCE, _T_CURR_UNTIL)
        persist_alerts(sess, report)
        sess.commit()
        alert_id = (
            sess.query(AlertDisappearedSkuModel.id)
            .filter_by(source_record_key="sku-09")
            .scalar()
        )

    client = TestClient(_make_test_app(engine))

    listed = client.get("/api/weekly/alerts?status=open")
    assert listed.status_code == 200
    assert {row["source_record_key"] for row in listed.json()} == {"sku-09", "sku-10"}

    resolved = client.post(f"/api/weekly/alerts/{alert_id}/resolve")
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"

    listed_again = client.get("/api/weekly/alerts?status=open")
    assert {row["source_record_key"] for row in listed_again.json()} == {"sku-10"}


def test_weekly_alert_api_rejects_unknown_status(engine):
    client = TestClient(_make_test_app(engine))
    response = client.get("/api/weekly/alerts?status=whatever")
    assert response.status_code == 400
