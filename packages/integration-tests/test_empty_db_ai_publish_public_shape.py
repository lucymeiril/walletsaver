"""HTTP/service-boundary empty DB publish harness without live crawler/AI calls.

This intentionally does not claim live all-source crawler or AI-provider success:
crawler-admin diagnostics and the AI provider are bounded fixtures, while
DB-admin and website are exercised through FastAPI TestClient service boundaries.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parent.parent.parent
DB_BACKEND = ROOT / "packages" / "db-admin" / "backend"
AI_BACKEND = ROOT / "packages" / "ai-admin" / "backend"
WEBSITE_BACKEND = ROOT / "packages" / "website" / "backend"
CRAWLER_BACKEND = ROOT / "packages" / "crawler-admin" / "backend"
CRAWLER_FIXTURES = CRAWLER_BACKEND / "tests" / "fixtures" / "marketplace_skeleton"
SHARED = ROOT / "packages" / "shared"

for path in (str(SHARED), str(DB_BACKEND)):
    if path in sys.path:
        sys.path.remove(path)
    sys.path.insert(0, path)

for module_name in [
    name
    for name in list(sys.modules)
    if name == "api"
    or name.startswith("api.")
    or name == "services"
    or name.startswith("services.")
    or name == "storage"
    or name.startswith("storage.")
]:
    sys.modules.pop(module_name, None)

from api.routes import ingestion as ingestion_routes
from api.auth import get_current_identity, require_moderator, require_viewer
from api.routes.ingestion import _calculate_quality
from core.contracts.ai_pipeline import (
    AIWorkerRole,
    FieldProposal,
    FieldProvenance,
    PipelineStatus,
    ProposalType,
    RawCrawlRecord,
)
from services.catalog_seed import seed_catalog_taxonomy
from storage.models import (
    Base,
    AuditLog,
    Category,
    DiscountHistory,
    Keyword,
    PendingIngestion,
    Product,
    ProductKeyword,
)


def _load_ai_review_publish():
    """Load ai-admin service despite db-admin using the same package names."""
    saved_path = list(sys.path)
    saved_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == "services"
        or name.startswith("services.")
        or name == "storage"
        or name.startswith("storage.")
    }
    for name in list(saved_modules):
        sys.modules.pop(name, None)
    sys.path.insert(0, str(AI_BACKEND))
    sys.path.insert(0, str(SHARED))
    try:
        module = importlib.import_module("services.review_publish")
    finally:
        for name in [
            name
            for name in list(sys.modules)
            if name == "services"
            or name.startswith("services.")
            or name == "storage"
            or name.startswith("storage.")
        ]:
            sys.modules.pop(name, None)
        sys.modules.update(saved_modules)
        sys.path = saved_path
    return module


AI_REVIEW_PUBLISH = _load_ai_review_publish()


def _make_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _patch_managed_session(monkeypatch, Session):
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

    monkeypatch.setattr(ingestion_routes, "managed_session", managed_test_session)
    monkeypatch.setattr(ingestion_routes, "get_session", Session)


def _make_db_admin_client(monkeypatch, Session) -> TestClient:
    _patch_managed_session(monkeypatch, Session)
    app = FastAPI(title="db-admin integration boundary")
    app.include_router(ingestion_routes.router)

    async def test_identity() -> dict[str, Any]:
        return {"id": "integration-test", "email": "integration-test@example.com", "role": "admin"}

    app.dependency_overrides[get_current_identity] = test_identity
    app.dependency_overrides[require_viewer] = test_identity
    app.dependency_overrides[require_moderator] = test_identity
    return TestClient(app)


def _make_website_client(storage) -> TestClient:
    """Create the website app while avoiding package-name collisions with db-admin."""
    saved_path = list(sys.path)
    saved_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == "api"
        or name.startswith("api.")
        or name == "services"
        or name.startswith("services.")
    }
    for name in list(saved_modules):
        sys.modules.pop(name, None)
    sys.path.insert(0, str(WEBSITE_BACKEND))
    sys.path.insert(0, str(SHARED))
    try:
        app_path = WEBSITE_BACKEND / "api" / "app.py"
        spec = importlib.util.spec_from_file_location("website_app_for_http_integration", app_path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return TestClient(module.create_app(storage=storage, engine=None, event_bus=None))
    finally:
        for name in [
            name
            for name in list(sys.modules)
            if name == "api"
            or name.startswith("api.")
            or name == "services"
            or name.startswith("services.")
        ]:
            sys.modules.pop(name, None)
        sys.modules.update(saved_modules)
        sys.path = saved_path


def _ai_admin_api_stubbed_item(monkeypatch, tmp_path: Path, record: RawCrawlRecord) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run provider setup, labeling, and publish shaping through ai-admin HTTP routes."""
    saved_path = list(sys.path)
    saved_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == "api"
        or name.startswith("api.")
        or name == "services"
        or name.startswith("services.")
        or name == "storage"
        or name.startswith("storage.")
        or name == "providers"
        or name.startswith("providers.")
        or name == "config"
    }
    for name in list(saved_modules):
        sys.modules.pop(name, None)
    sys.path.insert(0, str(AI_BACKEND))
    sys.path.insert(0, str(SHARED))
    database = None
    try:
        ai_app = importlib.import_module("api.app")
        ai_deps = importlib.import_module("api.deps")
        ai_review_routes = importlib.import_module("api.routes.review")
        ai_ingestion = importlib.import_module("services.ai_ingestion")
        ai_storage = importlib.import_module("storage")

        database = ai_storage.create_database(
            f"sqlite:///{(tmp_path / ('ai-admin-boundary-' + uuid.uuid4().hex + '.db')).as_posix()}"
        )

        class BoundaryProvider:
            provider_mode = "stub"

            def __init__(self, config) -> None:
                self.config = config

            def call(self, *, prompt: str, schema=None) -> dict[str, Any]:
                return {
                    "items": [
                        {
                            "raw_record_id": record.raw_record_id,
                            "canonical_name": "풀무원 국산콩 두부 300g",
                            "source_title": record.raw_title,
                            "sale_price": 1980,
                            "brand": "풀무원",
                            "category_id": "processed.tofu.firm",
                            "keywords": ["두부"],
                            "aliases": ["국산콩두부"],
                            "attributes": {"origin": "domestic", "origin_label": "국산"},
                            "package_quantity": 300,
                            "package_unit": "g",
                            "display_unit": "300g",
                            "confidence": 0.98,
                            "notes": "stubbed ai-admin API boundary classification",
                        }
                    ]
                }

        monkeypatch.setattr(
            ai_ingestion,
            "provider_from_config",
            lambda config: BoundaryProvider(config),
        )

        app = ai_app.create_app()

        def _override():
            session = database.session()
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        app.dependency_overrides[ai_deps.get_db_session] = _override
        app.dependency_overrides[ai_review_routes.get_db] = lambda: database
        with TestClient(app) as client:
            provider_response = client.post(
                "/api/providers",
                json={
                    "provider_id": "google-dev",
                    "provider_kind": "gemini",
                    "display_name": "Google Dev Stub",
                    "base_url": None,
                    "default_model": "gemma-3-27b-it",
                    "secret_alias": "GOOGLE_API_KEY",
                    "is_enabled": True,
                    "max_concurrent_jobs": 1,
                    "min_request_interval_seconds": 1.0,
                    "daily_budget_limit": 0.0,
                },
            )
            assert provider_response.status_code == 200, provider_response.text

            ingest_response = client.post(
                "/api/ingest/raw-records/label",
                json={
                    "provider_id": "google-dev",
                    "source_name": record.source_name,
                    "crawler_name": "integration-provider-stub",
                    "schema_type": "mart_discount",
                    "records": [record.model_dump(mode="json")],
                },
            )
            assert ingest_response.status_code == 200, ingest_response.text
            ingest_body = ingest_response.json()
            provider_mode = ingest_body.get("provider_mode", BoundaryProvider.provider_mode)
            assert provider_mode == "stub"
            assert ingest_body["provider_calls"] == 1

            for proposal_id in ingest_body["proposal_ids"]:
                approve_response = client.post(
                    f"/api/review/proposals/{proposal_id}/approve",
                    json={"reviewer_id": "integration-test", "create_learning_rule": False},
                )
                assert approve_response.status_code == 200, approve_response.text

            eligibility_response = client.get(
                f"/api/review/publish-eligibility?batch_id={ingest_body['raw_batch_id']}"
            )
            assert eligibility_response.status_code == 200, eligibility_response.text
            eligibility = eligibility_response.json()
            assert eligibility["items"], eligibility
            item = eligibility["items"][0]["item"]
            item.setdefault("raw_data", {})["post_publish_audit_flags"] = item.get("post_publish_audit_flags", [])
            return item, {
                "provider_config_route": "/api/providers",
                "label_route": "/api/ingest/raw-records/label",
                "publish_shape_route": "/api/review/publish-eligibility",
                "provider_mode": provider_mode,
                "provider_calls": ingest_body["provider_calls"],
            }
    finally:
        if database is not None:
            database.dispose()
        for name in [
            name
            for name in list(sys.modules)
            if name == "api"
            or name.startswith("api.")
            or name == "services"
            or name.startswith("services.")
            or name == "storage"
            or name.startswith("storage.")
            or name == "providers"
            or name.startswith("providers.")
            or name == "config"
        ]:
            sys.modules.pop(name, None)
        sys.modules.update(saved_modules)
        sys.path = saved_path


