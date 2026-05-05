"""Website public catalog read boundary tests."""

import os
import sys

from fastapi.testclient import TestClient

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PACKAGES_DIR = os.path.dirname(os.path.dirname(_BACKEND_DIR))
sys.path.insert(0, _BACKEND_DIR)
sys.path.insert(0, os.path.join(_PACKAGES_DIR, "shared"))

from api.app import create_app
from api.utils.public_catalog import PublicCatalogReader


class FakeCatalogStorage:
    def get_product_detail(self, product_id):
        if product_id != 1:
            return None
        return {"id": 1, "name": "오리온 오징어땅콩", "price": 2990, "unit": "202g"}

    def get_price_history(self, product_id, days):
        if product_id != 1:
            return []
        return [
            {"date": "2026-04-01", "price": 3990, "source": "emart"},
            {"date": "2026-04-15", "price": 3490, "source": "homeplus"},
            {"date": "2026-04-30", "price": 2990, "source": "emart"},
        ]

    def get_price_compare(self, product_id):
        if product_id != 1:
            return []
        return [
            {"source": "emart", "price": 2990},
            {"source": "coupang", "price": 3590},
        ]


class SparseCatalogStorage(FakeCatalogStorage):
    def get_product_detail(self, product_id):
        if product_id != 3:
            return None
        return {"id": 3, "name": "신규 상품", "price": 4500, "unit": "1개", "source": "emart"}

    def get_price_history(self, product_id, days):
        return []

    def get_price_compare(self, product_id):
        return []


class PipelineCatalogStorage:
    def get_product_detail(self, product_id):
        if product_id != 2:
            return None
        return {
            "product": {
                "public_product_id": "prod-orion-squid-peanut",
                "canonical_name": "오리온 오징어땅콩",
                "category_id": "snack.nut",
                "keywords": ["오징어땅콩", "과자"],
                "brand": "오리온",
            },
            "variant": {
                "public_variant_id": "var-202g",
                "variant_name": "오리온 오징어땅콩 202g",
                "package_quantity": 202,
                "package_unit": "g",
                "standard_unit": "100g",
            },
            "offer": {
                "public_offer_id": "offer-emart",
                "source_name": "emart",
                "source_title": "오리온 오징어땅콩 202g 행사",
                "source_url": "https://example.test/offer",
                "image_url": "https://example.test/squid-peanut.jpg",
                "price": 2990,
                "original_price": 3990,
                "standard_unit_price": 1480.2,
                "price_per_100g": 1480.2,
                "raw_evidence": {"raw_unit": "202g"},
            },
        }

    def get_price_history(self, product_id, days):
        if product_id != 2:
            return []
        return [
            {"date": "2026-04-01", "price": 3990, "source_name": "emart"},
            {"date": "2026-04-30", "price": 2990, "source_name": "emart"},
        ]

    def get_price_compare(self, product_id):
        if product_id != 2:
            return []
        return [
            {"source_name": "emart", "price": 2990},
            {"source_name": "homeplus", "price": 3190},
        ]


def test_public_catalog_reader_builds_trust_summary():
    reader = PublicCatalogReader(FakeCatalogStorage())

    summary = reader.get_price_trust_summary(1)

    assert summary["current_price"] == 2990
    assert summary["historical_low_price"] == 2990
    assert summary["source_low_price"] == 2990
    assert summary["hotdeal_score"] >= 90
    assert "최저가" in summary["rationale"]


def test_public_catalog_reader_builds_stable_empty_price_history_summary():
    reader = PublicCatalogReader(SparseCatalogStorage())

    summary = reader.get_price_history_summary(3, 30)

    assert summary["history"] == []
    assert summary["points"] == []
    assert summary["point_count"] == 0
    assert summary["current_offer"]["price"] == 4500
    assert summary["average_price"] is None
    assert summary["min_price"] is None
    assert summary["max_price"] is None
    assert "현재 확인된 가격" in summary["message"]


def test_product_trust_endpoint_uses_public_read_boundary():
    client = TestClient(create_app(storage=FakeCatalogStorage()))

    resp = client.get("/api/products/1/trust")

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["product_id"] == 1
    assert body["data"]["reference_count"] == 5


def test_product_price_history_endpoint_returns_summary_shape():
    client = TestClient(create_app(storage=FakeCatalogStorage()))

    resp = client.get("/api/products/1/price-history?days=30")

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    assert data["product_id"] == 1
    assert data["point_count"] == 3
    assert len(data["history"]) == 3
    assert data["current_offer"]["price"] == 2990
    assert data["average_price"] == 3490
    assert data["min_price"] == 2990
    assert data["max_price"] == 3990


def test_product_price_history_endpoint_returns_empty_for_product_without_history():
    client = TestClient(create_app(storage=SparseCatalogStorage()))

    resp = client.get("/api/products/3/price-history?days=30")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["history"] == []
    assert data["is_sparse"] is True
    assert data["current_offer"]["price"] == 4500


def test_product_endpoint_flattens_approved_pipeline_public_catalog_data():
    client = TestClient(create_app(storage=PipelineCatalogStorage()))

    resp = client.get("/api/products/2")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["name"] == "오리온 오징어땅콩"
    assert data["category_id"] == "snack.nut"
    assert data["keywords"] == ["오징어땅콩", "과자"]
    assert data["source"] == "emart"
    assert data["source_title"] == "오리온 오징어땅콩 202g 행사"
    assert data["price"] == 2990
    assert data["original_price"] == 3990
    assert data["unit"] == "202g"
    assert data["standard_unit_price"] == 1480.2
    assert data["image_url"] == "https://example.test/squid-peanut.jpg"
    assert data["price_per_100g"] == 1480.2


def test_product_trust_endpoint_uses_pipeline_price_history_and_source_offers():
    client = TestClient(create_app(storage=PipelineCatalogStorage()))

    resp = client.get("/api/products/2/trust")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["current_price"] == 2990
    assert data["standard_unit_price"] == 1480.2
    assert data["source_low_price"] == 2990
    assert data["reference_count"] == 4
    assert "최저가" in data["rationale"]


def test_product_trust_endpoint_returns_404_when_product_missing():
    client = TestClient(create_app(storage=FakeCatalogStorage()))

    resp = client.get("/api/products/404/trust")

    assert resp.status_code == 404
