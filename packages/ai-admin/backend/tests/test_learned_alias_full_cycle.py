"""Integration tests: learned_alias 사이클 end-to-end.

Scenarios
---------
A – RULE_LEARNED_ALIAS automation gate fires when success_count >= threshold
    (sub-case: gate blocked when success_count < threshold)
B – ProductMatchStore signature-based bypass eliminates AI provider call
C – success_count increments correctly on repeated keyword approval   ← Gap-1 test
D – frontend approve button → POST /keyword-proposals/{id}/approve
    → LearnedKnowledgeRepository wiring
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

import api.routes.review as review_routes
from api.app import create_app
from api.routes.review import get_db as review_get_db
from api.routes.prompts import get_db as prompts_get_db
from core.contracts.ai_pipeline import (
    AIWorkerRole,
    FieldProposal,
    FieldProvenance,
    PipelineStatus,
    ProposalType,
    RawCrawlRecord,
)
from core.contracts.control_plane import (
    LearnedKnowledgeContract,
    ProductMatchContract,
    ProductMatchProvenanceSource,
    ProductMatchStatus,
    ProductMatchTargetType,
    RawCrawlBatchContract,
)
from services.review_automation import (
    RULE_LEARNED_ALIAS,
    AutomationGateConfig,
    apply_automation_gates,
    build_automation_preview,
)
from services.keyword_catalog import KeywordCatalogAdapter
from services import ai_ingestion
from storage import (
    Database,
    FieldProposalRepository,
    KeywordProposalRepository,
    LearnedKnowledgeRepository,
    ProductMatchStoreRepository,
    RawCrawlBatchRepository,
    create_database,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_CATEGORY_ID = "processed.tofu.firm"   # safe seed category
_SOURCE_NAME = "emart"
_KEYWORD = "두부"
_ALIAS_TERM = "국산콩두부"
_KNOWLEDGE_ID = "knowledge:tofu-alias-test"

_SSAMJANG_CATEGORY = "processed.sauce.ssamjang"
_SSAMJANG_KEYWORD = "쌈장"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path) -> Database:
    database = create_database(f"sqlite:///{(tmp_path / 'learned-alias.db').as_posix()}")
    yield database
    database.dispose()


@pytest.fixture()
def db_admin_url(tmp_path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Lightweight in-memory keyword catalog used by approve_keyword_proposal."""
    url = f"sqlite:///{(tmp_path / 'db-admin.db').as_posix()}"
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE keywords ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "word VARCHAR(100) UNIQUE NOT NULL, "
                "synonyms JSON, "
                "category_id VARCHAR(100), "
                "search_count INTEGER DEFAULT 0, "
                "is_active BOOLEAN DEFAULT 1)"
            )
        )
        conn.execute(
            text("CREATE TABLE products (id INTEGER PRIMARY KEY, name VARCHAR(255))")
        )
        conn.execute(
            text(
                "CREATE TABLE product_keywords ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "product_id INTEGER NOT NULL, "
                "keyword_id INTEGER NOT NULL, "
                "UNIQUE(product_id, keyword_id))"
            )
        )

    def _init_adapter(adapter: KeywordCatalogAdapter, database_url=None) -> None:
        adapter.database_url = url
        adapter.engine = create_engine(url, connect_args={"check_same_thread": False})

    monkeypatch.setattr(KeywordCatalogAdapter, "__init__", _init_adapter)
    return url


@pytest.fixture()
def client(db: Database, db_admin_url: str) -> TestClient:
    app = create_app()
    app.dependency_overrides[prompts_get_db] = lambda: db
    app.dependency_overrides[review_get_db] = lambda: db
    return TestClient(app)