def _run_crawler_admin_diagnostics_http() -> dict[str, Any]:
    """Hit crawler-admin's HTTP diagnostics boundary with saved fixtures only."""
    saved_path = list(sys.path)
    saved_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == "api"
        or name.startswith("api.")
        or name == "services"
        or name.startswith("services.")
        or name == "storage"
        or name.startswith("storage.")
        or name == "pipeline"
        or name.startswith("pipeline.")
        or name == "crawlers"
        or name.startswith("crawlers.")
        or name == "core"
        or name.startswith("core.")
        or name in {"config", "audit", "concurrency", "logging_config", "error_middleware", "error_api"}
    }
    saved_env = {
        "CRAWLER_ADMIN_API_KEY": os.environ.get("CRAWLER_ADMIN_API_KEY"),
        "REQUIRE_AUTH": os.environ.get("REQUIRE_AUTH"),
    }
    for name in list(saved_modules):
        sys.modules.pop(name, None)
    sys.path.insert(0, str(CRAWLER_BACKEND))
    sys.path.insert(0, str(SHARED))
    os.environ["CRAWLER_ADMIN_API_KEY"] = "integration-test-crawler-admin-key"
    os.environ["REQUIRE_AUTH"] = "true"
    try:
        app_module = importlib.import_module("api.app")
        client = TestClient(app_module.create_app())
        headers = {"X-API-Key": os.environ["CRAWLER_ADMIN_API_KEY"]}
        fixture_html = (CRAWLER_FIXTURES / "gmarket.html").read_text(encoding="utf-8")
        response = client.post(
            "/api/crawlers/diagnostics",
            headers=headers,
            json={
                "crawler_ids": ["gmarket", "coupang", "unknown_diagnostic"],
                "fixtures": {"gmarket": fixture_html},
                "live_enabled": False,
            },
        )
        assert response.status_code == 200, response.text
        diagnostics = response.json()
    finally:
        for name in [
            name
            for name in list(sys.modules)
            if name == "api"
            or name.startswith("api.")
            or name == "services"
            or name.startswith("services.")
            or name == "storage"
            or name.startswith("storage.")
            or name == "pipeline"
            or name.startswith("pipeline.")
            or name == "crawlers"
            or name.startswith("crawlers.")
            or name == "core"
            or name.startswith("core.")
            or name in {"config", "audit", "concurrency", "logging_config", "error_middleware", "error_api"}
        ]:
            sys.modules.pop(name, None)
        sys.modules.update(saved_modules)
        sys.path = saved_path
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    by_id = {report["crawler_id"]: report for report in diagnostics["crawlers"]}
    gmarket = by_id["gmarket"]
    coupang = by_id["coupang"]
    unknown = by_id["unknown_diagnostic"]
    counts = gmarket["quality_evidence"]["counts"]
    missing_codes = [
        diagnostic["code"]
        for diagnostic in coupang.get("operator_diagnostics", [])
        if diagnostic.get("code")
    ]
    unknown_codes = [
        diagnostic["code"]
        for diagnostic in unknown.get("operator_diagnostics", [])
        if diagnostic.get("code")
    ]
    return {
        "boundary": "crawler-admin TestClient POST /api/crawlers/diagnostics",
        "request": {
            "crawler_ids": ["gmarket", "coupang", "unknown_diagnostic"],
            "fixture_sources": ["gmarket"],
            "live_enabled": False,
        },
        "response_schema": diagnostics["schema"],
        "diagnosed_count": diagnostics["diagnosed_count"],
        "quality_evidence_count": diagnostics["quality_evidence_count"],
        "metadata": {
            "live_network_default": diagnostics["live_network_default"],
            "live_enabled": diagnostics["live_enabled"],
            "source_raw": counts["source_raw"],
            "parsed": counts["parsed"],
            "valid": counts["valid"],
            "can_claim_collecting": gmarket["quality_evidence"]["can_claim_collecting"],
            "cannot_claim_collecting": not gmarket["quality_evidence"]["can_claim_collecting"],
            "collection_status": gmarket["quality_evidence"]["collection_status"],
            "fixture_available": gmarket["fixture"]["available"],
        },
        "negative_path": {
            "missing_fixture": {
                "crawler_id": "coupang",
                "fixture_available": coupang["fixture"]["available"],
                "codes": missing_codes,
                "reason": coupang["source_drift_readiness"]["reason"],
            },
            "unknown_crawler": {
                "crawler_id": "unknown_diagnostic",
                "registration_status": unknown["registration_status"],
                "codes": unknown_codes,
            },
        },
    }


