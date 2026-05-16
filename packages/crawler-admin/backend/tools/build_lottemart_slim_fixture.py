"""Build slim lottemart hydrated fixture (5 products) from live hydrated capture.

Extracts 5 productEntities from the live hydrated promotions page and wraps them
back in the minimal __INITIAL_STATE__ envelope shape (`data.products.productEntities`)
so the existing LottemartCrawler._extract_from_initial_state still parses them.

The slim fixture must:
 - be < 80 KB
 - contain at least one item with both price.original and price.current
 - contain at least one item with price.original = null (sale-only)
 - preserve productId, name, categoryPath, image.src, offer.description
"""
from __future__ import annotations

import json
import pathlib
import re

SRC = pathlib.Path("tests/fixtures/live_probe/lottemart_hydrated_promotions.html")
OUT = pathlib.Path("tests/fixtures/lottemart/hydrated_5cards.html")
OUT.parent.mkdir(parents=True, exist_ok=True)


def extract_initial_state(html: str) -> dict:
    m = re.search(r"__INITIAL_STATE__\s*=\s*", html)
    i = m.end()
    depth = 0
    in_str = False
    esc = False
    end = None
    for j in range(i, len(html)):
        c = html[j]
        if esc:
            esc = False
            continue
        if c == "\\":
            esc = True
            continue
        if c == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                end = j + 1
                break
    return json.loads(html[i:end])


def trim_product(p: dict) -> dict:
    keep_keys = {
        "productId", "retailerProductId", "name", "available", "brand",
        "categoryPath", "price", "regular", "offer", "offers", "image",
        "ratingSummary",
    }
    out = {k: p[k] for k in keep_keys if k in p}
    # trim image to src only
    if isinstance(out.get("image"), dict):
        out["image"] = {"src": out["image"].get("src", ""),
                        "description": out["image"].get("description", "")}
    # trim offer
    if isinstance(out.get("offer"), dict):
        off = out["offer"]
        out["offer"] = {k: off.get(k) for k in ("id", "description", "type", "retailerPromotionId") if k in off}
    if isinstance(out.get("offers"), list):
        out["offers"] = [
            {k: o.get(k) for k in ("id", "description", "type", "retailerPromotionId") if k in o}
            for o in out["offers"][:2] if isinstance(o, dict)
        ]
    return out


def main() -> int:
    html = SRC.read_text(encoding="utf-8")
    state = extract_initial_state(html)
    pe = state["data"]["products"]["productEntities"]
    items = list(pe.items())
    # find 1 with price.original and price.current
    discount = next(
        (kv for kv in items
         if isinstance(kv[1].get("price"), dict)
         and isinstance(kv[1]["price"].get("original"), dict)
         and isinstance(kv[1]["price"].get("current"), dict)
         and kv[1]["price"]["original"].get("amount") != kv[1]["price"]["current"].get("amount")),
        None,
    )
    sale_only = next(
        (kv for kv in items
         if isinstance(kv[1].get("price"), dict)
         and kv[1]["price"].get("original") is None
         and isinstance(kv[1]["price"].get("current"), dict)),
        None,
    )
    has_category = next(
        (kv for kv in items
         if isinstance(kv[1].get("categoryPath"), list) and kv[1]["categoryPath"]),
        None,
    )
    has_offer = next(
        (kv for kv in items
         if isinstance(kv[1].get("offer"), dict) and kv[1]["offer"].get("description")),
        None,
    )

    picks_map = {}
    for kv in (discount, sale_only, has_category, has_offer):
        if kv and kv[0] not in picks_map:
            picks_map[kv[0]] = kv[1]
    # pad to 5 with first ones
    for k, v in items:
        if len(picks_map) >= 5:
            break
        if k not in picks_map:
            picks_map[k] = v
    picks = picks_map

    print("picked product ids:")
    for pid, v in picks.items():
        op = v.get("price", {}).get("original")
        cp = v.get("price", {}).get("current")
        print(f"  {pid}  name={v['name'][:40]!r:42} orig={op}  curr={cp}")

    trimmed = {pid: trim_product(v) for pid, v in picks.items()}
    envelope = {
        "data": {
            "products": {
                "productEntities": trimmed
            }
        }
    }

    # Reassemble a minimal HTML host page that LottemartCrawler can parse.
    body = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>롯데마트제타 slim hydrated fixture</title></head><body>"
        "<script>window.__INITIAL_STATE__ = "
        + json.dumps(envelope, ensure_ascii=False)
        + ";</script></body></html>"
    )
    OUT.write_text(body, encoding="utf-8")
    print(f"wrote {OUT} bytes={len(body)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