@pytest.fixture(autouse=True)
def stub_db_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _preflight():
        return {
            "status": "ready",
            "ready_to_mutate": True,
            "snapshot": {"verified": True, "latest_backup": "test.sqlite"},
        }

    async def _final_approve(ingestion_id, *, notes=None):
        raise RuntimeError("final_approve not stubbed in learned_alias tests")

    monkeypatch.setattr(review_routes, "_check_db_admin_mutation_preflight", _preflight)
    monkeypatch.setattr(review_routes, "_ai_safe_final_approve_db_admin", _final_approve)


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def _raw_record(
    raw_record_id: str,
    *,
    raw_title: str = "풀무원 국산콩 두부 300g",
    raw_price: float = 2480,
    source_url: str | None = None,
    category_id: str = _CATEGORY_ID,
) -> RawCrawlRecord:
    url = source_url or f"https://emart.example/{raw_record_id}"
    return RawCrawlRecord(
        raw_record_id=raw_record_id,
        source_name=_SOURCE_NAME,
        source_url=url,
        raw_title=raw_title,
        raw_price=raw_price,
        raw_payload={
            "source_url": url,
            "unit": "300g",
            "expected_ai": {
                "canonical_name": raw_title,
                "category_id": category_id,
            },
        },
    )


def _field_proposal(
    raw_id: str,
    target_field: str,
    value,
    *,
    status: PipelineStatus = PipelineStatus.APPROVED,
    proposal_type: ProposalType = ProposalType.NORMALIZED_FIELD,
    confidence: float = 0.96,
    alternatives: list | None = None,
) -> FieldProposal:
    return FieldProposal(
        proposal_id=f"{raw_id}:{target_field}",
        proposal_type=proposal_type,
        target_field=target_field,
        proposed_value=value,
        status=status,
        provenance=FieldProvenance(
            raw_record_id=raw_id,
            source_field="raw_title",
            evidence_text=f"evidence:{raw_id}:{target_field}",
            worker_role=(
                AIWorkerRole.KEYWORD_GENERATOR
                if proposal_type == ProposalType.KEYWORD
                else AIWorkerRole.CLASSIFIER
            ),
            confidence=confidence,
        ),
        alternatives=alternatives or [],
    )


def _background_proposals(raw_id: str, *, category_id: str = _CATEGORY_ID) -> list[FieldProposal]:
    """Approved filler proposals so build_raw_ai_audit sees all required signals."""
    return [
        _field_proposal(raw_id, "canonical_name", "풀무원 국산콩 두부 300g"),
        _field_proposal(raw_id, "package_unit", "g"),
        _field_proposal(
            raw_id,
            "category_id",
            category_id,
            proposal_type=ProposalType.CATEGORY,
        ),
    ]


def _seed_automation_record(
    db: Database,
    *,
    batch_id: str = "batch-A",
    raw_id: str = "alias-A",
    success_count: int = 2,
) -> None:
    """Scenario A seed: full batch with one AI_PROPOSED keyword proposal backed by LearnedKnowledge."""
    record = _raw_record(raw_id)
    with db.session_scope() as session:
        raw_repo = RawCrawlBatchRepository(session)
        raw_repo.save(
            RawCrawlBatchContract(
                batch_id=batch_id,
                source_name=_SOURCE_NAME,
                crawler_name="alias-test",
                item_count=1,
                schema_type="product_offer",
                status=PipelineStatus.RAW_INGESTED,
            )
        )
        raw_repo.save_records(batch_id, [record])

        proposal_repo = FieldProposalRepository(session)
        for prop in _background_proposals(raw_id):
            proposal_repo.save(prop)

        proposal_repo.save(
            _field_proposal(
                raw_id,
                "keywords",
                _KEYWORD,
                status=PipelineStatus.AI_PROPOSED,
                proposal_type=ProposalType.KEYWORD,
                confidence=0.97,
                alternatives=[
                    {
                        "word": _KEYWORD,
                        "knowledge_id": _KNOWLEDGE_ID,
                        "matched_term": _ALIAS_TERM,
                        "category_id": _CATEGORY_ID,
                        "evidence_class": "learned_alias",
                        "trust_label": "reuse_learned_alias",
                    }
                ],
            )
        )

        LearnedKnowledgeRepository(session).save(
            LearnedKnowledgeContract(
                knowledge_id=_KNOWLEDGE_ID,
                knowledge_type="keyword_alias_approved",
                source_name=_SOURCE_NAME,
                pattern=_ALIAS_TERM,
                target_value={"word": _KEYWORD, "category_id": _CATEGORY_ID},
                positive_examples=["풀무원 국산콩 두부 300g"],
                success_count=success_count,
            )
        )


