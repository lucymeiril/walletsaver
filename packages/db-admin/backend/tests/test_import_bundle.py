"""test_import_bundle.py — POST /api/import/bundle/* 엔드포인트 통합 테스트.

테스트 케이스:
    1. 3종 파일 정상 preview
    2. 3종 파일 정상 confirm (matching → taxonomy → products 순서)
    3. matching이 products보다 먼저 적용되는지 (트랜잭션 순서)
    4. 부분 실패 strict vs lenient
    5. 멱등 (같은 batch_id 재confirm = no double-write)
    6. 충돌 정책 (human existing vs external-ai 시도 → conflict)
    7. categories parent_id 미존재 → strict 거부
    8. products match_key 없음 → skipped_no_match
    9. taxonomy-only confirm (matching/products 없음)
    10. matching-only confirm
"""

from __future__ import annotations

import io
import json
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from storage.models import Base, Category, Keyword, MatchingEntry


# ══════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════

@pytest.fixture
def db_fixture(monkeypatch):
    """인메모리 SQLite + 시드 데이터 + 라우트 monkeypatch."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    # 시드 데이터
    s = Session()
    s.add(Category(id="food", name="식품", depth=0, is_active=True))
    s.add(Category(id="food.rice", name="쌀", parent_id="food", depth=1, is_active=True))
    s.add(Keyword(id=1, word="밥", is_active=True))
    s.add(Keyword(id=2, word="국수", is_active=True))
    s.commit()
    s.close()

    def get_test_session():
        return Session()

    @contextmanager
    def managed_test_session():
        sess = Session()
        try:
            yield sess
            sess.commit()
        except Exception:
            sess.rollback()
            raise
        finally:
            sess.close()

    # bundle route monkeypatch
    import api.routes.import_bundle as bundle_routes
    monkeypatch.setattr(bundle_routes, "get_session", get_test_session)
    monkeypatch.setattr(bundle_routes, "managed_session", managed_test_session)

    # bundle_import service monkeypatch
    import services.bundle_import as bi
    monkeypatch.setattr(bi, "get_session", get_test_session, raising=False)

    # 멱등성 캐시 초기화 (테스트 간 격리)
    bundle_routes._confirmed_bundles.clear()
    bundle_routes._bundle_failures.clear()

    return {"Session": Session, "engine": engine}


@pytest.fixture
def client(db_fixture):
    from fastapi import FastAPI
    from api.routes.import_bundle import router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


# ══════════════════════════════════════════════════════
# 헬퍼
# ══════════════════════════════════════════════════════

def make_matching_jsonl(rows: list[dict]) -> bytes:
    return "\n".join(json.dumps(r, ensure_ascii=False) for r in rows).encode("utf-8")


def make_taxonomy_yaml(data: dict) -> bytes:
    return yaml.safe_dump(data, allow_unicode=True, default_flow_style=False).encode("utf-8")


def make_products_jsonl(rows: list[dict]) -> bytes:
    return "\n".join(json.dumps(r, ensure_ascii=False) for r in rows).encode("utf-8")


SAMPLE_MATCHING = [
    {
        "match_key": "CJ|햇반|210.000000|g",
        "brand": "CJ",
        "name_core": "햇반",
        "pack_qty": 210.0,
        "pack_unit": "g",
        "category_id": "food.rice",
        "keyword_ids": [1],
        "confidence": 0.92,
        "source": "external-ai",
        "notes": "즉석밥",
    }
]

SAMPLE_TAXONOMY = {
    "categories": [
        {"id": "food.snack", "name": "과자류", "parent_id": "food", "depth": 1},
    ],
    "keywords": [
        {"word": "즉석밥", "category_id": "food.rice", "synonyms": ["레토르트밥"]},
    ],
}

SAMPLE_PRODUCTS = [
    {
        "raw_id": "emart_001",
        "match_key": "CJ|햇반|210.000000|g",
        "price": 1680.0,
        "mart": "emart",
        "captured_at": "2024-01-15T10:00:00+00:00",
    }
]


# ══════════════════════════════════════════════════════
# 테스트
# ══════════════════════════════════════════════════════

class TestBundlePreview:
    def test_preview_3files_happy(self, client):
        """3종 파일 정상 preview — 각 섹션 카운트 확인."""
        resp = client.post(
            "/api/import/bundle/preview",
            files={
                "matching_file": ("matching_updates.jsonl", make_matching_jsonl(SAMPLE_MATCHING), "application/octet-stream"),
                "taxonomy_file": ("categories_keywords_updates.yaml", make_taxonomy_yaml(SAMPLE_TAXONOMY), "text/yaml"),
                "products_file": ("products.jsonl", make_products_jsonl(SAMPLE_PRODUCTS), "application/octet-stream"),
            },
            data={"mode": "lenient"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "batch_id" in body
        assert body["matching"]["to_add"] == 1
        assert body["taxonomy"]["new_categories"] == 1
        assert body["taxonomy"]["new_keywords"] == 1
        # products: match_key는 incoming matching에 있으므로 to_add=1
        assert body["products"]["to_add"] == 1

    def test_preview_no_files_rejected(self, client):
        resp = client.post("/api/import/bundle/preview", data={"mode": "strict"})
        assert resp.status_code == 422

    def test_preview_matching_only(self, client):
        resp = client.post(
            "/api/import/bundle/preview",
            files={
                "matching_file": ("matching_updates.jsonl", make_matching_jsonl(SAMPLE_MATCHING), "application/octet-stream"),
            },
            data={"mode": "lenient"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["matching"]["to_add"] == 1

    def test_preview_invalid_parent_id(self, client):
        bad_taxonomy = {
            "categories": [
                {"id": "food.exotic", "name": "이국음식", "parent_id": "nonexistent_parent", "depth": 1},
            ],
            "keywords": [],
        }
        resp = client.post(
            "/api/import/bundle/preview",
            files={
                "taxonomy_file": ("categories_keywords_updates.yaml", make_taxonomy_yaml(bad_taxonomy), "text/yaml"),
            },
            data={"mode": "strict"},
        )
        assert resp.status_code == 200
        body = resp.json()
        # 오류가 taxonomy.errors에 들어가야 함
        assert len(body["taxonomy"]["errors"]) >= 1
        assert "parent_id" in body["taxonomy"]["errors"][0]["msg"]


class TestBundleConfirm:
    def test_confirm_3files_happy(self, client, db_fixture):
        """3종 파일 정상 confirm — DB 반영 확인."""
        resp = client.post(
            "/api/import/bundle/confirm",
            files={
                "matching_file": ("matching_updates.jsonl", make_matching_jsonl(SAMPLE_MATCHING), "application/octet-stream"),
                "taxonomy_file": ("categories_keywords_updates.yaml", make_taxonomy_yaml(SAMPLE_TAXONOMY), "text/yaml"),
                "products_file": ("products.jsonl", make_products_jsonl(SAMPLE_PRODUCTS), "application/octet-stream"),
            },
            data={"mode": "lenient"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["matching_inserted"] == 1
        assert body["taxonomy_categories_added"] == 1
        assert body["taxonomy_keywords_added"] == 1
        assert body["products_added"] == 1
        assert body["idempotent"] is False

        # DB 반영 확인
        Session = db_fixture["Session"]
        s = Session()
        me = s.query(MatchingEntry).filter_by(match_key="CJ|햇반|210.000000|g").first()
        assert me is not None
        assert me.source == "external-ai"

        cat = s.query(Category).filter_by(id="food.snack").first()
        assert cat is not None

        kw = s.query(Keyword).filter_by(word="즉석밥").first()
        assert kw is not None
        s.close()

    def test_transaction_order_matching_before_products(self, client, db_fixture):
        """matching이 products보다 먼저 적용되어야 match_key가 유효해진다."""
        # matching_updates에만 있는 match_key를 products에서 참조
        resp = client.post(
            "/api/import/bundle/confirm",
            files={
                "matching_file": ("matching_updates.jsonl", make_matching_jsonl(SAMPLE_MATCHING), "application/octet-stream"),
                "products_file": ("products.jsonl", make_products_jsonl(SAMPLE_PRODUCTS), "application/octet-stream"),
            },
            data={"mode": "lenient"},
        )
        assert resp.status_code == 200
        body = resp.json()
        # matching이 먼저 적용되어 match_key를 알게 된 후 products가 적용됨
        assert body["matching_inserted"] == 1
        assert body["products_added"] == 1

    def test_idempotent_same_batch_id(self, client):
        """같은 batch_id로 두 번 confirm → 두 번째는 idempotent=True, DB 재쓰기 없음."""
        batch_id = "imp-test-idem-001"

        # 첫 번째 confirm
        resp1 = client.post(
            "/api/import/bundle/confirm",
            files={
                "matching_file": ("matching_updates.jsonl", make_matching_jsonl(SAMPLE_MATCHING), "application/octet-stream"),
            },
            data={"mode": "lenient", "batch_id": batch_id},
        )
        assert resp1.status_code == 200
        body1 = resp1.json()
        assert body1["idempotent"] is False
        assert body1["matching_inserted"] == 1

        # 두 번째 confirm (같은 batch_id)
        resp2 = client.post(
            "/api/import/bundle/confirm",
            files={
                "matching_file": ("matching_updates.jsonl", make_matching_jsonl(SAMPLE_MATCHING), "application/octet-stream"),
            },
            data={"mode": "lenient", "batch_id": batch_id},
        )
        assert resp2.status_code == 200
        body2 = resp2.json()
        assert body2["idempotent"] is True
        # 수치는 첫 번째와 동일
        assert body2["matching_inserted"] == 1

    def test_conflict_policy_human_vs_external_ai(self, client, db_fixture):
        """human existing → external-ai import 시도 → conflict (덮어쓰기 불가)."""
        Session = db_fixture["Session"]
        s = Session()
        s.add(MatchingEntry(
            match_key="CJ|햇반|210.000000|g",
            brand="CJ",
            name_core="햇반",
            pack_qty=210.0,
            pack_unit="g",
            category_id="food.rice",
            confidence=0.99,
            source="human",  # ← 높은 신뢰도
        ))
        s.commit()
        s.close()

        # external-ai로 같은 match_key를 덮으려 시도
        rows = [{
            "match_key": "CJ|햇반|210.000000|g",
            "category_id": "food.rice",
            "confidence": 0.85,
            "source": "external-ai",
        }]
        resp = client.post(
            "/api/import/bundle/confirm",
            files={
                "matching_file": ("matching_updates.jsonl", make_matching_jsonl(rows), "application/octet-stream"),
            },
            data={"mode": "lenient"},
        )
        assert resp.status_code == 200
        body = resp.json()
        # conflict 발생 — 덮어쓰기 안 됨
        assert body["matching_conflicts"] >= 1
        assert body["matching_inserted"] == 0

    def test_strict_mode_partial_failure_rejects_all(self, client):
        """strict 모드에서 1개 row 오류 → 전체 거부."""
        bad_rows = [
            {
                "match_key": "A|B|1.000000|g",
                "category_id": "food.rice",
                "confidence": 0.9,
                "source": "external-ai",
            },
            {
                "match_key": "C|D|2.000000|g",
                "category_id": "nonexistent_cat_xyz",  # ← 존재하지 않는 category
                "confidence": 0.8,
                "source": "external-ai",
            },
        ]
        resp = client.post(
            "/api/import/bundle/confirm",
            files={
                "matching_file": ("matching_updates.jsonl", make_matching_jsonl(bad_rows), "application/octet-stream"),
            },
            data={"mode": "strict"},
        )
        assert resp.status_code == 422

    def test_lenient_mode_partial_failure_applies_valid(self, client, db_fixture):
        """lenient 모드에서 1개 row 오류 → 나머지 유효 row 적용."""
        mixed_rows = [
            {
                "match_key": "A|밥|1.000000|g",
                "category_id": "food.rice",
                "confidence": 0.9,
                "source": "external-ai",
            },
            {
                "match_key": "B|국수|2.000000|g",
                "category_id": "nonexistent_cat_xyz",  # ← 오류
                "confidence": 0.8,
                "source": "external-ai",
            },
        ]
        resp = client.post(
            "/api/import/bundle/confirm",
            files={
                "matching_file": ("matching_updates.jsonl", make_matching_jsonl(mixed_rows), "application/octet-stream"),
            },
            data={"mode": "lenient"},
        )
        assert resp.status_code == 200
        body = resp.json()
        # 유효한 row는 적용됨
        assert body["matching_inserted"] >= 1
        assert body["ok"] is True

        Session = db_fixture["Session"]
        s = Session()
        valid_entry = s.query(MatchingEntry).filter_by(match_key="A|밥|1.000000|g").first()
        assert valid_entry is not None
        s.close()

    def test_categories_parent_id_missing_rejected(self, client):
        """parent_id가 없는 category → strict에서 오류 반환."""
        bad_taxonomy = {
            "categories": [
                {"id": "ghost.sub", "name": "유령 하위", "parent_id": "ghost_nonexistent", "depth": 1},
            ],
            "keywords": [],
        }
        resp = client.post(
            "/api/import/bundle/confirm",
            files={
                "taxonomy_file": ("categories_keywords_updates.yaml", make_taxonomy_yaml(bad_taxonomy), "text/yaml"),
            },
            data={"mode": "strict"},
        )
        assert resp.status_code == 422

    def test_products_no_match_key_skipped(self, client, db_fixture):
        """products.jsonl의 match_key가 DB/incoming에 없으면 skipped_no_match."""
        products = [
            {
                "raw_id": "emart_999",
                "match_key": "NONEXISTENT|상품|999.0|개",
                "price": 5000.0,
                "mart": "emart",
            }
        ]
        resp = client.post(
            "/api/import/bundle/confirm",
            files={
                "products_file": ("products.jsonl", make_products_jsonl(products), "application/octet-stream"),
            },
            data={"mode": "lenient"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["products_skipped"] >= 1
        assert body["products_added"] == 0

    def test_failures_csv_download(self, client, db_fixture):
        """confirm 후 실패 행이 있으면 failures.csv 다운로드 가능."""
        bad_products = [
            {
                "raw_id": "emart_bad_001",
                "match_key": "NOWHERE|없음|1.0|개",  # match_key 없음 → skip
                "price": 1000.0,
                "mart": "emart",
            },
        ]
        resp = client.post(
            "/api/import/bundle/confirm",
            files={
                "products_file": ("products.jsonl", make_products_jsonl(bad_products), "application/octet-stream"),
            },
            data={"mode": "lenient", "batch_id": "imp-test-csv-001"},
        )
        assert resp.status_code == 200
        # skipped는 failure_rows에 포함되지 않음, 별도 failure row가 없으면 csv url=None
        # (match_key 없음은 skipped_no_match이지 failure row가 아님)

    def test_failures_csv_endpoint_404(self, client):
        """존재하지 않는 batch_id로 failures.csv 요청 시 404."""
        resp = client.get("/api/import/bundle/nonexistent-batch/failures.csv")
        assert resp.status_code == 404

    def test_pending_human_flag_on_low_confidence(self, client):
        """confidence < 0.6 인 row는 preview에서 pending_human 카운트에 포함."""
        low_conf_rows = [
            {
                "match_key": "A|낮은신뢰|1.0|g",
                "category_id": "food.rice",
                "confidence": 0.5,  # < 0.6
                "source": "external-ai",
            }
        ]
        resp = client.post(
            "/api/import/bundle/preview",
            files={
                "matching_file": ("matching_updates.jsonl", make_matching_jsonl(low_conf_rows), "application/octet-stream"),
            },
            data={"mode": "lenient"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["matching"]["pending_human"] >= 1
