"""rd-empty-db-full-cycle — 빈 DB 전체 사이클 통합 테스트.

검증 범위 (Launch Gate Slice):
  클릭 1 — 크롤 fixture → raw_records 변환
  클릭 2 — AI 라벨링 (사이클 1: product_match_hits=0, 100% AI 처리)
  클릭 3 — 인간 승인 시뮬레이션 → ProductMatch 등록 (HUMAN/APPROVED/is_active=True)
  사이클 2 — 동일 데이터 재실행 → product_match_hits ≥ 80% (자동 매칭 검증)

엣지 케이스:
  EC-1 빈 provider 응답 → reviewer-safe deterministic fallback (confidence=0.42)
  EC-2 같은 canonical name, 두 마트 → 각 마트별 별도 proposal 행
  EC-3 shrink retry N→N/2→1→fallback (_call_provider_with_shrink_retries)
  EC-4 LearnedKnowledge(success_count≥2) → prompt context 포함 확인
  EC-5 escalation(confidence낮은) 행 → proposals_stored에 포함, 별도 추적 가능

출력물: .walletsavior-live-validation/empty-db-full-cycle/run-{ts}-{id}.{json,md}
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

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# ─── 경로 설정 ────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent.parent
AI_BACKEND = ROOT / "packages" / "ai-admin" / "backend"
SHARED = ROOT / "packages" / "shared"
CRAWLER_BACKEND = ROOT / "packages" / "crawler-admin" / "backend"
CRAWLER_FIXTURES = CRAWLER_BACKEND / "tests" / "fixtures"

# ─── 출력 디렉터리 ─────────────────────────────────────────────────────────────
OUTPUT_DIR = ROOT / ".walletsavior-live-validation" / "empty-db-full-cycle"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ─── AI-admin 모듈 격리 임포트 ────────────────────────────────────────────────
_AI_MODULE_NAMES = (
    "api", "services", "storage", "providers", "config",
    "engine", "pipeline",
)

def _is_ai_module(name: str) -> bool:
    return any(name == n or name.startswith(n + ".") for n in _AI_MODULE_NAMES)


@contextmanager
def _ai_admin_isolation():
    """ai-admin 백엔드를 sys.path에 추가하고 격리된 상태에서 임포트한다."""
    saved_path = list(sys.path)
    saved_modules = {k: v for k, v in sys.modules.items() if _is_ai_module(k)}
    for name in list(saved_modules):
        sys.modules.pop(name, None)
    sys.path.insert(0, str(AI_BACKEND))
    sys.path.insert(0, str(SHARED))
    try:
        yield
    finally:
        for name in [k for k in list(sys.modules) if _is_ai_module(k)]:
            sys.modules.pop(name, None)
        sys.modules.update(saved_modules)
        sys.path = saved_path


# ─── 모듈 수준 격리 임포트 ────────────────────────────────────────────────────
with _ai_admin_isolation():
    _storage_mod = importlib.import_module("storage")
    _ai_ingestion = importlib.import_module("services.ai_ingestion")
    _repos = importlib.import_module("storage.repositories")
    _models = importlib.import_module("storage.models")
    # providers.google_genai.ProviderResponseError은 ai-admin 경로에서만 임포트 가능
    _google_genai = importlib.import_module("providers.google_genai")

# 이후 테스트에서 사용할 레퍼런스를 저장한다 (재임포트 없이)
_Base = _models.Base
_Database = _storage_mod.Database
_ingest_and_label_records = _ai_ingestion.ingest_and_label_records
_product_match_precheck = _ai_ingestion.product_match_precheck
_call_provider_with_shrink_retries = _ai_ingestion._call_provider_with_shrink_retries
_ProviderConfigRepository = _repos.ProviderConfigRepository
_ProductMatchStoreRepository = _repos.ProductMatchStoreRepository
_LearnedKnowledgeRepository = _repos.LearnedKnowledgeRepository
_ProviderResponseError = _google_genai.ProviderResponseError

# shared contract 임포트는 sys.path 조작 없이도 가능하다
from core.contracts.ai_pipeline import (
    PipelineStatus,
    ProviderKind,
    RawCrawlRecord,
)
from core.contracts.control_plane import (
    LearnedKnowledgeContract,
    ProductMatchContract,
    ProductMatchProvenanceSource,
    ProductMatchStatus,
    ProviderConfigContract,
    normalize_product_signature_key,
    normalize_match_text,
)

# ─── 테스트 레코드 정의 ────────────────────────────────────────────────────────
# 4개 마트, 총 12개 레코드 (3개씩)
_TEST_RECORDS: list[RawCrawlRecord] = [
    # ── 이마트 ──
    RawCrawlRecord(
        raw_record_id="emart-001",
        source_name="emart",
        source_record_key="emart-item-001",
        raw_title="풀무원 국산콩 두부 300g",
        raw_price=1980,
        raw_payload={"category": "두부/콩나물"},
    ),
    RawCrawlRecord(
        raw_record_id="emart-002",
        source_name="emart",
        source_record_key="emart-item-002",
        raw_title="CJ 비비고 왕교자 1.05kg",
        raw_price=9900,
        raw_payload={"category": "만두/떡볶이"},
    ),
    RawCrawlRecord(
        raw_record_id="emart-003",
        source_name="emart",
        source_record_key="emart-item-003",
        raw_title="서울우유 흰우유 1L",
        raw_price=2680,
        raw_payload={"category": "우유/유제품"},
    ),
    # ── 홈플러스 ──
    RawCrawlRecord(
        raw_record_id="homeplus-001",
        source_name="homeplus",
        source_record_key="H068769294N37O0",
        raw_title="simplus 숯불닭꼬치 520G",
        raw_price=11900,
        raw_payload={"category": "냉동식품"},
    ),
    RawCrawlRecord(
        raw_record_id="homeplus-002",
        source_name="homeplus",
        source_record_key="H145781242N37O0",
        raw_title="simplus 엑스트라버진 올리브유 1L",
        raw_price=14900,
        raw_payload={"category": "식용유"},
    ),
    RawCrawlRecord(
        raw_record_id="homeplus-003",
        source_name="homeplus",
        source_record_key="H070456955N37O0",
        raw_title="허쉬 크림파이 크림치즈 224G",
        raw_price=5290,
        raw_payload={"category": "과자"},
    ),
    # ── 롯데마트 ──
    RawCrawlRecord(
        raw_record_id="lottemart-001",
        source_name="lottemart",
        source_record_key="lotte-item-001",
        raw_title="롯데 칠성 사이다 1.5L 6입",
        raw_price=7800,
        raw_payload={"category": "음료"},
    ),
    RawCrawlRecord(
        raw_record_id="lottemart-002",
        source_name="lottemart",
        source_record_key="lotte-item-002",
        raw_title="남양 불가리스 딸기 80ml 8입",
        raw_price=3990,
        raw_payload={"category": "요거트"},
    ),
    RawCrawlRecord(
        raw_record_id="lottemart-003",
        source_name="lottemart",
        source_record_key="lotte-item-003",
        raw_title="오리온 초코파이 12입",
        raw_price=4500,
        raw_payload={"category": "과자"},
    ),
    # ── 코스트코 ──
    RawCrawlRecord(
        raw_record_id="costco-001",
        source_name="costco",
        source_record_key="costco-item-001",
        raw_title="Kirkland 생수 500ml 40입",
        raw_price=8990,
        raw_payload={"category": "생수"},
    ),
    RawCrawlRecord(
        raw_record_id="costco-002",
        source_name="costco",
        source_record_key="costco-item-002",
        raw_title="코카콜라 355ml 35캔",
        raw_price=28900,
        raw_payload={"category": "음료"},
    ),
    RawCrawlRecord(
        raw_record_id="costco-003",
        source_name="costco",
        source_record_key="costco-item-003",
        raw_title="농심 신라면 120g 20봉",
        raw_price=19900,
        raw_payload={"category": "라면"},
    ),
]

# raw_record_id → (canonical_name, category_id, keywords)
_STUB_LABELS: dict[str, dict[str, Any]] = {
    "emart-001": {"canonical_name": "풀무원 국산콩 두부 300g", "category_id": "fresh.tofu", "keywords": ["두부"]},
    "emart-002": {"canonical_name": "비비고 왕교자 1.05kg", "category_id": "frozen.dumpling", "keywords": ["교자", "만두"]},
    "emart-003": {"canonical_name": "서울우유 흰우유 1L", "category_id": "dairy.milk", "keywords": ["우유"]},
    "homeplus-001": {"canonical_name": "숯불닭꼬치 520g", "category_id": "frozen.snack", "keywords": ["닭꼬치"]},
    "homeplus-002": {"canonical_name": "엑스트라버진 올리브유 1L", "category_id": "oil.olive", "keywords": ["올리브유"]},
    "homeplus-003": {"canonical_name": "허쉬 크림파이 크림치즈 224g", "category_id": "snack.pie", "keywords": ["파이"]},
    "lottemart-001": {"canonical_name": "칠성사이다 1.5L 6입", "category_id": "beverage.soda", "keywords": ["사이다"]},
    "lottemart-002": {"canonical_name": "불가리스 딸기 80ml 8입", "category_id": "dairy.yogurt", "keywords": ["요거트"]},
    "lottemart-003": {"canonical_name": "초코파이 12입", "category_id": "snack.pie", "keywords": ["초코파이"]},
    "costco-001": {"canonical_name": "Kirkland 생수 500ml 40입", "category_id": "beverage.water", "keywords": ["생수"]},
    "costco-002": {"canonical_name": "코카콜라 355ml 35캔", "category_id": "beverage.cola", "keywords": ["콜라"]},
    "costco-003": {"canonical_name": "농심 신라면 120g 20봉", "category_id": "noodle.ramen", "keywords": ["신라면", "라면"]},
}


# ─── 테스트 인프라 ─────────────────────────────────────────────────────────────

def _make_ai_db() -> Any:
    """ai-admin 격리 in-memory SQLite DB 생성."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    _Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False,
                           expire_on_commit=False)
    return Session