def _seed_product_match_record(
    db: Database,
    *,
    batch_id: str = "batch-B",
    raw_id: str = "match-B",
    raw_title: str = "풀무원 두부 300g",
) -> None:
    """Scenario B seed: raw record + matching HUMAN-approved ProductMatchContract."""
    record = _raw_record(raw_id, raw_title=raw_title)
    with db.session_scope() as session:
        raw_repo = RawCrawlBatchRepository(session)
        raw_repo.save(
            RawCrawlBatchContract(
                batch_id=batch_id,
                source_name=_SOURCE_NAME,
                crawler_name="match-test",
                item_count=1,
                schema_type="product_offer",
                status=PipelineStatus.RAW_INGESTED,
            )
        )
        raw_repo.save_records(batch_id, [record])
        ProductMatchStoreRepository(session).save(
            ProductMatchContract(
                source_id=_SOURCE_NAME,
                source_name=_SOURCE_NAME,
                # signature_key == raw_title → get_by_source_signature path fires
                signature_key=raw_title,
                target_type=ProductMatchTargetType.SOURCE_LISTING,
                target_id="listing-tofu",
                canonical_product_name="풀무원 두부 300g",
                category_id=_CATEGORY_ID,
                keywords=[_KEYWORD],
                allowed_title_patterns=["풀무원 두부 300g"],
                package_signature="300g",
                provenance_source=ProductMatchProvenanceSource.HUMAN,
                status=ProductMatchStatus.APPROVED,
                audit_reason="test approved match",
                reviewed_by="reviewer-test",
            )
        )


def _seed_keyword_proposal(
    db: Database,
    proposal_id: str,
    *,
    keyword: str = _SSAMJANG_KEYWORD,
    match_terms: list[str] | None = None,
    raw_record_id: str = "ssamjang-1",
) -> None:
    match_terms = match_terms or ["고기쌈장", keyword]
    with db.session_scope() as session:
        KeywordProposalRepository(session).save(
            {
                "proposal_id": proposal_id,
                "proposed_keyword": keyword,
                "match_terms": match_terms,
                "triggering_records": [
                    {
                        "raw_record_id": raw_record_id,
                        "raw_title": "고기쌈장 500g",
                        "raw_price": 3980,
                        "source_name": _SOURCE_NAME,
                    }
                ],
                "status": PipelineStatus.AI_PROPOSED.value,
            }
        )


# ---------------------------------------------------------------------------
# Scenario A – RULE_LEARNED_ALIAS automation gate
# ---------------------------------------------------------------------------

class TestScenarioA_AutomationGate:
    """RULE_LEARNED_ALIAS fires iff success_count >= learned_alias_min_success_count."""

    def test_gate_fires_when_success_count_meets_threshold(self, db: Database) -> None:
        _seed_automation_record(db, success_count=2)
        config = AutomationGateConfig(
            enabled=True,
            selected_rule_ids=[RULE_LEARNED_ALIAS],
            learned_alias_min_success_count=2,
        )
        with db.session_scope() as session:
            result = apply_automation_gates(session, config, batch_id="batch-A")

        assert result["applied_count"] == 1, (
            f"expected gate to fire for learned alias; blockers: "
            f"{[row['blockers'] for row in result.get('blocked_items', [])]}"
        )
        assert result["eligible_count"] == 1

    def test_gate_blocked_when_success_count_below_threshold(self, db: Database) -> None:
        _seed_automation_record(db, success_count=1)
        config = AutomationGateConfig(
            enabled=True,
            selected_rule_ids=[RULE_LEARNED_ALIAS],
            learned_alias_min_success_count=2,
        )
        with db.session_scope() as session:
            result = build_automation_preview(session, config, batch_id="batch-A")

        assert result["eligible_count"] == 0
        blocked_reasons = " | ".join(
            blocker
            for row in result["blocked_items"]
            for blocker in row["blockers"]
        )
        assert "success_count" in blocked_reasons, (
            f"Expected success_count blocker; got: {blocked_reasons}"
        )

    def test_gate_approves_proposal_in_db(self, db: Database) -> None:
        _seed_automation_record(db, success_count=3)
        config = AutomationGateConfig(
            enabled=True,
            selected_rule_ids=[RULE_LEARNED_ALIAS],
            learned_alias_min_success_count=2,
        )
        with db.session_scope() as session:
            apply_automation_gates(session, config, batch_id="batch-A")

        with db.session_scope() as session:
            proposal = FieldProposalRepository(session).get("alias-A:keywords")

        assert proposal is not None
        assert proposal.status == PipelineStatus.APPROVED

    def test_gate_requires_no_negative_examples(self, db: Database) -> None:
        # Seed knowledge WITH negative examples → gate must be blocked
        _seed_automation_record(db, success_count=5)
        with db.session_scope() as session:
            LearnedKnowledgeRepository(session).save(
                LearnedKnowledgeContract(
                    knowledge_id=_KNOWLEDGE_ID,
                    knowledge_type="keyword_alias_approved",
                    source_name=_SOURCE_NAME,
                    pattern=_ALIAS_TERM,
                    target_value={"word": _KEYWORD, "category_id": _CATEGORY_ID},
                    positive_examples=["풀무원 국산콩 두부 300g"],
                    negative_examples=["가짜 두부"],
                    success_count=5,
                )
            )
        config = AutomationGateConfig(
            enabled=True,
            selected_rule_ids=[RULE_LEARNED_ALIAS],
        )
        with db.session_scope() as session:
            result = build_automation_preview(session, config, batch_id="batch-A")

        assert result["eligible_count"] == 0
        blocked_reasons = " | ".join(
            blocker
            for row in result["blocked_items"]
            for blocker in row["blockers"]
        )
        assert "negative" in blocked_reasons


