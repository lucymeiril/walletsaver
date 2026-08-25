"""DB 유지보수 API 회귀 테스트.

테스트 대상:
  - POST /api/admin/maintenance/purge (scope=raw|mappings|all)
  - POST /api/admin/maintenance/migrate
  - GET  /api/admin/maintenance/integrity

검증 포인트:
  1. confirm=true 누락 시 400
  2. 각 scope 가 의도한 테이블만 비운다
  3. AuditLog 가 DB에 영속화된다 (in-memory 가 아님)
  4. integrity 가 null / duplicate / orphan 을 모두 계수한다
"""

import os
# Rate limit 을 충분히 풀어둔다 — 테스트에서 destructive 5/min 제약이 걸리지 않게.
os.environ.setdefault("RATE_LIMIT_DESTRUCTIVE", "1000/minute")
os.environ.setdefault("RATE_LIMIT_ADMIN", "1000/minute")
os.environ.setdefault("RATE_LIMIT_GLOBAL", "10000/minute")

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from storage.models import (
    AuditLog,
    Base,
    BaselinePrice,
    Category,
    CategoryCorrection,
    CrawlLog,
    CrawlStatus,
    DiscountHistory,
    HotdealPrice,
    IngestionStatus,
    Keyword,
    PendingCategorization,
    PendingIngestion,
    Product,
    ProductKeyword,
)