def _proposal(
    raw_id: str,
    target: str,
    value: Any,
    *,
    proposal_type: ProposalType = ProposalType.NORMALIZED_FIELD,
    status: PipelineStatus = PipelineStatus.APPROVED,
) -> FieldProposal:
    return FieldProposal(
        proposal_id=f"{raw_id}:{target}",
        proposal_type=proposal_type,
        target_field=target,
        proposed_value=value,
        status=status,
        provenance=FieldProvenance(
            raw_record_id=raw_id,
            source_field="provider-stub",
            evidence_text=f"stubbed evidence for {target}",
            worker_role=AIWorkerRole.NORMALIZER,
            reviewed_by="integration-test",
            reviewed_at=datetime.utcnow(),
        ),
    )


def _crawler_like_record(*, image_url: str | None = "https://emart.example/images/tofu-300g.jpg") -> RawCrawlRecord:
    raw_payload = {
        "name": "원천명 국산콩 두부 300g",
        "source": "emart",
        "store": "이마트",
        "sale_price": 1980,
        "unit": "300g",
        "source_url": "https://emart.example/products/tofu-300g",
        "category_id": None,
        "keywords": [],
    }
    if image_url is not None:
        raw_payload["image_url"] = image_url
    return RawCrawlRecord(
        raw_record_id="cross-service-tofu-300g",
        source_name="emart",
        source_record_key="emart-sku-tofu-300g",
        source_url=raw_payload["source_url"],
        raw_title=raw_payload["name"],
        raw_price=raw_payload["sale_price"],
        raw_payload=raw_payload,
    )