# ---------------------------------------------------------------------------
# Scenario B – ProductMatchStore signature bypass
# ---------------------------------------------------------------------------

class TestScenarioB_ProductMatchBypass:
    """product_match_precheck returns approved proposals; unmatched list is empty."""

    def test_signature_match_skips_ai_provider(self, db: Database) -> None:
        raw_title = "풀무원 두부 300g"
        _seed_product_match_record(db, raw_title=raw_title)
        record = _raw_record("match-B", raw_title=raw_title)

        with db.session_scope() as session:
            repo = ProductMatchStoreRepository(session)
            proposals, unmatched, matched = ai_ingestion.product_match_precheck(
                repository=repo,
                records=[record],
                root_batch_id="batch-B",
            )

        assert len(matched) == 1, "expected one matched record"
        assert len(unmatched) == 0, "expected no unmatched records"
        assert len(proposals) > 0, "expected pre-built proposals from match"
        assert matched[0]["raw_record_id"] == "match-B"
        assert matched[0]["source"] == "learned_match/product_match"

    def test_unrecognised_title_falls_through_to_unmatched(self, db: Database) -> None:
        _seed_product_match_record(db, raw_title="풀무원 두부 300g")
        unknown_record = _raw_record("unknown-1", raw_title="완전 다른 상품 999g")

        with db.session_scope() as session:
            repo = ProductMatchStoreRepository(session)
            _, unmatched, matched = ai_ingestion.product_match_precheck(
                repository=repo,
                records=[unknown_record],
                root_batch_id="batch-B-miss",
            )

        assert len(unmatched) == 1
        assert len(matched) == 0

    def test_inactive_match_not_reused(self, db: Database) -> None:
        raw_title = "비활성 두부 300g"
        record = _raw_record("inactive-1", raw_title=raw_title)
        with db.session_scope() as session:
            raw_repo = RawCrawlBatchRepository(session)
            raw_repo.save(
                RawCrawlBatchContract(
                    batch_id="batch-B-inactive",
                    source_name=_SOURCE_NAME,
                    crawler_name="inactive-test",
                    item_count=1,
                    schema_type="product_offer",
                    status=PipelineStatus.RAW_INGESTED,
                )
            )
            raw_repo.save_records("batch-B-inactive", [record])
            ProductMatchStoreRepository(session).save(
                ProductMatchContract(
                    source_id=_SOURCE_NAME,
                    source_name=_SOURCE_NAME,
                    signature_key=raw_title,
                    target_type=ProductMatchTargetType.SOURCE_LISTING,
                    target_id="listing-inactive",
                    canonical_product_name=raw_title,
                    category_id=_CATEGORY_ID,
                    keywords=[_KEYWORD],
                    allowed_title_patterns=[raw_title],
                    package_signature="300g",
                    provenance_source=ProductMatchProvenanceSource.HUMAN,
                    status=ProductMatchStatus.APPROVED,
                    is_active=False,   # explicitly inactive
                    audit_reason="inactive match",
                    reviewed_by="reviewer-test",
                )
            )

        with db.session_scope() as session:
            repo = ProductMatchStoreRepository(session)
            _, unmatched, matched = ai_ingestion.product_match_precheck(
                repository=repo,
                records=[record],
                root_batch_id="batch-B-inactive",
            )

        assert len(unmatched) == 1, "inactive match must not be reused"
        assert len(matched) == 0


