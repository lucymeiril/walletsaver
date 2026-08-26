"""Weekly diff contracts with physically separate history and alert databases.

The crawler owns this test completely: db-admin source code is not imported.
History fixtures expose only the current read contract used by weekly diff, while
``alert_disappeared_skus`` lives in a separate crawler-owned state database.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

_backend = Path(__file__).resolve().parents[1]
_shared = _backend.parent.parent / "shared"
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


_T_PREV_SINCE = datetime(2025, 1, 1)
_T_PREV_UNTIL = datetime(2025, 1, 8)
_T_CURR_SINCE = _T_PREV_UNTIL
_T_CURR_UNTIL = datetime(2025, 1, 15)
_MART = "emart"


def _memory_engine():
    return create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _make_history_engine():
    engine = _memory_engine()
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                display_name TEXT,
                mart TEXT,
                mart_native_code TEXT,
                canon_hash TEXT,
                is_active INTEGER NOT NULL DEFAULT 1
            )
        """))
        connection.execute(text("""
            CREATE TABLE discount_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                price INTEGER,
                source TEXT NOT NULL,
                crawled_at DATETIME NOT NULL,
                raw_data TEXT
            )
        """))
    return engine


def _make_alert_engine():
    engine = _memory_engine()
    AlertSkuBase.metadata.create_all(engine, checkfirst=True)
    return engine


@pytest.fixture
def history_engine():
    return _make_history_engine()


@pytest.fixture
def history_session(history_engine):
    SessionLocal = sessionmaker(bind=history_engine, autoflush=False, autocommit=False)
    sess = SessionLocal()
    try:
        yield sess
    finally:
        sess.close()


@pytest.fixture
def alert_engine():
    return _make_alert_engine()


@pytest.fixture
def alert_session(alert_engine):
    SessionLocal = sessionmaker(bind=alert_engine, autoflush=False, autocommit=False)
    sess = SessionLocal()
    try:
        yield sess
    finally:
        sess.close()


def _product_for_key(
    session: Session,
    key: str,
    title: str,
    mart: str = _MART,
) -> int:
    product_id = session.execute(
        text(
            "SELECT id FROM products "
            "WHERE mart=:mart AND mart_native_code=:key LIMIT 1"
        ),
        {"mart": mart, "key": key},
    ).scalar_one_or_none()
    if product_id is not None:
        return int(product_id)

    session.execute(
        text(
            "INSERT INTO products "
            "(name, display_name, mart, mart_native_code, canon_hash, is_active) "
            "VALUES (:name, :display_name, :mart, :key, :canon_hash, 1)"
        ),
        {
            "name": title,
            "display_name": title,
            "mart": mart,
            "key": key,
            "canon_hash": f"canon-{mart}-{key}",
        },
    )
    session.flush()
    return int(session.execute(
        text(
            "SELECT id FROM products "
            "WHERE mart=:mart AND mart_native_code=:key ORDER BY id DESC LIMIT 1"
        ),
        {"mart": mart, "key": key},
    ).scalar_one())


def _insert_observation(
    session: Session,
    *,
    key: str,
    title: str,
    price: int,
    crawled_at: datetime,
    raw_source_key: str | None = None,
    mart: str = _MART,
) -> None:
    product_id = _product_for_key(session, key, title, mart=mart)
    source_key = key if raw_source_key is None else raw_source_key
    raw_data = {} if source_key == "" else {"source_record_key": source_key}
    session.execute(
        text(
            "INSERT INTO discount_history "
            "(product_id, price, source, crawled_at, raw_data) "
            "VALUES (:product_id, :price, :source, :crawled_at, :raw_data)"
        ),
        {
            "product_id": product_id,
            "price": price,
            "source": mart,
            "crawled_at": crawled_at,
            "raw_data": json.dumps(raw_data, ensure_ascii=False),
        },
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


def test_compute_weekly_diff_against_discount_history(history_session):
    _seed_standard(history_session)

    report = compute_weekly_diff(
        history_session,
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


def test_latest_observation_wins_inside_each_window(history_session):
    _insert_observation(
        history_session,
        key="sku-01",
        title="상품1",
        price=1000,
        crawled_at=datetime(2025, 1, 4, 9),
    )
    _insert_observation(
        history_session,
        key="sku-01",
        title="상품1",
        price=1100,
        crawled_at=datetime(2025, 1, 6, 9),
    )
    _insert_observation(
        history_session,
        key="sku-01",
        title="상품1",
        price=1200,
        crawled_at=datetime(2025, 1, 10, 9),
    )
    _insert_observation(
        history_session,
        key="sku-01",
        title="상품1",
        price=1300,
        crawled_at=datetime(2025, 1, 13, 9),
    )
    history_session.commit()

    report = compute_weekly_diff(history_session, _MART, _T_CURR_SINCE, _T_CURR_UNTIL)

    assert report.retained_count == 1
    assert report.price_changes == [
        {
            "source_record_key": "sku-01",
            "old_price": 1100,
            "new_price": 1300,
            "pct_change": 18.18,
        }
    ]


def test_missing_raw_source_key_falls_back_to_real_product_identity(history_session):
    _insert_observation(
        history_session,
        key="native-42",
        raw_source_key="",
        title="fallback identity",
        price=1990,
        crawled_at=datetime(2025, 1, 11, 12),
    )
    history_session.commit()

    report = compute_weekly_diff(history_session, _MART, _T_CURR_SINCE, _T_CURR_UNTIL)

    assert [row["source_record_key"] for row in report.new_skus] == ["native-42"]


def test_other_mart_history_is_not_mixed(history_session):
    _insert_observation(
        history_session,
        key="hp-1",
        title="홈플러스 상품",
        price=3000,
        crawled_at=datetime(2025, 1, 11, 12),
        mart="homeplus",
    )
    history_session.commit()

    report = compute_weekly_diff(history_session, _MART, _T_CURR_SINCE, _T_CURR_UNTIL)

    assert report.new_skus == []


def test_persist_alerts_is_idempotent_while_alert_is_open(history_session, alert_session):
    _seed_standard(history_session)
    report = compute_weekly_diff(history_session, _MART, _T_CURR_SINCE, _T_CURR_UNTIL)

    assert persist_alerts(alert_session, report) == 2
    alert_session.commit()
    assert persist_alerts(alert_session, report) == 0
    alert_session.commit()

    assert alert_session.query(AlertDisappearedSkuModel).count() == 2


def test_weekly_alert_state_is_physically_separate(history_session, alert_session):
    _seed_standard(history_session)
    report = compute_weekly_diff(history_session, _MART, _T_CURR_SINCE, _T_CURR_UNTIL)
    persist_alerts(alert_session, report)
    alert_session.commit()

    history_tables = set(history_session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table'")
    ).scalars())
    alert_tables = set(alert_session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table'")
    ).scalars())

    assert "alert_disappeared_skus" not in history_tables
    assert "alert_disappeared_skus" in alert_tables


