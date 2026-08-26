#!/usr/bin/env python3
"""주간 diff 실행 CLI — 4사 마트 순환, alert 자동 적재.

사용법:
    py -3 tools/run_weekly_diff.py --mart all --days 7
    py -3 tools/run_weekly_diff.py --mart emart --days 7
    py -3 tools/run_weekly_diff.py --mart emart,homeplus --days 14

DB 계약:
    crawler-admin ``config.DB_ADMIN_DATABASE_URL``의 db-admin working DB는
    ``discount_history`` + ``products`` 비교 입력으로만 읽는다.
    사라진 SKU alert는 crawler-owned ``config.WEEKLY_STATE_DB_PATH`` SQLite에
    따로 적재한다.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_repo_root = Path(__file__).resolve().parent.parent
_crawler_backend = _repo_root / "packages" / "crawler-admin" / "backend"
_shared = _repo_root / "packages" / "shared"

for _p in (_crawler_backend, _shared):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("run_weekly_diff")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.weekly_diff import compute_weekly_diff, create_weekly_alert_engine, persist_alerts

ALL_MARTS = ["emart", "homeplus", "lottemart", "costco"]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="주간 SKU diff 실행 + alert 적재")
    parser.add_argument(
        "--mart",
        default="all",
        help="마트 이름 or 'all'. 콤마 구분 복수 가능. 예: emart,homeplus",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="current window 기간(일). default=7",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="diff 계산만 하고 alert 적재 생략",
    )
    return parser.parse_args()


def _build_history_session_factory(db_url: str):
    engine = create_engine(
        db_url,
        connect_args={"check_same_thread": False} if "sqlite" in db_url else {},
    )
    return sessionmaker(bind=engine, autoflush=False, autocommit=False), engine


def _build_alert_session_factory(db_path: Path):
    engine = create_weekly_alert_engine(db_path)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False), engine


def main() -> None:
    args = _parse_args()
    db_url = config.DB_ADMIN_DATABASE_URL
    if not db_url:
        logger.error("DB_ADMIN_DATABASE_URL이 설정되지 않았습니다.")
        sys.exit(1)

    if args.mart.lower() == "all":
        marts = ALL_MARTS
    else:
        marts = [m.strip() for m in args.mart.split(",") if m.strip()]

    invalid = sorted(set(marts) - set(ALL_MARTS))
    if invalid:
        logger.error("지원하지 않는 mart: %s", ", ".join(invalid))
        sys.exit(2)

    until = datetime.now(timezone.utc).replace(tzinfo=None)
    since = until - timedelta(days=args.days)
    HistorySessionFactory, history_engine = _build_history_session_factory(db_url)
    AlertSessionFactory, alert_engine = _build_alert_session_factory(config.WEEKLY_STATE_DB_PATH)

    total_disappeared = 0
    total_new = 0
    total_alerts_inserted = 0

    for mart in marts:
        logger.info("▶ mart=%s window=[%s, %s)", mart, since.isoformat(), until.isoformat())
        history_session = HistorySessionFactory()
        try:
            report = compute_weekly_diff(
                history_session,
                mart=mart,
                since=since,
                until=until,
            )
            logger.info(
                "  사라짐=%d 신규=%d 유지=%d 가격변동=%d",
                len(report.disappeared),
                len(report.new_skus),
                report.retained_count,
                len(report.price_changes),
            )
            total_disappeared += len(report.disappeared)
            total_new += len(report.new_skus)
        except Exception:
            logger.exception("  ✗ mart=%s diff 실패", mart)
            continue
        finally:
            history_session.close()

        if args.dry_run:
            logger.info("  [dry-run] alert 적재 생략")
            continue

        alert_session = AlertSessionFactory()
        try:
            inserted = persist_alerts(alert_session, report)
            alert_session.commit()
            total_alerts_inserted += inserted
            if inserted:
                logger.info("  alert 적재: %d건", inserted)
        except Exception:
            alert_session.rollback()
            logger.exception("  ✗ mart=%s alert 적재 실패", mart)
        finally:
            alert_session.close()

    logger.info(
        "완료 — 사라짐 누계=%d 신규 누계=%d alert 삽입=%d",
        total_disappeared,
        total_new,
        total_alerts_inserted,
    )
    history_engine.dispose()
    alert_engine.dispose()


if __name__ == "__main__":
    main()