# ---------------------------------------------------------------------------
# Scenario C – success_count increments on repeat approval  ← Gap 1 test
# ---------------------------------------------------------------------------

class TestScenarioC_SuccessCountIncrement:
    """Each approval of the same keyword term must raise success_count by 1.

    Before the Gap-1 fix this test fails: success_count stays at 0 after
    every approval because _save_keyword_learning always passes success_count=0
    (the LearnedKnowledgeContract field default) when constructing the entry.
    """

    def test_first_approval_sets_success_count_to_one(
        self,
        client: TestClient,
        db: Database,
    ) -> None:
        _seed_keyword_proposal(db, "kw-c1", raw_record_id="ssamjang-C1")
        resp = client.post(
            "/api/review/keyword-proposals/kw-c1/approve",
            json={
                "reviewer_id": "tester",
                "proposed_keyword": _SSAMJANG_KEYWORD,
                "match_terms": ["고기쌈장", _SSAMJANG_KEYWORD],
                "category_suggestion": _SSAMJANG_CATEGORY,
            },
        )
        assert resp.status_code == 200, resp.text

        with db.session_scope() as session:
            entries = LearnedKnowledgeRepository(session).list(active_only=True)
        approved = [e for e in entries if e.knowledge_type == "keyword_alias_approved"]
        assert approved, "expected at least one LearnedKnowledge entry after approval"
        assert all(e.success_count >= 1 for e in approved), (
            f"Gap 1: success_count was not incremented; entries: "
            f"{[(e.pattern, e.success_count) for e in approved]}"
        )

    def test_second_approval_increments_success_count_to_two(
        self,
        client: TestClient,
        db: Database,
    ) -> None:
        # Two separate proposals for the same keyword / match term
        _seed_keyword_proposal(db, "kw-c2a", raw_record_id="ssamjang-C2a")
        _seed_keyword_proposal(db, "kw-c2b", raw_record_id="ssamjang-C2b")

        for pid in ("kw-c2a", "kw-c2b"):
            resp = client.post(
                f"/api/review/keyword-proposals/{pid}/approve",
                json={
                    "reviewer_id": "tester",
                    "proposed_keyword": _SSAMJANG_KEYWORD,
                    "match_terms": ["고기쌈장", _SSAMJANG_KEYWORD],
                    "category_suggestion": _SSAMJANG_CATEGORY,
                },
            )
            assert resp.status_code == 200, f"approve {pid}: {resp.text}"

        with db.session_scope() as session:
            entries = LearnedKnowledgeRepository(session).list(active_only=True)

        approved = [e for e in entries if e.knowledge_type == "keyword_alias_approved"]
        assert approved
        max_count = max(e.success_count for e in approved)
        assert max_count >= 2, (
            f"Gap 1: expected success_count >= 2 after two approvals; "
            f"got {[(e.pattern, e.success_count) for e in approved]}"
        )

    def test_success_count_reaches_gate_threshold_after_two_approvals(
        self,
        client: TestClient,
        db: Database,
    ) -> None:
        """After two approvals the RULE_LEARNED_ALIAS gate threshold of 2 is reachable."""
        _seed_keyword_proposal(db, "kw-c3a", raw_record_id="ssamjang-C3a")
        _seed_keyword_proposal(db, "kw-c3b", raw_record_id="ssamjang-C3b")

        for pid in ("kw-c3a", "kw-c3b"):
            resp = client.post(
                f"/api/review/keyword-proposals/{pid}/approve",
                json={
                    "reviewer_id": "tester",
                    "proposed_keyword": _SSAMJANG_KEYWORD,
                    "match_terms": ["고기쌈장", _SSAMJANG_KEYWORD],
                    "category_suggestion": _SSAMJANG_CATEGORY,
                },
            )
            assert resp.status_code == 200, f"approve {pid}: {resp.text}"

        with db.session_scope() as session:
            entries = LearnedKnowledgeRepository(session).list(active_only=True)

        # At least one term for "쌈장" must have success_count >= 2
        ssamjang_entries = [
            e for e in entries
            if e.knowledge_type == "keyword_alias_approved"
        ]
        assert any(e.success_count >= 2 for e in ssamjang_entries), (
            f"Gap 1: no entry reached threshold=2; "
            f"entries: {[(e.pattern, e.success_count) for e in ssamjang_entries]}"
        )


