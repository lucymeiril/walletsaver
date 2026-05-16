"""1회용: 코스트코 실 페이지 fixture 캡처 + 구조 점검."""
import re
import pathlib

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
session = requests.Session()
session.headers.update({"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"})

OUT = pathlib.Path("packages/crawler-admin/backend/tests/fixtures/live_probe")
OUT.mkdir(parents=True, exist_ok=True)

TARGETS = {
    "costco_special_offers": "https://www.costco.co.kr/Special-Price-Offers/c/SpecialPriceOffers",
    "costco_events": "https://www.costco.co.kr/events",
    "costco_home": "https://www.costco.co.kr/",
    "homeplus_main": "https://front.homeplus.co.kr/",
    "lottemart_main": "https://www.lottemart.com/",
    "emart_search_haengsa": "https://emart.ssg.com/search.ssg?target=all&query=%ED%96%89%EC%82%AC",
}

for name, url in TARGETS.items():
    try:
        r = session.get(url, timeout=20)
        (OUT / f"{name}.html").write_text(r.text, encoding="utf-8", errors="replace")
        html = r.text
        p_links = len(re.findall(r"/p/\d+", html))
        product_class = len(re.findall(r'class="[^"]*product[^"]*"', html, re.I))
        won_strings = len(re.findall(r"[0-9,]+\s*원", html))
        title_match = re.search(r"<title[^>]*>([^<]+)</title>", html)
        title = title_match.group(1).strip() if title_match else ""
        print(f"{name}: status={r.status_code} bytes={len(html)} p_links={p_links} product_class={product_class} won={won_strings} title={title[:60]!r}")
    except Exception as e:
        print(f"{name}: ERR {e}")
