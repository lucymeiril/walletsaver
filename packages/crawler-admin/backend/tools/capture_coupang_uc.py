"""undetected-chromedriver fallback capture for coupang search '생수'."""
from __future__ import annotations

import json
import pathlib
import random
import sys
import time

import undetected_chromedriver as uc

OUT = pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "live_probe"
OUT.mkdir(parents=True, exist_ok=True)


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
    opts = uc.ChromeOptions()
    opts.add_argument("--lang=ko-KR")
    opts.add_argument("--window-size=1366,900")
    driver = uc.Chrome(options=opts, version_main=None, headless=False)
    try:
        # home
        time.sleep(random.uniform(3.0, 5.0))
        driver.get("https://www.coupang.com/")
        time.sleep(10)
        html1 = driver.page_source
        ph = {"step": "home", "size": len(html1), "blocked": _is_blocked(html1)}
        report["phases"].append(ph)
        time.sleep(random.uniform(3.0, 6.0))
        # search
        driver.get("https://www.coupang.com/np/search?component=&q=%EC%83%9D%EC%88%98&channel=user")
        time.sleep(8)
        html2 = driver.page_source
        ph2 = {"step": "search", "size": len(html2), "blocked": _is_blocked(html2)}
        if not ph2["blocked"]:
            out = OUT / "coupang_search_uc.html"
            out.write_text(html2, encoding="utf-8")
            ph2["saved"] = str(out.name)
        else:
            out = OUT / "coupang_uc_blocked.html"
            out.write_text(html2, encoding="utf-8")
            ph2["saved"] = str(out.name)
        report["phases"].append(ph2)
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["phases"][-1].get("blocked") is False else 2


if __name__ == "__main__":
    sys.exit(main())
