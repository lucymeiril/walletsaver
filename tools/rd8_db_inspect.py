"""RD8 실데이터 관찰용 일회성 진단.

S1/S2 단계에서 사용. 현재 DB의 raw_crawl_records / products / matching_entries
상태를 빠르게 까보고 마트별 source 누락, 중복, 타이틀/brand 합성 등 어떤 결함이
지금 박혀있는지 한 번에 출력한다. 수정은 하지 않는다.
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CRAWLER_DB = REPO / "packages" / "crawler-admin" / "backend" / "orchestrator.db"
DB_ADMIN_DB = REPO / "packages" / "db-admin" / "backend" / "walletguardian.db"
AI_DB = REPO / "packages" / "ai-admin" / "backend" / "ai_control.db"


def list_tables(db: Path) -> list[str]:
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    rows = [r[0] for r in cur.fetchall()]
    conn.close()
    return rows


def head(db: Path, table: str, n: int = 3) -> list[dict]:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT * FROM {table} LIMIT {n}")
        rows = [dict(r) for r in cur.fetchall()]
    except sqlite3.OperationalError as e:
        rows = [{"_error": str(e)}]
    conn.close()
    return rows


def count(db: Path, table: str) -> int:
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        n = cur.fetchone()[0]
    except sqlite3.OperationalError:
        n = -1
    conn.close()
    return n


def source_distribution(db: Path) -> Counter:
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    try:
        cur.execute("SELECT source_name, COUNT(*) FROM raw_crawl_records GROUP BY source_name")
        rows = dict(cur.fetchall())
    except sqlite3.OperationalError:
        rows = {}
    conn.close()
    return Counter(rows)


def main() -> None:
    for label, db in [("crawler", CRAWLER_DB), ("db-admin", DB_ADMIN_DB), ("ai", AI_DB)]:
        print(f"\n=== {label} :: {db}")
        if not db.exists():
            print("(missing)")
            continue
        tables = list_tables(db)
        print("tables:", tables)
        for t in tables:
            n = count(db, t)
            if n > 0:
                print(f"  - {t}: {n}")
    print("\n--- crawler raw_crawl_records source distribution ---")
    print(dict(source_distribution(CRAWLER_DB)))
    print(dict(source_distribution(AI_DB)))
    print("\n--- db-admin products head ---")
    for row in head(DB_ADMIN_DB, "products", 3):
        print(json.dumps(row, ensure_ascii=False, default=str)[:400])
    print("\n--- db-admin matching_entries head ---")
    for row in head(DB_ADMIN_DB, "matching_entries", 3):
        print(json.dumps(row, ensure_ascii=False, default=str)[:400])
    print("\n--- crawler raw_crawl_records head ---")
    for row in head(CRAWLER_DB, "raw_crawl_records", 3):
        print(json.dumps(row, ensure_ascii=False, default=str)[:500])
    print("\n--- ai raw_crawl_records head ---")
    for row in head(AI_DB, "raw_crawl_records", 3):
        print(json.dumps(row, ensure_ascii=False, default=str)[:500])


if __name__ == "__main__":
    main()