def _provider_stub_proposals(record: RawCrawlRecord) -> list[FieldProposal]:
    return [
        _proposal(record.raw_record_id, "canonical_name", "풀무원 국산콩 두부 300g"),
        _proposal(record.raw_record_id, "sale_price", 1980),
        _proposal(record.raw_record_id, "category_id", "processed.tofu.firm", proposal_type=ProposalType.CATEGORY, status=PipelineStatus.AI_PROPOSED),
        _proposal(record.raw_record_id, "keywords", ["두부"], proposal_type=ProposalType.KEYWORD, status=PipelineStatus.AI_PROPOSED),
        _proposal(record.raw_record_id, "package_quantity", 300),
        _proposal(record.raw_record_id, "package_unit", "g"),
        _proposal(record.raw_record_id, "display_unit", "300g"),
    ]


def _ai_admin_stubbed_item(record: RawCrawlRecord) -> dict[str, Any]:
    proposals = _provider_stub_proposals(record)
    item = AI_REVIEW_PUBLISH.db_item_from_review(record, proposals, {})
    audit_flags = AI_REVIEW_PUBLISH.build_post_publish_audit_flags(record, proposals, [], [])
    item["post_publish_audit_flags"] = audit_flags
    item["raw_data"]["post_publish_audit_flags"] = audit_flags
    item["raw_data"]["anomaly_audit"] = {
        "status": "warning",
        "scope": "ready_or_published",
        "review_queue": [
            {
                "type": "post_publish_audit_flags",
                "raw_record_id": record.raw_record_id,
                "recommended_action": "Review relaxed taxonomy/keyword flags after DB-admin approval.",
            }
        ],
    }
    return item


def _db_admin_ingestion_payload(item: dict[str, Any]) -> dict[str, Any]:
    quality_score, quality_details = _calculate_quality([item], "DiscountItem")
    return {
        "crawler_name": "ai-admin:provider-stub",
        "crawl_status": "success",
        "items": [item],
        "schema_type": "DiscountItem",
        "strategy_used": "ai_review_publish_provider_stub",
        "duration_seconds": 0,
        "errors": [],
        "source_url": item.get("source_url"),
        "quality_score": quality_score,
        "quality_details": quality_details,
    }


def _submit_ai_ingestion_http(client: TestClient, item: dict[str, Any]) -> int:
    response = client.post("/api/ingestions", json=_db_admin_ingestion_payload(item))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "pending"
    return body["id"]


class PersistedPublicCatalogStorage:
    """Website-facing read adapter over the isolated db-admin test session."""

    def __init__(self, Session):
        self.Session = Session

    def get_product_detail(self, product_id: int) -> dict[str, Any] | None:
        with self.Session() as session:
            product = session.get(Product, product_id)
            if product is None:
                return None
            history = session.execute(
                select(DiscountHistory)
                .where(DiscountHistory.product_id == product_id)
                .order_by(DiscountHistory.crawled_at.desc())
                .limit(1)
            ).scalar_one()
            keywords = [
                link.keyword.word
                for link in session.execute(
                    select(ProductKeyword).where(ProductKeyword.product_id == product_id)
                ).scalars()
            ]
            raw = history.raw_data or {}
            return {
                "product": {
                    "canonical_name": product.name,
                    "category_id": product.category_id,
                    "keywords": keywords,
                    "attributes": product.attributes or {},
                },
                "variant": {
                    "display_unit": raw.get("display_unit") or product.unit,
                    "package_quantity": raw.get("package_quantity"),
                    "package_unit": raw.get("package_unit"),
                    "standard_unit": raw.get("standard_unit"),
                },
                "offer": {
                    "source_name": history.source,
                    "source_title": raw.get("source_title"),
                    "source_url": history.source_url,
                    "image_url": product.image_url or raw.get("image_url"),
                    "price": history.price,
                    "original_price": history.original_price,
                    "discount_rate": history.discount_rate,
                    "standard_unit_price": raw.get("standard_unit_price"),
                    "price_per_100g": raw.get("price_per_100g"),
                    "raw_data": raw,
                },
            }

    def get_price_history(self, product_id: int, days: int) -> list[dict[str, Any]]:
        with self.Session() as session:
            rows = session.execute(
                select(DiscountHistory).where(DiscountHistory.product_id == product_id)
            ).scalars().all()
            return [
                {
                    "date": row.crawled_at.isoformat(),
                    "price": row.price,
                    "source": row.source,
                    "source_url": row.source_url,
                    "original_price": row.original_price,
                    "discount_rate": row.discount_rate,
                    "raw_data": row.raw_data,
                }
                for row in rows
            ]

    def get_price_compare(self, product_id: int) -> list[dict[str, Any]]:
        with self.Session() as session:
            rows = session.execute(
                select(DiscountHistory).where(DiscountHistory.product_id == product_id)
            ).scalars().all()
            return [
                {
                    "source": row.source,
                    "price": row.price,
                    "source_url": row.source_url,
                    "original_price": row.original_price,
                    "discount_rate": row.discount_rate,
                    "raw_data": row.raw_data,
                }
                for row in rows
            ]


