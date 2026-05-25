#!/usr/bin/env python3
"""주간 diff 실행 CLI — 4사 마트 순환, alert 자동 적재.

사용법:
    py -3 tools/run_weekly_diff.py --mart all --days 7
    py -3 tools/run_weekly_diff.py --mart emart --days 7
    py -3 tools/run_weekly_diff.py --mart emart,homeplus --days 14

환경변수:
    DATABASE_URL  (필수)  — raw_crawl_records + alert_disappeared_skus 가 있는 DB URL
    WEEKLY_DIFF_DB_URL    — alert DB가 별도일 경우 이 값을 우선 사용 (선택)

멱등성:
    이미 open 상태인 동일 mart+key alert는 중복 삽입하지 않는다.
    같은 인자로 재실행해도 안전.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── sys.path 설정 ──────────────────────────────────────────────────────────
_repo_root = Path(__file__).resolve().parent.parent
_crawler_backend = _repo_root / "packages" / "crawler-admin" / "backend"
_shared = _repo_root / "packages" / "shared"

for _p in (_crawler_backend, _shared):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# .env 로드
try:
    import config  # noqa: F401 — load_dotenv 수행
except ImportError:
    pass

# ── 로깅 ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("run_weekly_diff")

# ── import ─────────────────────────────────────────────────────────────────
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.weekly_diff import (
    AlertSkuBase,
    compute_weekly_diff,
    persist_alerts,
)

# ── 마트 목록 ──────────────────────────────────────────────────────────────
ALL_MARTS = ["emart", "homeplus", "lottemart", "costco"]


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="주간 SKU diff 실행 + alert 적재")
    p.add_argument(
        "--mart",
        default="all",
        help="마트 이름 or 'all'. 콤마 구분 복수 가능. 예: emart,homeplus",
    )
    p.add_argument(
        "--days",
        type=int,
        default=7,
        help="current window 기간(일). default=7",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="diff 계산만 하고 alert 적재 생략",
    )
    return p.parse_args()


def _build_session_factory(db_url: str):
    engine = create_engine(
        db_url,
        connect_args={"check_same_thread": False} if "sqlite" in db_url else {},
    )
    # 테이블이 없으면 생성 (SQLite 개발 환경 대비)
    AlertSkuBase.metadata.create_all(engine, checkfirst=True)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False), engine


def main() -> None:
    args = _parse_args()

    db_url = os.getenv("WEEKLY_DIFF_DB_URL") or os.getenv("DATABASE_URL", "")
    if not db_url:
        logger.error("DATABASE_URL 환경변수가 설정되지 않았습니다.")
        sys.exit(1)

    # 마트 목록 결정
    if args.mart.lower() == "all":
        marts = ALL_MARTS
    else:
        marts = [m.strip() for m in args.mart.split(",") if m.strip()]

    until = datetime.now(timezone.utc).replace(tzinfo=None)
    since = until - timedelta(days=args.days)

    SessionFactory, engine = _build_session_factory(db_url)

    total_disappeared = 0
    total_new = 0
    total_alerts_inserted = 0

    for mart in marts:
        logger.info("▶ mart=%s  window=[%s, %s)", mart, since.isoformat(), until.isoformat())
        session = SessionFactory()
        try:
            report = compute_weekly_diff(session, mart=mart, since=since, until=until)

            logger.info(
                "  사라짐=%d  신규=%d  유지=%d  가격변동=%d",
                len(report.disappeared),
                len(report.new_skus),
                report.retained_count,
                len(report.price_changes),
            )

            total_disappeared += len(report.disappeared)
            total_new += len(report.new_skus)

            if not args.dry_run:
                inserted = persist_alerts(session, report)
                session.commit()
                total_alerts_inserted += inserted
                if inserted:
                    logger.info("  alert 적재: %d건", inserted)
            else:
                logger.info("  [dry-run] alert 적재 생략")

        except Exception:
            session.rollback()
            logger.exception("  ✗ mart=%s diff 실패", mart)
        finally:
            session.close()

    logger.info(
        "완료 — 사라짐 누계=%d  신규 누계=%d  alert 삽입=%d",
        total_disappeared,
        total_new,
        total_alerts_inserted,
    )

    engine.dispose()


if __name__ == "__main__":
    main()
