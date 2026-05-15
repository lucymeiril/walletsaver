"""Website serving acceptance over a locally persisted DB-admin publish dataset."""

from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from test_empty_db_ai_publish_public_shape import (
    ROOT,
    _ai_admin_stubbed_item,
    _crawler_like_record,
    _make_db_admin_client,
    _make_website_client,
    _submit_ai_ingestion_http,
    seed_catalog_taxonomy,
)

from storage.db import DBStorage
from storage.models import Base, DiscountHistory, Product


def _local_acceptance_db_url() -> tuple[str, Path]:
    db_dir = ROOT / ".pytest_cache" / "website-serving-acceptance"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / f"{uuid.uuid4().hex}.db"
    return f"sqlite:///{db_path}", db_path


def test_website_public_api_serves_db_admin_published_local_db(monkeypatch):
    db_url, db_path = _local_acceptance_db_url()
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=engine)
    storage = None

    try:
        Base.metadata.create_all(engine)
        db_admin_client = _make_db_admin_client(monkeypatch, Session)
        with Session.begin() as session:
            seed_catalog_taxonomy(session)

        record = _crawler_like_record()
        item = _ai_admin_stubbed_item(record)
        ingestion_id = _submit_ai_ingestion_http(db_admin_client, item)
        approve_response = db_admin_client.post(
            f"/api/ingestions/{ingestion_id}/ai-safe-final-approve",
            json={"action": "approve", "notes": "website serving acceptance local DB"},
        )
        assert approve_response.status_code == 200, approve_response.text
        assert approve_response.json()["saved"] == 1

        storage = DBStorage(db_url)
        storage.init_db()
        website_client = _make_website_client(storage)

        with Session() as session:
            product = session.execute(select(Product)).scalar_one()
            history = session.execute(select(DiscountHistory)).scalar_one()
            raw_data = history.raw_data

        detail_response = website_client.get(f"/api/products/{product.id}")
        assert detail_response.status_code == 200, detail_response.text
        public_product = detail_response.json()["data"]
        assert public_product["id"] == product.id
        assert public_product["name"] == product.name
        assert public_product["category_id"] == product.category_id
        assert public_product.get("price", public_product.get("cur")) == history.price
        assert public_product["source"] == history.source
        assert public_product["source_url"] == history.source_url
        assert public_product["source_url"] == raw_data["published_item"]["source_url"]
        assert public_product["price_observation_only"] is True

        search_response = website_client.get("/api/products/search", params={"q": "두부"})
        assert search_response.status_code == 200, search_response.text
        search_items = search_response.json()["data"]
        assert any(row["id"] == product.id and row["source_url"] == history.source_url for row in search_items)

        history_response = website_client.get(f"/api/products/{product.id}/price-history?days=30")
        assert history_response.status_code == 200, history_response.text
        public_history = history_response.json()["data"]
        assert public_history["point_count"] == 1
        assert public_history["current_offer"]["price"] == history.price
        assert public_history["current_offer"]["url"] == history.source_url
        assert public_history["history"][0]["source_url"] == history.source_url
        assert public_history["history"][0]["price_observation_only"] is True

        compare_response = website_client.get(f"/api/products/{product.id}/price-compare")
        assert compare_response.status_code == 200, compare_response.text
        compare_items = compare_response.json()["data"]
        assert compare_items
        assert compare_items[0]["source"] == history.source
        assert compare_items[0]["price"] == history.price
        assert compare_items[0]["source_url"] == history.source_url
        assert compare_items[0]["price_observation_only"] is True

        category_response = website_client.get(f"/api/products/category/{product.category_id}/compare")
        assert category_response.status_code == 200, category_response.text
        category_data = category_response.json()["data"]
        category_product = next(row for row in category_data["products"] if row["id"] == product.id)
        assert category_product["current_price"] == history.price
        assert category_product["source_url"] == history.source_url
        assert category_product["per_100g"] == raw_data["price_per_100g"]
    finally:
        if storage is not None:
            storage.SessionLocal.remove()
            storage.engine.dispose()
        engine.dispose()
        if db_path.exists():
            db_path.unlink()