def _run_empty_db_cross_service_flow(monkeypatch, tmp_path: Path) -> dict[str, Any]:
    Session = _make_session_factory()
    db_admin_client = _make_db_admin_client(monkeypatch, Session)
    crawler_upstream = _run_crawler_admin_diagnostics_http()
    record = _crawler_like_record()
    item, ai_admin_api = _ai_admin_api_stubbed_item(monkeypatch, tmp_path, record)

    with Session.begin() as session:
        started_empty = (
            session.query(Product).count() == 0
            and session.query(DiscountHistory).count() == 0
            and session.query(Category).count() == 0
            and session.query(Keyword).count() == 0
        )
        seed_catalog_taxonomy(session)
        assert session.query(Product).count() == 0
        assert session.query(DiscountHistory).count() == 0

    ingestion_id = _submit_ai_ingestion_http(db_admin_client, item)
    with Session() as session:
        queued = session.get(PendingIngestion, ingestion_id)
        assert queued is not None
        assert queued.status.value == "pending"
        assert json.loads(queued.items_json)[0]["raw_record_id"] == record.raw_record_id
        assert session.query(Product).count() == 0
        assert session.query(DiscountHistory).count() == 0

    approve_response = db_admin_client.post(
        f"/api/ingestions/{ingestion_id}/ai-safe-final-approve",
        json={"action": "approve", "notes": "cross-service empty DB one-action approval"},
    )
    assert approve_response.status_code == 200, approve_response.text
    approved = approve_response.json()
    assert approved["status"] == "approved"
    assert approved["saved"] == 1

    missing_response = db_admin_client.post(
        "/api/ingestions/99999/ai-safe-final-approve",
        json={"action": "approve", "notes": "surface missing ingestion error"},
    )
    assert missing_response.status_code == 404
    assert missing_response.json()["detail"]

    website_client = _make_website_client(PersistedPublicCatalogStorage(Session))
    with Session() as session:
        product = session.execute(select(Product)).scalar_one()
        history = session.execute(select(DiscountHistory)).scalar_one()
        ingestion = session.get(PendingIngestion, ingestion_id)
        audit = session.execute(
            select(AuditLog).where(AuditLog.action == "ingestion_ai_safe_final_approve")
        ).scalar_one()
        raw_data = history.raw_data
        public_product_response = website_client.get(f"/api/products/{product.id}")
        assert public_product_response.status_code == 200, public_product_response.text
        public_product = public_product_response.json()["data"]
        public_history_response = website_client.get(f"/api/products/{product.id}/price-history?days=30")
        assert public_history_response.status_code == 200, public_history_response.text
        public_history = public_history_response.json()["data"]
        return {
            "started_empty": started_empty,
            "boundary_coverage": {
                "crawler_admin": "HTTP TestClient diagnostics fixture upstream; no live crawler network",
                "ai_admin": "HTTP TestClient provider config, raw-record label, and publish-eligibility using provider_mode=stub",
                "db_admin": "HTTP TestClient submit and ai-safe-final-approve",
                "website": "HTTP TestClient public product and price-history reads",
                "service_error_visible": missing_response.json()["detail"],
            },
            "crawler_admin_upstream": crawler_upstream,
            "ai_admin_api": ai_admin_api,
            "mutation_gate": {
                "submit_retains_pending_only": True,
                "explicit_final_approval_route": "/api/ingestions/{id}/ai-safe-final-approve",
                "approved_action": "approve",
            },
            "ids": {"ingestion_id": ingestion.id, "product_id": product.id, "history_id": history.id},
            "counts": {
                "products": session.query(Product).count(),
                "discount_histories": session.query(DiscountHistory).count(),
                "product_keywords": session.query(ProductKeyword).count(),
                "pending_ingestions": session.query(PendingIngestion).count(),
            },
            "db_product": {
                "name": product.name,
                "category_id": product.category_id,
                "unit": product.unit,
                "image_url": product.image_url,
                "attributes": product.attributes,
            },
            "db_history": {
                "price": history.price,
                "source": history.source,
                "source_url": history.source_url,
                "original_price": history.original_price,
                "discount_rate": history.discount_rate,
                "published_discount_percent": raw_data["published_item"].get("discount_percent"),
                "publication_kind": raw_data["publication"]["publication_kind"],
                "price_observation_only": raw_data["publication"]["price_observation_only"],
                "discount_claim_status": raw_data["publication"]["discount_claim_status"],
                "claim_basis": raw_data["publication"]["claim_basis"],
                "claim_blockers": raw_data["publication"]["claim_blockers"],
                "raw_title": raw_data["raw_evidence"]["raw_title"],
                "raw_unit": raw_data["raw_evidence"]["raw_unit"],
                "package_quantity": raw_data["package_quantity"],
                "package_unit": raw_data["package_unit"],
                "price_per_100g": raw_data["price_per_100g"],
                "standard_unit_price": raw_data["standard_unit_price"],
            },
            "public_product": {
                "name": public_product["name"],
                "category_id": public_product["category_id"],
                "keywords": public_product["keywords"],
                "source": public_product["source"],
                "source_title": public_product["source_title"],
                "source_url": public_product["source_url"],
                "image_url": public_product["image_url"],
                "price": public_product["price"],
                "original_price": public_product.get("original_price"),
                "discount_rate": public_product.get("discount_rate"),
                "unit": public_product["unit"],
                "publication_kind": public_product["publication_kind"],
                "price_observation_only": public_product["price_observation_only"],
                "discount_claim_status": public_product["discount_claim_status"],
                "has_discount_metadata": public_product["has_discount_metadata"],
            },
            "public_history": {
                "point_count": public_history["point_count"],
                "current_offer_price": public_history["current_offer"]["price"],
                "current_offer_source": public_history["current_offer"]["source"],
                "current_offer_original_price": public_history["current_offer"].get("original_price"),
                "current_offer_discount_rate": public_history["current_offer"].get("discount_rate"),
                "current_offer_publication_kind": public_history["current_offer"]["publication_kind"],
                "current_offer_price_observation_only": public_history["current_offer"]["price_observation_only"],
                "current_offer_discount_claim_status": public_history["current_offer"]["discount_claim_status"],
                "history_source_url": public_history["history"][0]["source_url"],
                "history_original_price": public_history["history"][0]["original_price"],
                "history_discount_rate": public_history["history"][0]["discount_rate"],
                "history_publication_kind": public_history["history"][0]["publication_kind"],
                "history_price_observation_only": public_history["history"][0]["price_observation_only"],
                "history_discount_claim_status": public_history["history"][0]["discount_claim_status"],
            },
            "raw_vs_final": {
                "raw_name": record.raw_payload["name"],
                "final_name": raw_data["published_item"]["name"],
                "raw_category_id": record.raw_payload["category_id"],
                "final_category_id": raw_data["published_item"]["category_id"],
                "raw_keywords": record.raw_payload["keywords"],
                "final_keywords": raw_data["published_item"]["keywords"],
                "raw_record_id": raw_data["raw_record"]["raw_record_id"],
                "audit_raw_record_id": raw_data["audit_provenance"]["raw_record_id"],
                "raw_source_url": raw_data["raw_evidence"]["raw_payload"]["source_url"],
                "final_source_url": raw_data["published_item"]["source_url"],
            },
            "post_publish_audit_codes": [
                flag["code"] for flag in raw_data.get("post_publish_audit_flags", [])
            ],
            "approval_audit_visible": audit.new_value.get(
                "raw_evidence_retained",
                approved["raw_evidence_retained"],
            ),
        }