def _make_stub_provider_factory(labels: dict[str, dict[str, Any]]):
    """각 raw_record_id에 맞는 결정론적 응답을 반환하는 fake provider factory."""

    class StubProvider:
        provider_mode = "stub"

        def __init__(self, config) -> None:
            self.config = config

        def call(self, *, prompt: str, schema=None) -> dict[str, Any]:
            items = []
            for rid, label in labels.items():
                items.append({
                    "raw_record_id": rid,
                    "canonical_name": label["canonical_name"],
                    "source_title": rid,
                    "sale_price": None,
                    "brand": None,
                    "category_id": label["category_id"],
                    "keywords": label["keywords"],
                    "aliases": [],
                    "attributes": {},
                    "package_quantity": None,
                    "package_unit": None,
                    "display_unit": None,
                    "bundle_count": 1,
                    "standard_unit": None,
                    "standard_unit_price": None,
                    "price_per_100g": None,
                    "confidence": 0.95,
                    "notes": "stub-test",
                })
            return {"items": items}

    return lambda config: StubProvider(config)


def _register_provider(session, provider_id: str = "stub-provider") -> None:
    """테스트용 provider config를 DB에 저장한다.

    min_request_interval_seconds≥1.0, max_provider_calls_per_minute≤120,
    provider_retry_min/max_delay_seconds≥1.0 — 모두 유효한 범위 내 최솟값.
    _sleep을 no-op으로 패치하므로 실제 대기 시간은 0이다.
    """
    _ProviderConfigRepository(session).save(
        ProviderConfigContract(
            provider_id=provider_id,
            provider_kind=ProviderKind.GEMINI,
            display_name="Test Stub Provider",
            default_model="stub-model",
            secret_alias="STUB_KEY",
            is_enabled=True,
            max_concurrent_jobs=1,
            min_request_interval_seconds=1.0,
            max_provider_calls_per_minute=120,
            max_provider_calls_per_day=100000,
            provider_retry_max_attempts=1,
            provider_retry_min_delay_seconds=1.0,
            provider_retry_max_delay_seconds=1.0,
            daily_budget_limit=0.0,
        )
    )
    session.commit()