@pytest.fixture
def factories(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    s = Session()
    s.add(Category(id="food", name="식품", depth=0, is_active=True))
    s.add(Product(id=1, name="우유", category_id="food", unit="L", source_type="emart", is_active=True))
    s.add(Product(id=2, name="우유", category_id="food", unit="L", source_type="emart", is_active=True))
    s.add(Product(id=3, name="", category_id=None, unit="개", source_type="emart", is_active=True))

    now = datetime.utcnow()
    s.add(BaselinePrice(product_id=1, price=1500, source="emart", unit="L", recorded_at=now))
    s.add(BaselinePrice(product_id=999, price=1500, source="emart", unit="L", recorded_at=now))
    s.add(DiscountHistory(product_id=1, price=1200, source="emart", crawled_at=now))
    s.add(HotdealPrice(product_id=1, price=1100, source="algumon", title="t", crawled_at=now))

    s.add(Keyword(id=1, word="우유", category_id="food"))
    s.add(ProductKeyword(product_id=1, keyword_id=1))
    s.add(CategoryCorrection(product_name_pattern="우유", wrong_category_id="food", correct_category_id="food"))
    s.add(PendingCategorization(product_id=1, suggested_category_id="food", confidence=0.5))

    s.add(PendingIngestion(crawler_name="emart", crawl_status="success", items_count=0, items_json="[]", schema_type="X", status=IngestionStatus.PENDING))
    s.add(CrawlLog(crawler_name="emart", status=CrawlStatus.SUCCESS, started_at=now, finished_at=now, items_found=10, items_saved=10))
    s.commit()
    s.close()

    def get_test_session():
        return Session()

    import services.base as base_module
    import api.routes.maintenance as maint

    monkeypatch.setattr(base_module, "get_session", get_test_session)
    monkeypatch.setattr(maint, "get_session", get_test_session)

    return Session


@pytest.fixture
def client(factories):
    from config import settings
    settings.REQUIRE_AUTH = False
    from api.app import create_app
    return TestClient(create_app())


def test_purge_requires_confirm(client):
    r = client.post("/api/admin/maintenance/purge", json={"scope": "raw", "confirm": False})
    assert r.status_code == 400


def test_purge_rejects_unknown_scope(client):
    r = client.post("/api/admin/maintenance/purge", json={"scope": "unknown", "confirm": True})
    assert r.status_code == 400


def test_purge_rejects_retired_canonical_scope(client):
    r = client.post("/api/admin/maintenance/purge", json={"scope": "canonical", "confirm": True})
    assert r.status_code == 400


def test_purge_raw_only(client, factories):
    Session = factories
    r = client.post("/api/admin/maintenance/purge", json={"scope": "raw", "confirm": True})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["scope"] == "raw"
    assert data["deleted"]["pending_ingestions"] >= 1
    assert data["deleted"]["crawl_logs"] >= 1

    s = Session()
    try:
        assert s.query(PendingIngestion).count() == 0
        assert s.query(CrawlLog).count() == 0
        assert s.query(Product).count() == 3
        assert s.query(Keyword).count() == 1
    finally:
        s.close()


def test_purge_mappings_only(client, factories):
    Session = factories
    r = client.post("/api/admin/maintenance/purge", json={"scope": "mappings", "confirm": True})
    assert r.status_code == 200
    data = r.json()
    assert data["deleted"]["keywords"] == 1
    assert data["deleted"]["product_keywords"] == 1
    s = Session()
    try:
        assert s.query(Keyword).count() == 0
        assert s.query(ProductKeyword).count() == 0
        assert s.query(CategoryCorrection).count() == 0
        assert s.query(PendingCategorization).count() == 0
        assert s.query(Product).count() == 3
        assert s.query(PendingIngestion).count() == 1
    finally:
        s.close()


def test_purge_all_wipes_everything_except_categories(client, factories):
    Session = factories
    r = client.post("/api/admin/maintenance/purge", json={"scope": "all", "confirm": True})
    assert r.status_code == 200
    s = Session()
    try:
        assert s.query(Product).count() == 0
        assert s.query(BaselinePrice).count() == 0
        assert s.query(DiscountHistory).count() == 0
        assert s.query(HotdealPrice).count() == 0
        assert s.query(Keyword).count() == 0
        assert s.query(PendingIngestion).count() == 0
        assert s.query(CrawlLog).count() == 0
        assert s.query(Category).count() == 1
    finally:
        s.close()


def test_purge_persists_audit_log_to_db(client, factories):
    Session = factories
    r = client.post(
        "/api/admin/maintenance/purge",
        json={"scope": "raw", "confirm": True, "note": "테스트 데이터 정리"},
    )
    assert r.status_code == 200
    s = Session()
    try:
        rows = s.query(AuditLog).filter(AuditLog.action == "maintenance.purge").all()
        assert len(rows) == 1
        row = rows[0]
        assert row.entity_type == "database"
        assert row.entity_id == "raw"
        assert row.new_value is not None
        assert "counts" in row.new_value
        assert row.new_value.get("note") == "테스트 데이터 정리"
    finally:
        s.close()


def test_integrity_reports_null_duplicate_orphan(client):
    r = client.get("/api/admin/maintenance/integrity")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["null"]["products_without_category"] >= 1
    assert data["null"]["products_without_name"] >= 1
    assert data["duplicates"]["products"] >= 1
    assert data["orphan_fk"]["baseline_prices"] >= 1
    assert data["issue_total"] >= 4


def test_migrate_invokes_alembic_and_audits(client, factories, monkeypatch):
    import api.routes.maintenance as maint

    class FakeCompleted:
        def __init__(self):
            self.returncode = 0
            self.stdout = "INFO  [alembic] upgrade to head OK"
            self.stderr = ""

    def fake_run(cmd, **kwargs):
        assert "alembic" in cmd
        assert "upgrade" in cmd
        return FakeCompleted()

    monkeypatch.setattr(maint.subprocess, "run", fake_run)
    r = client.post("/api/admin/maintenance/migrate", json={"revision": "head"})
    assert r.status_code == 200, r.text
    assert r.json()["returncode"] == 0

    Session = factories
    s = Session()
    try:
        rows = s.query(AuditLog).filter(AuditLog.action == "maintenance.migrate").all()
        assert len(rows) == 1
    finally:
        s.close()


def test_migrate_failure_returns_500_and_audits(client, factories, monkeypatch):
    import api.routes.maintenance as maint

    class FakeCompleted:
        returncode = 1
        stdout = ""
        stderr = "alembic ERROR: schema mismatch"

    monkeypatch.setattr(maint.subprocess, "run", lambda *a, **k: FakeCompleted())
    r = client.post("/api/admin/maintenance/migrate", json={"revision": "head"})
    assert r.status_code == 500
    Session = factories
    s = Session()
    try:
        rows = s.query(AuditLog).filter(AuditLog.action == "maintenance.migrate").all()
        assert len(rows) == 1
    finally:
        s.close()
