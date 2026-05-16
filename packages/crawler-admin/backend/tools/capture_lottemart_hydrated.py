"""Headful Playwright capture of lottemartzetta.com with hydration wait.

Saves raw page.content() to tests/fixtures/live_probe/lottemart_hydrated_<cat>.html
ONLY if __INITIAL_STATE__.data.products.productEntities ends up populated.

Live-capture rules:
- 3~8 s sleep between GETs.
- max 4 categories per run, exits early on first success.
- WAF 202 → reload once, then skip.
"""
from __future__ import annotations

import json
import pathlib
import random
import sys
import time

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE = "https://www.lottemart.com"
ZETTA = "https://www.lottemartzetta.com"
CATEGORIES = [
    ("promotions", f"{ZETTA}/promotions"),
    ("best", f"{ZETTA}/best"),
    ("one_plus_one", f"{ZETTA}/promotions/1+1"),
    ("search_sale", f"{ZETTA}/search?query=%ED%95%A0%EC%9D%B8"),
]
OUT = pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "live_probe"
OUT.mkdir(parents=True, exist_ok=True)

HYDRATION_PROBE = r"""
() => {
  try {
    const s = window.__INITIAL_STATE__;
    if (!s) return false;
    const products = s?.data?.products?.productEntities || s?.products?.productEntities || s?.product?.productEntities;
    if (products && Object.keys(products).length >= 3) return true;
    // also accept if zentra renders cards
    const cards = document.querySelectorAll('[data-product-id],[data-goods-no],article[class*=product]');
    return cards.length >= 5;
  } catch (e) { return false; }
}
"""


def main() -> int:
    report = {"attempts": [], "success": None}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
        try:
            ctx = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="ko-KR",
                viewport={"width": 1366, "height": 900},
            )
            page = ctx.new_page()
            for name, url in CATEGORIES:
                time.sleep(random.uniform(3.0, 8.0))
                rec = {"name": name, "url": url, "status": None, "size": 0, "hydrated": False, "note": ""}
                try:
                    resp = page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    rec["status"] = resp.status if resp else None
                    if rec["status"] == 202:
                        rec["note"] = "aws_waf_202_first_try"
                        time.sleep(random.uniform(3.0, 6.0))
                        try:
                            resp = page.reload(wait_until="domcontentloaded", timeout=30000)
                            rec["status"] = resp.status if resp else None
                        except Exception as e:
                            rec["note"] += f";reload_fail:{e}"
                    try:
                        page.wait_for_function(HYDRATION_PROBE, timeout=12000)
                        rec["hydrated"] = True
                    except PWTimeout:
                        rec["note"] += ";hydration_timeout"
                    html = page.content()
                    rec["size"] = len(html)
                    fname = OUT / f"lottemart_hydrated_{name}.html"
                    fname.write_text(html, encoding="utf-8")
                    if rec["hydrated"]:
                        report["success"] = name
                        report["attempts"].append(rec)
                        break
                except Exception as e:
                    rec["note"] = f"err:{type(e).__name__}:{e}"
                report["attempts"].append(rec)
        finally:
            browser.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["success"] else 2


if __name__ == "__main__":
    sys.exit(main())
