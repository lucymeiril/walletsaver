#!/usr/bin/env python3
"""tools/rd8_products_ingest.py

RD8 최종 단계: 라이브 크롤 raw → products + baseline_prices DB 적재.

사용:
    py tools/rd8_products_ingest.py

동작:
    1. baseline_prices / products 테이블 비우기 (잔여 테스트 데이터 제거)
    2. l2 matching_updates_final.jsonl → 이름 기반 인덱스 구축
    3. 각 마트의 raw jsonl → match_key 매핑 → apply_products 호출
    4. 매칭 실패 행 → artifacts/rd8/products_unmatched.jsonl 저장
    5. 검증 SQL 실행 및 결과 출력
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "packages" / "db-admin" / "backend"))

DB_PATH = REPO / "packages" / "db-admin" / "backend" / "walletguardian.db"
RAW_DIR = REPO / "artifacts" / "exports" / "raw-batch" / "rd8-live-20260526"
L2_DIR = REPO / "artifacts" / "rd8" / "l2_classified"
OUT_DIR = REPO / "artifacts" / "rd8"

MARTS = ["costco", "homeplus", "lottemart"]


def norm(s: str) -> str:
    """이름 정규화: 양쪽 공백 제거, 내부 연속 공백→단일 공백."""
    return re.sub(r'\s+', ' ', (s or "").strip())


def clean_candidates(raw_name: str) -> list[str]:
    """raw 상품명에서 정제된 후보 이름 목록 생성.

    1) 원본
    2) 괄호 접두사 제거: (행사), (행사상품), (1+1) 등
    3) 대괄호 접두사 제거: [브랜드], [25년산 햅쌀] 등
    4) 알파뉴머릭 SEO 코드 제거: VN13JP93, YF22ZI60 등
    """
    candidates = []
    n = norm(raw_name)
    candidates.append(n)

    # 괄호 접두사 제거: (xxx) at start
    c = re.sub(r'^\([^\)]+\)\s*', '', n).strip()
    if c and c != n:
        candidates.append(norm(c))

    # 대괄호 접두사 제거: [xxx] at start
    c = re.sub(r'^\[[^\]]+\]\s*', '', n).strip()
    if c and c != n:
        candidates.append(norm(c))

    # 행사/한정/이벤트 괄호 어디서나 제거
    c = re.sub(r'\s*\([행사한정이벤트]+[^\)]*\)\s*', ' ', n).strip()
    c = norm(c)
    if c and c != n:
        candidates.append(c)

    # 알파뉴머릭 SEO 코드 제거 (XX99XX99 형식)
    c = re.sub(r'\b[A-Z]{2}\d{2}[A-Z]{2}\d{2}\b', '', n).strip()
    c = norm(c)
    if c and c != n:
        candidates.append(c)

    # 8자+ 대문자/숫자 코드 제거
    c = re.sub(r'\b[A-Z0-9]{8,}\b', '', n).strip()
    c = norm(c)
    if c and c != n:
        candidates.append(c)

    return [x for x in dict.fromkeys(candidates) if len(x) > 3]


def load_l2_indexes(mart: str) -> tuple[dict, dict, dict]:
    """l2 matching_updates_final.jsonl → 3종 인덱스 반환.

    모든 키는 소문자 정규화. 매칭 시 .lower() 비교 사용.
    Returns:
        alias_idx   : norm(alias).lower()                   → l2_row
        brand_name  : norm(brand + ' ' + name_core).lower() → l2_row
        name_core   : norm(name_core).lower()               → l2_row
    """
    path = L2_DIR / mart / "matching_updates_final.jsonl"
    alias_idx: dict[str, dict] = {}
    brand_name_idx: dict[str, dict] = {}
    name_core_idx: dict[str, dict] = {}

    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            mk = row.get("match_key", "")
            if not mk:
                continue
            brand = (row.get("brand") or "").strip()
            name_core = (row.get("name_core") or "").strip()

            # 1) aliases 인덱스 (aliases 필드에 원본 raw 상품명 저장됨)
            for alias in (row.get("aliases") or []):
                k = norm(alias).lower()
                if k and k not in alias_idx:
                    alias_idx[k] = row

            # 2) brand + " " + name_core 인덱스 (홈플러스: raw_name = brand+" "+name_core)
            if brand and name_core:
                k = norm(brand + " " + name_core).lower()
                if k and k not in brand_name_idx:
                    brand_name_idx[k] = row

            # 3) name_core 단독 인덱스 (롯데마트: raw_name ≈ name_core)
            if name_core:
                k = norm(name_core).lower()
                if k and k not in name_core_idx:
                    name_core_idx[k] = row

    return alias_idx, brand_name_idx, name_core_idx


def build_db_fallback_index(db_path: Path) -> dict[str, str]:
    """matching_entries DB에서 이름→match_key 폴백 인덱스 구축.

    name_core (leading ')' 제거 포함) 와 brand+name_core 모두 인덱싱.
    모든 키는 소문자 정규화.
    Returns: {normalized_name_lower: match_key}
    """
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        "SELECT match_key, brand, name_core FROM matching_entries"
    ).fetchall()
    conn.close()

    idx: dict[str, str] = {}
    for mk, brand, name_core in rows:
        nc = norm(name_core or "")
        br = norm(brand or "")
        # name_core 그대로 (소문자)
        if nc:
            for key in [nc.lower(), nc.lstrip(")").strip().lower()]:
                if key and key not in idx:
                    idx[key] = mk
        # brand + " " + name_core (소문자)
        if br and nc:
            k = norm(br + " " + nc).lower()
            if k and k not in idx:
                idx[k] = mk
    return idx


def match_raw(raw_name: str,
              alias_idx: dict,
              brand_name_idx: dict,
              name_core_idx: dict,
              db_fallback: dict | None = None) -> tuple[str | None, str]:
    """raw 상품명으로 match_key 찾기.

    우선순위:
    1. 원본 alias → match_key (l2)
    2. 원본 brand+name_core → match_key (l2)
    3. 원본 name_core → match_key (l2)
    4. 정제된 후보들로 위 1-3 재시도
    5. DB 폴백 인덱스 (match_key 직접)

    Returns: (match_key | None, method_str)
    """
    candidates = clean_candidates(raw_name)

    # 1-3: l2 인덱스에서 찾기 (각 정제 후보에 대해)
    for cand in candidates:
        k = cand.lower()
        if k in alias_idx:
            return alias_idx[k]["match_key"], "alias"
        if k in brand_name_idx:
            return brand_name_idx[k]["match_key"], "brand_name"
        if k in name_core_idx:
            return name_core_idx[k]["match_key"], "name_core"

    # 4: DB 폴백 인덱스 (name_core 직접 매칭)
    if db_fallback is not None:
        for cand in candidates:
            k = cand.lower()
            if k in db_fallback:
                return db_fallback[k], "db_fallback"

    return None, "no_match"


def get_price(raw: dict) -> float | None:
    """raw row에서 유효한 가격 추출. sale_price > 0 우선, 없으면 original_price."""
    sale = raw.get("sale_price")
    orig = raw.get("original_price")
    if isinstance(sale, (int, float)) and sale > 0:
        return float(sale)
    if isinstance(orig, (int, float)) and orig > 0:
        return float(orig)
    return None


def main() -> None:
    import sqlite3
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from services.bundle_import import apply_products

    print("=" * 60)
    print("RD8 products ingest 시작")
    print("=" * 60)

    # ── Step 1: 잔여 데이터 비우기 ───────────────────────────────
    print("\n[Step 1] baseline_prices / products 비우기...")
    conn = sqlite3.connect(str(DB_PATH))
    bp_del = conn.execute("DELETE FROM baseline_prices").rowcount
    pr_del = conn.execute("DELETE FROM products").rowcount
    conn.commit()
    conn.close()
    print(f"  삭제: products={pr_del}, baseline_prices={bp_del}")

    # ── Step 2+3: 마트별 raw → apply_products ────────────────────
    engine = create_engine(f"sqlite:///{DB_PATH}")
    Session = sessionmaker(bind=engine)
    session = Session()

    # DB 폴백 인덱스 (한 번만 빌드)
    print("\n[Step 2] DB 폴백 인덱스 구축...")
    db_fallback = build_db_fallback_index(DB_PATH)
    print(f"  DB 폴백 인덱스 크기: {len(db_fallback)}")

    all_unmatched: list[dict] = []
    mart_results: dict[str, dict] = {}
    mart_match_counts: dict[str, dict] = {}

    for mart in MARTS:
        print(f"\n[Step 3] [{mart}] 처리 중...")
        alias_idx, brand_name_idx, name_core_idx = load_l2_indexes(mart)
        print(f"  인덱스: alias={len(alias_idx)}, brand+name={len(brand_name_idx)}, name_core={len(name_core_idx)}")

        raw_path = RAW_DIR / f"{mart}.jsonl"
        rows: list[dict] = []
        unmatched: list[dict] = []
        no_price_cnt = 0
        match_by: dict[str, int] = {"alias": 0, "brand_name": 0, "name_core": 0, "db_fallback": 0}

        with raw_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                raw = json.loads(line)
                raw_name = (raw.get("name") or "").strip()
                if not raw_name:
                    continue

                price = get_price(raw)
                if price is None:
                    no_price_cnt += 1
                    unmatched.append({
                        "name": raw_name, "mart": mart, "reason": "no_price",
                        "sale_price": raw.get("sale_price"),
                        "original_price": raw.get("original_price"),
                    })
                    continue

                mk, method = match_raw(raw_name, alias_idx, brand_name_idx, name_core_idx, db_fallback)

                if mk is None:
                    unmatched.append({
                        "name": raw_name, "mart": mart, "reason": "no_l2_match",
                        "price": price,
                    })
                    continue

                match_by[method] = match_by.get(method, 0) + 1
                crawled_at = raw.get("crawled_at") or datetime.now(timezone.utc).isoformat()

                rows.append({
                    "match_key": mk,
                    "mart": mart,
                    "price": price,
                    "captured_at": crawled_at,
                    "raw_name": raw_name,
                })

        print(f"  raw 매칭: matched={len(rows)}, unmatched={len(unmatched)} (no_price={no_price_cnt})")
        print(f"  매칭 방법: {match_by}")
        all_unmatched.extend(unmatched)
        mart_match_counts[mart] = {
            "matched": len(rows),
            "unmatched": len(unmatched),
            "no_price": no_price_cnt,
            "match_by": match_by,
        }

        # apply_products 호출
        result = apply_products(session, rows, mode="lenient")
        session.commit()
        mart_results[mart] = result
        print(f"  apply_products: created={result['created']}, matched={result['matched']}, "
              f"skipped={result['skipped']}, rejected={result['rejected']}, "
              f"baselines_upserted={result['baselines_upserted']}")

    session.close()

    # ── Step 4: unmatched 저장 ────────────────────────────────────
    unmatched_path = OUT_DIR / "products_unmatched.jsonl"
    with unmatched_path.open("w", encoding="utf-8") as f:
        for row in all_unmatched:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"\n[Step 4] 미매칭 저장: {unmatched_path} ({len(all_unmatched)}건)")

    # ── Step 5: 검증 SQL ──────────────────────────────────────────
    print("\n[Step 5] 검증 SQL")
    conn = sqlite3.connect(str(DB_PATH))

    total_products = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    distinct_keys = conn.execute(
        "SELECT COUNT(DISTINCT brand||'|'||COALESCE(name_core,'')||'|'||COALESCE(pack_qty,'')||'|'||COALESCE(pack_unit,'')) FROM products"
    ).fetchone()[0]
    total_bp = conn.execute("SELECT COUNT(*) FROM baseline_prices").fetchone()[0]

    print(f"\n  products total={total_products}, distinct(brand|name_core|pack_qty|pack_unit)={distinct_keys}")
    print(f"  baseline_prices total={total_bp}")

    print("\n  baseline_prices 마트별:")
    bp_by_mart = {}
    for row in conn.execute("SELECT mart_code, COUNT(*) c FROM baseline_prices GROUP BY mart_code"):
        print(f"    {row[0]}: {row[1]}")
        bp_by_mart[row[0]] = row[1]

    print("\n  products source_marts 분포 (상위 10):")
    for row in conn.execute("SELECT source_marts, COUNT(*) c FROM products GROUP BY source_marts ORDER BY c DESC LIMIT 10"):
        print(f"    {row[0]}: {row[1]}")

    print("\n  products category_id 상위 10:")
    for row in conn.execute("SELECT category_id, COUNT(*) c FROM products GROUP BY category_id ORDER BY c DESC LIMIT 10"):
        print(f"    {row[0]}: {row[1]}")

    # 적대적 검증
    null_brand = conn.execute(
        "SELECT COUNT(*) FROM products WHERE brand IS NULL OR brand=''"
    ).fetchone()[0]
    null_name = conn.execute(
        "SELECT COUNT(*) FROM products WHERE name_core IS NULL OR name_core=''"
    ).fetchone()[0]
    null_unit_kind = conn.execute(
        "SELECT COUNT(*) FROM products WHERE unit_kind IS NULL OR unit_kind=''"
    ).fetchone()[0]
    null_mart_code = conn.execute(
        "SELECT COUNT(*) FROM baseline_prices WHERE mart_code IS NULL OR mart_code=''"
    ).fetchone()[0]
    dup_groups = conn.execute(
        """SELECT COUNT(*) FROM (
            SELECT brand, name_core, pack_qty, pack_unit
            FROM products
            GROUP BY brand, name_core, pack_qty, pack_unit
            HAVING COUNT(*) > 1
        )"""
    ).fetchone()[0]
    avg_bp = conn.execute(
        "SELECT AVG(c) FROM (SELECT product_id, COUNT(*) c FROM baseline_prices GROUP BY product_id)"
    ).fetchone()[0]

    # 리프 카테고리 확인: 자식이 없는 카테고리 = 리프
    non_leaf = conn.execute(
        """SELECT COUNT(*) FROM products p
           WHERE p.category_id IS NOT NULL
           AND EXISTS (SELECT 1 FROM categories c WHERE c.parent_id = p.category_id)"""
    ).fetchone()[0]

    print(f"\n  [적대적 자가검증]")
    print(f"    products.brand=null/empty:     {null_brand}")
    print(f"    products.name_core=null/empty: {null_name}")
    print(f"    products.unit_kind=null/empty: {null_unit_kind}")
    print(f"    baseline_prices.mart_code=null:{null_mart_code}")
    print(f"    중복 (brand|name_core|pack_qty|pack_unit) 그룹: {dup_groups}  (0=OK)")
    print(f"    avg baseline_prices per product: {avg_bp:.3f}")
    print(f"    products with non-leaf category_id: {non_leaf}")

    conn.close()

    # ── 요약 출력 ──────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("RD8 products ingest 완료")
    print("=" * 60)
    print(f"  입력 마트: {MARTS}")
    for m in MARTS:
        mc = mart_match_counts.get(m, {})
        r = mart_results.get(m, {})
        print(f"  [{m}] raw_matched={mc.get('matched',0)}, "
              f"created={r.get('created',0)}, "
              f"matched(dedup)={r.get('matched',0)}, "
              f"baselines={r.get('baselines_upserted',0)}")
    print(f"  전체 미매칭: {len(all_unmatched)}건")
    print(f"  products 최종: {total_products}")
    print(f"  baseline_prices 최종: {total_bp}")

    # 게이트 판정
    gates = {
        "중복 0 (UNIQUE 보장)": dup_groups == 0,
        "products ≥ 2000건": total_products >= 2000,
        "baseline_prices avg ≥ 1.0 per product": (avg_bp or 0) >= 1.0,
        "brand null = 0": null_brand == 0,
        "name_core null = 0": null_name == 0,
        "mart_code null = 0": null_mart_code == 0,
    }
    print("\n  [RD8 게이트]")
    all_pass = True
    for name, ok in gates.items():
        status = "✓ PASS" if ok else "✗ FAIL"
        print(f"    {status}  {name}")
        if not ok:
            all_pass = False
    print(f"\n  종합: {'ALL PASS ✓' if all_pass else 'SOME GATES FAILED ✗'}")

    return {
        "total_products": total_products,
        "total_bp": total_bp,
        "mart_results": mart_results,
        "mart_match_counts": mart_match_counts,
        "unmatched_total": len(all_unmatched),
        "gates": gates,
        "verification": {
            "null_brand": null_brand,
            "null_name": null_name,
            "null_unit_kind": null_unit_kind,
            "null_mart_code": null_mart_code,
            "dup_groups": dup_groups,
            "avg_bp_per_product": avg_bp,
            "non_leaf_category": non_leaf,
        },
    }


if __name__ == "__main__":
    main()
