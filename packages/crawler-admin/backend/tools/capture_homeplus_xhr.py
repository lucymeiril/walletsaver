"""Homeplus XHR interception capture via Playwright headful.

Loads mfront search pages with discount-leaning queries and captures the JSON
envelope (`returnStatus:200`+`data.dataList`) emitted by the underlying XHR.

Saves any envelope where >=1 dataList row carries dcPrice != null.
"""
from __future__ import annotations

import json
import pathlib
import random
import sys
import time
from urllib.parse import quote

from playwright.sync_api import sync_playwright

OUT = pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "live_probe"
OUT.mkdir(parents=True, exist_ok=True)
KEYWORDS = ["1+1", "특가", "행사", "원프라이스", "단독"]


def main() -> int:
    report = {"attempts": []}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
            locale="ko-KR",
            viewport={"width": 412, "height": 869, "isMobile": True} if False else {"width": 1366, "height": 900},
        )
        page = ctx.new_page()
        captured: list[tuple[str, dict]] = []

        def on_response(resp):
            try:
                ct = (resp.headers.get("content-type") or "").lower()
                if "json" not in ct:
                    return
                url = resp.url
                if "homeplus" not in url:
                    return
                body = resp.text()
                if "dataList" not in body or "returnStatus" not in body:
                    return
                env = json.loads(body)
                if not isinstance(env, dict) or env.get("returnStatus") != 200:
                    return
                dl = (env.get("data") or {}).get("dataList") or []
                if not dl:
                    return
                captured.append((url, env))
            except Exception:
                pass

        page.on("response", on_response)

        for kw in KEYWORDS:
            time.sleep(random.uniform(3.0, 8.0))
            url = f"https://mfront.homeplus.co.kr/search?keyword={quote(kw)}&storeType=HYPER"
            rec = {"keyword": kw, "url": url, "captured_before": len(captured), "status": None}
            try:
                resp = page.goto(url, wait_until="networkidle", timeout=30000)
                rec["status"] = resp.status if resp else None
            except Exception as e:
                rec["error"] = f"{type(e).__name__}:{e}"
            time.sleep(2)
            rec["captured_after"] = len(captured)
            report["attempts"].append(rec)
            # check if any captured envelope has dc rows
            for u, env in captured:
                dl = env["data"]["dataList"]
                dc = sum(1 for r in dl if r.get("dcPrice") is not None)
                if dc >= 1:
                    safe = kw.replace("+", "plus").replace("/", "_")
                    p_out = OUT / f"homeplus_dc_{safe}.json"
                    p_out.write_text(json.dumps(env, ensure_ascii=False), encoding="utf-8")
                    rec["saved"] = str(p_out.name)
                    rec["rows"] = len(dl)
                    rec["dc_rows"] = dc
                    print(json.dumps(report, ensure_ascii=False, indent=2))
                    browser.close()
                    return 0

        browser.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1


if __name__ == "__main__":
    sys.exit(main())