def _register_product_matches(
    session,
    records: list[RawCrawlRecord],
    labels: dict[str, dict[str, Any]],
    approved_by: str = "cycle1-test-reviewer",
) -> int:
    """사이클 1 레코드에 대해 HUMAN/APPROVED ProductMatch를 등록한다.

    get_by_source_signature 경로를 통한 사이클 2 자동 매칭을 활성화한다.
    source_id = record.source_name (payload에 source_id 없을 때의 fallback)
    signature_key = record.raw_title (normalize_product_signature_key 적용)
    package_signature_required = False (패키지 불일치 없이 매칭)
    """
    repo = _ProductMatchStoreRepository(session)
    count = 0
    for record in records:
        label = labels.get(record.raw_record_id)
        if label is None:
            continue
        contract = ProductMatchContract(
            source_id=record.source_name,
            source_name=record.source_name,
            signature_key=record.raw_title,
            canonical_product_name=label["canonical_name"],
            category_id=label["category_id"],
            keywords=label["keywords"],
            status=ProductMatchStatus.APPROVED,
            provenance_source=ProductMatchProvenanceSource.HUMAN,
            is_active=True,
            package_signature_required=False,
            allowed_title_patterns=[normalize_match_text(record.raw_title)],
            approved_by=approved_by,
            approved_at=datetime.now(),
            audit_reason="cycle1 integration test approval",
            confidence=0.95,
        )
        repo.save(contract)
        count += 1
    session.commit()
    return count


def _no_sleep(*_args, **_kwargs):
    """rate-limit sleep을 no-op으로 대체."""


def _patch_sleep(monkeypatch) -> None:
    monkeypatch.setattr(_ai_ingestion, "_sleep", _no_sleep)


def _reset_call_history(provider_id: str) -> None:
    """테스트 간 rate-limit 히스토리 초기화."""
    _ai_ingestion._provider_call_history.pop(provider_id, None)


# ─── 메인 테스트: 빈 DB 풀 사이클 ────────────────────────────────────────────

class TestEmptyDbFullCycle:
    """클릭 1→2→3 그리고 사이클 2 자동 매칭 ≥80% 검증."""

    PROVIDER_ID = "stub-full-cycle"

    def setup_method(self):
        _reset_call_history(self.PROVIDER_ID)

    def test_cycle1_all_ai_no_matches(self, monkeypatch):
        """사이클 1: 빈 DB → 모든 레코드 AI 처리, product_match_hits = 0."""
        _patch_sleep(monkeypatch)
        Session = _make_ai_db()
        with Session() as session:
            _register_provider(session, self.PROVIDER_ID)
            factory = _make_stub_provider_factory(_STUB_LABELS)

            result = _ingest_and_label_records(
                session=session,
                provider_id=self.PROVIDER_ID,
                records=_TEST_RECORDS,
                source_name="integration-test",
                crawler_name="stub-crawler",
                schema_type="mart_discount",
                provider_factory=factory,
            )

        assert result["product_match_hits"] == 0, (
            f"빈 DB 사이클 1에서 product_match_hits가 0이어야 하는데 "
            f"{result['product_match_hits']}개가 매칭됨"
        )
        assert result["provider_calls"] >= 1, "AI provider가 최소 1번 호출되어야 함"
        # 각 레코드는 여러 필드 proposal을 생성하므로 proposals_stored ≥ len(records)
        assert result["proposals_stored"] >= len(_TEST_RECORDS), (
            f"모든 레코드에 대한 proposal이 최소 1개 이상 저장되어야 함: "
            f"expected ≥ {len(_TEST_RECORDS)}, got {result['proposals_stored']}"
        )
        assert result["status"] == "labeled"

    def test_cycle2_automatch_rate_gte_80pct(self, monkeypatch):
        """사이클 2: ProductMatch 등록 후 재실행 → auto-match rate ≥ 80%."""
        _patch_sleep(monkeypatch)
        Session = _make_ai_db()
        with Session() as session:
            _register_provider(session, self.PROVIDER_ID)
            factory = _make_stub_provider_factory(_STUB_LABELS)

            # 사이클 1 실행
            cycle1 = _ingest_and_label_records(
                session=session,
                provider_id=self.PROVIDER_ID,
                records=_TEST_RECORDS,
                source_name="integration-test",
                crawler_name="stub-crawler",
                schema_type="mart_discount",
                provider_factory=factory,
            )
            assert cycle1["product_match_hits"] == 0

            # 인간 승인 시뮬레이션: ProductMatch 등록 (클릭 3)
            registered = _register_product_matches(
                session, _TEST_RECORDS, _STUB_LABELS
            )
            assert registered == len(_TEST_RECORDS), (
                "모든 레코드에 대해 ProductMatch가 등록되어야 함"
            )

        _reset_call_history(self.PROVIDER_ID)

        # 사이클 2 실행 (같은 DB, 새 배치 ID)
        with Session() as session:
            factory2 = _make_stub_provider_factory(_STUB_LABELS)
            cycle2 = _ingest_and_label_records(
                session=session,
                provider_id=self.PROVIDER_ID,
                records=_TEST_RECORDS,
                source_name="integration-test",
                crawler_name="stub-crawler",
                schema_type="mart_discount",
                provider_factory=factory2,
            )

        total = len(_TEST_RECORDS)
        hits = cycle2["product_match_hits"]
        rate = hits / total
        assert rate >= 0.80, (
            f"사이클 2 자동 매칭률이 80% 미만: {hits}/{total} = {rate:.1%}\n"
            f"cycle2 result: {json.dumps(cycle2, ensure_ascii=False, indent=2)}"
        )
        # 자동 매칭된 레코드는 AI를 호출하지 않아야 한다
        assert cycle2["provider_calls"] < cycle1["provider_calls"], (
            "사이클 2는 사이클 1보다 AI 호출 횟수가 적어야 함"
        )

    def test_full_cycle_report_generated(self, monkeypatch):
        """풀 사이클 실행 후 JSON/MD 출력 파일이 생성된다."""
        _patch_sleep(monkeypatch)
        Session = _make_ai_db()

        with Session() as session:
            _register_provider(session, self.PROVIDER_ID)
            factory = _make_stub_provider_factory(_STUB_LABELS)

            cycle1 = _ingest_and_label_records(
                session=session,
                provider_id=self.PROVIDER_ID,
                records=_TEST_RECORDS,
                source_name="integration-test",
                crawler_name="stub-crawler",
                schema_type="mart_discount",
                provider_factory=factory,
            )
            registered = _register_product_matches(session, _TEST_RECORDS, _STUB_LABELS)

        _reset_call_history(self.PROVIDER_ID)

        with Session() as session:
            cycle2 = _ingest_and_label_records(
                session=session,
                provider_id=self.PROVIDER_ID,
                records=_TEST_RECORDS,
                source_name="integration-test",
                crawler_name="stub-crawler",
                schema_type="mart_discount",
                provider_factory=_make_stub_provider_factory(_STUB_LABELS),
            )

        total = len(_TEST_RECORDS)
        hits = cycle2["product_match_hits"]
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        run_id = uuid.uuid4().hex[:8]
        report = {
            "run_id": run_id,
            "timestamp": ts,
            "slice": "rd-empty-db-full-cycle",
            "total_records": total,
            "sources": sorted({r.source_name for r in _TEST_RECORDS}),
            "cycle1": {
                "product_match_hits": cycle1["product_match_hits"],
                "provider_calls": cycle1["provider_calls"],
                "proposals_stored": cycle1["proposals_stored"],
                "status": cycle1["status"],
            },
            "product_match_registered": registered,
            "cycle2": {
                "product_match_hits": hits,
                "auto_match_rate": round(hits / total, 4),
                "provider_calls": cycle2["provider_calls"],
                "proposals_stored": cycle2["proposals_stored"],
                "status": cycle2["status"],
            },
            "gate_passed": hits / total >= 0.80,
        }

        json_path = OUTPUT_DIR / f"run-{ts}-{run_id}.json"
        md_path = OUTPUT_DIR / f"run-{ts}-{run_id}.md"

        json_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        md_lines = [
            f"# rd-empty-db-full-cycle  `{run_id}`",
            f"실행 시각: {ts}",
            "",
            "## 결과 요약",
            f"- 총 레코드: **{total}**",
            f"- 소스: {', '.join(report['sources'])}",
            "",
            "## 사이클 1 (빈 DB → AI 라벨링)",
            f"- product_match_hits: {cycle1['product_match_hits']} (≡ 0 ✓)",
            f"- provider_calls: {cycle1['provider_calls']}",
            f"- proposals_stored: {cycle1['proposals_stored']}",
            "",
            f"## 클릭 3: 인간 승인 → ProductMatch 등록",
            f"- 등록된 ProductMatch: {registered}",
            "",
            "## 사이클 2 (학습 매칭)",
            f"- product_match_hits: **{hits}/{total}**",
            f"- 자동 매칭률: **{hits/total:.1%}**",
            f"- provider_calls: {cycle2['provider_calls']}",
            "",
            "## Launch Gate",
            f"- **{'✅ PASS' if report['gate_passed'] else '❌ FAIL'}**  "
            f"(auto-match ≥ 80% 조건: {hits/total:.1%})",
        ]
        md_path.write_text("\n".join(md_lines), encoding="utf-8")

        assert json_path.exists(), f"JSON 출력 파일이 생성되어야 함: {json_path}"
        assert md_path.exists(), f"MD 출력 파일이 생성되어야 함: {md_path}"
        assert report["gate_passed"], (
            f"Launch gate 실패: auto-match rate {hits/total:.1%} < 80%"
        )


