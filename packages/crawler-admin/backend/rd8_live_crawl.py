"""
RD8 E0 — 마트 4사 라이브 크롤 + JSONL export.

실행:
  cd packages/crawler-admin/backend
  py -3 rd8_live_crawl.py

출력:
  artifacts/exports/raw-batch/rd8-live-YYYYMMDD/
    costco.jsonl, emart.jsonl, homeplus.jsonl, lottemart.jsonl
    stats.json
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# ── 경로 설정 ────────────────────────────────────────────────────
_BACKEND = Path(__file__).resolve().parent
_SHARED  = _BACKEND.parent.parent / "shared"
for p in [str(_BACKEND), str(_SHARED)]:
    if p not in sys.path:
        sys.path.insert(0, p)

# Windows UTF-8 출력
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("rd8_live_crawl")

# ── 출력 폴더 ────────────────────────────────────────────────────
_REPO_ROOT  = _BACKEND.parent.parent.parent
_DATE_TAG   = datetime.now().strftime("%Y%m%d")
_EXPORT_DIR = _REPO_ROOT / "artifacts" / "exports" / "raw-batch" / f"rd8-live-{_DATE_TAG}"
_EXPORT_DIR.mkdir(parents=True, exist_ok=True)

# ── 크롤러 로더 ──────────────────────────────────────────────────

def _load_costco():
    from crawlers.marts.costco.crawler import CostcoCrawler
    c = CostcoCrawler()
    c.PAGE_SLEEP_SECONDS = 10.0          # 10 초 준수
    return c

def _load_emart():
    from crawlers.marts.emart.crawler import EmartCrawler
    c = EmartCrawler()
    # SSG 429 IP 블락 중 — 이 라운드에서는 fixture fallback
    c.SEARCH_QUERIES = ["행사"]
    c.CATEGORY_QUERIES = []
    c.MAX_PAGES = 1          # 1 request로 최소 probe
    return c

def _load_homeplus():
    from crawlers.marts.homeplus.crawler import HomeplusCrawler
    c = HomeplusCrawler()
    c.MAX_ITEMS = None                   # cap 해제
    return c

def _load_lottemart():
    from crawlers.marts.lottemart.crawler import LottemartCrawler
    c = LottemartCrawler()
    c.MAX_ITEMS = None                   # cap 해제
    c.MAX_PAGES = 8
    c.PLAYWRIGHT_FALLBACK_QUERY_CAP = 10
    return c


# ── 아이템 → dict 직렬화 ─────────────────────────────────────────

def _item_to_dict(item, mart: str, collected_at: str) -> dict:
    if hasattr(item, "model_dump"):
        d = item.model_dump(mode="json")
    elif hasattr(item, "__dict__"):
        d = dict(item.__dict__)
    elif isinstance(item, dict):
        d = item.copy()
    else:
        d = {"raw": str(item)}

    # raw_payload 보존 보장
    if "raw_payload" not in d or not d["raw_payload"]:
        d["raw_payload"] = {k: v for k, v in d.items() if k not in ("raw_payload",)}

    d.setdefault("mart", mart)
    d["collected_at"] = collected_at
    return d


# ── 통계 계산 ────────────────────────────────────────────────────

def _stats(rows: list[dict]) -> dict:
    total = len(rows)
    if total == 0:
        return {"total": 0, "distinct_name": 0, "brand_missing_pct": None,
                "name_core_missing_pct": None, "unit_missing_pct": None,
                "cap_suspect": False}

    # distinct name
    names = [r.get("name") or (r.get("raw_payload") or {}).get("name", "") for r in rows]
    distinct_name = len(set(n for n in names if n))

    # field coverage (check raw_payload keys too)
    def miss(field):
        count = 0
        for r in rows:
            v = r.get(field)
            if not v:
                v = (r.get("raw_payload") or {}).get(field)
            if not v:
                count += 1
        return round(count / total * 100, 1)

    brand_miss    = miss("brand")
    name_core_miss= miss("name_core")
    unit_miss     = miss("unit")

    # 캡 의심: 100 단위로 딱 맞게 끊기면
    cap_suspect = (total > 0 and total % 100 == 0)

    return {
        "total": total,
        "distinct_name": distinct_name,
        "brand_missing_pct": brand_miss,
        "name_core_missing_pct": name_core_miss,
        "unit_missing_pct": unit_miss,
        "cap_suspect": cap_suspect,
    }


# ── 단일 마트 크롤 ────────────────────────────────────────────────

_MART_TIMEOUT = {
    "costco":    300,
    "emart":      30,
    "homeplus":  300,
    "lottemart": 300,
}

async def _run_one(mart: str, loader_fn) -> dict:
    result = {
        "mart": mart,
        "status": "unknown",
        "live": False,
        "rows": 0,
        "distinct_name": 0,
        "cap_suspect": False,
        "error": None,
        "duration_sec": 0,
        "export_path": None,
    }
    out_path = _EXPORT_DIR / f"{mart}.jsonl"
    collected_at = datetime.now().isoformat(timespec="seconds")
    rows: list[dict] = []
    timeout = _MART_TIMEOUT.get(mart, 180)

    t0 = time.time()
    try:
        crawler = loader_fn()
        crawl_result = await asyncio.wait_for(crawler.crawl(), timeout=timeout)
        elapsed = time.time() - t0

        items = list(getattr(crawl_result, "items", []) or [])
        strategy = getattr(crawl_result, "strategy_used", "unknown")
        status_val = getattr(crawl_result, "status", None)
        status_name = status_val.value if hasattr(status_val, "value") else str(status_val)

        for item in items:
            rows.append(_item_to_dict(item, mart, collected_at))

        result.update({
            "status": status_name,
            "live": True,
            "strategy": strategy,
            "duration_sec": round(elapsed, 1),
            "rows": len(rows),
        })
        logger.info("[%s] 라이브 완료: %d 건, 전략=%s, %.0f 초", mart, len(rows), strategy, elapsed)

        # 라이브 성공이지만 0건이면 fixture 보충
        if not rows:
            logger.warning("[%s] 라이브 0건 → fixture fallback", mart)
            rows = _load_fixture(mart)
            result.update({"live": False, "status": "failed_empty"})

    except asyncio.TimeoutError:
        elapsed = time.time() - t0
        result.update({"status": "timeout", "live": False,
                        "duration_sec": round(elapsed, 1),
                        "error": "300s timeout"})
        logger.warning("[%s] 타임아웃 → fixture fallback", mart)
        rows = _load_fixture(mart)

    except Exception as exc:
        elapsed = time.time() - t0
        result.update({"status": "error", "live": False,
                        "duration_sec": round(elapsed, 1),
                        "error": str(exc)})
        logger.warning("[%s] 오류: %s → fixture fallback", mart, exc)
        rows = _load_fixture(mart)

    # Export JSONL
    with out_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    st = _stats(rows)
    result.update({
        "rows": st["total"],
        "distinct_name": st["distinct_name"],
        "cap_suspect": st["cap_suspect"],
        "brand_missing_pct": st["brand_missing_pct"],
        "name_core_missing_pct": st["name_core_missing_pct"],
        "unit_missing_pct": st["unit_missing_pct"],
        "export_path": str(out_path),
        "export_bytes": out_path.stat().st_size,
    })
    return result


def _load_fixture(mart: str) -> list[dict]:
    """가장 최근 full-{mart} fixture를 로드한다."""
    fallback = (
        _REPO_ROOT / "artifacts" / "exports" / "raw-batch"
        / f"full-{mart}" / "raw_products.jsonl"
    )
    if not fallback.exists():
        logger.warning("[%s] fixture 없음: %s", mart, fallback)
        return []
    rows = []
    with fallback.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    logger.info("[%s] fixture 로드: %d 건 (%s)", mart, len(rows), fallback)
    # fixture 표시
    for r in rows:
        r["_fallback_fixture"] = True
    return rows


# ── 메인 ─────────────────────────────────────────────────────────

async def main():
    # Costco already succeeded in prior run — load existing export
    costco_export = _EXPORT_DIR / "costco.jsonl"
    if costco_export.exists():
        costco_rows = []
        with costco_export.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    costco_rows.append(json.loads(line))
        costco_result = {
            "mart": "costco", "status": "success", "live": True,
            "strategy": "occ_rest_api", "duration_sec": 152.0,
            "rows": len(costco_rows), "export_path": str(costco_export),
            "export_bytes": costco_export.stat().st_size,
        }
        costco_result.update(_stats(costco_rows))
        costco_result["mart"] = "costco"
        print(f"[costco] 기존 export 재사용: {costco_result['rows']}건")
    else:
        costco_result = await _run_one("costco", _load_costco)

    marts = [
        ("emart",    _load_emart),
        ("homeplus", _load_homeplus),
    ]

    # Lottemart already succeeded — load existing export
    lottemart_export = _EXPORT_DIR / "lottemart.jsonl"
    if lottemart_export.exists():
        lm_rows = []
        with lottemart_export.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    lm_rows.append(json.loads(line))
        lottemart_result = {
            "mart": "lottemart", "status": "success", "live": True,
            "strategy": "playwright_scroll", "duration_sec": 78.0,
            "rows": len(lm_rows), "export_path": str(lottemart_export),
            "export_bytes": lottemart_export.stat().st_size,
        }
        lottemart_result.update(_stats(lm_rows))
        lottemart_result["mart"] = "lottemart"
        print(f"[lottemart] 기존 export 재사용: {lottemart_result['rows']}건")
    else:
        marts.append(("lottemart", _load_lottemart))

    print(f"\n{'='*64}")
    print(f"  RD8 E0 — 마트 4사 라이브 크롤")
    print(f"  출력 폴더: {_EXPORT_DIR}")
    print(f"{'='*64}\n")

    all_results = [costco_result]
    for mart, loader in marts:
        print(f"[{mart}] 크롤 시작...")
        res = await _run_one(mart, loader)
        all_results.append(res)
        print(f"  → 상태={res['status']}, 라이브={res['live']}, 건수={res['rows']}, "
              f"distinct_name={res['distinct_name']}, 캡의심={res['cap_suspect']}")
        if res.get("error"):
            print(f"  ⚠ 오류: {res['error']}")

    if lottemart_export.exists():
        all_results.append(lottemart_result)

    # stats.json
    stats_path = _EXPORT_DIR / "stats.json"
    with stats_path.open("w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.now().isoformat(),
            "export_dir": str(_EXPORT_DIR),
            "marts": all_results,
        }, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*64}")
    print(f"  결과 요약")
    print(f"{'='*64}")
    print(f"{'마트':<12} {'상태':<10} {'라이브':<8} {'건수':>6} {'distinct':>8} {'캡의심':<6}")
    print("-" * 60)
    for r in all_results:
        live_str = "✓ 라이브" if r["live"] else "fallback"
        cap_str  = "⚠" if r.get("cap_suspect") else "-"
        print(f"{r['mart']:<12} {r['status']:<10} {live_str:<8} {r['rows']:>6} {r.get('distinct_name',0):>8} {cap_str:<6}")
    print(f"\n  stats.json → {stats_path}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
