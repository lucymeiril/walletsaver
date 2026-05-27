"""RD8 S2: 결함 카탈로그 1회 진단.

products 중복, source 평탄화, brand 누락, title 중복어, 단위 환산 이상 등을
한 번에 출력. docs/RD8/real_data_gap_catalog.md 작성 전 1차 사실 수집용.
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB_ADMIN_DB = REPO / "packages" / "db-admin" / "backend" / "walletguardian.db"
AI_DB = REPO / "packages" / "ai-admin" / "backend" / "ai_control.db"


def q(db: Path, sql: str, params: tuple = ()) -> list[dict]:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def main() -> None:
    print("# RD8 결함 카탈로그 (1차)")
    print()

    print("## 1. products.source_type 분포 (현 스키마)")
    for r in q(DB_ADMIN_DB, "SELECT source_type, COUNT(*) c FROM products GROUP BY source_type"):
        print(f"- {r['source_type']}: {r['c']}")
    print("→ 마트별 분리가 안 됨. products 테이블에 mart code 컬럼 부재.")
    print()

    print("## 2. products name 중복 Top 10")
    dups = q(
        DB_ADMIN_DB,
        "SELECT name, COUNT(*) c FROM products GROUP BY name HAVING c>1 ORDER BY c DESC LIMIT 10",
    )
    for r in dups:
        print(f"- {r['name']}: {r['c']}건")
    total_dup_rows = sum(r["c"] for r in q(DB_ADMIN_DB, "SELECT name, COUNT(*) c FROM products GROUP BY name HAVING c>1"))
    distinct_names = q(DB_ADMIN_DB, "SELECT COUNT(DISTINCT name) c FROM products")[0]["c"]
    total = q(DB_ADMIN_DB, "SELECT COUNT(*) c FROM products")[0]["c"]
    print(f"→ products total={total}, distinct names={distinct_names}, dup_rows(name>1)={total_dup_rows}")
    print()

    print("## 3. 같은 name이 같은 mart 안에서도 중복?")
    print("→ products.source_type가 mart_crawl 단일이라 mart 분리 불가. raw에서 확인:")
    by_raw = q(
        AI_DB,
        """
        SELECT source_name, raw_title, COUNT(*) c
        FROM raw_crawl_records
        GROUP BY source_name, raw_title
        HAVING c>1 ORDER BY c DESC LIMIT 10
        """,
    )
    for r in by_raw:
        print(f"- {r['source_name']} :: {r['raw_title']}: {r['c']}건")
    print()

    print("## 4. brand 결측 / 합성 타이틀 중복어 케이스")
    no_brand = q(
        AI_DB,
        "SELECT source_name, raw_title FROM raw_crawl_records WHERE raw_title NOT LIKE '%[%' LIMIT 20",
    )
    redundant = []
    for r in no_brand:
        words = r["raw_title"].split()
        if len(words) >= 2 and words[0] == words[1]:
            redundant.append(r)
    print(f"- title 첫 단어 반복(예: 코카콜라 코카콜라) 후보: {len(redundant)}건")
    for r in redundant[:5]:
        print(f"  - {r['source_name']}: {r['raw_title']}")
    print()

    print("## 5. matching_entries 적재 카운트 vs products")
    print(f"- matching_entries: {q(DB_ADMIN_DB, 'SELECT COUNT(*) c FROM matching_entries')[0]['c']}")
    print(f"- products: {total}")
    print("→ matching 21 vs products 800. raw 800건이 matching_entries 21건에 의존해 들어간 게 아니라 직접 매칭 없이 들어간 구조.")
    print()

    print("## 6. 단위 분포 (products.unit)")
    for r in q(DB_ADMIN_DB, "SELECT unit, COUNT(*) c FROM products GROUP BY unit ORDER BY c DESC"):
        print(f"- '{r['unit']}': {r['c']}")
    print()

    print("## 7. raw_payload 키 분포 (마트별 첫 50건)")
    for mart in ("emart", "homeplus", "lottemart", "costco"):
        rows = q(AI_DB, "SELECT raw_payload FROM raw_crawl_records WHERE source_name=? LIMIT 50", (mart,))
        key_counter: Counter = Counter()
        for r in rows:
            try:
                d = json.loads(r["raw_payload"]) if isinstance(r["raw_payload"], str) else r["raw_payload"]
            except Exception:
                continue
            if isinstance(d, dict):
                for k in d.keys():
                    key_counter[k] += 1
                if "attributes" in d and isinstance(d["attributes"], dict):
                    for k in d["attributes"].keys():
                        key_counter[f"attributes.{k}"] += 1
        print(f"- {mart}: {dict(key_counter)}")
    print()

    print("## 8. products.attributes / image_url / description 채움 비율")
    for col in ("attributes", "image_url", "description"):
        n = q(DB_ADMIN_DB, f"SELECT COUNT(*) c FROM products WHERE {col} IS NOT NULL AND {col}!=''")[0]["c"]
        print(f"- {col}: {n}/{total}")
    print()

    print("## 9. baseline_prices 마트별 분포 (가격 비교 가능성)")
    try:
        for r in q(
            DB_ADMIN_DB,
            "SELECT mart_code, COUNT(*) c FROM baseline_prices GROUP BY mart_code ORDER BY c DESC",
        ):
            print(f"- {r['mart_code']}: {r['c']}")
    except Exception as e:
        print(f"(error: {e})")
    print()

    print("## 10. 한 product 당 평균 baseline_prices 수 (=마트 비교 가능 product 비율)")
    try:
        row = q(
            DB_ADMIN_DB,
            """
            SELECT AVG(c) avg_c, MIN(c) min_c, MAX(c) max_c, SUM(CASE WHEN c>=2 THEN 1 ELSE 0 END) compare_ok
            FROM (SELECT product_id, COUNT(*) c FROM baseline_prices GROUP BY product_id)
            """,
        )[0]
        print(f"- avg={row['avg_c']:.2f}, min={row['min_c']}, max={row['max_c']}, products_with_>=2_marts={row['compare_ok']}")
    except Exception as e:
        print(f"(error: {e})")


if __name__ == "__main__":
    main()