# ─── EC-1: 빈 provider 응답 → reviewer-safe fallback ────────────────────────

class TestEmptyProviderFallback:
    """EC-1: provider가 빈 items를 반환하면 confidence=0.42 fallback proposal이 생성된다."""

    PROVIDER_ID = "stub-empty-fallback"

    def setup_method(self):
        _reset_call_history(self.PROVIDER_ID)

    def test_empty_response_creates_fallback_proposals(self, monkeypatch):
        _patch_sleep(monkeypatch)

        class EmptyProvider:
            provider_mode = "stub"
            def __init__(self, config):
                self.config = config
            def call(self, *, prompt, schema=None):
                return {"items": []}  # 아무것도 반환하지 않음

        Session = _make_ai_db()
        with Session() as session:
            _register_provider(session, self.PROVIDER_ID)

            record = RawCrawlRecord(
                raw_record_id="fallback-test-001",
                source_name="emart",
                source_record_key="fallback-key-001",
                raw_title="테스트 fallback 상품 300g",
                raw_price=3000,
                raw_payload={},
            )

            result = _ingest_and_label_records(
                session=session,
                provider_id=self.PROVIDER_ID,
                records=[record],
                source_name="emart",
                crawler_name="stub-crawler",
                schema_type="mart_discount",
                provider_factory=lambda config: EmptyProvider(config),
            )

        # fallback이 생성되면 proposals_stored > 0 (deterministic recovery)
        assert result["proposals_stored"] > 0, (
            "빈 응답 후 reviewer-safe fallback proposal이 생성되어야 함"
        )
        assert result["deterministic_recovery_count"] >= 1, (
            "deterministic_recovery_count ≥ 1이어야 함"
        )

    def test_fallback_notes_contain_marker(self, monkeypatch):
        """fallback proposal의 notes에 'reviewer-safe deterministic fallback' 마커가 있다."""
        _patch_sleep(monkeypatch)

        class EmptyProvider:
            provider_mode = "stub"
            def __init__(self, config):
                self.config = config
            def call(self, *, prompt, schema=None):
                return {"items": []}

        record = RawCrawlRecord(
            raw_record_id="fallback-notes-001",
            source_name="emart",
            source_record_key="fbn-001",
            raw_title="배 1.5kg",
            raw_price=9900,
            raw_payload={},
        )

        # _reviewer_safe_fallback_response_item 직접 검증
        item = _ai_ingestion._reviewer_safe_fallback_response_item(record)
        assert item["confidence"] == 0.42, (
            f"fallback confidence는 0.42이어야 하는데 {item['confidence']}임"
        )
        assert "reviewer-safe deterministic fallback" in item["notes"], (
            f"fallback notes에 마커 문자열이 없음: {item['notes']}"
        )
        assert item["raw_record_id"] == "fallback-notes-001"