def test_cross_service_empty_db_ai_safe_final_approve_public_shape_is_repeatable(monkeypatch, tmp_path):
    first = _run_empty_db_cross_service_flow(monkeypatch, tmp_path)
    second = _run_empty_db_cross_service_flow(monkeypatch, tmp_path)

    assert first == second
    assert first["started_empty"] is True
    assert first["boundary_coverage"] == {
        "crawler_admin": "HTTP TestClient diagnostics fixture upstream; no live crawler network",
        "ai_admin": "HTTP TestClient provider config, raw-record label, and publish-eligibility using provider_mode=stub",
        "db_admin": "HTTP TestClient submit and ai-safe-final-approve",
        "website": "HTTP TestClient public product and price-history reads",
        "service_error_visible": "대기열 항목을 찾을 수 없습니다",
    }
    assert first["ai_admin_api"] == {
        "provider_config_route": "/api/providers",
        "label_route": "/api/ingest/raw-records/label",
        "publish_shape_route": "/api/review/publish-eligibility",
        "provider_mode": "stub",
        "provider_calls": 1,
    }
    assert first["mutation_gate"] == {
        "submit_retains_pending_only": True,
        "explicit_final_approval_route": "/api/ingestions/{id}/ai-safe-final-approve",
        "approved_action": "approve",
    }
    assert first["crawler_admin_upstream"] == {
        "boundary": "crawler-admin TestClient POST /api/crawlers/diagnostics",
        "request": {
            "crawler_ids": ["gmarket", "coupang", "unknown_diagnostic"],
            "fixture_sources": ["gmarket"],
            "live_enabled": False,
        },
        "response_schema": "bounded_crawler_diagnostics.v1",
        "diagnosed_count": 3,
        "quality_evidence_count": 1,
        "metadata": {
            "live_network_default": "disabled",
            "live_enabled": False,
            "source_raw": 1,
            "parsed": 1,
            "valid": 1,
            "can_claim_collecting": False,
            "cannot_claim_collecting": True,
            "collection_status": "registered_unverified",
            "fixture_available": True,
        },
        "negative_path": {
            "missing_fixture": {
                "crawler_id": "coupang",
                "fixture_available": False,
                "codes": ["live_disabled_no_fixture"],
                "reason": "No saved fixture/raw input was supplied, so parser drift cannot be checked safely.",
            },
            "unknown_crawler": {
                "crawler_id": "unknown_diagnostic",
                "registration_status": "missing",
                "codes": ["crawler_not_registered"],
            },
        },
    }
    assert first["ids"] == {"ingestion_id": 1, "product_id": 1, "history_id": 1}
    assert first["counts"] == {
        "products": 1,
        "discount_histories": 1,
        "product_keywords": 1,
        "pending_ingestions": 1,
    }
    assert first["db_product"] == {
        "name": "풀무원 국산콩 두부 300g",
        "category_id": "processed.tofu.firm",
        "unit": "300g",
        "image_url": "https://emart.example/images/tofu-300g.jpg",
        "attributes": {"origin": "domestic", "origin_label": "국산"},
    }
    assert first["db_history"] == {
        "price": 1980,
        "source": "emart",
        "source_url": "https://emart.example/products/tofu-300g",
        "original_price": None,
        "discount_rate": None,
        "published_discount_percent": None,
        "publication_kind": "price_observation",
        "price_observation_only": True,
        "discount_claim_status": "hotdeal_claim_blocked",
        "claim_basis": "current_price_observation",
        "claim_blockers": [
            "hotdeal_claim_blocked: missing verified original_price/discount_percent/source_event/historical_baseline; publish as price_observation only; missing=original_price,discount_percent,source_event,historical_baseline"
        ],
        "raw_title": "원천명 국산콩 두부 300g",
        "raw_unit": "300g",
        "package_quantity": 300,
        "package_unit": "g",
        "price_per_100g": 660,
        "standard_unit_price": 6600,
    }
    assert first["public_product"] == {
        "name": "풀무원 국산콩 두부 300g",
        "category_id": "processed.tofu.firm",
        "keywords": ["두부"],
        "source": "emart",
        "source_title": "원천명 국산콩 두부 300g",
        "source_url": "https://emart.example/products/tofu-300g",
        "image_url": "https://emart.example/images/tofu-300g.jpg",
        "price": 1980,
        "original_price": None,
        "discount_rate": None,
        "unit": "300g",
        "publication_kind": "price_observation",
        "price_observation_only": True,
        "discount_claim_status": "hotdeal_claim_blocked",
        "has_discount_metadata": False,
    }
    assert first["public_history"] == {
        "point_count": 1,
        "current_offer_price": 1980,
        "current_offer_source": "emart",
        "current_offer_original_price": None,
        "current_offer_discount_rate": None,
        "current_offer_publication_kind": "price_observation",
        "current_offer_price_observation_only": True,
        "current_offer_discount_claim_status": "hotdeal_claim_blocked",
        "history_source_url": "https://emart.example/products/tofu-300g",
        "history_original_price": None,
        "history_discount_rate": None,
        "history_publication_kind": "price_observation",
        "history_price_observation_only": True,
        "history_discount_claim_status": "hotdeal_claim_blocked",
    }
    assert first["raw_vs_final"] == {
        "raw_name": "원천명 국산콩 두부 300g",
        "final_name": "풀무원 국산콩 두부 300g",
        "raw_category_id": None,
        "final_category_id": "processed.tofu.firm",
        "raw_keywords": [],
        "final_keywords": ["두부"],
        "raw_record_id": "cross-service-tofu-300g",
        "audit_raw_record_id": "cross-service-tofu-300g",
        "raw_source_url": "https://emart.example/products/tofu-300g",
        "final_source_url": "https://emart.example/products/tofu-300g",
    }
    assert first["post_publish_audit_codes"] == []
    assert first["approval_audit_visible"] is True


