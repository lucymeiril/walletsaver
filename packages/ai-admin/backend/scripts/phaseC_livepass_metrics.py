"""WalletSavior Phase C3 — Livepass Metrics CLI.

사용 예:
    py -3 packages\\ai-admin\\backend\\scripts\\phaseC_livepass_metrics.py \\
        --source fixtures \\
        --ai mock \\
        --dry-run \\
        --output-json .\\livepass_dryrun.json

옵션:
    --source fixtures                4사 진본 fixture 사용
    --source operator-capture <dir>  운영자 캡처 폴더 사용
    --dry-run / --commit             DB 반영 여부
    --ai mock / --ai live            AI 제공자 선택 (live는 WALLETSAVIOR_LIVE_AI=1 필요)
    --db-url <url>                   SQLAlchemy DB URL (기본: sqlite:///./ai_control.db)
    --output-json <path>             LivepassReport JSON 파일 경로

출력:
    한국어 콘솔 보고서 + JSON 파일 (--output-json 지정 시)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# ── 경로 보정 ─────────────────────────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _SCRIPT_DIR.parent
_SHARED_DIR = _BACKEND_DIR.parent.parent / "shared"
_DB_ADMIN_BACKEND = _BACKEND_DIR.parent.parent / "db-admin" / "backend"
_FIXTURE_BASE = (
    _BACKEND_DIR.parent.parent
    / "crawler-admin" / "backend" / "tests" / "fixtures"
)

for _p in (str(_SHARED_DIR), str(_BACKEND_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import yaml
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from services.livepass_pipeline import (
    LivepassReport,
    run_livepass,
    seed_categories_from_yaml,
    seed_from_raw_batch,
)
from services.postcheck_gate import PostcheckGate
from services.queue_ai_router import (
    QueueAiRouter,
    load_default_brand_dictionary,
    load_default_category_tree,
    load_default_synonyms,
)

# CanonicalBase와 seed 파서는 importlib로 로드된 db_admin_storage에서 가져온다.
# (ai-admin/backend/storage/ 패키지와의 이름 충돌 우회)
import sys as _sys
_canonical_models_mod = _sys.modules.get("db_admin_storage.canonical_models")
_canonical_seed_mod = _sys.modules.get("db_admin_storage.canonical_seed")

if _canonical_models_mod is None or _canonical_seed_mod is None:
    raise ImportError(
        "db_admin_storage 모듈 로드 실패 — livepass_pipeline import가 먼저 실행되어야 합니다."
    )

CanonicalBase = _canonical_models_mod.CanonicalBase
_parse_emart_raw = _canonical_seed_mod._parse_emart_raw
_parse_homeplus_raw = _canonical_seed_mod._parse_homeplus_raw
_parse_lottemart_raw = _canonical_seed_mod._parse_lottemart_raw
_parse_costco_raw = _canonical_seed_mod._parse_costco_raw


# ══════════════════════════════════════════════════════
# 픽스처 로더
# ══════════════════════════════════════════════════════

def _load_fixtures_mart_payloads(fixture_base: Path) -> dict[str, list[dict]]:
    """4사 fixture 파일을 파싱해 mart_payloads 반환."""
    payloads: dict[str, list[dict]] = {}

    emart_items = _parse_emart_raw(fixture_base)
    if emart_items:
        payloads["emart"] = emart_items

    homeplus_items = _parse_homeplus_raw(fixture_base)
    if homeplus_items:
        payloads["homeplus"] = homeplus_items

    lottemart_items = _parse_lottemart_raw(fixture_base)
    if lottemart_items:
        payloads["lottemart"] = lottemart_items

    costco_items = _parse_costco_raw(fixture_base)
    if costco_items:
        payloads["costco"] = costco_items

    return payloads


def _load_operator_capture_payloads(capture_dir: Path) -> dict[str, list[dict]]:
    """운영자 캡처 폴더에서 마트별 payloads 로드.
    폴더 구조: <dir>/{emart,homeplus,lottemart,costco,coupang}/...
    """
    payloads: dict[str, list[dict]] = {}

    if not capture_dir.exists():
        return payloads

    # 4사 파서 재사용
    emart_items = _parse_emart_raw(capture_dir)
    if emart_items:
        payloads["emart"] = emart_items

    homeplus_items = _parse_homeplus_raw(capture_dir)
    if homeplus_items:
        payloads["homeplus"] = homeplus_items

    lottemart_items = _parse_lottemart_raw(capture_dir)
    if lottemart_items:
        payloads["lottemart"] = lottemart_items

    costco_items = _parse_costco_raw(capture_dir)
    if costco_items:
        payloads["costco"] = costco_items

    # 쿠팡: JSON 파일 직접 파싱 (operator-capture 전용)
    coupang_dir = capture_dir / "coupang"
    if coupang_dir.exists():
        coupang_items: list[dict] = []
        for f in coupang_dir.glob("*.json"):
            try:
                with open(f, encoding="utf-8") as fp:
                    data = json.load(fp)
                if isinstance(data, list):
                    coupang_items.extend(data)
                elif isinstance(data, dict):
                    coupang_items.extend(data.get("items", [data]))
            except Exception:
                pass
        if coupang_items:
            payloads["coupang"] = coupang_items

    return payloads


# ══════════════════════════════════════════════════════
# PostcheckGate 제공자 (DB 기반)
# ══════════════════════════════════════════════════════

def _make_db_price_provider(session):
    """DB에서 카테고리별 sale_price 목록을 제공하는 provider."""
    def provider(category_node_id: str) -> list[int]:
        try:
            rows = session.execute(
                text(
                    "SELECT po.sale_price "
                    "FROM canonical_price_observations po "
                    "JOIN canonical_products cp ON po.canonical_id = cp.id "
                    "WHERE cp.category_path_internal_id = :cat"
                ),
                {"cat": category_node_id},
            ).fetchall()
            return [int(r[0]) for r in rows if r[0] is not None]
        except Exception:
            return []
    return provider


def _make_db_sibling_provider(session):
    """DB에서 sibling canonical product의 category_node_id 목록을 제공하는 provider."""
    def provider(canonical_id: str) -> list[str]:
        try:
            rows = session.execute(
                text(
                    "SELECT cp.category_path_internal_id "
                    "FROM canonical_products cp "
                    "WHERE cp.id != :cid "
                    "AND cp.category_path_internal_id IS NOT NULL "
                    "LIMIT 50"
                ),
                {"cid": canonical_id},
            ).fetchall()
            return [r[0] for r in rows if r[0]]
        except Exception:
            return []
    return provider


# ══════════════════════════════════════════════════════
# 콘솔 보고서 출력
# ══════════════════════════════════════════════════════

def _format_mart_line(mart_key: str, stats: dict) -> str:
    """마트별 통과율 한 줄 포맷."""
    if stats["input"] == 0:
        return f"  {mart_key:<10}: 입력 0 (데이터 없음, 스킵)"

    qi = stats["queue_initial"]
    if qi == 0:
        pct = "N/A (큐 없음)"
        pct_num = ""
    else:
        gate_p = stats["gate_passed"]
        pct_num_val = int(gate_p / qi * 100)
        pct_num = f" ({pct_num_val}%)"
        pct = ""

    line = (
        f"  {mart_key:<10}: 입력 {stats['input']}"
        f" → canonical {stats['canonical_created']}"
        f" → 큐 진입 {qi}"
        f" → AI해결 {stats['ai_resolved']}"
        f" → 게이트통과 {stats['gate_passed']}"
        f" → DB확정 {stats['final_db_rows']}{pct_num}"
    )
    return line


def _print_report(
    report: LivepassReport,
    source_desc: str,
    ai_desc: str,
) -> None:
    """한국어 콘솔 보고서 출력."""
    mode_label = "DRY-RUN" if report.mode == "dry_run" else "COMMIT"
    print()
    print("=" * 60)
    print("      WalletSavior Livepass C3 보고")
    print("=" * 60)
    print(f"입력 소스: {source_desc}")
    print(f"AI 제공자: {ai_desc}")
    print(f"모드: {mode_label}")
    print()
    print("마트별 통과율:")
    for mart_key, stats in sorted(report.by_mart.items()):
        print(_format_mart_line(mart_key, stats))

    if not report.by_mart:
        print("  (데이터 없음)")

    print()
    overall_qi = report.queue_initial
    overall_gp = report.gate_passed
    if overall_qi > 0:
        overall_pct = int(overall_gp / overall_qi * 100)
        print(
            f"전체: 큐 진입 {overall_qi}건 → 게이트통과 {overall_gp}건 ({overall_pct}%)"
        )
    else:
        print("전체: 큐 진입 0건 (분류할 항목 없음)")

    print()
    print("ESCALATE 사유 분포:")
    dist = report.escalation_reasons_distribution
    if dist:
        for reason, cnt in sorted(dist.items()):
            print(f"  {reason:<35}: {cnt}")
    else:
        print("  (없음)")

    elapsed = report.elapsed_ms
    parts = [f"{k} {v}ms" for k, v in elapsed.items()]
    print()
    print("소요시간: " + " / ".join(parts))
    print(f"최종 ReviewQueue 잔여: {report.final_db_pending}건")
    print(f"최종 ReviewQueue 확정: {report.final_db_resolved}건")
    print("=" * 60)
    print()


# ══════════════════════════════════════════════════════
# 메인
# ══════════════════════════════════════════════════════

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="WalletSavior Phase C3 Livepass Metrics CLI"
    )
    parser.add_argument(
        "--source",
        choices=["fixtures", "operator-capture"],
        default="fixtures",
        help="입력 소스 (fixtures 또는 operator-capture)",
    )
    parser.add_argument(
        "--capture-dir",
        type=Path,
        default=None,
        help="--source operator-capture 시 캡처 폴더 경로",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="DB 변경 없이 실행 (기본값)",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        default=False,
        help="DB 변경 확정",
    )
    parser.add_argument(
        "--ai",
        choices=["mock", "live"],
        default="mock",
        help="AI 제공자 (mock 또는 live)",
    )
    parser.add_argument(
        "--db-url",
        default="sqlite:///./ai_control.db",
        help="SQLAlchemy DB URL",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="LivepassReport JSON 출력 경로",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    dry_run = not args.commit

    # ── 입력 소스 결정 ───────────────────────────────────────────────────
    if args.source == "fixtures":
        mart_payloads = _load_fixtures_mart_payloads(_FIXTURE_BASE)
        coupang_count = 0
        source_desc = (
            f"fixtures (4사 fixture 진본, 쿠팡 운영자 캡처 {coupang_count}건)"
        )
    else:
        capture_dir = args.capture_dir or (_FIXTURE_BASE / "coupang")
        mart_payloads = _load_operator_capture_payloads(capture_dir)
        coupang_count = len(mart_payloads.get("coupang", []))
        source_desc = f"operator-capture ({capture_dir}) — 쿠팡 {coupang_count}건 포함"

    if not mart_payloads:
        print("[오류] 로드된 데이터 없음. fixture 경로를 확인하세요.")
        print(f"  fixture_base: {_FIXTURE_BASE}")
        return 1

    # ── AI 제공자 설정 ───────────────────────────────────────────────────
    category_tree = load_default_category_tree()
    brand_dictionary = load_default_brand_dictionary()
    synonyms = load_default_synonyms()

    if args.ai == "live":
        if not os.environ.get("WALLETSAVIOR_LIVE_AI"):
            print("[오류] --ai live 는 WALLETSAVIOR_LIVE_AI=1 환경변수 필요")
            return 1
        try:
            from providers.google_genai import GoogleGenAIProvider
            from config import Settings
            settings = Settings()
            provider = GoogleGenAIProvider(settings)
            ai_desc = f"google-genai/{getattr(provider, '_model', 'gemini-1.5-flash')}"
        except Exception as exc:
            print(f"[오류] live provider 초기화 실패: {exc}")
            return 1
        ai_provider_kind = "live"
    else:
        # Mock provider: 유효한 카테고리 id로 응답
        valid_ids = sorted({n["id"] for n in category_tree.get("nodes", []) if "id" in n})
        default_cat = valid_ids[0] if valid_ids else "unknown"

        class _FixedMockProvider:
            """항상 동일한 유효 카테고리로 응답하는 mock."""
            def call(self, *, prompt: str, schema=None) -> dict:
                return {
                    "category_node_id": default_cat,
                    "brand": None,
                    "name_core": "테스트상품",
                    "confidence": 0.90,
                    "reasons": ["mock 분류"],
                }

        provider = _FixedMockProvider()
        ai_desc = f"mock (고정 카테고리: {default_cat})"
        ai_provider_kind = "mock"

    ai_router = QueueAiRouter(provider, category_tree, brand_dictionary, synonyms)

    # ── DB 설정 ───────────────────────────────────────────────────────────
    engine = create_engine(args.db_url, echo=False)
    # canonical 테이블 bootstrap (없으면 생성)
    try:
        CanonicalBase.metadata.create_all(engine)
        with engine.connect() as conn:
            try:
                conn.execute(
                    text(
                        "ALTER TABLE canonical_product_review_queue "
                        "ADD COLUMN attributes TEXT"
                    )
                )
                conn.commit()
            except Exception:
                pass  # 이미 존재하면 skip
    except Exception as exc:
        print(f"[경고] 테이블 초기화 중 오류: {exc}")

    SessionFactory = sessionmaker(bind=engine)

    with SessionFactory() as session:
        postcheck_gate = PostcheckGate(
            category_tree=category_tree,
            price_stats_provider=_make_db_price_provider(session),
            sibling_provider=_make_db_sibling_provider(session),
        )

        report = run_livepass(
            mart_payloads=mart_payloads,
            session=session,
            ai_router=ai_router,
            postcheck_gate=postcheck_gate,
            dry_run=dry_run,
            ai_provider_kind=ai_provider_kind,
        )

    # ── 출력 ─────────────────────────────────────────────────────────────
    _print_report(report, source_desc, ai_desc)

    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report.as_dict(), f, ensure_ascii=False, indent=2, default=str)
        print(f"JSON 저장: {output_path.resolve()}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