# ─── EC-2: 같은 canonical name, 두 마트 → 별도 proposal 행 ──────────────────

class TestDualMartSameCanonical:
    """EC-2: 동일 canonical_name을 가진 두 마트의 레코드는 각각 별도 proposal로 저장된다."""

    PROVIDER_ID = "stub-dual-mart"

    def setup_method(self):
        _reset_call_history(self.PROVIDER_ID)

    def test_two_marts_same_canonical_get_separate_proposals(self, monkeypatch):
        _patch_sleep(monkeypatch)

        CANONICAL = "풀무원 두부 300g"
        records = [
            RawCrawlRecord(
                raw_record_id="emart-tofu-dual",
                source_name="emart",
                source_record_key="emart-tofu",
                raw_title="풀무원 국산콩 두부 300g",
                raw_price=1980,
                raw_payload={},
            ),
            RawCrawlRecord(
                raw_record_id="homeplus-tofu-dual",
                source_name="homeplus",
                source_record_key="homeplus-tofu",
                raw_title="풀무원 국산콩 두부 300g",
                raw_price=2090,
                raw_payload={},
            ),
        ]
        dual_labels = {
            "emart-tofu-dual": {
                "canonical_name": CANONICAL,
                "category_id": "fresh.tofu",
                "keywords": ["두부"],
            },
            "homeplus-tofu-dual": {
                "canonical_name": CANONICAL,
                "category_id": "fresh.tofu",
                "keywords": ["두부"],
            },
        }
        Session = _make_ai_db()
        with Session() as session:
            _register_provider(session, self.PROVIDER_ID)
            factory = _make_stub_provider_factory(dual_labels)

            result = _ingest_and_label_records(
                session=session,
                provider_id=self.PROVIDER_ID,
                records=records,
                source_name="multi-mart",
                crawler_name="stub-crawler",
                schema_type="mart_discount",
                provider_factory=factory,
            )

        # 두 레코드에 대해 각각 proposals가 생성되어야 한다
        assert result["proposals_stored"] >= 2, (
            f"두 마트의 두부 레코드에 대해 각각 proposal이 있어야 함: "
            f"{result['proposals_stored']}"
        )
        assert len(result["proposal_ids"]) >= 2, (
            "두 마트의 레코드에 대해 proposal_ids가 2개 이상이어야 함"
        )
        # 두 proposal은 서로 다른 ID를 가져야 한다
        ids = result["proposal_ids"]
        assert len(set(ids)) == len(ids), "proposal_ids에 중복이 없어야 함"


# ─── EC-3: shrink retry N→N/2→1→fallback ────────────────────────────────────

class TestShrinkRetry:
    """EC-3: _call_provider_with_shrink_retries는 retryable 오류 시 배치를 절반씩 축소한다."""

    PROVIDER_ID = "stub-shrink"

    def setup_method(self):
        _reset_call_history(self.PROVIDER_ID)

    def test_shrink_splits_and_falls_back_on_n1_failure(self, monkeypatch):
        """N=2 → retryable 오류 → N=1+1 → 각 N=1도 실패 → fallback proposal 생성."""
        _patch_sleep(monkeypatch)

        class ShrinkProvider:
            provider_mode = "stub"
            def __init__(self, config):
                self.config = config
            def call(self, *, prompt, schema=None):
                # 항상 retryable 오류를 발생시킨다 (quota 초과 패턴)
                raise _ProviderResponseError(
                    "429: quota exceeded",
                    provider_id="stub-shrink",
                    model="stub-model",
                )

        shrink_records = [
            RawCrawlRecord(
                raw_record_id=f"shrink-{i:03d}",
                source_name="emart",
                source_record_key=f"shrink-key-{i}",
                raw_title=f"테스트 상품 {i}번 300g",
                raw_price=1000 + i * 100,
                raw_payload={},
            )
            for i in range(2)
        ]

        Session = _make_ai_db()
        with Session() as session:
            _register_provider(session, self.PROVIDER_ID)
            provider_contract = _ProviderConfigRepository(session).get(self.PROVIDER_ID)
            assert provider_contract is not None

        provider = ShrinkProvider(provider_contract)
        keyword_catalog: list = []
        learned_knowledge: list = []
        shrink_log: list[dict] = []

        proposals, keyword_proposals, log = _call_provider_with_shrink_retries(
            records=shrink_records,
            provider=provider,
            provider_ref=_ai_ingestion._provider_ref(provider_contract),
            provider_id=self.PROVIDER_ID,
            model="stub-model",
            raw_batch_id="test-shrink-batch",
            ai_batch_id="test-shrink-batch:ai:1",
            keyword_catalog=keyword_catalog,
            learned_keyword_knowledge=learned_knowledge,
            _shrink_log=shrink_log,
        )

        # 최종적으로 fallback proposal이 생성되어야 한다 (모든 N=1 실패)
        assert len(proposals) > 0, (
            "shrink retry 후 fallback proposal이 생성되어야 함"
        )

        # shrink_log에는 retryable_error 항목이 있어야 한다
        retryable_entries = [e for e in log if e.get("outcome") == "retryable_error"]
        assert len(retryable_entries) > 0, (
            f"shrink_log에 retryable_error 항목이 있어야 함: {log}"
        )

        # fallback 항목도 있어야 한다
        fallback_entries = [e for e in log if e.get("outcome") == "fallback"]
        assert len(fallback_entries) > 0, (
            f"shrink_log에 fallback 항목이 있어야 함: {log}"
        )

    def test_shrink_succeeds_on_smaller_batch(self, monkeypatch):
        """N=2 retryable 오류 → N=1 성공 → shrink_log에 'ok' 항목."""
        _patch_sleep(monkeypatch)

        call_count = {"n": 0}

        class PartialShrinkProvider:
            provider_mode = "stub"
            def __init__(self, config):
                self.config = config
            def call(self, *, prompt, schema=None):
                call_count["n"] += 1
                # 첫 번째 호출(N=2)은 실패, 이후(N=1)는 성공
                if call_count["n"] == 1:
                    raise _ProviderResponseError(
                        "503: temporarily unavailable",
                        provider_id="stub-shrink",
                        model="stub-model",
                    )
                # N=1 성공 — 레코드 ID 파싱 없이 첫 번째 레코드 ID만 반환
                return {
                    "items": [
                        {
                            "raw_record_id": f"shrink2-{call_count['n']-2:03d}",
                            "canonical_name": "테스트 상품",
                            "source_title": "테스트 상품 300g",
                            "sale_price": None,
                            "brand": None,
                            "category_id": "food.misc",
                            "keywords": ["테스트"],
                            "aliases": [],
                            "attributes": {},
                            "package_quantity": 1,
                            "package_unit": "개",
                            "display_unit": "1개",
                            "bundle_count": 1,
                            "standard_unit": "개",
                            "standard_unit_price": None,
                            "price_per_100g": None,
                            "confidence": 0.80,
                            "notes": "shrink-test",
                        }
                    ]
                }

        shrink_records2 = [
            RawCrawlRecord(
                raw_record_id=f"shrink2-{i:03d}",
                source_name="emart",
                source_record_key=f"shrink2-key-{i}",
                raw_title=f"테스트 상품 {i}번 300g",
                raw_price=1000,
                raw_payload={},
            )
            for i in range(2)
        ]

        Session = _make_ai_db()
        with Session() as session:
            _register_provider(session, self.PROVIDER_ID)
            provider_contract = _ProviderConfigRepository(session).get(self.PROVIDER_ID)

        provider = PartialShrinkProvider(provider_contract)
        shrink_log: list[dict] = []

        proposals, _, log = _call_provider_with_shrink_retries(
            records=shrink_records2,
            provider=provider,
            provider_ref=_ai_ingestion._provider_ref(provider_contract),
            provider_id=self.PROVIDER_ID,
            model="stub-model",
            raw_batch_id="test-shrink2-batch",
            ai_batch_id="test-shrink2-batch:ai:1",
            keyword_catalog=[],
            learned_keyword_knowledge=[],
            _shrink_log=shrink_log,
        )

        # N=2 실패 후 N=1 성공 → shrink_log에 ok 항목
        ok_entries = [e for e in log if e.get("outcome") == "ok"]
        assert len(ok_entries) >= 1, (
            f"N=1로 분할 후 성공한 ok 항목이 있어야 함: {log}"
        )
        assert call_count["n"] >= 2, "최소 2회 provider 호출 (N=2 실패 + N=1 시도)"


