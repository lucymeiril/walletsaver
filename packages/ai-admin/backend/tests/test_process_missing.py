"""rd5-process-missing: POST /api/ingest/process-missing 회귀 테스트.

사용자 헌법: "AI 처리 가동 (E)" 버튼이 422 안 나야 하며, 실제로 ingest_and_label_records 가
호출되어 누락 raw 행이 줄어들어야 한다.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api.app import create_app
from api.deps import get_db_session
from api.routes.review import get_db as get_review_db
from core.contracts.ai_pipeline import PipelineStatus
from core.contracts.control_plane import ProviderConfigContract, RawCrawlBatchContract
from services import ai_ingestion
from storage import (
    Database,
    ProviderConfigRepository,
    RawCrawlBatchRepository,
    create_database,
)
from core.contracts.ai_pipeline import RawCrawlRecord as RawCrawlRecordContract


@pytest.fixture()
def db(tmp_path) -> Iterator[Database]:
    database = create_database(f"sqlite:///{(tmp_path / 'pm.db').as_posix()}")
    yield database
    database.dispose()


@pytest.fixture()
def client(db: Database, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    app = create_app()
    provider_call_count = {"n": 0}

    def _override() -> Iterator[Session]:
        session = db.session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    class FakeProvider:
        def __init__(self, config: ProviderConfigContract) -> None:
            self.config = config

        def call(self, *, prompt: str, schema=None) -> dict:
            provider_call_count["n"] += 1
            import re
            records = re.findall(r"- id=([^;]+);", prompt)
            return {
                "items": [
                    {
                        "raw_record_id": rid,
                        "canonical_name": f"정규화 {rid}",
                        "brand": "테스트",
                        "category_id": "mart.test",
                        "keywords": ["테스트"],
                        "aliases": [],
                        "attributes": {},
                        "package_quantity": 1,
                        "package_unit": "ea",
                        "bundle_count": 1,
                        "standard_unit": "ea",
                        "standard_unit_price": 1000,
                        "confidence": 0.9,
                    }
                    for rid in records
                ]
            }

    monkeypatch.setattr(ai_ingestion, "provider_from_config", lambda c: FakeProvider(c))
    app.dependency_overrides[get_db_session] = _override
    app.dependency_overrides[get_review_db] = lambda: db
    with db.session_scope() as session:
        ProviderConfigRepository(session).save(
            ProviderConfigContract(
                provider_id="google-dev",
                provider_kind="gemini",
                display_name="Google Dev",
                default_model="gemma-4-26b-a4b-it",
                secret_alias="GOOGLE_API_KEY",
            )
        )
    client = TestClient(app)
    client.provider_call_count = provider_call_count  # type: ignore[attr-defined]
    try:
        yield client
    finally:
        app.dependency_overrides.clear()


def _seed_raw(db: Database, ids: list[str]) -> None:
    with db.session_scope() as session:
        repo = RawCrawlBatchRepository(session)
        repo.save(
            RawCrawlBatchContract(
                batch_id="batch-seed",
                source_name="emart",
                crawler_name="emart-crawler",
                item_count=len(ids),
                schema_type="product_offer",
                status=PipelineStatus.RAW_INGESTED,
            )
        )
        repo.save_records(
            "batch-seed",
            [
                RawCrawlRecordContract(
                    raw_record_id=rid,
                    source_name="emart",
                    source_url=f"https://emart.example/{rid}",
                    raw_title=f"상품 {rid}",
                    raw_price=1000 + i,
                    raw_payload={},
                    crawled_at=datetime.now(),
                )
                for i, rid in enumerate(ids)
            ],
        )


def test_process_missing_zero_when_none(client: TestClient, db: Database) -> None:
    res = client.post(
        "/api/ingest/process-missing",
        json={"provider_id": "google-dev", "limit": 30},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["processed"] == 0
    assert body["proposals_created"] == 0
    assert body["missing_remaining"] == 0
    assert client.provider_call_count["n"] == 0  # type: ignore[attr-defined]


def test_process_missing_handles_three_records(client: TestClient, db: Database) -> None:
    _seed_raw(db, ["r1", "r2", "r3"])
    res = client.post(
        "/api/ingest/process-missing",
        json={"provider_id": "google-dev", "limit": 30},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["processed"] == 3
    assert body["proposals_created"] > 0, "provider mock must produce proposals"
    assert client.provider_call_count["n"] >= 1  # type: ignore[attr-defined]
    assert body["missing_remaining"] == 0


def test_process_missing_requires_provider_id(client: TestClient) -> None:
    res = client.post("/api/ingest/process-missing", json={"limit": 5})
    assert res.status_code == 422


def test_process_missing_rejects_limit_above_cap(client: TestClient) -> None:
    res = client.post(
        "/api/ingest/process-missing",
        json={"provider_id": "google-dev", "limit": 31},
    )
    assert res.status_code == 422


def test_process_missing_dry_run_skips_ingest(client: TestClient, db: Database) -> None:
    _seed_raw(db, ["d1", "d2"])
    res = client.post(
        "/api/ingest/process-missing",
        json={"provider_id": "google-dev", "limit": 30, "dry_run": True},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["dry_run"] is True
    assert body["processed"] == 0
    assert set(body["would_process"]) == {"d1", "d2"}
    assert body["missing_remaining"] == 2
    assert client.provider_call_count["n"] == 0  # type: ignore[attr-defined]


def test_process_missing_unknown_provider_returns_400(client: TestClient, db: Database) -> None:
    _seed_raw(db, ["u1"])
    res = client.post(
        "/api/ingest/process-missing",
        json={"provider_id": "nope-missing", "limit": 5},
    )
    assert res.status_code == 400, res.text
    detail = res.json().get("detail", {})
    if isinstance(detail, dict):
        assert detail.get("stage") in {"provider_lookup", "provider_setup"}


def test_raw_clear_all_dry_run_is_default(client: TestClient, db: Database) -> None:
    _seed_raw(db, ["c1", "c2"])
    res = client.post("/api/ingest/raw-records/clear-all", json={})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["dry_run"] is True
    assert body["would_delete"] == 2


def test_raw_clear_all_executes_when_dry_run_false(client: TestClient, db: Database) -> None:
    _seed_raw(db, ["x1", "x2", "x3"])
    res = client.post(
        "/api/ingest/raw-records/clear-all",
        json={"dry_run": False, "reviewer_id": "test-op", "reason": "regression test"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["dry_run"] is False
    assert body["deleted_records"] == 3
    # 다시 조회 → 모두 사라졌어야
    with db.session_scope() as session:
        from storage.models import RawCrawlRecord as RawModel
        from sqlalchemy import select as _sel
        rows = session.execute(_sel(RawModel)).scalars().all()
        assert rows == []


def test_process_missing_continues_after_sub_batch_504(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """rd5-partial-save-fix-2 회귀: 한 sub-batch 가 retry 다 소진해도 다른 sub-batch 의
    proposals 가 통째로 날아가지 않아야 한다. _call_provider_with_retries 가 raise 하는
    AIIngestionError(stage=provider_call, status=502) 가 batch 루프 내부에서 잡혀 missing
    으로 기록되고, 나머지 sub-batch 의 proposals 는 save 까지 진행되어야 한다.

    사용자 직격: "504 DEADLINE_EXCEEDED ... ai 요청 몇 번 발생했는데도 싹 다 결과물 날리네"
    """
    from services.ai_ingestion import AIIngestionError

    app = create_app()
    call_log: list[str] = []

    def _override() -> Iterator[Session]:
        session = db.session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    class FlakyProvider:
        """첫 호출은 504 retry 소진, 두 번째 호출은 성공."""

        def __init__(self, config: ProviderConfigContract) -> None:
            self.config = config

        def call(self, *, prompt: str, schema=None) -> dict:
            import re
            call_log.append("call")
            records = re.findall(r"- id=([^;]+);", prompt)
            # 첫 sub-batch 만 504 흉내. AIIngestionError 가 retry loop 에서 발사된다.
            if any(r.startswith("a") for r in records):
                # provider 가 던지는 retryable error 를 흉내 → retry 3회 소진 → AIIngestionError raise
                from providers.google_genai import ProviderResponseError as PRE
                raise PRE("504 DEADLINE_EXCEEDED.", provider_id="google-dev", model="gemma")
            return {
                "items": [
                    {
                        "raw_record_id": rid,
                        "canonical_name": f"정규화 {rid}",
                        "brand": "테스트",
                        "category_id": "mart.test",
                        "keywords": ["테스트"],
                        "aliases": [],
                        "attributes": {},
                        "package_quantity": 1,
                        "package_unit": "ea",
                        "bundle_count": 1,
                        "standard_unit": "ea",
                        "standard_unit_price": 1000,
                        "confidence": 0.9,
                    }
                    for rid in records
                ]
            }

    monkeypatch.setattr(ai_ingestion, "provider_from_config", lambda c: FlakyProvider(c))
    # retry/backoff 가속 — 회귀 테스트가 30 초씩 자게 두지 않는다.
    monkeypatch.setattr(ai_ingestion, "_sleep", lambda *_args, **_kw: None)
    monkeypatch.setattr(ai_ingestion, "_reserve_live_provider_call", lambda *_a, **_k: None)
    monkeypatch.setattr(ai_ingestion, "_is_live_provider", lambda _p: False)
    app.dependency_overrides[get_db_session] = _override
    app.dependency_overrides[get_review_db] = lambda: db
    with db.session_scope() as session:
        ProviderConfigRepository(session).save(
            ProviderConfigContract(
                provider_id="google-dev",
                provider_kind="gemini",
                display_name="Google Dev",
                default_model="gemma-4-26b-a4b-it",
                secret_alias="GOOGLE_API_KEY",
            )
        )
    # 작은 max_ai_batch_items 로 강제 분할: a-그룹 (실패 예정) + b-그룹 (성공 예정)
    _seed_raw(db, ["a1", "a2", "b1", "b2"])
    client = TestClient(app)
    try:
        res = client.post(
            "/api/ingest/process-missing",
            json={
                "provider_id": "google-dev",
                "limit": 30,
                "max_ai_batch_items": 2,
                "max_provider_calls": 10,
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert res.status_code == 200, res.text
    body = res.json()
    # 핵심 검증: b-그룹은 살아남았어야 한다 — 그 어떤 케이스라도 missing_remaining < 4.
    # a-그룹 2건은 missing 으로 남고, b-그룹 2건은 proposals 가 생성되었어야.
    assert body["proposals_created"] > 0, (
        "한 sub-batch 의 504 가 다른 sub-batch 의 proposals 까지 날렸다 — partial save 깨짐"
    )
    assert body["missing_remaining"] < 4, body