def test_cross_service_empty_db_missing_customer_visible_field_blocks_publish(monkeypatch):
    Session = _make_session_factory()
    db_admin_client = _make_db_admin_client(monkeypatch, Session)
    record = _crawler_like_record(image_url=None)
    item = _ai_admin_stubbed_item(record)
    ingestion_id = _submit_ai_ingestion_http(db_admin_client, item)

    response = db_admin_client.post(
        f"/api/ingestions/{ingestion_id}/ai-safe-final-approve",
        json={"action": "approve", "notes": "must block missing image"},
    )
    assert response.status_code == 200, response.text
    result = response.json()

    assert result["status"] == "pending"
    assert result["blocked"] is True
    assert any("image_url" in blocker for blocker in result["blockers"])

    list_response = db_admin_client.get("/api/ingestions", params={"status": "pending"})
    assert list_response.status_code == 200, list_response.text
    listed = list_response.json()
    assert listed["total"] == 1
    assert listed["items"][0]["id"] == ingestion_id
    assert listed["items"][0]["status"] == "pending"

    detail_response = db_admin_client.get(f"/api/ingestions/{ingestion_id}")
    assert detail_response.status_code == 200, detail_response.text
    detail = detail_response.json()
    assert detail["status"] == "pending"
    assert detail["items"][0]["raw_record_id"] == record.raw_record_id
    assert detail["items"][0]["raw_data"]["raw_record"]["raw_record_id"] == record.raw_record_id
    assert "must block missing image" in detail["db_reviewer_notes"]

    with Session() as session:
        retained = session.get(PendingIngestion, ingestion_id)
        assert retained is not None
        assert retained.status.value == "pending"
        retained_items = json.loads(retained.items_json)
        assert retained_items[0]["raw_record_id"] == record.raw_record_id
        assert retained_items[0]["raw_data"]["raw_record"]["raw_record_id"] == record.raw_record_id
        assert session.query(Product).count() == 0
        assert session.query(DiscountHistory).count() == 0
        blocked_audit = session.execute(
            select(AuditLog).where(AuditLog.action == "ingestion_ai_safe_final_blocked")
        ).scalar_one()
        assert any("image_url" in blocker for blocker in blocked_audit.new_value["blockers"])