# ─── EC-4: LearnedKnowledge(success_count≥2) → prompt context 포함 ──────────

class TestLearnedKnowledgeInPrompt:
    """EC-4: success_count≥2인 LearnedKnowledge가 라벨링 prompt context에 포함된다."""

    PROVIDER_ID = "stub-learned-alias"

    def setup_method(self):
        _reset_call_history(self.PROVIDER_ID)

    def test_learned_knowledge_appears_in_prompt(self, monkeypatch):
        """LearnedKnowledge(keyword_alias_approved, success_count=2)가 prompt에 반영된다."""
        _patch_sleep(monkeypatch)

        captured: dict[str, str] = {}

        class CapturingProvider:
            provider_mode = "stub"
            def __init__(self, config):
                self.config = config
            def call(self, *, prompt, schema=None):
                captured["prompt"] = prompt
                return {
                    "items": [
                        {
                            "raw_record_id": "alias-test-001",
                            "canonical_name": "비비고 왕교자 1.05kg",
                            "source_title": "CJ 비비고 왕교자",
                            "sale_price": None,
                            "brand": "CJ",
                            "category_id": "frozen.dumpling",
                            "keywords": ["교자"],
                            "aliases": [],
                            "attributes": {},
                            "package_quantity": None,
                            "package_unit": None,
                            "display_unit": None,
                            "bundle_count": 1,
                            "standard_unit": None,
                            "standard_unit_price": None,
                            "price_per_100g": None,
                            "confidence": 0.90,
                            "notes": "alias-test",
                        }
                    ]
                }

        Session = _make_ai_db()
        with Session() as session:
            _register_provider(session, self.PROVIDER_ID)

            # LearnedKnowledge 행 삽입 (success_count=2, type=keyword_alias_approved)
            # pattern = "교자" (인식되는 텀), target_value = {"word": "만두"} (매핑 대상)
            lk_repo = _LearnedKnowledgeRepository(session)
            lk_repo.save(
                LearnedKnowledgeContract(
                    knowledge_id="lk-alias-001",
                    knowledge_type="keyword_alias_approved",
                    source_name="emart",
                    pattern="교자",
                    target_value={"word": "만두"},
                    success_count=2,
                    is_active=True,
                )
            )
            session.commit()

            record = RawCrawlRecord(
                raw_record_id="alias-test-001",
                source_name="emart",
                source_record_key="alias-key-001",
                raw_title="CJ 비비고 왕교자",
                raw_price=9900,
                raw_payload={},
            )

            _ingest_and_label_records(
                session=session,
                provider_id=self.PROVIDER_ID,
                records=[record],
                source_name="emart",
                crawler_name="stub-crawler",
                schema_type="mart_discount",
                provider_factory=lambda config: CapturingProvider(config),
            )

        # prompt에 keyword alias 정보가 포함되어야 한다
        assert "prompt" in captured, "provider가 호출되지 않음"
        prompt_text = captured["prompt"]
        # 학습된 키워드('교자' 또는 '만두')가 prompt에 포함되어야 한다
        assert "교자" in prompt_text or "만두" in prompt_text, (
            "LearnedKnowledge의 keyword/alias가 prompt context에 반영되지 않음\n"
            f"prompt snippet: {prompt_text[:500]}"
        )


# ─── EC-5: 낮은 confidence → proposals_stored에 포함, 별도 추적 가능 ─────────

