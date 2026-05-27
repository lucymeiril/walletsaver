r"""Round R G3 auto-classify runner.

Examples:
    py -3 -m scripts.g3_auto_classify_run --jsonl crawler-output.jsonl --dry-run
    py -3 -m scripts.g3_auto_classify_run --staging-table crawler_staging_products --commit
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from sqlalchemy import text

from services.auto_classify import auto_classify_products
from services.base import get_session

_TABLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            text_line = line.strip()
            if not text_line:
                continue
            try:
                rows.append(json.loads(text_line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"JSONL {line_no}행 파싱 실패: {exc}") from exc
    return rows


def load_staging_table(table_name: str, limit: int | None = None) -> list[dict[str, Any]]:
    if not _TABLE_RE.match(table_name):
        raise ValueError("staging table 이름은 영문/숫자/밑줄만 허용합니다.")
    session = get_session()
    try:
        sql = f"SELECT * FROM {table_name}"
        if limit is not None:
            sql += " LIMIT :limit"
            result = session.execute(text(sql), {"limit": limit})
        else:
            result = session.execute(text(sql))
        return [dict(row._mapping) for row in result]
    finally:
        session.close()


def run(rows: list[dict[str, Any]], *, dry_run: bool) -> dict[str, Any]:
    session = get_session()
    try:
        return auto_classify_products(session, rows, dry_run=dry_run).as_dict()
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Round R G3 crawler product auto classification")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--jsonl", type=Path, help="크롤러 산출 JSONL 경로")
    source.add_argument("--staging-table", help="DB staging 테이블 이름")
    parser.add_argument("--limit", type=int, default=None, help="staging table 읽기 제한")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="DB 변경 없이 결과만 계산 (기본값)")
    mode.add_argument("--commit", action="store_true", help="DB에 반영")
    args = parser.parse_args()

    rows = load_jsonl(args.jsonl) if args.jsonl else load_staging_table(args.staging_table, args.limit)
    summary = run(rows, dry_run=not args.commit)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
