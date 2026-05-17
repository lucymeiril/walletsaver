"""
롯데마트 크롤러 라이브 검증 스크립트 — 3회 연속 실행, 각 200건 이상 확인.

실행: py -3 .walletsavior-live-validation/rd2-lottemart/live_validate.py
출력: run-{ts}-{n}.json, run-{ts}-{n}.md x 3
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import shutil
import time
from datetime import datetime
from pathlib import Path

# 크롤러 경로 추가 — 스크립트 위치 기반 절대경로 (../../.. == capston01 루트)
_here = Path(__file__).resolve().parent          # rd2-lottemart/
_root = _here.parent.parent                     # E:/pdf/capston01
_backend = _root / "packages" / "crawler-admin" / "backend"
_shared = _root / "packages" / "shared"

# __pycache__ 제거 (최신 소스 재컴파일 보장)
_pyc = _backend / "crawlers" / "marts" / "lottemart" / "__pycache__"
if _pyc.exists():
    shutil.rmtree(_pyc)

for _p in (_shared, _backend):
    p = str(_p)
    if p not in sys.path:
        sys.path.insert(0, p)

from crawlers.marts.lottemart.crawler import LottemartCrawler


RUNS = 3
PASS_THRESHOLD = 200


async def run_once(run_id: int) -> dict:
    ts = datetime.now().isoformat()
    c = LottemartCrawler()
    t0 = time.time()
    items = await c._fetch_promotions_scroll(target_count=220, max_scroll_steps=40)
    elapsed = round(time.time() - t0, 1)
    count = len(items)
    sample_items = [
        {"name": it.name, "sale_price": it.sale_price, "detail_url": it.detail_url}
        for it in items[:5]
    ]
    result = {
        "run_id": run_id,
        "timestamp": ts,
        "elapsed_seconds": elapsed,
        "items_count": count,
        "pass": count >= PASS_THRESHOLD,
        "sample_items": sample_items,
        "source": "live_lottemartzetta_com_xhr_scroll",
    }
    return result


async def main():
    results = []
    out_dir = os.path.dirname(os.path.abspath(__file__))
    batch_ts = datetime.now().strftime("%Y%m%dT%H%M%S")

    for i in range(1, RUNS + 1):
        print(f"\n[run {i}/{RUNS}] 시작...")
        try:
            r = await run_once(i)
        except Exception as e:
            r = {
                "run_id": i,
                "timestamp": datetime.now().isoformat(),
                "elapsed_seconds": 0,
                "items_count": 0,
                "pass": False,
                "error": f"{type(e).__name__}: {e}",
                "source": "live_lottemartzetta_com_xhr_scroll",
            }
        results.append(r)
        print(f"  → {r.get('items_count', 0)}건 {'✓ PASS' if r.get('pass') else '✗ FAIL'}")

        # 파일 저장
        run_file = os.path.join(out_dir, f"run-{batch_ts}-{i}.json")
        with open(run_file, "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=2)

        md_file = os.path.join(out_dir, f"run-{batch_ts}-{i}.md")
        with open(md_file, "w", encoding="utf-8") as f:
            f.write(f"# 롯데마트 라이브 검증 run {i}/{RUNS}\n\n")
            f.write(f"- 타임스탬프: {r['timestamp']}\n")
            f.write(f"- 소요 시간: {r.get('elapsed_seconds', 0)}s\n")
            f.write(f"- 수집 건수: **{r.get('items_count', 0)}건**\n")
            f.write(f"- 통과 기준: {PASS_THRESHOLD}건\n")
            f.write(f"- 결과: {'✓ PASS' if r.get('pass') else '✗ FAIL'}\n")
            f.write(f"- 수집원: live lottemartzetta.com XHR scroll\n\n")
            if r.get("sample_items"):
                f.write("## 샘플 상품 (5건)\n\n")
                for s in r["sample_items"]:
                    f.write(f"- {s['name']} / {s['sale_price']}원 / {s['detail_url']}\n")
            if r.get("error"):
                f.write(f"\n## 오류\n\n```\n{r['error']}\n```\n")

        if i < RUNS:
            print(f"  다음 실행까지 10초 대기...")
            await asyncio.sleep(10)

    all_pass = all(r.get("pass") for r in results)
    counts = [r.get("items_count", 0) for r in results]
    print(f"\n{'='*50}")
    print(f"3회 연속 결과: {counts}")
    print(f"모두 {PASS_THRESHOLD}건 이상: {'✓ YES' if all_pass else '✗ NO'}")
    print(f"{'='*50}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