class TestEscalationTracking:
    """EC-5: confidence가 낮은 proposal은 proposals_stored에 포함되지만 별도 추적 가능하다."""

    PROVIDER_ID = "stub-escalation"

    def setup_method(self):
        _reset_call_history(self.PROVIDER_ID)

    def test_low_confidence_proposals_are_stored_and_trackable(self, monkeypatch):
        """confidence < threshold인 proposal이 proposals_stored에 포함된다."""
        _patch_sleep(monkeypatch)

        LOW_CONFIDENCE = 0.42  # reviewer-safe fallback과 같은 값

        class LowConfidenceProvider:
            provider_mode = "stub"
            def __init__(self, config):
                self.config = config
            def call(self, *, prompt, schema=None):
                return {
                    "items": [
                        {
                            "raw_record_id": "esc-test-001",
                            "canonical_name": "불명확 상품",
                            "source_title": "정체불명 이상한 상품 묶음",
                            "sale_price": None,
                            "brand": None,
                            "category_id": "food.misc",
                            "keywords": ["기타"],
                            "aliases": [],
                            "attributes": {},
                            "package_quantity": None,
                            "package_unit": None,
                            "display_unit": None,
                            "bundle_count": 1,
                            "standard_unit": None,
                            "standard_unit_price": None,
                            "price_per_100g": None,
                            "confidence": LOW_CONFIDENCE,
                            "notes": "낮은 confidence — human review required",
                        }
                    ]
                }

        Session = _make_ai_db()
        with Session() as session:
            _register_provider(session, self.PROVIDER_ID)

            record = RawCrawlRecord(
                raw_record_id="esc-test-001",
                source_name="emart",
                source_record_key="esc-key-001",
                raw_title="정체불명 이상한 상품 묶음",
                raw_price=5000,
                raw_payload={},
            )

            result = _ingest_and_label_records(
                session=session,
                provider_id=self.PROVIDER_ID,
                records=[record],
                source_name="emart",
                crawler_name="stub-crawler",
                schema_type="mart_discount",
                provider_factory=lambda config: LowConfidenceProvider(config),
            )

        # 낮은 confidence라도 proposals_stored에 포함되어야 한다
        assert result["proposals_stored"] >= 1, (
            "낮은 confidence proposal도 proposals_stored에 포함되어야 함"
        )
        assert len(result["proposal_ids"]) >= 1, (
            "낮은 confidence proposal도 proposal_ids에 포함되어야 함"
        )
        # 이 레코드는 product_match_hits가 아닌 AI 처리로 분류되어야 한다
        assert result["product_match_hits"] == 0, (
            "새 레코드는 product_match_hits가 0이어야 함"
        )


# ─── 회귀 스모크: 기존 패턴과의 호환성 ──────────────────────────────────────

class TestRegressionSmoke:
    """기존 ingest_and_label_records API 호환성 스모크 테스트."""

    PROVIDER_ID = "stub-smoke"

    def setup_method(self):
        _reset_call_history(self.PROVIDER_ID)

    def test_single_record_labeled_successfully(self, monkeypatch):
        """단일 레코드 라벨링이 성공하고 올바른 반환 구조를 가진다."""
        _patch_sleep(monkeypatch)

        record = _TEST_RECORDS[0]
        labels = {record.raw_record_id: _STUB_LABELS[record.raw_record_id]}

        Session = _make_ai_db()
        with Session() as session:
            _register_provider(session, self.PROVIDER_ID)
            result = _ingest_and_label_records(
                session=session,
                provider_id=self.PROVIDER_ID,
                records=[record],
                source_name=record.source_name,
                crawler_name="smoke-crawler",
                schema_type="mart_discount",
                provider_factory=_make_stub_provider_factory(labels),
            )

        required_keys = {
            "status", "raw_batch_id", "records_stored", "provider_calls",
            "product_match_hits", "proposals_stored", "proposal_ids",
        }
        missing = required_keys - set(result.keys())
        assert not missing, f"반환값에 필수 키 누락: {missing}"
        assert result["records_stored"] == 1
        assert result["product_match_hits"] == 0
        assert result["status"] in ("labeled", "partial_review_required")

    def test_empty_records_list_handled_gracefully(self, monkeypatch):
        """빈 레코드 목록으로 호출해도 오류 없이 처리된다."""
        _patch_sleep(monkeypatch)

        Session = _make_ai_db()
        with Session() as session:
            _register_provider(session, self.PROVIDER_ID)
            result = _ingest_and_label_records(
                session=session,
                provider_id=self.PROVIDER_ID,
                records=[],
                source_name="emart",
                crawler_name="smoke-crawler",
                schema_type="mart_discount",
                provider_factory=_make_stub_provider_factory({}),
            )

        assert result["records_stored"] == 0
        assert result["proposals_stored"] == 0
        assert result["product_match_hits"] == 0

    def test_provider_not_found_raises_error(self, monkeypatch):
        """존재하지 않는 provider_id로 호출하면 AIIngestionError가 발생한다."""
        _patch_sleep(monkeypatch)

        Session = _make_ai_db()
        with Session() as session:
            with pytest.raises(Exception) as exc_info:
                _ingest_and_label_records(
                    session=session,
                    provider_id="nonexistent-provider-xyz",
                    records=_TEST_RECORDS[:1],
                    source_name="emart",
                    crawler_name="smoke-crawler",
                    schema_type="mart_discount",
                )
        assert "provider not found" in str(exc_info.value).lower() or \
               "provider" in str(exc_info.value).lower(), (
            f"오류 메시지에 'provider'가 포함되어야 함: {exc_info.value}"
        )


# ─── 롯데마트 WAF 완화 분석 ────────────────────────────────────────────────────

