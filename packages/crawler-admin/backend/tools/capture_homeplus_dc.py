"""Live mfront capture for homeplus with discount-leaning keywords via XHR.

Uses Playwright to hit https://mfront.homeplus.co.kr/search?keyword=... and capture
the JSON envelope from the underlying /search/api/... XHR request, looking for a
keyword whose dataList rows include dcPrice-populated entries.

Output: tests/fixtures/live_probe/homeplus_dc_<kw>.json (full live JSON envelope).
"""
from __future__ import annotations

import json
import pathlib
import random
import sys
import time
from urllib.parse import quote

import requests

OUT = pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "live_probe"
OUT.mkdir(parents=True, exist_ok=True)

KEYWORDS = ["1+1", "특가", "행사", "원프라이스", "단독", "할인"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.7",
    "Referer": "https://mfront.homeplus.co.kr/",
    "X-Requested-With": "XMLHttpRequest",
}

# Pattern derived from existing homeplus_probe_api.json structure — mfront mobile
# storefront uses /search.do or /v1/search backend. Try a few likely endpoints.
URL_TEMPLATES = [
    "https://mfront.homeplus.co.kr/search.do?keyword={kw}&page=1&storeType=HYPER",
    "https://front.homeplus.co.kr/search/v1/items?keyword={kw}&page=1&size=30&storeType=HYPER",
]


def _try_one(url: str, kw: str) -> dict:
    rec = {"url": url, "keyword": kw, "status": None, "bytes": 0, "envelope_ok": False,
           "rows": 0, "dc_rows": 0, "saved": None, "head": ""}
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        rec["status"] = r.status_code
        rec["bytes"] = len(r.content)
        rec["head"] = r.text[:120]
        if r.status_code == 200:
            try:
                env = r.json()
            except Exception:
                env = None
            if isinstance(env, dict) and env.get("returnStatus") == 200:
                rec["envelope_ok"] = True
                dl = (env.get("data") or {}).get("dataList") or []
                rec["rows"] = len(dl)
                rec["dc_rows"] = sum(1 for x in dl if x.get("dcPrice") is not None)
                if rec["dc_rows"] > 0 or rec["rows"] >= 10:
                    safe = kw.replace("+", "plus").replace("/", "_")
                    p = OUT / f"homeplus_dc_{safe}.json"
                    p.write_text(json.dumps(env, ensure_ascii=False), encoding="utf-8")
                    rec["saved"] = str(p.name)
    except Exception as e:
        rec["error"] = f"{type(e).__name__}:{e}"
    return rec


def main() -> int:
    report = {"attempts": []}
    attempts = 0
    for kw in KEYWORDS:
        for tpl in URL_TEMPLATES:
            if attempts >= 10:
                break
            attempts += 1
            time.sleep(random.uniform(3.0, 8.0))
            rec = _try_one(tpl.format(kw=quote(kw)), kw)
            report["attempts"].append(rec)
            if rec.get("saved") and rec.get("dc_rows", 0) >= 1:
                print(json.dumps(report, ensure_ascii=False, indent=2))
                return 0
    print(json.dumps(report, ensure_ascii=False, indent=2))
    # Even if no new fresh capture, existing live probe will be used as fallback.
    return 1


if __name__ == "__main__":
    sys.exit(main())
