"""WalletSavior Phase D3 — 원샷 공개 DB 빌더 CLI.

사용법:
    py -3 packages\\db-admin\\backend\\scripts\\phaseD_oneshot_public_db.py \\
        --source fixtures \\
        --ai mock \\
        --window-months 6 \\
        --out .\\.walletsavior\\public_snapshot.sqlite \\
        --meta-json .\\.walletsavior\\public_snapshot_meta.json \\
        --commit

옵션:
    --source fixtures     : 4사 crawler fixture 사용 (기본)
    --ai mock|live        : AI 공급자 종류 (기본: mock)
    --window-months N     : 가격 집계 기간 월 수 (기본: 6)
    --out PATH            : 스냅샷 SQLite 출력 경로
    --meta-json PATH      : 메타 JSON 출력 경로
    --commit              : 파일 쓰기 실행 (기본: dry-run)
    --dry-run             : 파일 쓰지 않음 (계산만)

콘솔 출력 (한국어):
    - 입력 건수 (마트별)
    - livepass 통과율
    - 분위수 산정 결과 (sufficient/insufficient 건수)
    - 분위수 샘플 5건 표
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from datetime import datetime

# ── 경로 설정 ────────────────────────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _SCRIPT_DIR.parent                              # db-admin/backend
_REPO_ROOT = _BACKEND_DIR.parent.parent.parent                 # capston01/
_SHARED_DIR = _REPO_ROOT / "packages" / "shared"
_AI_ADMIN_BACKEND = _REPO_ROOT / "packages" / "ai-admin" / "backend"
_DB_ADMIN_BACKEND = _BACKEND_DIR

_DEFAULT_FIXTURE_DIR = (
    _REPO_ROOT / "packages" / "crawler-admin" / "backend" / "tests" / "fixtures"
)
_DEFAULT_OUT = _REPO_ROOT / ".walletsavior" / "public_snapshot.sqlite"
_DEFAULT_META = _REPO_ROOT / ".walletsavior" / "public_snapshot_meta.json"


# ── sys.path 설정: ai-admin 을 먼저 등록해 services 패키지 충돌 방지 ─────────
# ai-admin/backend 의 services/ 를 먼저 등록해 livepass_pipeline 등을 정상 import.
# db-admin/backend 의 storage/ 는 oneshot_public_db 내부에서 자체 경로 보정.

for _p in [str(_SHARED_DIR), str(_AI_ADMIN_BACKEND)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ai-admin services import
from services.livepass_pipeline import run_livepass, LivepassReport  # noqa: E402
from services.queue_ai_router import (  # noqa: E402
    QueueAiRouter,
    load_default_brand_dictionary,
    load_default_category_tree,
    load_default_synonyms,
)
from services.postcheck_gate import PostcheckGate  # noqa: E402

# canonical_seed — livepass_pipeline이 importlib로 로드한 버전 재사용
from services.livepass_pipeline import (  # noqa: E402
    seed_categories_from_yaml,
    seed_from_raw_batch,
)

# db-admin storage — livepass_pipeline 이미 importlib로 등록했으므로 db_admin_storage 로 접근
# bootstrap_canonical_tables 은 importlib 직접 로드
def _load_bootstrap():
    """db-admin canonical_models.bootstrap_canonical_tables 로드."""
    db_storage = _DB_ADMIN_BACKEND / "storage"

    # db_admin_storage 패키지가 이미 등록돼 있으면 canonical_models도 거기서
    import sys as _sys
    if "db_admin_storage.canonical_models" in _sys.modules:
        return _sys.modules["db_admin_storage.canonical_models"].bootstrap_canonical_tables

    # 직접 로드
    _spec_pkg = importlib.util.spec_from_file_location(
        "db_admin_storage",
        db_storage / "__init__.py",
        submodule_search_locations=[str(db_storage)],
    )
    _pkg = importlib.util.module_from_spec(_spec_pkg)   # type: ignore
    _sys.modules.setdefault("db_admin_storage", _pkg)
    _spec_pkg.loader.exec_module(_pkg)                   # type: ignore

    for _sub in ("canonical_models",):
        _spec_sub = importlib.util.spec_from_file_location(
            f"db_admin_storage.{_sub}",
            db_storage / f"{_sub}.py",
            submodule_search_locations=[str(db_storage)],
        )
        _mod = importlib.util.module_from_spec(_spec_sub)   # type: ignore
        _mod.__package__ = "db_admin_storage"
        _sys.modules.setdefault(f"db_admin_storage.{_sub}", _mod)
        setattr(_pkg, _sub, _mod)
        _spec_sub.loader.exec_module(_mod)               # type: ignore

    return _sys.modules["db_admin_storage.canonical_models"].bootstrap_canonical_tables


bootstrap_canonical_tables = _load_bootstrap()


# oneshot_public_db — importlib로 로드 (services 패키지 이름 충돌 방지)
def _load_oneshot_module():
    """db-admin services/oneshot_public_db 를 importlib로 직접 로드."""
    _path = _DB_ADMIN_BACKEND / "services" / "oneshot_public_db.py"
    _spec = importlib.util.spec_from_file_location("db_admin_oneshot_public_db", _path)
    _mod = importlib.util.module_from_spec(_spec)    # type: ignore
    sys.modules.setdefault("db_admin_oneshot_public_db", _mod)
    _spec.loader.exec_module(_mod)                   # type: ignore
    return _mod


_oneshot_mod = _load_oneshot_module()
build_snapshot = _oneshot_mod.build_snapshot
SnapshotMeta = _oneshot_mod.SnapshotMeta

# canonical_seed 파서 — livepass_pipeline이 로드한 버전에서
_cs_mod = sys.modules.get("db_admin_storage.canonical_seed")

if _cs_mod is None:
    # fallback: importlib 로 직접 로드
    _db_storage = _DB_ADMIN_BACKEND / "storage"
    _spec_cs = importlib.util.spec_from_file_location(
        "db_admin_storage.canonical_seed",
        _db_storage / "canonical_seed.py",
        submodule_search_locations=[str(_db_storage)],
    )
    _cs_mod = importlib.util.module_from_spec(_spec_cs)   # type: ignore
    _cs_mod.__package__ = "db_admin_storage"
    sys.modules["db_admin_storage.canonical_seed"] = _cs_mod
    _spec_cs.loader.exec_module(_cs_mod)                  # type: ignore

_parse_emart_raw = _cs_mod._parse_emart_raw
_parse_homeplus_raw = _cs_mod._parse_homeplus_raw
_parse_lottemart_raw = _cs_mod._parse_lottemart_raw
_parse_costco_raw = _cs_mod._parse_costco_raw

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker      # noqa: E402


# ── 최소 DDL (in-memory SQLite 작업용) ────────────────────────────────────────

_DDL_CANONICAL = [
    """
    CREATE TABLE IF NOT EXISTS canonical_category_nodes (
        id TEXT PRIMARY KEY,
        parent_id TEXT REFERENCES canonical_category_nodes(id),
        name_kr TEXT NOT NULL,
        name_slug TEXT NOT NULL,
        level INTEGER NOT NULL,
        path TEXT NOT NULL UNIQUE,
        display_order INTEGER DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS canonical_products (
        id TEXT PRIMARY KEY,
        brand TEXT,
        name_core TEXT NOT NULL,
        pack_quantity REAL NOT NULL DEFAULT 1.0,
        pack_unit TEXT NOT NULL DEFAULT '개',
        category_path_internal_id TEXT REFERENCES canonical_category_nodes(id),
        representative_image_url TEXT,
        created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS canonical_mart_sku_aliases (
        id TEXT PRIMARY KEY,
        canonical_id TEXT NOT NULL REFERENCES canonical_products(id),
        mart TEXT NOT NULL,
        mart_item_id TEXT NOT NULL,
        mart_item_name_raw TEXT NOT NULL,
        source_url TEXT,
        first_seen_at DATETIME NOT NULL,
        last_seen_at DATETIME NOT NULL,
        UNIQUE(mart, mart_item_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS canonical_price_observations (
        id TEXT PRIMARY KEY,
        canonical_id TEXT NOT NULL REFERENCES canonical_products(id),
        mart TEXT NOT NULL,
        regular_price INTEGER,
        sale_price INTEGER NOT NULL,
        on_sale INTEGER NOT NULL,
        discount_rate INTEGER,
        unit_price_normalized REAL,
        unit_price_basis TEXT NOT NULL DEFAULT 'unknown',
        observed_at DATETIME NOT NULL,
        source_url TEXT,
        raw_payload_hash TEXT NOT NULL,
        event_labels TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS canonical_product_review_queue (
        id TEXT PRIMARY KEY,
        raw_payload TEXT NOT NULL,
        source_mart TEXT NOT NULL,
        reason TEXT NOT NULL,
        suggested_canonical_id TEXT REFERENCES canonical_products(id),
        attributes TEXT,
        created_at DATETIME NOT NULL,
        resolved_at DATETIME,
        resolver_user_id TEXT
    )
    """,
]


def _bootstrap_working_engine(db_url: str = "sqlite:///:memory:"):
    """작업용 SQLite 엔진 생성 + canonical 테이블 초기화."""
    from sqlalchemy import create_engine as _ce, text as _text
    engine = _ce(db_url, echo=False)
    with engine.connect() as conn:
        for ddl in _DDL_CANONICAL:
            conn.execute(_text(ddl))
        conn.commit()
    return engine


# ── argparse ─────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="WalletSavior Phase D — 원샷 공개 DB 스냅샷 빌더"
    )
    parser.add_argument(
        "--source",
        choices=["fixtures"],
        default="fixtures",
        help="입력 소스 (현재: fixtures만 지원)",
    )
    parser.add_argument(
        "--ai",
        choices=["mock", "live"],
        default="mock",
        help="AI 공급자 종류 (기본: mock)",
    )
    parser.add_argument(
        "--window-months",
        type=int,
        default=6,
        help="가격 집계 기간 (월, 기본: 6)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=_DEFAULT_OUT,
        help=f"스냅샷 SQLite 출력 경로 (기본: {_DEFAULT_OUT})",
    )
    parser.add_argument(
        "--meta-json",
        type=Path,
        default=_DEFAULT_META,
        help=f"메타 JSON 출력 경로 (기본: {_DEFAULT_META})",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--commit",
        action="store_true",
        default=False,
        help="파일 실제 생성 (기본: dry-run)",
    )
    mode.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="계산만 수행, 파일 미생성",
    )
    parser.add_argument(
        "--fixture-dir",
        type=Path,
        default=_DEFAULT_FIXTURE_DIR,
        help=f"fixture 루트 디렉터리 (기본: {_DEFAULT_FIXTURE_DIR})",
    )
    return parser.parse_args()


# ── 콘솔 출력 헬퍼 ────────────────────────────────────────────────────────────

def _print_section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def _print_meta(meta: SnapshotMeta) -> None:
    _print_section("Phase D — 원샷 공개 DB 빌드 결과")
    print(f"  생성 시각     : {meta.generated_at}")
    print(f"  집계 기간     : {meta.window_months}개월")
    print(f"  AI 공급자     : {meta.ai_provider_kind}")

    print("\n[입력 건수 (마트별)]")
    for mart, cnt in sorted(meta.input_counts.items()):
        print(f"  {mart:12s}: {cnt:4d}건")
    print(f"  {'합계':12s}: {meta.total_input:4d}건")

    print("\n[Livepass 통과율]")
    print(f"  통과율 : {meta.livepass_pass_rate * 100:.1f}%")

    print("\n[분위수 산정 결과]")
    print(f"  전체 canonical : {meta.total_canonical:4d}건")
    print(f"  sufficient     : {meta.sufficient_grades:4d}건 (표본 >= 5)")
    print(f"  insufficient   : {meta.insufficient_grades:4d}건 (표본 부족)")

    if meta.grade_sample:
        print("\n[분위수 샘플 (상위 5건)]")
        header = f"  {'canonical_id':14s} {'n':>4s} {'P10':>9s} {'P25':>9s} {'P50':>9s} {'P75':>9s}"
        print(header)
        print("  " + "-" * 56)
        for g in meta.grade_sample:
            def _fmt(v):
                return f"{v:9.1f}" if v is not None else f"{'N/A':>9s}"
            print(
                f"  {g['canonical_id']:14s} {g['sample_size']:>4d}"
                f" {_fmt(g['p10'])} {_fmt(g['p25'])} {_fmt(g['p50'])} {_fmt(g['p75'])}"
            )

    print()
    if meta.snapshot_path and Path(meta.snapshot_path).exists():
        size_kb = Path(meta.snapshot_path).stat().st_size // 1024
        print(f"  스냅샷 파일 : {meta.snapshot_path} ({size_kb}KB)")
    if meta.meta_json_path and Path(meta.meta_json_path).exists():
        print(f"  메타 JSON   : {meta.meta_json_path}")


# ── 메인 ─────────────────────────────────────────────────────────────────────

def main() -> int:
    args = _parse_args()
    write_files = args.commit  # --commit이면 True

    fixture_dir = args.fixture_dir
    if not fixture_dir.exists():
        print(f"[ERROR] fixture 디렉터리를 찾을 수 없음: {fixture_dir}")
        return 1

    print(f"Phase D 원샷 빌더 시작")
    print(f"  fixture 디렉터리 : {fixture_dir}")
    print(f"  AI 공급자        : {args.ai}")
    print(f"  집계 기간        : {args.window_months}개월")
    print(f"  출력 경로        : {args.out}")
    print(f"  메타 JSON        : {args.meta_json}")
    print(f"  모드             : {'COMMIT (파일 생성)' if write_files else 'DRY-RUN (파일 미생성)'}")

    # ── fixture 파싱 ─────────────────────────────────────────────────────────
    print("\n[1/4] fixture 파싱 중...")
    mart_payloads: dict[str, list[dict]] = {}
    for mart_key, parser in [
        ("emart", _parse_emart_raw),
        ("homeplus", _parse_homeplus_raw),
        ("lottemart", _parse_lottemart_raw),
        ("costco", _parse_costco_raw),
    ]:
        try:
            items = parser(fixture_dir)
            if items:
                mart_payloads[mart_key] = items
                print(f"  {mart_key:10s}: {len(items):3d}건")
            else:
                print(f"  {mart_key:10s}: fixture 없음 (skip)")
        except Exception as e:
            print(f"  {mart_key:10s}: 파싱 오류 — {e}")

    if not mart_payloads:
        print("[WARNING] 처리할 fixture가 없습니다.")
        return 0

    # ── AI 라우터 + 게이트 초기화 ────────────────────────────────────────────
    print("\n[2/4] AI 라우터 초기화 중...")
    category_tree = load_default_category_tree()
    brand_dict = load_default_brand_dictionary()
    synonyms = load_default_synonyms()

    if args.ai == "mock":
        # mock provider: 항상 첫 번째 유효 카테고리 노드 id 반환
        valid_ids = sorted(
            n["id"] for n in category_tree.get("nodes", []) if "id" in n
        )
        default_cat_id = valid_ids[0] if valid_ids else "unknown"

        class _MockProvider:
            def call(self, *, prompt: str, schema=None) -> dict:
                return {
                    "category_node_id": default_cat_id,
                    "brand": None,
                    "name_core": "상품",
                    "confidence": 0.95,
                    "reasons": ["mock 자동 분류"],
                }

        ai_provider = _MockProvider()
    else:
        # live AI — 실제 provider 사용 (환경 변수 필요)
        from core.ai_providers import get_default_provider
        ai_provider = get_default_provider()

    ai_router = QueueAiRouter(ai_provider, category_tree, brand_dict, synonyms)
    postcheck_gate = PostcheckGate(
        category_tree=category_tree,
        price_stats_provider=lambda _: [],
        sibling_provider=lambda _: [],
    )

    # ── 작업용 DB 초기화 ─────────────────────────────────────────────────────
    print("\n[3/4] 작업 DB 초기화 + 파이프라인 실행 중...")
    engine = _bootstrap_working_engine("sqlite:///:memory:")
    SessionFactory = sessionmaker(bind=engine)

    with SessionFactory() as session:
        meta = build_snapshot(
            mart_payloads=mart_payloads,
            working_session=session,
            ai_router=ai_router,
            postcheck_gate=postcheck_gate,
            snapshot_path=args.out,
            meta_json_path=args.meta_json,
            run_livepass=run_livepass,
            window_months=args.window_months,
            ai_provider_kind=args.ai,
            write_files=write_files,
        )

    # ── 결과 출력 ─────────────────────────────────────────────────────────────
    print("\n[4/4] 결과 보고")
    _print_meta(meta)

    if not write_files:
        print("\n  [DRY-RUN] 파일이 생성되지 않았습니다. --commit 옵션으로 재실행하세요.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
