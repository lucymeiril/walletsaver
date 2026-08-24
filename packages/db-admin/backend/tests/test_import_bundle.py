"""Focused integration tests for the current external-classification bundle contract."""
from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).parent.parent
SHARED_ROOT = BACKEND_ROOT.parent.parent / "shared"
for path in (str(BACKEND_ROOT), str(SHARED_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from core.match_key import NO_BRAND_SENTINEL, build_match_key
from storage.models import Base, BaselinePrice, Category, Keyword, MatchingEntry, Product


LEGACY_KEY = "CJ|햇반|210.000000|g"
CANONICAL_KEY = build_match_key("CJ", "햇반", 210, "g")

MATCHING_ROW = {
    "match_key": LEGACY_KEY,
    "brand": "CJ",
    "name_core": "햇반",
    "pack_qty": 210.0,
    "pack_unit": "g",
    "category_id": "food.rice",
    "keyword_ids": [1],
    "confidence": 0.95,
    "source": "external-ai",
}
PRODUCT_ROW = {
    "raw_id": "emart-1",
    "raw_name": "CJ 햇반 210g",
    "match_key": LEGACY_KEY,
    "price": 1680,
    "mart": "emart",
    "captured_at": "2026-08-24T00:00:00+00:00",
}


def _jsonl(rows: list[dict]) -> bytes:
    return "\n".join(json.dumps(row, ensure_ascii=False) for row in rows).encode("utf-8")


@pytest.fixture()
def db_fixture(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    with Session() as session:
        session.add_all(
            [
                Category(id="food", name="식품", depth=0, is_active=True),
                Category(id="food.rice", name="쌀/즉석밥", parent_id="food", depth=1, is_active=True),
                Keyword(id=1, word="즉석밥", category_id="food.rice", is_active=True),
            ]
        )
        session.commit()

    def get_test_session():
        return Session()

    @contextmanager
    def managed_test_session():
        session = Session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    import api.routes.import_bundle as routes

    monkeypatch.setattr(routes, "get_session", get_test_session)
    monkeypatch.setattr(routes, "managed_session", managed_test_session)
    routes._confirmed_bundles.clear()
    routes._bundle_failures.clear()

    yield Session
    engine.dispose()


@pytest.fixture()
def client(db_fixture):
    from api.routes.import_bundle import router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


def _bundle_files(matching_rows=None, product_rows=None):
    files = {}
    if matching_rows is not None:
        files["matching_file"] = (
            "matching_updates.jsonl",
            _jsonl(matching_rows),
            "application/octet-stream",
        )
    if product_rows is not None:
        files["products_file"] = (
            "products.jsonl",
            _jsonl(product_rows),
            "application/octet-stream",
        )
    return files


def test_preview_remaps_legacy_matching_and_product_keys(client):
    response = client.post(
        "/api/import/bundle/preview",
        files=_bundle_files([MATCHING_ROW], [PRODUCT_ROW]),
        data={"mode": "strict"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["matching"]["to_add"] == 1
    assert body["products"]["to_add"] == 1
    assert body["products"]["skipped_no_match"] == 0


def test_confirm_persists_only_canonical_key_and_links_product(client, db_fixture):
    response = client.post(
        "/api/import/bundle/confirm",
        files=_bundle_files([MATCHING_ROW], [PRODUCT_ROW]),
        data={"mode": "strict", "batch_id": "canonical-bundle"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["matching_inserted"] == 1
    assert body["products_processed"] == 1
    assert body["products_created"] == 1
    assert body["products_skipped"] == 0

    Session = db_fixture
    with Session() as session:
        entry = session.query(MatchingEntry).filter_by(match_key=CANONICAL_KEY).one()
        assert session.query(MatchingEntry).filter_by(match_key=LEGACY_KEY).first() is None
        assert entry.canonical_product_id not in (None, "")
        product = session.get(Product, int(entry.canonical_product_id))
        assert product is not None
        assert product.brand == "CJ"
        assert session.query(BaselinePrice).filter_by(product_id=product.id).count() == 1


def test_confirm_is_idempotent_for_same_batch_id(client, db_fixture):
    files = _bundle_files([MATCHING_ROW], [PRODUCT_ROW])
    first = client.post(
        "/api/import/bundle/confirm",
        files=files,
        data={"mode": "strict", "batch_id": "same-batch"},
    )
    assert first.status_code == 200

    second = client.post(
        "/api/import/bundle/confirm",
        files=_bundle_files([MATCHING_ROW], [PRODUCT_ROW]),
        data={"mode": "strict", "batch_id": "same-batch"},
    )
    assert second.status_code == 200
    assert second.json()["idempotent"] is True

    Session = db_fixture
    with Session() as session:
        assert session.query(MatchingEntry).count() == 1
        assert session.query(BaselinePrice).count() == 1


def test_human_matching_entry_cannot_be_overwritten_by_external_ai(client, db_fixture):
    Session = db_fixture
    with Session() as session:
        session.add(
            MatchingEntry(
                match_key=CANONICAL_KEY,
                brand="CJ",
                name_core="햇반",
                pack_qty=210,
                pack_unit="g",
                category_id="food.rice",
                keyword_ids=[1],
                confidence=1.0,
                source="human",
                hit_count=0,
            )
        )
        session.commit()

    incoming = {**MATCHING_ROW, "category_id": "food", "confidence": 0.99}
    response = client.post(
        "/api/import/bundle/confirm",
        files=_bundle_files([incoming], None),
        data={"mode": "lenient", "batch_id": "human-protected"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["matching_conflicts"] == 1
    with Session() as session:
        entry = session.query(MatchingEntry).filter_by(match_key=CANONICAL_KEY).one()
        assert entry.source == "human"
        assert entry.category_id == "food.rice"


def test_brandless_alias_becomes_stable_sentinel_product(client, db_fixture):
    legacy_brandless_key = "브랜드없음|두부|300.000000|g"
    matching = {
        "match_key": legacy_brandless_key,
        "brand": "브랜드없음",
        "name_core": "두부",
        "pack_qty": 300,
        "pack_unit": "g",
        "category_id": "food",
        "keyword_ids": [],
        "confidence": 0.9,
        "source": "external-ai",
    }
    product = {
        "raw_id": "homeplus-1",
        "match_key": legacy_brandless_key,
        "price": 2000,
        "mart": "homeplus",
    }

    response = client.post(
        "/api/import/bundle/confirm",
        files=_bundle_files([matching], [product]),
        data={"mode": "strict", "batch_id": "brandless"},
    )
    assert response.status_code == 200, response.text

    expected_key = build_match_key(None, "두부", 300, "g")
    Session = db_fixture
    with Session() as session:
        entry = session.query(MatchingEntry).filter_by(match_key=expected_key).one()
        assert entry.brand == NO_BRAND_SENTINEL
        linked = session.get(Product, int(entry.canonical_product_id))
        assert linked is not None
        assert linked.brand == NO_BRAND_SENTINEL


def test_strict_invalid_category_rolls_back_matching_insert(client, db_fixture):
    invalid = {**MATCHING_ROW, "category_id": "does.not.exist"}
    response = client.post(
        "/api/import/bundle/confirm",
        files=_bundle_files([invalid], None),
        data={"mode": "strict", "batch_id": "bad-category"},
    )

    assert response.status_code == 422
    Session = db_fixture
    with Session() as session:
        assert session.query(MatchingEntry).count() == 0