def test_resolved_alert_can_be_detected_again(history_session, alert_session):
    _seed_standard(history_session)
    report = compute_weekly_diff(history_session, _MART, _T_CURR_SINCE, _T_CURR_UNTIL)
    persist_alerts(alert_session, report)
    alert_session.commit()

    alert = (
        alert_session.query(AlertDisappearedSkuModel)
        .filter_by(mart=_MART, source_record_key="sku-09")
        .one()
    )
    alert.resolved_at = datetime(2025, 1, 16)
    alert_session.commit()

    assert persist_alerts(alert_session, report) == 1
    alert_session.commit()
    assert (
        alert_session.query(AlertDisappearedSkuModel)
        .filter_by(mart=_MART, source_record_key="sku-09", resolved_at=None)
        .count()
        == 1
    )


def test_empty_windows_are_valid(history_session):
    report = compute_weekly_diff(history_session, _MART, _T_CURR_SINCE, _T_CURR_UNTIL)
    assert report.disappeared == []
    assert report.new_skus == []
    assert report.retained_count == 0
    assert report.price_changes == []


def test_empty_report_does_not_create_alert(alert_session):
    report = WeeklyDiffReport(
        mart=_MART,
        previous_window=(_T_PREV_SINCE, _T_PREV_UNTIL),
        current_window=(_T_CURR_SINCE, _T_CURR_UNTIL),
    )
    assert persist_alerts(alert_session, report) == 0
    assert alert_session.query(AlertDisappearedSkuModel).count() == 0


def _make_test_app(alert_engine):
    from fastapi import FastAPI
    import api.routes.weekly as weekly_mod

    weekly_mod._alert_engine = alert_engine
    weekly_mod._AlertSessionLocal = sessionmaker(
        bind=alert_engine,
        autoflush=False,
        autocommit=False,
    )
    app = FastAPI()
    app.include_router(weekly_mod.router)
    return app


def test_weekly_alert_api_lists_and_resolves(history_session, alert_engine):
    AlertSessionLocal = sessionmaker(bind=alert_engine, autoflush=False, autocommit=False)
    with AlertSessionLocal() as alert_session:
        _seed_standard(history_session)
        report = compute_weekly_diff(history_session, _MART, _T_CURR_SINCE, _T_CURR_UNTIL)
        persist_alerts(alert_session, report)
        alert_session.commit()
        alert_id = (
            alert_session.query(AlertDisappearedSkuModel.id)
            .filter_by(source_record_key="sku-09")
            .scalar()
        )

    client = TestClient(_make_test_app(alert_engine))

    listed = client.get("/api/weekly/alerts?status=open")
    assert listed.status_code == 200
    assert {row["source_record_key"] for row in listed.json()} == {"sku-09", "sku-10"}

    resolved = client.post(f"/api/weekly/alerts/{alert_id}/resolve")
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"

    listed_again = client.get("/api/weekly/alerts?status=open")
    assert {row["source_record_key"] for row in listed_again.json()} == {"sku-10"}


def test_weekly_alert_api_rejects_unknown_status(alert_engine):
    client = TestClient(_make_test_app(alert_engine))
    response = client.get("/api/weekly/alerts?status=whatever")
    assert response.status_code == 400
