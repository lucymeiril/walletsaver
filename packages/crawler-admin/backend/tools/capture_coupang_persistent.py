"""Persistent-profile Playwright capture for coupang search '생수'.

Uses a brand-new user data dir (NOT the user's chrome profile) to bypass Akamai
mid-tier checks. If still blocked, sets exit=2 so caller can choose fallback.

Saves any successful HTML to tests/fixtures/live_probe/coupang_search_persistent.html.
Akamai-blocked responses are saved to coupang_persistent_blocked.html for audit.
"""
from __future__ import annotations

import json
import pathlib
import random
import sys
import time

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

REPO = pathlib.Path(__file__).resolve().parents[4]
PROFILE_DIR = REPO / ".copilot" / "session-state" / "062b8dc2-33d4-4964-a823-a2a03ff963fc" / "files" / "coupang_profile"
PROFILE_DIR.mkdir(parents=True, exist_ok=True)

OUT = pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "live_probe"
OUT.mkdir(parents=True, exist_ok=True)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def _is_blocked(html: str) -> bool:
    lo = html.lower()
    if "access denied" in lo and ("edgesuite" in lo or "akamai" in lo or "permission to access" in lo):
        return True
    if "edgesuite.net" in lo:
        return True
    if len(html) < 800 and "search-product" not in lo and "vp/products/" not in lo:
        return True
    return False


def main() -> int:
    report = {"phases": []}
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            user_agent=UA,
            locale="ko-KR",
            viewport={"width": 1366, "height": 900},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
            ],
        )
        try:
            page = ctx.new_page()
            # 1) Home, sleep ~10s for any initial Akamai cookies
            time.sleep(random.uniform(3.0, 5.0))
            phase = {"step": "home", "url": "https://www.coupang.com/", "status": None, "size": 0, "blocked": None}
            try:
                resp = page.goto("https://www.coupang.com/", wait_until="domcontentloaded", timeout=30000)
                phase["status"] = resp.status if resp else None
                time.sleep(10)
                html = page.content()
                phase["size"] = len(html)
                phase["blocked"] = _is_blocked(html)
            except Exception as e:
                phase["error"] = f"{type(e).__name__}:{e}"
            report["phases"].append(phase)

            # 2) Type into search box if available, otherwise go directly
            time.sleep(random.uniform(3.0, 6.0))
            search_url = "https://www.coupang.com/np/search?component=&q=%EC%83%9D%EC%88%98&channel=user"
            phase2 = {"step": "search", "url": search_url, "status": None, "size": 0, "blocked": None, "html_saved": None}
            try:
                resp = page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                phase2["status"] = resp.status if resp else None
                # try to wait for product cards
                try:
                    page.wait_for_selector('[class*="search-product"], li.search-product, [data-product-id]', timeout=10000)
                except PWTimeout:
                    pass
                time.sleep(random.uniform(3.0, 5.0))
                html = page.content()
                phase2["size"] = len(html)
                phase2["blocked"] = _is_blocked(html)
                if not phase2["blocked"]:
                    out = OUT / "coupang_search_persistent.html"
                    out.write_text(html, encoding="utf-8")
                    phase2["html_saved"] = str(out.name)
                else:
                    out = OUT / "coupang_persistent_blocked.html"
                    out.write_text(html, encoding="utf-8")
                    phase2["html_saved"] = str(out.name)
            except Exception as e:
                phase2["error"] = f"{type(e).__name__}:{e}"
            report["phases"].append(phase2)
        finally:
            ctx.close()

    print(json.dumps(report, ensure_ascii=False, indent=2))
    last = report["phases"][-1]
    return 0 if (last.get("blocked") is False) else 2


if __name__ == "__main__":
    sys.exit(main())
