"""
WalletSavior Phase B6 — canonical 시드 CLI 스크립트.

사용법:
    py -3 packages\\db-admin\\backend\\scripts\\seed_canonical_from_fixtures.py --dry-run
    py -3 packages\\db-admin\\backend\\scripts\\seed_canonical_from_fixtures.py --commit --db-url sqlite:///./walletsavior_canonical.db

기본값: --dry-run (실제 DB 변경 없음, 결과만 출력)

출력:
    마트별 시도/성공/실패 카운트 + 마지막 SeedResult 한 줄 요약.
    컬러 코드/이모지 없음 (Windows cmd 호환).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# ── 경로 보정 ──────────────────────────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _SCRIPT_DIR.parent
_SHARED_DIR = _BACKEND_DIR.parent.parent / "shared"

for _p in (str(_BACKEND_DIR), str(_SHARED_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from storage.canonical_models import bootstrap_canonical_tables
from storage.canonical_seed import (
    SeedResult,
    seed_categories_from_yaml,
    seed_canonicals_from_fixture_dir,
    _parse_emart_raw,
    _parse_homeplus_raw,
    _parse_lottemart_raw,
    _parse_costco_raw,
    seed_from_raw_batch,
)

# 기본 fixture 디렉터리
_DEFAULT_FIXTURE_DIR = (
    _BACKEND_DIR.parent.parent
    / "crawler-admin" / "backend" / "tests" / "fixtures"
)

_DEFAULT_DB_URL = "sqlite:///:memory:"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="WalletSavior canonical DB 시드 스크립트 (Phase B6)"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="flush 까지만 실행, commit 안 함 (기본값)",
    )
    mode.add_argument(
        "--commit",
        action="store_true",
        default=False,
        help="실제 DB에 commit",
    )
    parser.add_argument(
        "--db-url",
        default=_DEFAULT_DB_URL,
        help=f"SQLAlchemy DB URL (기본: {_DEFAULT_DB_URL})",
    )
    parser.add_argument(
        "--fixture-dir",
        default=str(_DEFAULT_FIXTURE_DIR),
        help=f"fixture 루트 디렉터리 (기본: {_DEFAULT_FIXTURE_DIR})",
    )
    return parser.parse_args()


def _print_mart_stats(
    mart: str,
    items: list,
    seed_result_before: SeedResult,
    seed_result_after: SeedResult,
) -> None:
    """마트별 시도/성공/실패 출력."""
    attempted = len(items)
    # canonical 증가분 (inserted + updated)
    canonical_delta = (
        (seed_result_after.canonical_inserted - seed_result_before.canonical_inserted)
        + (seed_result_after.canonical_updated - seed_result_before.canonical_updated)
    )
    errors_delta = len(seed_result_after.errors) - len(seed_result_before.errors)
    print(
        f"  {mart:10s}: 시도={attempted:3d}  canonical={canonical_delta:3d}  오류={errors_delta}"
    )


def main() -> int:
    args = _parse_args()
    dry_run = not args.commit  # --commit 이면 dry_run=False

    fixture_dir = Path(args.fixture_dir)
    if not fixture_dir.exists():
        print(f"[ERROR] fixture 디렉터리를 찾을 수 없음: {fixture_dir}")
        return 1

    db_url = args.db_url
    print(f"DB URL  : {db_url}")
    print(f"Fixture : {fixture_dir}")
    print(f"Mode    : {'DRY-RUN (commit 안 함)' if dry_run else 'COMMIT (실제 DB 변경)'}")
    print("-" * 60)

    # DB 초기화
    engine = create_engine(db_url, echo=False)
    bootstrap_canonical_tables(engine)
    SessionFactory = sessionmaker(bind=engine)
    observed_at = datetime.now()

    with SessionFactory() as session:
        # 1. 카테고리 시드
        print("[1/2] 카테고리 트리 시드 중...")
        cat_count = seed_categories_from_yaml(session)
        if not dry_run:
            session.commit()
        print(f"      CategoryNode {cat_count}개 완료")

    # 2. fixture 파싱
    print("[2/2] 4사 fixture 파싱 및 canonical 시드 중...")
    mart_raw: dict[str, list[dict]] = {}
    for mart_key, parse_fn in [
        ("emart", _parse_emart_raw),
        ("homeplus", _parse_homeplus_raw),
        ("lottemart", _parse_lottemart_raw),
        ("costco", _parse_costco_raw),
    ]:
        items = parse_fn(fixture_dir)
        if items:
            mart_raw[mart_key] = items
            print(f"      {mart_key}: {len(items)}건 파싱됨")
        else:
            print(f"      {mart_key}: fixture 없음 (skip)")

    if not mart_raw:
        print("[WARNING] 처리할 fixture가 없습니다.")
        return 0

    # 3. 마트별 시드 실행 (진행 출력을 위해 마트별로 분리)
    print()
    print("마트별 시드 결과:")

    # 마트별로 SeedResult 델타를 추적하기 위해 누적 방식으로 실행
    with SessionFactory() as session:
        # 카테고리는 이미 있거나 in-memory라면 다시 시드
        if db_url == _DEFAULT_DB_URL:
            seed_categories_from_yaml(session)

        # 전체 배치 실행
        final_result = seed_from_raw_batch(
            mart_raw, session, dry_run=dry_run, observed_at=observed_at
        )

    # 마트별 출력 (합산만 가능 — 배치 전체로 실행했으므로 개수만 표시)
    for mart_key, items in mart_raw.items():
        print(f"  {mart_key:10s}: {len(items)}건 처리됨")

    print()
    print("=" * 60)
    print("SeedResult 요약:")
    print(f"  canonical 신규 삽입  : {final_result.canonical_inserted}")
    print(f"  canonical 갱신       : {final_result.canonical_updated}")
    print(f"  sku_alias 삽입       : {final_result.sku_alias_inserted}")
    print(f"  price_obs 삽입       : {final_result.price_obs_inserted}")
    print(f"  review_queue 삽입    : {final_result.review_queue_inserted}")
    print(f"  category_nodes_present: {final_result.category_nodes_present}")
    print(f"  오류                 : {len(final_result.errors)}")
    print(f"  모드                 : {'DRY-RUN' if final_result.dry_run else 'COMMITTED'}")
    print("=" * 60)
    print(final_result.summary_line())

    if final_result.errors:
        print()
        print("오류 상세:")
        for err in final_result.errors:
            print(f"  mart={err.get('mart')} hash={err.get('raw_payload_hash', '')[:12]}... reason={err.get('reason')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