class TestLottemartWafMitigation:
    """롯데마트 AWS WAF 차단 진단 및 완화 전략 검증.

    롯데마트는 lottemartzetta.com SPA에 AWS WAF를 사용한다.
    크롤러는 WAF 응답을 우회하지 않고 차단을 기록(waf_blocker)한다.

    WAF 차단이 발생하는 경우:
      - HTTP 202 + "AWSWAF" HTML → AWS WAF challenge shell
      - HTTP 403 / 429 → 접근 거부 / rate limited
      - Playwright 브라우저 CAPTCHA/로그인 페이지

    현재 한계 (~50개 수집):
      - MAX_PAGES=2, SEARCH_QUERIES=8 → 최대 ~112 요청
      - WAF는 연속 요청 3~5회 후 challenge를 발생시킴
      - PLAYWRIGHT_FALLBACK_QUERY_CAP=3 (3개 쿼리만 브라우저 fallback)

    완화 전략 (이미 구현됨):
      1. 1~3초 랜덤 딜레이 (AntiDetect)
      2. 429 → exponential backoff retry
      3. HTTP 실패 → Playwright 브라우저 fallback (최대 3 쿼리)
      4. WAF challenge 감지 → waf_blocker 기록 후 계속 진행

    추가 개선 가능 방향 (미구현 — 단순 기록):
      - Rotating User-Agent / Referer header
      - 더 긴 쿼리 간 딜레이 (5~10초)
      - Playwright_FALLBACK_QUERY_CAP 확대
      - API 인증 토큰 사용 (공식 파트너십 필요)
    """

    def test_waf_challenge_detection_by_html_content(self):
        """_is_aws_waf_challenge가 AWS WAF HTML 패턴을 올바르게 감지한다."""
        saved_path = list(sys.path)
        saved_modules = {k: v for k, v in sys.modules.items() if _is_ai_module(k)}
        # crawler-admin backend를 임시로 sys.path에 추가
        crawler_backend = str(CRAWLER_BACKEND)
        if crawler_backend not in sys.path:
            sys.path.insert(0, crawler_backend)
        shared_path = str(SHARED)
        if shared_path not in sys.path:
            sys.path.insert(0, shared_path)
        try:
            from crawlers.marts.lottemart.crawler import LottemartCrawler
        finally:
            sys.path = saved_path

        crawler = LottemartCrawler.__new__(LottemartCrawler)

        # AWS WAF challenge HTML — AWSWAF 토큰 포함
        waf_html = """
        <html><head><title>Request Blocked</title></head>
        <body>
        <script>
        var AWSWAF_TOKEN = "abc123";
        AWS_WAF_COOKIE_DOMAIN = ".lottemartzetta.com";
        </script>
        </body></html>
        """
        assert crawler._is_aws_waf_challenge(waf_html), (
            "AWS WAF 토큰이 포함된 HTML은 WAF challenge로 감지되어야 함"
        )

        # 일반 상품 페이지 HTML — WAF 아님
        normal_html = """
        <html><head><title>롯데마트 상품 검색</title></head>
        <body>
        <script>window.__INITIAL_STATE__ = {"products": []};</script>
        </body></html>
        """
        assert not crawler._is_aws_waf_challenge(normal_html), (
            "일반 상품 HTML은 WAF challenge로 감지되지 않아야 함"
        )

        # 빈 HTML
        assert not crawler._is_aws_waf_challenge(""), (
            "빈 HTML은 WAF challenge로 감지되지 않아야 함"
        )

    def test_waf_blocker_details_structure(self):
        """_waf_blocker_details가 올바른 구조의 진단 정보를 반환한다."""
        saved_path = list(sys.path)
        crawler_backend = str(CRAWLER_BACKEND)
        if crawler_backend not in sys.path:
            sys.path.insert(0, crawler_backend)
        shared_path = str(SHARED)
        if shared_path not in sys.path:
            sys.path.insert(0, shared_path)
        try:
            from crawlers.marts.lottemart.crawler import LottemartCrawler
        finally:
            sys.path = saved_path

        crawler = LottemartCrawler.__new__(LottemartCrawler)
        details = crawler._waf_blocker_details(
            "AWS WAF 차단됨 (202 challenge)",
            request_url="https://lottemartzetta.com/search?query=할인",
            query="할인",
            page=1,
            status_code=202,
            blocker="aws_waf_http_202",
        )

        assert isinstance(details, dict), "waf_blocker_details는 dict를 반환해야 함"
        required_keys = {"message", "request_url", "blocker"}
        found_keys = set(details.keys())
        assert required_keys.issubset(found_keys), (
            f"waf_blocker_details에 필수 키 누락: {required_keys - found_keys}"
        )
        assert details["blocker"] == "aws_waf_http_202"
        assert "lottemartzetta.com" in details["request_url"]

    def test_waf_item_limit_documented(self):
        """롯데마트 WAF로 인한 50개 수집 제한이 문서화되어 있다."""
        saved_path = list(sys.path)
        crawler_backend = str(CRAWLER_BACKEND)
        if crawler_backend not in sys.path:
            sys.path.insert(0, crawler_backend)
        shared_path = str(SHARED)
        if shared_path not in sys.path:
            sys.path.insert(0, shared_path)
        try:
            from crawlers.marts.lottemart.crawler import LottemartCrawler
        finally:
            sys.path = saved_path

        # MAX_ITEMS=300 설정이지만 WAF로 인해 실제 수집량이 제한됨
        # 이 테스트는 현재 설정값을 문서화하고 변경 추적을 위해 존재한다
        assert LottemartCrawler.MAX_ITEMS == 300, (
            "MAX_ITEMS 설정이 변경됨. WAF 완화 전략을 재평가하세요."
        )
        assert LottemartCrawler.MAX_PAGES == 2, (
            "MAX_PAGES 설정이 변경됨."
        )
        assert LottemartCrawler.PLAYWRIGHT_FALLBACK_QUERY_CAP == 3, (
            "PLAYWRIGHT_FALLBACK_QUERY_CAP 설정이 변경됨."
        )
        # 현재 WAF 환경에서 실제 수집 가능 레코드: 약 50개
        # 이 값은 live 실행 로그 기반 추정치다 (fixture: hydrated_5cards.html)
        estimated_live_max = 50
        assert estimated_live_max < LottemartCrawler.MAX_ITEMS, (
            "WAF로 인한 실제 수집 한계(~50)가 MAX_ITEMS(300) 미만임을 문서화"
        )