def test_cross_service_repeated_final_approvals_accumulate_public_price_history(monkeypatch):
    Session = _make_session_factory()
    db_admin_client = _make_db_admin_client(monkeypatch, Session)
    record = _crawler_like_record()
    item = _ai_admin_stubbed_item(record)
    item["raw_data"]["raw_payload"]["source_signature"] = record.source_record_key
    item["raw_data"]["raw_record"]["source_record_key"] = record.source_record_key
    item["source_record_key"] = record.source_record_key
    second_item = json.loads(json.dumps(item))
    second_item.update(
        {
            "sale_price": 1880,
            "current_price": 1880,
            "source_url": "https://emart.example/products/tofu-300g?crawl=2",
            "detail_url": "https://emart.example/products/tofu-300g?crawl=2",
        }
    )
    second_item["raw_data"]["raw_payload"]["sale_price"] = 1880
    second_item["raw_data"]["raw_record"]["raw_price"] = 1880
    second_item["raw_data"]["raw_evidence"]["raw_price"] = 1880

    with Session.begin() as session:
        seed_catalog_taxonomy(session)

    first_ingestion_id = _submit_ai_ingestion_http(db_admin_client, item)
    first_approve = db_admin_client.post(
        f"/api/ingestions/{first_ingestion_id}/ai-safe-final-approve",
        json={"action": "approve", "notes": "first accumulation approval"},
    )
    assert first_approve.status_code == 200, first_approve.text
    assert first_approve.json()["saved"] == 1

    second_ingestion_id = _submit_ai_ingestion_http(db_admin_client, second_item)
    second_approve = db_admin_client.post(
        f"/api/ingestions/{second_ingestion_id}/ai-safe-final-approve",
        json={"action": "approve", "notes": "second accumulation approval"},
    )
    assert second_approve.status_code == 200, second_approve.text
    assert second_approve.json()["saved"] == 1

    website_client = _make_website_client(PersistedPublicCatalogStorage(Session))
    with Session() as session:
        product = session.execute(select(Product)).scalar_one()
        histories = session.execute(
            select(DiscountHistory)
            .where(DiscountHistory.product_id == product.id)
            .order_by(DiscountHistory.id)
        ).scalars().all()

    assert len(histories) == 2
    assert [history.price for history in histories] == [1980, 1880]
    assert {history.source_url for history in histories} == {
        "https://emart.example/products/tofu-300g",
        "https://emart.example/products/tofu-300g?crawl=2",
    }

    public_history_response = website_client.get(f"/api/products/{product.id}/price-history?days=30")
    assert public_history_response.status_code == 200, public_history_response.text
    public_history = public_history_response.json()["data"]
    assert public_history["point_count"] == 2
    assert [point["price"] for point in public_history["history"]] == [1980, 1880]
    assert all(point["price_observation_only"] is True for point in public_history["history"])
    assert all(point["original_price"] is None for point in public_history["history"])
    assert all(point["discount_rate"] is None for point in public_history["history"])


def test_cross_service_empty_db_published_row_can_be_queued_for_re_review_and_rolled_back(monkeypatch):
    Session = _make_session_factory()
    db_admin_client = _make_db_admin_client(monkeypatch, Session)
    record = _crawler_like_record()
    item = _ai_admin_stubbed_item(record)
    ingestion_id = _submit_ai_ingestion_http(db_admin_client, item)

    approve_response = db_admin_client.post(
        f"/api/ingestions/{ingestion_id}/ai-safe-final-approve",
        json={"action": "approve", "notes": "publish before re-review regression"},
    )
    assert approve_response.status_code == 200, approve_response.text
    assert approve_response.json()["raw_evidence_retained"] is True

    re_review_response = db_admin_client.post(
        f"/api/ingestions/{ingestion_id}/published-items/0/re-review",
        json={"reason": "operator wants second review before broad rollout"},
    )
    assert re_review_response.status_code == 200, re_review_response.text
    re_review = re_review_response.json()
    assert re_review["raw_evidence_retained"] is True
    assert re_review["re_review_status"] == "crawler_approved"

    with Session() as session:
        re_review_row = session.get(PendingIngestion, re_review["re_review_ingestion_id"])
        assert re_review_row is not None
        review_item = json.loads(re_review_row.items_json)[0]
        assert review_item["raw_data"]["re_review_source"]["ingestion_id"] == ingestion_id
        assert review_item["raw_data"]["re_review_source"]["original_item"]["raw_record_id"] == record.raw_record_id
        assert session.query(Product).count() == 1
        assert session.query(DiscountHistory).count() == 1

    rollback_response = db_admin_client.post(
        f"/api/ingestions/{ingestion_id}/published-items/0/rollback",
        json={"reason": "operator rollback acceptance test"},
    )
    assert rollback_response.status_code == 200, rollback_response.text
    rollback = rollback_response.json()
    assert rollback["raw_evidence_retained"] is True
    assert rollback["rollback"]["status"] == "rolled_back"

    with Session() as session:
        original = session.get(PendingIngestion, ingestion_id)
        assert original is not None
        original_items = json.loads(original.items_json)
        assert original_items[0]["raw_record_id"] == record.raw_record_id
        assert original_items[0]["_db_admin_rollback"]["status"] == "rolled_back"
        product = session.execute(select(Product)).scalar_one()
        assert product.is_active is False
        assert product.categorization_method == "rolled_back"
        assert session.query(DiscountHistory).count() == 0
        audit_actions = {
            row.action
            for row in session.execute(select(AuditLog)).scalars().all()
        }
        assert "ingestion_published_row_re_review" in audit_actions
        assert "ingestion_published_row_rollback" in audit_actions
