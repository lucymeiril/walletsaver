"""Website public catalog read boundary tests."""

import os
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


def test_public_catalog_reader_builds_trust_summary():
    reader = PublicCatalogReader(FakeCatalogStorage())

    summary = reader.get_price_trust_summary(1)

    assert summary["current_price"] == 2990
    assert summary["historical_low_price"] == 2990
    assert summary["source_low_price"] == 2990
    assert summary["hotdeal_score"] >= 90
    assert "최저가" in summary["rationale"]


def test_product_trust_endpoint_uses_public_read_boundary():
    client = TestClient(create_app(storage=FakeCatalogStorage()))

    resp = client.get("/api/products/1/trust")

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["product_id"] == 1
    assert body["data"]["reference_count"] == 5


def test_product_trust_endpoint_returns_404_when_product_missing():
    client = TestClient(create_app(storage=FakeCatalogStorage()))

    resp = client.get("/api/products/404/trust")

    assert resp.status_code == 404
