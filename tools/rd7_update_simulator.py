"""RD7: 갱신 데이터 시뮬레이터.

이미 DB가 800건으로 구축된 상태에서 '다음 주 갱신'을 모사한다:
  - 기존 match_key 중 70% 재등장(가격 ±15% 변동, 할인 토글)
  - 기존 match_key 중 30%는 미등장(품절/단종 시뮬레이션)
  - 신상품 5건 추가 (새 match_key, AI 분류 필요)

raw_products.jsonl 형태로 fixture를 만들어 raw_crawl_records에 직접 적재.
이후 crawler-admin /api/export/raw-batch 를 호출하면, 매칭 테이블에 이미 등록된
70% 재등장 상품은 miss에서 제외되어야 한다(즉 export miss = 신상품 5건만).

CLI:
  py -3 tools/rd7_update_simulator.py --check
"""
from __future__ import annotations
import argparse
import json
import random
import sqlite3
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB_DB = REPO / "packages/db-admin/backend/walletguardian.db"
AI_DB = REPO / "packages/ai-admin/backend/ai_control.db"
CR_API = "http://127.0.0.1:8001"
CR_KEY = "walletsavior-dev-crawler-key-2025"


def fetch_existing_matches() -> list[dict]:
    with sqlite3.connect(DB_DB) as conn:
        rows = conn.execute(
            "SELECT match_key, brand, name_core, pack_qty, pack_unit, category_id FROM matching_entries"
        ).fetchall()
    return [
        {"match_key": r[0], "brand": r[1], "name_core": r[2],
         "pack_qty": r[3], "pack_unit": r[4], "category_id": r[5]}
        for r in rows
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="검증만 실행")
    args = ap.parse_args()

    random.seed(20260525)
    matches = fetch_existing_matches()
    if not matches:
        print("ERROR: matching_entries 비어있음. 먼저 800건 라운드 진행 필요.", file=sys.stderr)
        return 1
    print(f"기존 matching_entries: {len(matches)}건")

    # 70% 재등장
    n_reappear = max(1, int(len(matches) * 0.7))
    reappear = random.sample(matches, n_reappear)
    print(f"재등장(가격 변동): {len(reappear)}")

    # 신상품 5건 합성
    novel = [
        {"brand": "오리온", "name": "오감자 80g", "category_hint": "snack.chip"},
        {"brand": "롯데웰푸드", "name": "꼬깔콘 콘스프맛 144g", "category_hint": "snack.chip"},
        {"brand": "남양", "name": "맛있는두유GT 200ml", "category_hint": "beverage"},
        {"brand": "CJ", "name": "비비고 김치만두 350g", "category_hint": "processed"},
        {"brand": "동원", "name": "양반 오징어채볶음 80g", "category_hint": "seafood"},
    ]
    print(f"신상품: {len(novel)}")

    # raw_crawl_records로 적재 (마트 emart로)
    now = datetime.now(timezone.utc).isoformat()
    rows: list[tuple] = []
    rid_seq = 0
    batch_id = f"rd7-update-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

    for m in reappear:
        rid_seq += 1
        price = random.randint(1500, 9000)
        name = f"{m['brand']} {m['name_core']}".strip()
        if random.random() < 0.4:
            name = "[행사] " + name
        payload = {
            "name": name,
            "brand": m["brand"],
            "pack_qty": m["pack_qty"],
            "pack_unit": m["pack_unit"],
            "price": price,
        }
        rows.append((
            f"{batch_id}-{rid_seq:04d}", batch_id, "emart", name, price,
            json.dumps(payload, ensure_ascii=False), now, now,
        ))

    for n in novel:
        rid_seq += 1
        price = random.randint(1500, 9000)
        payload = {"name": n["name"], "brand": n["brand"], "price": price}
        rows.append((
            f"{batch_id}-{rid_seq:04d}", batch_id, "emart", n["name"], price,
            json.dumps(payload, ensure_ascii=False), now, now,
        ))

    if args.check:
        print(f"[check] would-insert {len(rows)} rows into ai.raw_crawl_records")
        return 0

    with sqlite3.connect(AI_DB) as conn:
        cur = conn.cursor()
        cols = [c[1] for c in cur.execute("PRAGMA table_info(raw_crawl_records)").fetchall()]
        print(f"raw_crawl_records columns: {cols}")
        # 동적 insert: id, batch_id, source, product_name(or display_name), price, payload, ...
        # 실제 컬럼명은 환경별 차이 — 안전하게 fallback
        sql = (
            "INSERT INTO raw_crawl_records "
            "(raw_record_id, batch_id, source_name, source_record_key, raw_title, raw_price, raw_payload, crawled_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
        )
        cur.executemany(sql, [
            (r[0], r[1], r[2], r[0], r[3], r[4], r[5], r[6]) for r in rows
        ])
        conn.commit()
    print(f"적재 완료: {len(rows)}건 (batch={batch_id})")
    print("다음 단계: crawler-admin /api/export/raw-batch 호출 → miss_rows가 신상품 5건만 나와야 함")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
