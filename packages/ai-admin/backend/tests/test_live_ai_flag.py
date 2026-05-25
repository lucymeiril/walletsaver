"""2026-05-25 보류: AI 라이브 파이프라인 feature flag 테스트.

사용자가 AI live pipeline(504 timeout 무한 회귀)을 보류하기로 결정.
코드는 보존, feature flag로 비활성화, 프론트에 "보류" 배지 표시.
향후 복귀 가능.
"""
from __future__ import annotations

from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api.app import create_app
from api.deps import get_db_session
from api.routes.review import get_db as get_review_db
from core.contracts.control_plane import ProviderConfigContract
from services import ai_ingestion
from storage import Database, ProviderConfigRepository, create_database


@pytest.fixture()
def db(tmp_path) -> Iterator[Database]:
    database = create_database(f"sqlite:///{(tmp_path / 'flag.db').as_posix()}")
    yield database
    database.dispose()


@pytest.fixture()
def client_with_flag_disabled(db: Database, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """flag=False일 때 API는 503을 반환해야 한다."""
    app = create_app()
    
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

    monkeypatch.setenv("WALLETSAVIOR_LIVE_AI_ENABLED", "false")
    # ai_ingestion 모듈을 reload하여 flag 값 재설정
    monkeypatch.setattr(ai_ingestion, "WALLETSAVIOR_LIVE_AI_ENABLED", False)
    
    # ingest.py 모듈도 reload하여 import된 WALLETSAVIOR_LIVE_AI_ENABLED 업데이트
    from api.routes import ingest as ingest_routes
    monkeypatch.setattr(ingest_routes, "WALLETSAVIOR_LIVE_AI_ENABLED", False)
    
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
    try:
        yield client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def client_with_flag_enabled(db: Database, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """flag=True일 때 API는 정상 경로로 진입해야 한다."""
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

    monkeypatch.setenv("WALLETSAVIOR_LIVE_AI_ENABLED", "true")
    monkeypatch.setattr(ai_ingestion, "WALLETSAVIOR_LIVE_AI_ENABLED", True)
    
    from api.routes import ingest as ingest_routes
    monkeypatch.setattr(ingest_routes, "WALLETSAVIOR_LIVE_AI_ENABLED", True)

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


def test_process_missing_503_when_flag_disabled(client_with_flag_disabled: TestClient):
    """flag=False일 때 /api/ingest/process-missing은 HTTP 503을 반환."""
    response = client_with_flag_disabled.post(
        "/api/ingest/process-missing",
        json={
            "provider_id": "google-dev",
            "limit": 30,
            "dry_run": False,
        },
    )
    assert response.status_code == 503
    detail = response.json().get("detail", {})
    assert detail.get("status") == "deprecated"
    assert "external classifier" in detail.get("detail", "").lower()


def test_raw_records_label_503_when_flag_disabled(client_with_flag_disabled: TestClient):
    """flag=False일 때 /api/ingest/raw-records/label는 HTTP 503을 반환."""
    response = client_with_flag_disabled.post(
        "/api/ingest/raw-records/label",
        json={
            "provider_id": "google-dev",
            "source_name": "test-source",
            "crawler_name": "test-crawler",
            "schema_type": "product_offer",
            "records": [
                {
                    "raw_record_id": "test-001",
                    "source_name": "test-source",
                    "source_record_key": "key-001",
                    "source_url": "https://example.com/001",
                    "raw_title": "테스트 상품",
                    "raw_price": "10000",
                    "raw_payload": {},
                    "crawled_at": "2024-01-01T00:00:00Z",
                }
            ],
        },
    )
    assert response.status_code == 503
    detail = response.json().get("detail", {})
    assert detail.get("stage") == "deprecated"
    assert "disabled" in detail.get("message", "").lower()


def test_process_missing_works_when_flag_enabled(client_with_flag_enabled: TestClient):
    """flag=True일 때 /api/ingest/process-missing은 정상 경로로 진입."""
    response = client_with_flag_enabled.post(
        "/api/ingest/process-missing",
        json={
            "provider_id": "google-dev",
            "limit": 30,
            "dry_run": True,  # dry_run=True이면 DB 조회 없이 빈 결과 반환
        },
    )
    # dry_run이므로 상태는 200 OK
    assert response.status_code == 200
    data = response.json()
    assert data.get("ok") is True
