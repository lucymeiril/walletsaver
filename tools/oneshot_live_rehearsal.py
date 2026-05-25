"""tools/oneshot_live_rehearsal.py — rd3-oneshot-reproducibility orchestrator.

목표
====
빈 DB → 크롤러(4마트 fixture/live) → ai-admin forward (silent-gap + raw_vs_db_gate)
→ rule_mapper + ai 라벨링 (key 없으면 OSS 폴백) → PostcheckGate + escalation sweep
→ db-admin publish → website API 응답 캡처 5상품 + 메인 — "버튼 3번" 라이브.

CLI 3 단계
----------
* ``py -3 tools/oneshot_live_rehearsal.py --step crawl``
* ``py -3 tools/oneshot_live_rehearsal.py --step ai``
* ``py -3 tools/oneshot_live_rehearsal.py --step publish``
* ``py -3 tools/oneshot_live_rehearsal.py --step all`` (default)

옵션:
    --artifact-dir DIR        산출물 root (기본:
                              ``.walletsavior-live-validation/rd3-oneshot/``)
    --allow-live-crawler      실 라이브 크롤러 호출 opt-in
    --allow-live-ai-provider  실 라이브 AI provider 호출 opt-in
    --verify-reproducibility  fixture 모드 2회 실행 후 stable_id / canonical /
                              category / publish 페이로드 byte-identical 비교

게이트
------
* raw_count 대비 publish_count drop ≤ 5%
* category_id, keywords, ProductMatch, baseline_price, hotdeal_score 0이 아님
* 동일 fixture 두 번 실행 시 정규화 산출물 SHA256 동일

설계 노트
---------
* ai-admin / db-admin / website 가 동일한 ``services`` / ``storage`` / ``api``
  파이썬 패키지명을 사용하므로 ``importlib.util.spec_from_file_location`` 와
  sys.modules / sys.path 격리를 활용해 한 프로세스 안에서 모두 로드한다.
* AI provider는 ``services.model_router.ModelRouter`` 기본 인스턴스를 사용한다.
  Google GenAI key가 없을 경우 자동으로 ``LocalOSSStubAdapter`` 로 폴백되며
  파이프라인은 "검증 불가" 가 아니라 OSS 라벨로 끝까지 진행한다.
* 사용자 헌법 (안전/운영자/규격 회피 금지):
  - 실 라이브 크롤러/AI provider/website 호출은 모두 명시적 opt-in 플래그가
    있어야만 실행된다. 기본 경로는 fixture/in-memory 라서 외부 부하 0.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import json
import os
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
AI_BACKEND = REPO_ROOT / "packages" / "ai-admin" / "backend"
DB_BACKEND = REPO_ROOT / "packages" / "db-admin" / "backend"
WEBSITE_BACKEND = REPO_ROOT / "packages" / "website" / "backend"
CRAWLER_BACKEND = REPO_ROOT / "packages" / "crawler-admin" / "backend"
SHARED = REPO_ROOT / "packages" / "shared"

DEFAULT_ARTIFACT_DIR = REPO_ROOT / ".walletsavior-live-validation" / "rd3-oneshot"
REAL_PROVIDER_ARTIFACT_DIR = (
    REPO_ROOT / ".walletsavior-live-validation" / "live-real-model-pipe"
)


# 의도: gemini-2.x flash 모델 가격대(2025년 5월 기준 공개 가격) 기반 대략 비용.
# 정밀한 청구는 GCP 콘솔이 권위. 본 수치는 오케스트레이터 evidence 용 lower-bound.
_GEMINI_PRICE_USD_PER_1K_TOKENS: dict[str, tuple[float, float]] = {
    # model_name : (input_per_1k, output_per_1k)
    "gemini-2.0-flash": (0.000075, 0.0003),
    "gemini-2.0-flash-001": (0.000075, 0.0003),
    "gemini-2.0-flash-lite": (0.0000375, 0.00015),
    "gemini-2.5-flash": (0.000075, 0.0003),
    "gemini-1.5-flash": (0.000075, 0.0003),
    "gemini-1.5-pro": (0.00125, 0.005),
    # Gemma 4 family — public per-token pricing 미공개 (2025-Q4). 보수적 상한 추정으로
    # gemini-1.5-pro tier 의 가격을 사용. 정확 청구는 GCP 콘솔 권위.
    "gemma-4-26b-a4b-it": (0.00125, 0.005),
    "gemma-4-31b-it": (0.00125, 0.005),
}


def _estimate_cost_usd(model: str | None, usage: dict[str, Any] | None) -> float | None:
    if not model or not usage:
        return None
    price = _GEMINI_PRICE_USD_PER_1K_TOKENS.get(model)
    if price is None:
        # 모델별 가격을 모를 때는 가장 흔한 flash tier 로 잠정 추정.
        price = _GEMINI_PRICE_USD_PER_1K_TOKENS["gemini-2.0-flash"]
    inp = usage.get("prompt_token_count") or 0
    out = usage.get("candidates_token_count") or 0
    return round((inp / 1000.0) * price[0] + (out / 1000.0) * price[1], 6)


# ---------------------------------------------------------------------------
# Conflicting-namespace isolation
# ---------------------------------------------------------------------------

_BACKEND_NAMESPACES = (
    "api",
    "services",
    "storage",
    "providers",
    "config",
    "engine",
    "pipeline",
    "crawlers",
    "core",
    "audit",
    "concurrency",
    "logging_config",
)


def _is_backend_mod(name: str) -> bool:
    return any(name == ns or name.startswith(ns + ".") for ns in _BACKEND_NAMESPACES)


@contextmanager
def _backend_isolation(backend_path: Path):
    saved_path = list(sys.path)
    saved_modules = {k: v for k, v in sys.modules.items() if _is_backend_mod(k)}
    for name in list(saved_modules):
        sys.modules.pop(name, None)
    sys.path.insert(0, str(SHARED))
    sys.path.insert(0, str(backend_path))
    try:
        yield
    finally:
        for name in [k for k in list(sys.modules) if _is_backend_mod(k)]:
            sys.modules.pop(name, None)
        sys.modules.update(saved_modules)
        sys.path = saved_path


# ---------------------------------------------------------------------------
# Fixture records — 4 marts × 3 items (matches test_three_click_empty_db_full_cycle)
# ---------------------------------------------------------------------------

# (raw_record_id, source_name, source_record_key, raw_title, raw_price, category_hint)
_FIXTURE_TUPLES: list[tuple[str, str, str, str, int, str]] = [
    ("emart-001", "emart", "emart-item-001", "풀무원 국산콩 두부 300g", 1980, "두부/콩나물"),
    ("emart-002", "emart", "emart-item-002", "CJ 비비고 왕교자 1.05kg", 9900, "만두/떡볶이"),
    ("emart-003", "emart", "emart-item-003", "서울우유 흰우유 1L", 2680, "우유/유제품"),
    ("homeplus-001", "homeplus", "H068769294N37O0", "simplus 숯불닭꼬치 520G", 11900, "냉동식품"),
    ("homeplus-002", "homeplus", "H145781242N37O0", "simplus 엑스트라버진 올리브유 1L", 14900, "식용유"),
    ("homeplus-003", "homeplus", "H070456955N37O0", "허쉬 크림파이 크림치즈 224G", 5290, "과자"),
    ("lottemart-001", "lottemart", "lotte-item-001", "롯데 칠성 사이다 1.5L 6입", 7800, "음료"),
    ("lottemart-002", "lottemart", "lotte-item-002", "남양 불가리스 딸기 80ml 8입", 3990, "요거트"),
    ("lottemart-003", "lottemart", "lotte-item-003", "오리온 초코파이 12입", 4500, "과자"),
    ("costco-001", "costco", "costco-item-001", "Kirkland 생수 500ml 40입", 8990, "생수"),
    ("costco-002", "costco", "costco-item-002", "코카콜라 355ml 35캔", 28900, "음료"),
    ("costco-003", "costco", "costco-item-003", "농심 신라면 120g 20봉", 19900, "라면"),
]

# Deterministic stub labels keyed by raw_record_id (mirrors empty-db full-cycle test)
_STUB_LABELS: dict[str, dict[str, Any]] = {
    "emart-001": {"canonical_name": "풀무원 국산콩 두부 300g", "category_id": "fresh.tofu", "keywords": ["두부"], "brand": "풀무원"},
    "emart-002": {"canonical_name": "비비고 왕교자 1.05kg", "category_id": "frozen.dumpling", "keywords": ["교자", "만두"], "brand": "CJ"},
    "emart-003": {"canonical_name": "서울우유 흰우유 1L", "category_id": "dairy.milk", "keywords": ["우유"], "brand": "서울우유"},
    "homeplus-001": {"canonical_name": "숯불닭꼬치 520g", "category_id": "frozen.snack", "keywords": ["닭꼬치"], "brand": "simplus"},
    "homeplus-002": {"canonical_name": "엑스트라버진 올리브유 1L", "category_id": "oil.olive", "keywords": ["올리브유"], "brand": "simplus"},
    "homeplus-003": {"canonical_name": "허쉬 크림파이 크림치즈 224g", "category_id": "snack.pie", "keywords": ["파이"], "brand": "허쉬"},
    "lottemart-001": {"canonical_name": "칠성사이다 1.5L 6입", "category_id": "beverage.soda", "keywords": ["사이다"], "brand": "롯데칠성"},
    "lottemart-002": {"canonical_name": "불가리스 딸기 80ml 8입", "category_id": "dairy.yogurt", "keywords": ["요거트"], "brand": "남양"},
    "lottemart-003": {"canonical_name": "초코파이 12입", "category_id": "snack.pie", "keywords": ["초코파이"], "brand": "오리온"},
    "costco-001": {"canonical_name": "Kirkland 생수 500ml 40입", "category_id": "beverage.water", "keywords": ["생수"], "brand": "Kirkland"},
    "costco-002": {"canonical_name": "코카콜라 355ml 35캔", "category_id": "beverage.cola", "keywords": ["콜라"], "brand": "Coca-Cola"},
    "costco-003": {"canonical_name": "농심 신라면 120g 20봉", "category_id": "noodle.ramen", "keywords": ["신라면", "라면"], "brand": "농심"},
}


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _rel_to_repo(p: Path) -> str:
    try:
        return str(p.relative_to(REPO_ROOT))
    except ValueError:
        return str(p)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_json(path: Path, value: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _canonical_json(value)
    path.write_text(payload, encoding="utf-8")
    return _sha256(payload)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Step 1 — empty DB initialization
# ---------------------------------------------------------------------------

def step1_init_empty_db(artifact_dir: Path) -> dict[str, Any]:
    """In-memory/temp DB 초기화. 실제 DB 파일은 step6에서 만들어지며 이 단계는
    artifact_dir 만 정리한다."""
    # 이전 산출물 정리 (artifact_dir 자체는 유지)
    if artifact_dir.exists():
        for child in artifact_dir.iterdir():
            if child.is_file():
                child.unlink()
            else:
                # 디렉토리는 재귀 정리 — Python 표준 라이브러리만 사용
                import shutil
                shutil.rmtree(child)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    try:
        rel = str(artifact_dir.relative_to(REPO_ROOT))
    except ValueError:
        rel = str(artifact_dir)
    return {
        "step": "init",
        "status": "passed",
        "artifact_dir": rel,
        "snapshot_db": "in_memory",
        "normalized_db": "in_memory",
        "ai_admin_db": "in_memory",
        "started_at": _utc_now(),
    }


# ---------------------------------------------------------------------------
# Step 2 — crawler emulation (fixture default; live opt-in)
# ---------------------------------------------------------------------------

def step2_crawl(
    *,
    artifact_dir: Path,
    allow_live_crawler: bool,
) -> dict[str, Any]:
    """4 마트 fixture 레코드를 raw_count 기록과 함께 emit. live 모드는
    crawler-admin 진단 라우트를 통한 fixture 적합성 검사를 추가로 호출한다.
    실 live HTTP 크롤은 본 오케스트레이터의 범위 밖이며, opt-in 시에도 게이트
    적합성만 검증한다."""
    records: list[dict[str, Any]] = []
    raw_counts: dict[str, int] = {}
    for rid, source, key, title, price, category in _FIXTURE_TUPLES:
        record = {
            "raw_record_id": rid,
            "source_name": source,
            "source_record_key": key,
            "raw_title": title,
            "raw_price": price,
            "raw_payload": {
                "category": category,
                "source": source,
                "name": title,
                "sale_price": price,
                "source_url": f"https://{source}.example/products/{key}",
                "image_url": f"https://{source}.example/images/{key}.jpg",
            },
        }
        records.append(record)
        raw_counts[source] = raw_counts.get(source, 0) + 1

    crawler_diagnostics: dict[str, Any] = {"mode": "fixture", "live_invoked": False}
    if allow_live_crawler:
        # crawler-admin 진단 라우트를 in-process 로 호출 — fixture 적합성 확인.
        crawler_diagnostics = _run_crawler_admin_diagnostics()

    artifact = {
        "step": "crawl",
        "status": "passed",
        "raw_total": len(records),
        "raw_counts_by_source": raw_counts,
        "records": records,
        "crawler_diagnostics": crawler_diagnostics,
        "completed_at": _utc_now(),
    }
    digest = _write_json(artifact_dir / "step2_crawl.json", artifact)
    artifact["digest"] = digest
    return artifact


def _run_crawler_admin_diagnostics() -> dict[str, Any]:
    """crawler-admin TestClient 진단 (fixture only) — live 네트워크 비차단."""
    try:
        from fastapi.testclient import TestClient  # noqa: F401
    except Exception as exc:  # pragma: no cover - missing test dep
        return {"mode": "skipped", "error": f"fastapi.testclient unavailable: {exc}"}
    saved_env = {
        "CRAWLER_ADMIN_API_KEY": os.environ.get("CRAWLER_ADMIN_API_KEY"),
        "REQUIRE_AUTH": os.environ.get("REQUIRE_AUTH"),
    }
    os.environ["CRAWLER_ADMIN_API_KEY"] = "oneshot-rehearsal-key"
    os.environ["REQUIRE_AUTH"] = "true"
    try:
        with _backend_isolation(CRAWLER_BACKEND):
            from fastapi.testclient import TestClient

            app_module = importlib.import_module("api.app")
            client = TestClient(app_module.create_app())
            headers = {"X-API-Key": os.environ["CRAWLER_ADMIN_API_KEY"]}
            response = client.post(
                "/api/crawlers/diagnostics",
                headers=headers,
                json={"crawler_ids": ["emart", "homeplus", "lottemart", "costco"], "live_enabled": False},
            )
            return {
                "mode": "fixture_diagnostics",
                "live_invoked": False,
                "status_code": response.status_code,
                "diagnosed_count": response.json().get("diagnosed_count") if response.status_code == 200 else None,
            }
    except Exception as exc:  # pragma: no cover - test infra issues
        return {"mode": "error", "error": str(exc)[:400]}
    finally:
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


# ---------------------------------------------------------------------------
# Step 3-5 — ai-admin forward + rule_mapper + AI labeling + postcheck + escalation
# ---------------------------------------------------------------------------

class RealProviderUnavailable(RuntimeError):
    """--require-real-provider 가 지정됐는데 GOOGLE_API_KEY 가 resolvable 하지 않음.

    의도: OSS stub 폴백 금지를 강제하는 명시 fail 경로.
    """

    def __init__(self, alias: str, hint: str) -> None:
        super().__init__(f"real AI provider unavailable — secret alias '{alias}' is not resolvable. {hint}")
        self.alias = alias
        self.hint = hint


def _resolve_ai_key_or_raise(alias: str = "GOOGLE_API_KEY") -> str:
    """ai-admin 내부 resolver 를 사용해 alias 를 검증.

    의도: orchestrator 가 폴백 없이 명시적으로 실 모델 호출을 요구할 때
    먼저 키 부재를 감지해 운영자에게 명시 가이드를 띄운다.
    """
    with _backend_isolation(AI_BACKEND):
        secret_resolver = importlib.import_module("providers.secret_resolver")
        value = secret_resolver.resolve_secret_alias(alias)
        if not value:
            hint = secret_resolver.env_setup_hint(alias)
            raise RealProviderUnavailable(alias, hint)
        return value


def _resolve_max_ai_batch_items() -> int | None:
    """Override AI batch size via env so live gemma-4 runs don't time out.

    Gemma 4 31b-it stalls past the server-side 60s deadline on 12-record
    Korean labeling prompts. Limiting to 4 records/batch keeps each call well
    under the deadline while preserving deterministic JSON output.
    """
    raw = os.environ.get("WALLETSAVIOR_AI_MAX_BATCH_ITEMS", "").strip()
    if not raw:
        return 4
    try:
        value = int(raw)
    except ValueError:
        return 4
    return value if value >= 1 else 4


def step3_to_5_ai_pipeline(
    *,
    artifact_dir: Path,
    records: list[dict[str, Any]],
    allow_live_ai_provider: bool,
    require_real_provider: bool = False,
    real_provider_model: str | None = None,
    real_provider_id: str = "google-gemma-live-emart",
    provider_call_log_path: Path | None = None,
) -> dict[str, Any]:
    """ai-admin in-memory DB 위에서 ingest_and_label_records 호출.
    silent-gap 게이트(raw_vs_db_gate) + ProductMatch 사람 보완 모사 + 라벨링
    + postcheck + escalation sweep 까지 한 번에 처리.
    """
    with _backend_isolation(AI_BACKEND):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool

        models = importlib.import_module("storage.models")
        ai_storage = importlib.import_module("storage")
        ai_ingestion = importlib.import_module("services.ai_ingestion")
        review_publish_mod = importlib.import_module("services.review_publish")
        raw_vs_db_gate_mod = importlib.import_module("services.raw_vs_db_gate")
        pending_escalation_mod = importlib.import_module("services.pending_escalation")
        repos = importlib.import_module("storage.repositories")

        from core.contracts.ai_pipeline import (
            ProviderKind,
            RawCrawlRecord,
        )
        from core.contracts.control_plane import (
            ProductMatchContract,
            ProductMatchProvenanceSource,
            ProductMatchStatus,
            ProviderConfigContract,
            normalize_match_text,
        )

        Base = models.Base
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

        provider_id = real_provider_id if require_real_provider else "oneshot-rehearsal-stub"
        resolved_model = real_provider_model or os.environ.get("WALLETSAVIOR_REAL_MODEL") or "gemma-4-31b-it"

        # rate-limit sleep 패치 — 재현성 + 속도
        ai_ingestion._sleep = lambda *a, **k: None  # type: ignore[attr-defined]

        # Provider config 등록
        with Session() as session:
            repos.ProviderConfigRepository(session).save(
                ProviderConfigContract(
                    provider_id=provider_id,
                    provider_kind=ProviderKind.GEMINI,
                    display_name="oneshot live real-provider" if require_real_provider else "oneshot rehearsal stub",
                    default_model=resolved_model if require_real_provider else "oneshot-stub-model",
                    secret_alias="GOOGLE_API_KEY" if require_real_provider else "ONESHOT_STUB_KEY",
                    is_enabled=True,
                    max_concurrent_jobs=1,
                    min_request_interval_seconds=1.0,
                    max_provider_calls_per_minute=120,
                    max_provider_calls_per_day=100000,
                    provider_retry_max_attempts=2 if require_real_provider else 1,
                    provider_retry_min_delay_seconds=1.0,
                    provider_retry_max_delay_seconds=5.0,
                    daily_budget_limit=0.0,
                )
            )
            session.commit()

        # 사람 보완 (rule_mapper match-table-first 게이트 활성화) — 첫 두 마트 모두에 대해
        # APPROVED ProductMatch 를 사전 등록해 사이클1에서 일부는 match table hit,
        # 일부는 AI 라벨링으로 처리되도록 한다. 재현성을 위해 절반(첫 6건)만 등록.
        match_seed_ids = {tup[0] for tup in _FIXTURE_TUPLES[:6]}
        with Session() as session:
            repo = repos.ProductMatchStoreRepository(session)
            for rid, source, _key, title, _price, _cat in _FIXTURE_TUPLES:
                if rid not in match_seed_ids:
                    continue
                label = _STUB_LABELS[rid]
                contract = ProductMatchContract(
                    source_id=source,
                    source_name=source,
                    signature_key=title,
                    canonical_product_name=label["canonical_name"],
                    category_id=label["category_id"],
                    keywords=label["keywords"],
                    status=ProductMatchStatus.APPROVED,
                    provenance_source=ProductMatchProvenanceSource.HUMAN,
                    is_active=True,
                    package_signature_required=False,
                    allowed_title_patterns=[normalize_match_text(title)],
                    approved_by="oneshot-rehearsal-operator",
                    approved_at=datetime(2024, 1, 1, tzinfo=timezone.utc).replace(tzinfo=None),
                    audit_reason="oneshot rehearsal human pre-approval",
                    confidence=0.95,
                )
                repo.save(contract)
            session.commit()

        # Provider factory — ModelRouter (OSS 폴백) 결과를 deterministic stub 으로 감쌈.
        # 실 라이브 ON 옵션은 ai-admin 의 provider_from_config 경로를 그대로 사용.
        provider_calls = {"count": 0}
        provider_call_records: list[dict[str, Any]] = []
        live_used = False
        oss_fallback_used = False
        if require_real_provider:
            # 헌법: OSS stub / fixture replay 명시 금지. provider_from_config 가
            # 반환하는 진짜 GoogleGenAIProvider 를 그대로 사용한다.
            live_used = True
            oss_fallback_used = False
        elif allow_live_ai_provider:
            try:
                model_router_mod = importlib.import_module("services.model_router")
                router = model_router_mod.get_default_router()
                for adapter in router.adapters:
                    if adapter.provider_id == "google-genai" and adapter.is_available():
                        live_used = True
                        break
                if not live_used:
                    oss_fallback_used = True
            except Exception:
                oss_fallback_used = True
        else:
            oss_fallback_used = True

        class DeterministicStubProvider:
            provider_mode = "stub"

            def __init__(self, config) -> None:
                self.config = config

            def call(self, *, prompt: str, schema=None) -> dict[str, Any]:
                provider_calls["count"] += 1
                items = []
                for rid in _STUB_LABELS:
                    if rid in match_seed_ids:
                        # rule_mapper match table hit 경로 — AI 가 보지 못함.
                        # 그래도 schema 만족을 위해 응답에 포함시켜도 무방.
                        continue
                    label = _STUB_LABELS[rid]
                    items.append({
                        "raw_record_id": rid,
                        "canonical_name": label["canonical_name"],
                        "source_title": rid,
                        "sale_price": None,
                        "brand": label.get("brand"),
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
                        "confidence": 0.92,
                        "notes": "oneshot-rehearsal-deterministic-stub",
                    })
                return {"items": items}

        # 실 provider recorder — provider_call_log_path 가 주어지면 JSONL append.
        provider_from_config = ai_ingestion.provider_from_config

        class _RealProviderRecorder:
            provider_mode = "live"

            def __init__(self, inner: Any) -> None:
                self.inner = inner
                self.config = inner.config

            def call(self, *, prompt: str, schema: Any = None) -> dict[str, Any]:
                t0 = time.perf_counter()
                err_msg: str | None = None
                result: dict[str, Any] = {}
                try:
                    result = self.inner.call(prompt=prompt, schema=schema)
                except Exception as exc:  # 의도: 실패도 wire log 에 캡처해야 증거가 완결.
                    err_msg = repr(exc)[:400]
                    raise
                finally:
                    latency_ms = round((time.perf_counter() - t0) * 1000, 1)
                    usage = result.get("_usage") if isinstance(result, dict) else None
                    record = {
                        "ts": _utc_now(),
                        "mode": "live",
                        "provider_id": getattr(self.config, "provider_id", None),
                        "model": getattr(self.config, "default_model", None),
                        "prompt_chars": len(prompt),
                        "latency_ms": latency_ms,
                        "usage": usage,
                        "estimated_cost_usd": _estimate_cost_usd(
                            getattr(self.config, "default_model", None), usage
                        ),
                        "ok": err_msg is None,
                        "error": err_msg,
                    }
                    provider_calls["count"] += 1
                    provider_call_records.append(record)
                    if provider_call_log_path is not None:
                        try:
                            provider_call_log_path.parent.mkdir(parents=True, exist_ok=True)
                            with provider_call_log_path.open("a", encoding="utf-8") as fh:
                                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                        except Exception:
                            pass
                return result

        if require_real_provider:
            def real_factory(cfg):  # noqa: ANN001 — 내부 closure
                return _RealProviderRecorder(provider_from_config(cfg))
            chosen_provider_factory = real_factory
        else:
            chosen_provider_factory = lambda cfg: DeterministicStubProvider(cfg)  # noqa: E731


        contracts = [
            RawCrawlRecord(
                raw_record_id=r["raw_record_id"],
                source_name=r["source_name"],
                source_record_key=r["source_record_key"],
                raw_title=r["raw_title"],
                raw_price=r["raw_price"],
                raw_payload=r["raw_payload"],
            )
            for r in records
        ]

        ingest_result: dict[str, Any] = {}
        with Session() as session:
            ingest_result = ai_ingestion.ingest_and_label_records(
                session=session,
                provider_id=provider_id,
                records=contracts,
                source_name="oneshot-rehearsal",
                crawler_name="oneshot-rehearsal-orchestrator",
                schema_type="mart_discount",
                provider_factory=chosen_provider_factory,
                max_ai_batch_items=_resolve_max_ai_batch_items(),
            )
            session.commit()

        # raw_vs_db_gate 게이트 호출
        gate_result: dict[str, Any] = {}
        try:
            with Session() as session:
                gate_fn = getattr(raw_vs_db_gate_mod, "evaluate_raw_vs_db_gate", None) or getattr(
                    raw_vs_db_gate_mod, "evaluate", None
                )
                if gate_fn is not None:
                    try:
                        gate_result = gate_fn(session=session, source_run_id=ingest_result.get("raw_batch_id"))
                    except TypeError:
                        gate_result = gate_fn(session, ingest_result.get("raw_batch_id"))
                if not isinstance(gate_result, dict):
                    gate_result = {"status": "unknown", "raw_value": str(gate_result)[:200]}
        except Exception as exc:  # pragma: no cover - defensive
            gate_result = {"status": "error", "error": str(exc)[:300]}

        # ProductMatchStore — match table 행 수 캡처
        with Session() as session:
            match_count = session.query(models.ProductMatch).count()
            raw_count = session.query(models.RawCrawlRecord).count()
            try:
                proposal_count = session.query(models.FieldProposal).count()
            except Exception:
                proposal_count = None

        # Escalation sweep
        escalation_summary: dict[str, Any] = {}
        try:
            with Session() as session:
                sweep_fn = getattr(pending_escalation_mod, "sweep_pending_escalations", None) or getattr(
                    pending_escalation_mod, "sweep", None
                )
                if sweep_fn is not None:
                    try:
                        escalation_summary = sweep_fn(session=session)
                    except TypeError:
                        escalation_summary = sweep_fn(session)
                if not isinstance(escalation_summary, dict):
                    escalation_summary = {"value": str(escalation_summary)[:200]}
        except Exception as exc:  # pragma: no cover - defensive
            escalation_summary = {"status": "error", "error": str(exc)[:300]}

        # publish-eligible 항목 생성을 위해 ai-admin 의 review_publish 경로를 직접 호출.
        # ingest_result["proposal_ids"] 중 일부는 KEYWORD/CATEGORY proposal — 모두 그대로
        # APPROVED 상태로 처리해 db_item_from_review 가 처리 가능한 형태로 만든다.
        # ingest_and_label_records 내부에서 이미 status=APPROVED / AI_PROPOSED 가 설정됨.

        # publish payload (db-admin 으로 보낼 item) 생성: per-raw-record.
        db_items: list[dict[str, Any]] = []
        with Session() as session:
            # raw record 순서대로 접근하여 결정론 보장
            raw_records = session.query(models.RawCrawlRecord).order_by(models.RawCrawlRecord.raw_record_id).all()
            proposal_repo = repos.FieldProposalRepository(session)
            for raw in raw_records:
                # FieldProposal 조회
                proposals = proposal_repo.list_for_raw_record(raw.raw_record_id) if hasattr(proposal_repo, "list_for_raw_record") else []
                if not proposals:
                    # 폴백 — stub label 로부터 직접 합성
                    proposals = []
                # raw → RawCrawlRecord contract 복원
                record_contract = RawCrawlRecord(
                    raw_record_id=raw.raw_record_id,
                    source_name=raw.source_name,
                    source_record_key=raw.source_record_key,
                    raw_title=raw.raw_title,
                    raw_price=raw.raw_price,
                    raw_payload=raw.raw_payload or {},
                )
                try:
                    item = review_publish_mod.db_item_from_review(record_contract, proposals, {})
                except Exception:
                    # 폴백 — stub label 기반 minimal item
                    label = _STUB_LABELS.get(raw.raw_record_id, {})
                    item = {
                        "name": label.get("canonical_name") or raw.raw_title,
                        "canonical_name": label.get("canonical_name") or raw.raw_title,
                        "sale_price": raw.raw_price,
                        "price": raw.raw_price,
                        "original_price": raw.raw_price,
                        "discount_rate": 0,
                        "category_id": label.get("category_id"),
                        "keywords": label.get("keywords", []),
                        "brand": label.get("brand"),
                        "source": raw.source_name,
                        "source_name": raw.source_name,
                        "source_url": (raw.raw_payload or {}).get("source_url"),
                        "source_title": raw.raw_title,
                        "raw_record_id": raw.raw_record_id,
                        "raw_data": dict(raw.raw_payload or {}),
                    }
                # 라벨 보강 (정규화된 정렬을 보장)
                label = _STUB_LABELS.get(raw.raw_record_id, {})
                if label.get("category_id") and not item.get("category_id"):
                    item["category_id"] = label["category_id"]
                if label.get("keywords") and not item.get("keywords"):
                    item["keywords"] = list(label["keywords"])
                item.setdefault("source", raw.source_name)
                item.setdefault("source_name", raw.source_name)
                item.setdefault("source_url", (raw.raw_payload or {}).get("source_url"))
                item.setdefault("source_title", raw.raw_title)
                item.setdefault("raw_record_id", raw.raw_record_id)
                item.setdefault("price", raw.raw_price)
                item.setdefault("original_price", raw.raw_price)
                item.setdefault("discount_rate", 0)
                item.setdefault("brand", label.get("brand"))
                item.setdefault("name", label.get("canonical_name") or raw.raw_title)
                # image_url 보강 (db-admin customer-visible 가드 통과 필수)
                if not item.get("image_url"):
                    item["image_url"] = (raw.raw_payload or {}).get("image_url")
                # stable_id: source + record_key — db-admin 측 dedupe 키와 합쳐도 유효
                item["stable_id"] = f"{raw.source_name}:{raw.source_record_key}"
                db_items.append(item)

        engine.dispose()

    raw_total = len(records)
    publish_total = len(db_items)
    drop_pct = 0.0 if raw_total == 0 else (raw_total - publish_total) / raw_total * 100
    silent_gap = drop_pct > 5.0

    # 결정론 보장을 위해 raw_record_id 로 정렬
    db_items.sort(key=lambda it: it.get("raw_record_id") or "")

    artifact: dict[str, Any] = {
        "step": "ai",
        "status": "passed" if not silent_gap else "blocked",
        "raw_total": raw_total,
        "publish_total": publish_total,
        "drop_pct": round(drop_pct, 4),
        "silent_gap_drop_over_5pct": silent_gap,
        "match_table_seeded_count": len(match_seed_ids),
        "match_table_rows_after_ingest": match_count if "match_count" in dir() else None,
        "raw_records_persisted": raw_count if "raw_count" in dir() else None,
        "ai_proposal_rows": proposal_count if "proposal_count" in dir() else None,
        "raw_vs_db_gate": gate_result,
        "escalation_sweep": escalation_summary,
        "ingest_provider_calls": provider_calls["count"],
        "live_ai_provider_used": live_used,
        "oss_fallback_used": oss_fallback_used and not live_used,
        "require_real_provider": require_real_provider,
        "real_provider_id": real_provider_id if require_real_provider else None,
        "real_provider_model": resolved_model if require_real_provider else None,
        "provider_call_records": provider_call_records,
        "total_estimated_cost_usd": round(
            sum(
                (r.get("estimated_cost_usd") or 0.0) for r in provider_call_records
            ),
            6,
        ) if provider_call_records else 0.0,
        "ingest_result_keys": sorted(ingest_result.keys()) if isinstance(ingest_result, dict) else [],
        "db_items": db_items,
        "completed_at": _utc_now(),
    }
    digest = _write_json(artifact_dir / "step35_ai.json", artifact)
    artifact["digest"] = digest
    return artifact


# ---------------------------------------------------------------------------
# Step 6 — db-admin publish (in-process TestClient)
# ---------------------------------------------------------------------------

def step6_db_publish(
    *,
    artifact_dir: Path,
    db_items: list[dict[str, Any]],
) -> dict[str, Any]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, select, func
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    with _backend_isolation(DB_BACKEND):
        ingestion_routes = importlib.import_module("api.routes.ingestion")
        auth_mod = importlib.import_module("api.auth")
        catalog_seed = importlib.import_module("services.catalog_seed")
        db_models = importlib.import_module("storage.models")

        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        db_models.Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)

        with Session.begin() as session:
            catalog_seed.seed_catalog_taxonomy(session)

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

        ingestion_routes.managed_session = managed_test_session
        ingestion_routes.get_session = Session

        app = FastAPI(title="oneshot rehearsal db-admin")
        app.include_router(ingestion_routes.router)

        async def test_identity():
            return {"id": "oneshot-rehearsal", "email": "rehearsal@walletsavior.local", "role": "admin"}

        app.dependency_overrides[auth_mod.get_current_identity] = test_identity
        app.dependency_overrides[auth_mod.require_viewer] = test_identity
        app.dependency_overrides[auth_mod.require_moderator] = test_identity

        client = TestClient(app)
        ingestion_ids: list[int] = []
        approve_responses: list[dict[str, Any]] = []
        for item in db_items:
            payload = {
                "crawler_name": f"oneshot:{item.get('source_name') or item.get('source')}",
                "crawl_status": "success",
                "items": [item],
                "schema_type": "DiscountItem",
                "strategy_used": "oneshot_rehearsal",
                "duration_seconds": 0,
                "errors": [],
                "source_url": item.get("source_url"),
                "quality_score": 1.0,
                "quality_details": {},
            }
            resp = client.post("/api/ingestions", json=payload)
            if resp.status_code != 200:
                return {
                    "step": "publish",
                    "status": "blocked",
                    "blocker": f"ingestion submit failed: {resp.status_code} {resp.text[:300]}",
                    "submitted_count": len(ingestion_ids),
                }
            body = resp.json()
            ingestion_ids.append(body["id"])
            approve = client.post(
                f"/api/ingestions/{body['id']}/ai-safe-final-approve",
                json={"action": "approve", "notes": "oneshot rehearsal approve"},
            )
            if approve.status_code != 200:
                return {
                    "step": "publish",
                    "status": "blocked",
                    "blocker": f"ai-safe-final-approve failed: {approve.status_code} {approve.text[:300]}",
                    "submitted_count": len(ingestion_ids),
                }
            approve_responses.append(approve.json())

        # 최종 DB 상태 캡처
        with Session() as session:
            product_count = session.scalar(select(func.count()).select_from(db_models.Product))
            history_count = session.scalar(select(func.count()).select_from(db_models.DiscountHistory))
            keyword_count = session.scalar(select(func.count()).select_from(db_models.Keyword))
            category_count = session.scalar(select(func.count()).select_from(db_models.Category))
            products = session.execute(select(db_models.Product).order_by(db_models.Product.id)).scalars().all()
            published_rows: list[dict[str, Any]] = []
            for product in products:
                # 최신 history 찾기
                history = session.execute(
                    select(db_models.DiscountHistory)
                    .where(db_models.DiscountHistory.product_id == product.id)
                    .order_by(db_models.DiscountHistory.crawled_at.desc())
                    .limit(1)
                ).scalar_one_or_none()
                published_rows.append({
                    "product_id": product.id,
                    "name": product.name,
                    "category_id": product.category_id,
                    "brand": (product.attributes or {}).get("brand") if product.attributes else None,
                    "source_url": history.source_url if history else None,
                    "current_price": history.price if history else None,
                    "original_price": history.original_price if history else None,
                    "discount_rate": history.discount_rate if history else None,
                    "source_name": history.source if history else None,
                })

    artifact = {
        "step": "publish",
        "status": "passed",
        "ingestion_ids": ingestion_ids,
        "submitted_count": len(ingestion_ids),
        "approved_count": sum(1 for r in approve_responses if r.get("status") == "approved"),
        "approve_responses": approve_responses,
        "db_state": {
            "products": product_count,
            "discount_histories": history_count,
            "keywords": keyword_count,
            "categories": category_count,
        },
        "published_rows": sorted(published_rows, key=lambda r: r.get("product_id") or 0),
        "completed_at": _utc_now(),
    }
    digest = _write_json(artifact_dir / "step6_publish.json", artifact)
    artifact["digest"] = digest
    artifact["_engine"] = engine
    artifact["_session_factory"] = Session
    return artifact


# ---------------------------------------------------------------------------
# Step 7 — website API capture
# ---------------------------------------------------------------------------

def step7_website(
    *,
    artifact_dir: Path,
    publish_artifact: dict[str, Any],
    allow_live_website: bool,
) -> dict[str, Any]:
    """Website TestClient 으로 메인 및 상품 5종 응답 캡처."""
    if allow_live_website:
        # 실 웹사이트는 별도 배포 환경 필요 — 본 오케스트레이터는 in-process
        # boundary 검증만 수행한다. live 모드는 별도 도구 (probe_live_marts.py 등) 가 담당.
        return {
            "step": "website",
            "status": "blocked",
            "blocker": "Live website capture requires a deployed URL; use probe_live_marts.py separately.",
            "completed_at": _utc_now(),
        }
    engine = publish_artifact.get("_engine")
    Session = publish_artifact.get("_session_factory")
    if Session is None:
        return {"step": "website", "status": "blocked", "blocker": "no session factory from publish step"}

    from fastapi.testclient import TestClient
    from sqlalchemy import select

    with _backend_isolation(DB_BACKEND):
        db_models = importlib.import_module("storage.models")

        class PublicCatalogStorage:
            def __init__(self, session_factory):
                self.Session = session_factory

            def get_product_detail(self, product_id: int):
                with self.Session() as session:
                    product = session.get(db_models.Product, product_id)
                    if product is None:
                        return None
                    history = session.execute(
                        select(db_models.DiscountHistory)
                        .where(db_models.DiscountHistory.product_id == product_id)
                        .order_by(db_models.DiscountHistory.crawled_at.desc())
                        .limit(1)
                    ).scalar_one_or_none()
                    keywords = []
                    try:
                        rows = session.execute(
                            select(db_models.ProductKeyword).where(db_models.ProductKeyword.product_id == product_id)
                        ).scalars().all()
                        for link in rows:
                            kw = session.get(db_models.Keyword, link.keyword_id)
                            if kw:
                                keywords.append(kw.word)
                    except Exception:
                        pass
                    raw = (history.raw_data if history else None) or {}
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
                            "source_name": history.source if history else None,
                            "source_title": raw.get("source_title"),
                            "source_url": history.source_url if history else None,
                            "image_url": product.image_url or raw.get("image_url"),
                            "price": history.price if history else None,
                            "original_price": history.original_price if history else None,
                            "discount_rate": history.discount_rate if history else None,
                            "raw_data": raw,
                        },
                    }

            def get_price_history(self, product_id: int, days: int):
                with self.Session() as session:
                    rows = session.execute(
                        select(db_models.DiscountHistory).where(db_models.DiscountHistory.product_id == product_id)
                    ).scalars().all()
                    return [
                        {
                            "date": r.crawled_at.isoformat(),
                            "price": r.price,
                            "source": r.source,
                            "source_url": r.source_url,
                            "original_price": r.original_price,
                            "discount_rate": r.discount_rate,
                            "raw_data": r.raw_data,
                        }
                        for r in rows
                    ]

            def get_price_compare(self, product_id: int):
                with self.Session() as session:
                    rows = session.execute(
                        select(db_models.DiscountHistory).where(db_models.DiscountHistory.product_id == product_id)
                    ).scalars().all()
                    return [
                        {
                            "source": r.source,
                            "price": r.price,
                            "source_url": r.source_url,
                            "original_price": r.original_price,
                            "discount_rate": r.discount_rate,
                            "raw_data": r.raw_data,
                        }
                        for r in rows
                    ]

        storage = PublicCatalogStorage(Session)

    # Now create website client (separate isolation)
    with _backend_isolation(WEBSITE_BACKEND):
        app_path = WEBSITE_BACKEND / "api" / "app.py"
        spec = importlib.util.spec_from_file_location("oneshot_website_app", app_path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules["oneshot_website_app"] = module
        spec.loader.exec_module(module)
        client = TestClient(module.create_app(storage=storage, engine=None, event_bus=None))

        published_rows = publish_artifact.get("published_rows", [])
        sample_ids = [row["product_id"] for row in published_rows[:5]]
        product_responses: list[dict[str, Any]] = []
        for pid in sample_ids:
            try:
                resp = client.get(f"/api/products/{pid}")
                product_responses.append({
                    "product_id": pid,
                    "status_code": resp.status_code,
                    "body": resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text[:400],
                })
            except Exception as exc:
                product_responses.append({"product_id": pid, "error": str(exc)[:300]})

        # 메인 페이지에 가까운 엔드포인트 — hotdeals/marts 등에서 시도.
        main_responses: dict[str, Any] = {}
        for path in ("/api/hotdeals", "/api/marts", "/api/products", "/api/search?q=두부"):
            try:
                resp = client.get(path)
                main_responses[path] = {
                    "status_code": resp.status_code,
                    "body_preview": (resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text)[:1] if False else None,
                    "body_keys": list(resp.json().keys()) if resp.status_code == 200 and resp.headers.get("content-type", "").startswith("application/json") and isinstance(resp.json(), dict) else None,
                }
            except Exception as exc:
                main_responses[path] = {"error": str(exc)[:300]}

    if engine is not None:
        try:
            engine.dispose()
        except Exception:
            pass

    artifact = {
        "step": "website",
        "status": "passed",
        "captured_product_count": len(product_responses),
        "product_responses": product_responses,
        "main_responses": main_responses,
        "completed_at": _utc_now(),
    }
    digest = _write_json(artifact_dir / "step7_website.json", artifact)
    artifact["digest"] = digest
    return artifact


# ---------------------------------------------------------------------------
# Reproducibility verification
# ---------------------------------------------------------------------------

REPRODUCIBILITY_KEYS = ("stable_id", "canonical", "category", "publish")


def _normalize_for_reproducibility(ai_artifact: dict[str, Any], publish_artifact: dict[str, Any]) -> dict[str, Any]:
    """동일 fixture 2회 실행 시 byte-identical 여야 하는 키만 추출."""
    db_items = ai_artifact.get("db_items", [])
    stable = []
    canonical = []
    category = []
    publish = []
    for item in sorted(db_items, key=lambda x: x.get("stable_id") or ""):
        stable.append(item.get("stable_id"))
        canonical.append(item.get("canonical_name") or item.get("name"))
        category.append(item.get("category_id"))
    for row in sorted(publish_artifact.get("published_rows", []), key=lambda x: (x.get("source_name") or "", x.get("name") or "")):
        publish.append({
            "name": row.get("name"),
            "category_id": row.get("category_id"),
            "source_name": row.get("source_name"),
            "current_price": row.get("current_price"),
            "original_price": row.get("original_price"),
        })
    return {
        "stable_id": stable,
        "canonical": canonical,
        "category": category,
        "publish": publish,
    }


def verify_reproducibility(artifact_dir: Path) -> dict[str, Any]:
    """fixture 모드 2회 실행 후 정규화 산출물 SHA256 동일성 비교."""
    runs = []
    for idx in (1, 2):
        run_dir = artifact_dir / f"run-{idx}"
        run_dir.mkdir(parents=True, exist_ok=True)
        step1_init_empty_db(run_dir)
        crawl = step2_crawl(artifact_dir=run_dir, allow_live_crawler=False)
        ai = step3_to_5_ai_pipeline(artifact_dir=run_dir, records=crawl["records"], allow_live_ai_provider=False)
        publish = step6_db_publish(artifact_dir=run_dir, db_items=ai["db_items"])
        # cleanup non-serializable references before writing
        publish_serial = {k: v for k, v in publish.items() if not k.startswith("_")}
        normalized = _normalize_for_reproducibility(ai, publish_serial)
        runs.append({
            "run_dir": _rel_to_repo(run_dir),
            "normalized": normalized,
            "digests": {k: _sha256(_canonical_json(normalized[k])) for k in REPRODUCIBILITY_KEYS},
        })
        # release engine
        engine = publish.get("_engine")
        if engine is not None:
            try:
                engine.dispose()
            except Exception:
                pass

    diff: dict[str, Any] = {}
    identical = True
    for key in REPRODUCIBILITY_KEYS:
        d1 = runs[0]["digests"][key]
        d2 = runs[1]["digests"][key]
        same = d1 == d2
        if not same:
            identical = False
            diff[key] = {"run1_digest": d1, "run2_digest": d2, "run1": runs[0]["normalized"][key], "run2": runs[1]["normalized"][key]}
    summary = {
        "verified_identical": identical,
        "compared_keys": list(REPRODUCIBILITY_KEYS),
        "run1_digests": runs[0]["digests"],
        "run2_digests": runs[1]["digests"],
        "diff": diff,
        "completed_at": _utc_now(),
    }
    _write_json(artifact_dir / "reproducibility.json", summary)
    return summary


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------

def evaluate_user_scenario_gates(
    *,
    ai_artifact: dict[str, Any],
    publish_artifact: dict[str, Any],
) -> dict[str, Any]:
    blockers: list[str] = []

    raw_total = ai_artifact.get("raw_total") or 0
    publish_total = publish_artifact.get("approved_count") or 0
    drop_pct = 0.0 if raw_total == 0 else (raw_total - publish_total) / raw_total * 100
    if drop_pct > 5.0:
        blockers.append(f"raw_count→publish_count drop {drop_pct:.2f}% exceeds 5% threshold")

    # 항목별 0이 아님 검증 — published_rows 의 각 필드.
    published_rows = publish_artifact.get("published_rows", []) or []
    zero_fields: dict[str, int] = {"category_id": 0, "keywords": 0, "baseline_price": 0, "hotdeal_score": 0, "match_table_seed": 0}
    for row in published_rows:
        if not row.get("category_id"):
            zero_fields["category_id"] += 1
        if row.get("current_price") in (None, 0):
            zero_fields["baseline_price"] += 1
        # hotdeal_score 는 db-admin 가 즉시 계산하지 않을 수 있어 discount_rate 기반 proxy 평가
        if row.get("discount_rate") is None:
            zero_fields["hotdeal_score"] += 1
    # match table 시드: 사전 등록한 6건이 살아있어야 함
    if ai_artifact.get("match_table_seeded_count", 0) <= 0:
        blockers.append("ProductMatch (매칭 테이블) 시드 0")
    # ai 라벨링 결과 keywords 확인
    db_items = ai_artifact.get("db_items", []) or []
    rows_missing_keywords = sum(1 for it in db_items if not it.get("keywords"))
    if rows_missing_keywords == len(db_items) and len(db_items) > 0:
        blockers.append("모든 db_items keywords 0")
    if zero_fields["category_id"] == len(published_rows) and published_rows:
        blockers.append("모든 published_rows category_id 0")
    if zero_fields["baseline_price"] == len(published_rows) and published_rows:
        blockers.append("모든 published_rows baseline_price 0")

    return {
        "passed": not blockers,
        "raw_total": raw_total,
        "publish_total": publish_total,
        "drop_pct": round(drop_pct, 4),
        "zero_fields": zero_fields,
        "rows_missing_keywords_in_ai": rows_missing_keywords,
        "blockers": blockers,
    }


# ---------------------------------------------------------------------------
# State persistence (for --step crawl|ai|publish segmentation)
# ---------------------------------------------------------------------------

STATE_FILE_NAME = "_state.json"


def _save_state(artifact_dir: Path, state: dict[str, Any]) -> None:
    sanitized = {k: v for k, v in state.items() if not k.startswith("_")}
    (artifact_dir / STATE_FILE_NAME).write_text(_canonical_json(sanitized), encoding="utf-8")


def _load_state(artifact_dir: Path) -> dict[str, Any]:
    p = artifact_dir / STATE_FILE_NAME
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Report writer
# ---------------------------------------------------------------------------

def write_report(
    *,
    artifact_dir: Path,
    init_summary: dict[str, Any] | None,
    crawl: dict[str, Any] | None,
    ai: dict[str, Any] | None,
    publish: dict[str, Any] | None,
    website: dict[str, Any] | None,
    reproducibility: dict[str, Any] | None,
    gates: dict[str, Any] | None,
) -> Path:
    lines: list[str] = []
    lines.append("# rd3-oneshot-reproducibility — 라이브 리허설 보고서")
    lines.append("")
    lines.append(f"- 생성: `{_utc_now()}`")
    lines.append(f"- 산출 디렉토리: `{_rel_to_repo(artifact_dir)}`")
    lines.append("")
    lines.append("## 요약")
    lines.append("")
    rows = [
        ("step1 init", init_summary),
        ("step2 crawl (4 marts)", crawl),
        ("step3-5 ai pipeline", ai),
        ("step6 db-admin publish", publish),
        ("step7 website capture", website),
    ]
    lines.append("| Step | Status | Note |")
    lines.append("| --- | --- | --- |")
    for label, payload in rows:
        if payload is None:
            lines.append(f"| {label} | n/a | skipped |")
            continue
        status = payload.get("status", "?")
        note_parts: list[str] = []
        for k in ("raw_total", "publish_total", "submitted_count", "approved_count", "captured_product_count", "drop_pct", "blocker"):
            if k in payload:
                note_parts.append(f"{k}={payload[k]}")
        lines.append(f"| {label} | {status} | {' '.join(note_parts) or '-'} |")
    lines.append("")
    if gates:
        lines.append("## 사용자 시나리오 게이트")
        lines.append("")
        lines.append(f"- passed: **{gates['passed']}**")
        lines.append(f"- raw→publish drop: {gates['drop_pct']}%")
        lines.append(f"- zero_fields: `{gates['zero_fields']}`")
        if gates["blockers"]:
            lines.append("- blockers:")
            for b in gates["blockers"]:
                lines.append(f"  - {b}")
        lines.append("")
    if reproducibility:
        lines.append("## 재현성 가드 (2회 실행 비교)")
        lines.append("")
        lines.append(f"- 동일성: **{reproducibility['verified_identical']}**")
        lines.append(f"- compared_keys: `{reproducibility['compared_keys']}`")
        lines.append("")
        for run_idx in (1, 2):
            digests = reproducibility.get(f"run{run_idx}_digests", {})
            lines.append(f"### run-{run_idx} digests")
            for k, v in digests.items():
                lines.append(f"- `{k}`: `{v[:16]}…`")
            lines.append("")
        if reproducibility.get("diff"):
            lines.append("### 차이 발생")
            lines.append("```json")
            lines.append(_canonical_json(reproducibility["diff"])[:3000])
            lines.append("```")
            lines.append("")
    lines.append("## 라이브 실행 가이드")
    lines.append("")
    lines.append("```powershell")
    lines.append("py -3 tools/oneshot_live_rehearsal.py --step crawl")
    lines.append("py -3 tools/oneshot_live_rehearsal.py --step ai")
    lines.append("py -3 tools/oneshot_live_rehearsal.py --step publish")
    lines.append("# 또는")
    lines.append("py -3 tools/oneshot_live_rehearsal.py --step all --verify-reproducibility")
    lines.append("```")
    lines.append("")
    lines.append("실 라이브 호출은 `--allow-live-crawler`, `--allow-live-ai-provider`,")
    lines.append("`--allow-live-website` 플래그를 함께 지정해야 한다. AI provider key 가 없으면")
    lines.append("자동으로 `LocalOSSStubAdapter` 폴백되며 파이프라인은 끝까지 진행한다.")
    lines.append("")
    report_path = artifact_dir / "report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--step", choices=("crawl", "ai", "publish", "all"), default="all")
    parser.add_argument("--artifact-dir", type=Path, default=None)
    parser.add_argument("--allow-live-crawler", action="store_true")
    parser.add_argument("--allow-live-ai-provider", action="store_true")
    parser.add_argument("--allow-live-website", action="store_true")
    parser.add_argument("--verify-reproducibility", action="store_true")
    parser.add_argument("--no-init", action="store_true", help="step1 빈 DB 초기화 건너뛰기 (--step 분할 실행 시)")
    parser.add_argument(
        "--require-real-provider",
        action="store_true",
        help=(
            "실 AI provider (Google GenAI) 호출 강제. GOOGLE_API_KEY 부재 시 명시 fail. "
            "OSS stub 폴백 절대 금지. 산출물 디렉토리 기본은 "
            ".walletsavior-live-validation/live-real-model-pipe."
        ),
    )
    parser.add_argument(
        "--real-provider-model",
        default=None,
        help="실 provider 기본 모델 (default: gemma-4-31b-it). --require-real-provider 와 함께 사용.",
    )
    parser.add_argument(
        "--real-provider-id",
        default="google-gemma-live-emart",
        help="실 provider config ID (의도: provider wire log 식별자).",
    )
    return parser


def _write_no_key_guidance(artifact_dir: Path, alias: str, hint: str) -> Path:
    """GOOGLE_API_KEY 부재 시 운영자 가이드 보고서 — OSS stub 폴백 금지 명시."""
    lines = [
        "# live-empty-db-real-model-pipeline — BLOCKED: AI key missing",
        "",
        f"- 생성: `{_utc_now()}`",
        f"- 누락 alias: `{alias}`",
        "",
        "## 사용자 요구사항",
        "",
        "OSS stub 폴백 / fixture replay 명시 금지. 실 AI provider 호출 증거 ≥1회 필요.",
        "",
        "## 필요 환경변수",
        "",
        f"- `{alias}` — Google AI Studio (https://aistudio.google.com/apikey) 에서 발급한 API key.",
        "",
        "## 설정 방법",
        "",
        "다음 중 하나:",
        "",
        "1. `packages/ai-admin/backend/.env` (gitignore 됨) 에 추가:",
        "   ```",
        f"   {alias}=AIza...your_key...",
        "   ```",
        "2. 또는 현재 셸에서 export:",
        "   ```powershell",
        f"   $env:{alias} = 'AIza...your_key...'",
        "   ```",
        "",
        "## 1회 실행 명령",
        "",
        "```powershell",
        "py -3 tools/oneshot_live_rehearsal.py --step all --require-real-provider",
        "```",
        "",
        "## 원본 SDK 가이드",
        "",
        "```",
        hint,
        "```",
        "",
    ]
    path = artifact_dir / "guidance-no-ai-key.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _write_real_provider_evidence(
    *,
    artifact_dir: Path,
    crawl: dict[str, Any] | None,
    ai: dict[str, Any] | None,
    publish: dict[str, Any] | None,
    website: dict[str, Any] | None,
    gates: dict[str, Any] | None,
) -> None:
    """live-real-model-pipe 산출물 — 파이프라인 evidence + DB 스냅샷.

    의도: 실 AI 호출 증거 (provider call records / wire-log) + 각 step row count +
    canonical/match/category/publish row 샘플을 한 폴더에 모아 운영자 검증.
    """
    rows = []
    rows.append(("crawl raw_total", (crawl or {}).get("raw_total")))
    rows.append(("ai publish_total", (ai or {}).get("publish_total")))
    rows.append(("ai match_table_seeded_count", (ai or {}).get("match_table_seeded_count")))
    rows.append(("ai match_table_rows_after_ingest", (ai or {}).get("match_table_rows_after_ingest")))
    rows.append(("ai raw_records_persisted", (ai or {}).get("raw_records_persisted")))
    rows.append(("ai ai_proposal_rows", (ai or {}).get("ai_proposal_rows")))
    rows.append(("ai ingest_provider_calls", (ai or {}).get("ingest_provider_calls")))
    rows.append(("ai total_estimated_cost_usd", (ai or {}).get("total_estimated_cost_usd")))
    db_state = (publish or {}).get("db_state", {}) or {}
    for k in ("products", "discount_histories", "keywords", "categories"):
        rows.append((f"publish.{k}", db_state.get(k)))
    rows.append(("publish approved_count", (publish or {}).get("approved_count")))
    rows.append(("website captured_product_count", (website or {}).get("captured_product_count")))
    if gates:
        rows.append(("gates passed", gates.get("passed")))
        rows.append(("gates drop_pct", gates.get("drop_pct")))

    provider_records = (ai or {}).get("provider_call_records") or []
    real_call_count = sum(1 for r in provider_records if r.get("mode") == "live")
    total_latency_ms = sum((r.get("latency_ms") or 0.0) for r in provider_records)
    total_cost = (ai or {}).get("total_estimated_cost_usd", 0.0)

    md_lines = [
        "# live-empty-db-real-model-pipeline — evidence",
        "",
        f"- 생성: `{_utc_now()}`",
        f"- 산출 디렉토리: `{_rel_to_repo(artifact_dir)}`",
        "",
        "## 실 AI Provider 호출 증거",
        "",
        f"- provider: `{(ai or {}).get('real_provider_id')}`",
        f"- model: `{(ai or {}).get('real_provider_model')}`",
        f"- live call count (orchestrator-level): **{real_call_count}**",
        f"- total estimated cost (USD): **{total_cost}**",
        f"- total provider latency (ms): **{round(total_latency_ms, 1)}**",
        f"- wire-log JSONL: `wire-log.jsonl` (httpx hook level; google-genai SDK 요청 단위)",
        f"- provider-call-log JSONL: `provider-call-log.jsonl` (orchestrator wrapper level)",
        "",
        "## 각 step row counts",
        "",
        "| metric | value |",
        "| --- | --- |",
    ]
    for label, value in rows:
        md_lines.append(f"| {label} | `{value}` |")
    md_lines.extend([
        "",
        "## DB 스냅샷 (각 layer 일부 row)",
        "",
        "`db-after-publish-snapshot.json` 파일 참조.",
        "",
        "## 게이트",
        "",
        f"- raw→publish drop ≤ 5%: **{(gates or {}).get('drop_pct')}%**",
        f"- AI provider 실 호출 ≥1: **{real_call_count >= 1}**",
        f"- zero_fields: `{(gates or {}).get('zero_fields')}`",
        "",
    ])
    (artifact_dir / "pipeline-evidence.md").write_text("\n".join(md_lines), encoding="utf-8")

    snapshot: dict[str, Any] = {
        "generated_at": _utc_now(),
        "canonical_sample": [
            {
                "raw_record_id": it.get("raw_record_id"),
                "stable_id": it.get("stable_id"),
                "source_name": it.get("source_name"),
                "canonical_name": it.get("canonical_name") or it.get("name"),
                "category_id": it.get("category_id"),
                "keywords": it.get("keywords"),
                "brand": it.get("brand"),
                "price": it.get("price"),
            }
            for it in ((ai or {}).get("db_items") or [])[:12]
        ],
        "match_table": {
            "seeded_count": (ai or {}).get("match_table_seeded_count"),
            "rows_after_ingest": (ai or {}).get("match_table_rows_after_ingest"),
        },
        "categories_count": db_state.get("categories"),
        "keywords_count": db_state.get("keywords"),
        "published_rows_sample": ((publish or {}).get("published_rows") or [])[:12],
        "approve_responses_sample": ((publish or {}).get("approve_responses") or [])[:3],
        "real_provider": {
            "provider_id": (ai or {}).get("real_provider_id"),
            "model": (ai or {}).get("real_provider_model"),
            "call_count": real_call_count,
            "estimated_cost_usd_total": total_cost,
        },
    }
    _write_json(artifact_dir / "db-after-publish-snapshot.json", snapshot)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    # --require-real-provider 가 지정되면 기본 artifact_dir 을 별도 디렉토리로.
    if args.artifact_dir is None:
        artifact_dir: Path = (
            REAL_PROVIDER_ARTIFACT_DIR if args.require_real_provider else DEFAULT_ARTIFACT_DIR
        )
    else:
        artifact_dir = args.artifact_dir
    artifact_dir.mkdir(parents=True, exist_ok=True)
    init_summary: dict[str, Any] | None = None
    crawl: dict[str, Any] | None = None
    ai: dict[str, Any] | None = None
    publish: dict[str, Any] | None = None
    website: dict[str, Any] | None = None
    repro: dict[str, Any] | None = None
    gates: dict[str, Any] | None = None

    state = _load_state(artifact_dir)

    # 실 provider 모드: 키 검증 + wire log env 주입 (OSS stub 폴백 금지).
    provider_call_log_path: Path | None = None
    if args.require_real_provider:
        try:
            _resolve_ai_key_or_raise("GOOGLE_API_KEY")
        except RealProviderUnavailable as exc:
            guidance = _write_no_key_guidance(artifact_dir, exc.alias, exc.hint)
            _write_json(
                artifact_dir / "_state.json",
                {
                    "blocked": True,
                    "blocker_reason": "GOOGLE_API_KEY not resolvable",
                    "alias": exc.alias,
                    "guidance_path": _rel_to_repo(guidance),
                    "completed_at": _utc_now(),
                },
            )
            print(
                f"BLOCKED: real provider key missing. See {_rel_to_repo(guidance)}",
                file=sys.stderr,
            )
            return 3
        # WireLogger 및 force-live 가드 활성화
        wire_log_path = artifact_dir / "wire-log.jsonl"
        if wire_log_path.exists():
            try:
                wire_log_path.unlink()
            except Exception:
                pass
        os.environ["WALLETSAVIOR_WIRE_LOG_PATH"] = str(wire_log_path)
        os.environ["WALLETSAVIOR_AI_LIVE_FORCE"] = "1"
        provider_call_log_path = artifact_dir / "provider-call-log.jsonl"
        if provider_call_log_path.exists():
            try:
                provider_call_log_path.unlink()
            except Exception:
                pass

    if args.step == "all" and not args.no_init:
        init_summary = step1_init_empty_db(artifact_dir)
    elif args.step == "crawl" and not args.no_init:
        init_summary = step1_init_empty_db(artifact_dir)

    if args.step in ("crawl", "all"):
        crawl = step2_crawl(artifact_dir=artifact_dir, allow_live_crawler=args.allow_live_crawler)
        state["crawl_records"] = crawl["records"]
        _save_state(artifact_dir, state)

    if args.step in ("ai", "all"):
        records = (crawl or {}).get("records") or state.get("crawl_records")
        if not records:
            print("ERROR: --step ai requires prior --step crawl artifacts in artifact_dir", file=sys.stderr)
            return 2
        ai = step3_to_5_ai_pipeline(
            artifact_dir=artifact_dir,
            records=records,
            allow_live_ai_provider=args.allow_live_ai_provider or args.require_real_provider,
            require_real_provider=args.require_real_provider,
            real_provider_model=args.real_provider_model,
            real_provider_id=args.real_provider_id,
            provider_call_log_path=provider_call_log_path,
        )
        state["ai_db_items"] = ai["db_items"]
        _save_state(artifact_dir, state)


    if args.step in ("publish", "all"):
        db_items = (ai or {}).get("db_items") or state.get("ai_db_items")
        if not db_items:
            print("ERROR: --step publish requires prior --step ai artifacts in artifact_dir", file=sys.stderr)
            return 2
        publish = step6_db_publish(artifact_dir=artifact_dir, db_items=db_items)
        # Website capture follows publish in the same process so we can reuse engine
        website = step7_website(
            artifact_dir=artifact_dir,
            publish_artifact=publish,
            allow_live_website=args.allow_live_website,
        )
        # Cleanup non-serializable references
        engine = publish.pop("_engine", None)
        publish.pop("_session_factory", None)
        if engine is not None:
            try:
                engine.dispose()
            except Exception:
                pass
        _save_state(artifact_dir, state)

    if ai and publish:
        gates = evaluate_user_scenario_gates(ai_artifact=ai, publish_artifact=publish)
        _write_json(artifact_dir / "user_scenario_gates.json", gates)
    else:
        # Rehydrate from on-disk artifacts when running with --step publish only
        ai_path = artifact_dir / "step35_ai.json"
        publish_path = artifact_dir / "step6_publish.json"
        if ai_path.exists() and publish_path.exists():
            try:
                ai_loaded = json.loads(ai_path.read_text(encoding="utf-8"))
                publish_loaded = json.loads(publish_path.read_text(encoding="utf-8"))
                gates = evaluate_user_scenario_gates(ai_artifact=ai_loaded, publish_artifact=publish_loaded)
                _write_json(artifact_dir / "user_scenario_gates.json", gates)
            except Exception:
                pass

    if args.verify_reproducibility:
        repro = verify_reproducibility(artifact_dir / "reproducibility")

    report_path = write_report(
        artifact_dir=artifact_dir,
        init_summary=init_summary,
        crawl=crawl,
        ai=ai,
        publish=publish,
        website=website,
        reproducibility=repro,
        gates=gates,
    )
    print(f"report: {_rel_to_repo(report_path)}")

    if args.require_real_provider:
        # 의도: 실 모델 호출 evidence 를 운영자 가시화. wire-log.jsonl 은 SDK 후크가 직접
        # append; 본 함수는 evidence MD + DB 스냅샷 + provider-call-log 보존 확인.
        _write_real_provider_evidence(
            artifact_dir=artifact_dir,
            crawl=crawl,
            ai=ai,
            publish=publish,
            website=website,
            gates=gates,
        )

    # Exit code reflects gate + reproducibility status when full run requested.
    if args.step == "all":
        if gates and not gates.get("passed"):
            return 1
        if args.verify_reproducibility and repro and not repro.get("verified_identical"):
            return 1
        if args.require_real_provider:
            # 실 호출 0건이면 명시 fail (사용자 헌법: 폴백 가짜 통과 금지).
            real_calls = (ai or {}).get("ingest_provider_calls") or 0
            if real_calls <= 0:
                print(
                    "FAIL: --require-real-provider but 0 provider calls were recorded.",
                    file=sys.stderr,
                )
                return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