# ---------------------------------------------------------------------------
# Scenario D – frontend approve button → route → LearnedKnowledgeRepository
# ---------------------------------------------------------------------------

class TestScenarioD_ApproveRouteWiring:
    """POST /keyword-proposals/{id}/approve creates a LearnedKnowledge entry."""

    def test_approve_creates_learned_knowledge_entry(
        self,
        client: TestClient,
        db: Database,
    ) -> None:
        _seed_keyword_proposal(db, "kw-d1", raw_record_id="tofu-D1", keyword=_KEYWORD,
                               match_terms=["국산콩두부", _KEYWORD])
        resp = client.post(
            "/api/review/keyword-proposals/kw-d1/approve",
            json={
                "reviewer_id": "lucy",
                "proposed_keyword": _KEYWORD,
                "match_terms": ["국산콩두부", _KEYWORD],
                "category_suggestion": _CATEGORY_ID,
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["proposal"]["status"] == "approved"

        with db.session_scope() as session:
            entries = LearnedKnowledgeRepository(session).list(active_only=True)
        approved = [e for e in entries if e.knowledge_type == "keyword_alias_approved"]
        assert approved, "approve route must create LearnedKnowledge entry"
        patterns = {e.pattern for e in approved}
        assert _KEYWORD in patterns or "국산콩두부" in patterns, (
            f"Expected keyword/alias pattern in entries; got {patterns}"
        )

    def test_approve_rejects_already_decided_proposal(
        self,
        client: TestClient,
        db: Database,
    ) -> None:
        _seed_keyword_proposal(db, "kw-d2", raw_record_id="tofu-D2")
        payload = {
            "reviewer_id": "lucy",
            "proposed_keyword": _SSAMJANG_KEYWORD,
            "match_terms": ["고기쌈장"],
            "category_suggestion": _SSAMJANG_CATEGORY,
        }
        first = client.post("/api/review/keyword-proposals/kw-d2/approve", json=payload)
        assert first.status_code == 200, first.text

        second = client.post("/api/review/keyword-proposals/kw-d2/approve", json=payload)
        assert second.status_code == 400, (
            f"re-approving an already-approved proposal must return 400; got {second.status_code}"
        )

    def test_approve_returns_404_for_missing_proposal(
        self,
        client: TestClient,
    ) -> None:
        resp = client.post(
            "/api/review/keyword-proposals/does-not-exist/approve",
            json={"reviewer_id": "lucy"},
        )
        assert resp.status_code == 404

    def test_approve_persists_positive_examples_from_triggering_records(
        self,
        client: TestClient,
        db: Database,
    ) -> None:
        _seed_keyword_proposal(
            db,
            "kw-d3",
            raw_record_id="tofu-D3",
            keyword=_KEYWORD,
            match_terms=["국산콩두부", _KEYWORD],
        )
        resp = client.post(
            "/api/review/keyword-proposals/kw-d3/approve",
            json={
                "reviewer_id": "lucy",
                "proposed_keyword": _KEYWORD,
                "match_terms": ["국산콩두부", _KEYWORD],
                "category_suggestion": _CATEGORY_ID,
            },
        )
        assert resp.status_code == 200, resp.text

        with db.session_scope() as session:
            entries = LearnedKnowledgeRepository(session).list(active_only=True)
        approved = [e for e in entries if e.knowledge_type == "keyword_alias_approved"]
        # triggering record raw_title ("고기쌈장 500g") must appear in positive_examples
        all_examples = {ex for e in approved for ex in e.positive_examples}
        assert "고기쌈장 500g" in all_examples, (
            f"triggering record title missing from positive_examples; got {all_examples}"
        )
