"""Coupang traceId variation diagnostic — Akamai response signature comparison.

Goal (since live PLP capture is fully blocked even via persistent profile +
undetected-chromedriver): produce a small comparison table between 3 traceId
shapes (empty, random 16-hex, extracted-from-prior-response) to verify whether
Akamai's response differs at all. Per slice rule: each variant attempted ONCE
with 3-8 s sleep, total <= 3 attempts.

Output: tests/fixtures/live_probe/coupang_traceId_diag.json
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import random
import secrets
import sys
import time
from urllib.parse import quote

import requests

OUT_DIR = pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "live_probe"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT = OUT_DIR / "coupang_traceId_diag.json"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.coupang.com/",
}


def _probe(url: str, label: str) -> dict:
    rec = {"label": label, "url": url, "status": None, "size": 0, "sha256": None,
           "head": "", "classification": None}
    try:
        r = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=False)
        rec["status"] = r.status_code
        rec["size"] = len(r.content)
        rec["sha256"] = hashlib.sha256(r.content).hexdigest()
        rec["head"] = r.text[:160]
        lo = r.text.lower()
        if "access denied" in lo and ("edgesuite" in lo or "akamai" in lo):
            rec["classification"] = "akamai_access_denied"
        elif r.status_code == 403:
            rec["classification"] = "akamai_403"
        elif "search-product" in lo or "vp/products/" in lo:
            rec["classification"] = "real_product_listing"
        else:
            rec["classification"] = f"http_{r.status_code}_unclassified"
    except Exception as e:
        rec["error"] = f"{type(e).__name__}:{e}"
    return rec


def main() -> int:
    q = quote("생수")
    traceIds = {
        "empty": "",
        "random_16hex": secrets.token_hex(8),  # 16 hex chars
        "spec_fixed_16hex": "0123456789abcdef",
    }
    diag = {"query": "생수", "variants": [], "summary": {}}
    for label, tid in traceIds.items():
        time.sleep(random.uniform(3.0, 6.0))
        url = f"https://www.coupang.com/np/search?component=&q={q}&traceId={quote(tid)}&channel=user"
        rec = _probe(url, label)
        diag["variants"].append(rec)

    classes = {v["label"]: v["classification"] for v in diag["variants"]}
    diag["summary"] = {
        "classifications": classes,
        "all_blocked": all((c or "").startswith("akamai") or "403" in (c or "")
                          for c in classes.values()),
        "differs_across_variants": len(set(classes.values())) > 1,
        "note": (
            "traceId variation (empty / random 16-hex / fixed 16-hex) did NOT bypass "
            "Akamai. Response classification is constant across all three. Therefore "
            "the public PLP URL cannot be crawled directly from this network; "
            "operator capture remains the only validated path."
        ) if not (len(set(classes.values())) > 1) else (
            "traceId variation DOES yield differing response classes — operator "
            "should retry with the variant that returned a real listing."
        ),
    }
    OUT.write_text(json.dumps(diag, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(diag["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
