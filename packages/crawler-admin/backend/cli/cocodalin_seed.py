"""CLI for importing Cocodalin Costco seed data into price_history."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import config
from services.cocodalin_seed_importer import import_cocodalin_seed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import Cocodalin Costco seed price history")
    parser.add_argument("--source", type=Path, default=None, help="JSON/CSV Cocodalin export path. Omit to crawl live.")
    parser.add_argument("--dry-run", action="store_true", help="Compute counts without writing price_history rows.")
    parser.add_argument("--database-url", default=config.DB_ADMIN_DATABASE_URL, help="SQLAlchemy database URL.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    connect_args = {"check_same_thread": False} if args.database_url.startswith("sqlite") else {}
    engine = create_engine(args.database_url, connect_args=connect_args)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with SessionLocal() as session:
        report = import_cocodalin_seed(session, source_path=args.source, dry_run=args.dry_run)
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
