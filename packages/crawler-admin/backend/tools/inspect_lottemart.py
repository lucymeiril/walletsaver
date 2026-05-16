"""1회용 라이브 캡처 인스펙터 (lottemart).

각 파일에서 어떤 store/data shape 가 들어있는지 빠르게 식별하고,
슬림 fixture 추출 가능한지 판정한다.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIVE = ROOT / "tests" / "fixtures" / "live_probe"

FILES = [
    "lottemart_zetta_promotions.html",
    "lottemart_zetta_best.html",
    "lottemart_zetta_search_sale.html",
    "lottemart_zetta_one_plus_one.html",
    "lottemart_zetta_browse_root.html",
    "lottemart_main.html",
]

for name in FILES:
    p = LIVE / name
    if not p.exists():
        continue
    t = p.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"<title[^>]*>(.*?)</title>", t)
    print("===", name, "len=", len(t))
    print(" title:", (m.group(1) if m else "")[:140])
    for marker in ("__NEXT_DATA__", "__NUXT__", "__INITIAL_STATE__", "__APOLLO_STATE__"):
        if marker in t:
            print(" marker:", marker)
    for sel in ("goodsNo", "goodsNm", "salePrice", "discountRate", "data-goods", "/p/", "productList", "search-product"):
        if sel in t:
            cnt = t.count(sel)
            print(f"   {sel}: {cnt}")
sys.exit(0)
