"""1회용: 코스트코 가격/이름 셀렉터 + 미니 fixture 추출."""
import pathlib
from bs4 import BeautifulSoup

html = pathlib.Path("packages/crawler-admin/backend/tests/fixtures/live_probe/costco_special_offers.html").read_text(
    encoding="utf-8", errors="replace"
)
soup = BeautifulSoup(html, "lxml")

cards = soup.select("li.product-list-item")
print("li.product-list-item count:", len(cards))

if cards:
    c = cards[0]
    print("=== first card raw (1800c) ===")
    print(str(c)[:1800])
    print()
    print("=== text-only ===")
    print(c.get_text(" | ", strip=True)[:600])

slim_cards = "\n".join(str(c) for c in cards[:5])
slim_html = f"<!doctype html><html><body><ul class='product-listing product-grid'>{slim_cards}</ul></body></html>"
out_path = pathlib.Path("packages/crawler-admin/backend/tests/fixtures/costco/special_offers_5cards.html")
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(slim_html, encoding="utf-8")
print(f"\nslim fixture saved: {out_path} ({len(slim_html)} bytes)")

price_nodes = soup.select("[class*='price']")
print(f"\nglobal price-class nodes: {len(price_nodes)}")
seen_cls = set()
for n in price_nodes:
    cls = " ".join(n.get("class") or [])
    txt = n.get_text(" ", strip=True)[:120]
    if txt and cls not in seen_cls:
        seen_cls.add(cls)
        print(f"  [{cls[:80]}] {txt}")
        if len(seen_cls) > 12: break
