"""Round R G1 limited live/fixture seeding for mart product rows.

Run from the repository root:
    py -3 -m crawler_admin.backend.scripts.round_r_g1_seed
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import quote

import requests
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

REPO_ROOT = Path(__file__).resolve().parents[4]
CRAWLER_BACKEND = REPO_ROOT / "packages" / "crawler-admin" / "backend"
DB_BACKEND = REPO_ROOT / "packages" / "db-admin" / "backend"
SHARED = REPO_ROOT / "packages" / "shared"
for path in (CRAWLER_BACKEND, DB_BACKEND, SHARED):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from crawlers.marts.emart.crawler import EmartCrawler
from crawlers.marts.homeplus.crawler import HomeplusCrawler
from crawlers.marts.lottemart.crawler import LottemartCrawler
from crawlers.marts.costco.crawler import (
    BASE_URL as COSTCO_BASE_URL,
    cards_to_discount_items,
    parse_costco_listing,
    parse_costco_occ_response,
)
from crawlers._fetch.browser_session import render_html
from crawlers.marts.source_utils import compute_canon_hash, normalize_costco_url, normalize_lottemart_url
from storage.db import DBStorage
from storage.models import Product

MART_ORDER = ("emart", "homeplus", "lottemart", "costco")
FIXTURES = CRAWLER_BACKEND / "tests" / "fixtures"
REPORT_PATH = REPO_ROOT / "devlog" / "round-R" / "g1-seed-report.md"
BOT_TEXT = (
    "captcha", "access denied", "bot", "blocked", "forbidden", "awswaf", "aws waf",
    "cloudflare", "비정상", "자동화", "보안문자", "접근이 제한",
)
DEFAULT_DB_URL = "sqlite:///" + (DB_BACKEND / "walletguardian.db").as_posix()


@dataclass
class MartRun:
    mart: str
    mode: str = "fixture"
    reason: str = ""
    attempted_urls: list[str] = field(default_factory=list)
    parsed: int = 0
    saved: int = 0


def _db_url() -> str:
    return os.getenv("DB_ADMIN_DATABASE_URL") or os.getenv("DATABASE_URL") or DEFAULT_DB_URL


def _limited(values: Iterable[Any], n: int = 2) -> list[Any]:
    return list(values)[:n]


def _bad_response(resp: requests.Response) -> str | None:
    if resp.status_code >= 400:
        return f"HTTP {resp.status_code}"
    sample = (resp.text or "")[:20000].lower()
    for marker in BOT_TEXT:
        if marker in sample:
            return f"bot/block marker: {marker}"
    return None


async def _fetch_pages(requests_to_make: list[dict[str, Any]], timeout: int = 20) -> tuple[list[dict[str, Any]], str]:
    pages: list[dict[str, Any]] = []
    consecutive_bad = 0
    last_reason = ""
    for req in requests_to_make:
        url = str(req["url"])
        try:
            html, diag = await render_html(
                url,
                wait_selector=str(req.get("wait_selector") or "body"),
                scroll_selector=str(req.get("scroll_selector") or req.get("wait_selector") or "body"),
                scroll=bool(req.get("scroll", True)),
                headless=False,
                timeout=timeout * 1000,
                extra_http_headers={"Referer": str(req.get("referer") or url)},
            )
        except Exception as exc:
            consecutive_bad += 1
            last_reason = f"browser fetch error fetching {url}: {type(exc).__name__}: {exc}"
            if consecutive_bad >= 3:
                return pages, last_reason
            continue
        sample = (html or "")[:20000].lower()
        marker = next((m for m in BOT_TEXT if m in sample), None)
        if marker:
            consecutive_bad += 1
            last_reason = f"bot/block marker: {marker} fetching {url}"
            if consecutive_bad >= 3:
                return pages, last_reason
            continue
        consecutive_bad = 0
        pages.append({**req, "html": html, "status_code": diag.get("status_code"), "final_url": diag.get("final_url")})
    return pages, last_reason


def _extract_pack(name: str) -> tuple[float | None, str | None]:
    match = re.search(r"(\d+(?:\.\d+)?)\s*(kg|g|ml|l|L|개|봉|팩|입|매)", name or "", re.I)
    if not match:
        return None, None
    qty: float | int = float(match.group(1))
    if float(qty).is_integer():
        qty = int(qty)
    return float(qty), match.group(2)


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text_value = str(value)
    nums = re.findall(r"[0-9][0-9,]*(?:\.\d+)?", text_value)
    if not nums:
        return None
    return float(nums[-1].replace(",", ""))


def _clean_native(mart: str, native: Any, detail_url: str = "") -> str:
    value = str(native or "").strip()
    if mart == "lottemart":
        os_match = re.search(r"OS(\d{13})", value) or re.search(r"OS(\d{13})", detail_url or "")
        if os_match:
            return os_match.group(1)
        ean = re.search(r"\b(\d{13})\b", value)
        if ean:
            return ean.group(1)
        return "" if re.fullmatch(r"[0-9a-fA-F-]{36}", value) else value
    if mart == "costco":
        p_match = re.search(r"/p/(\d+)", detail_url or value)
        return p_match.group(1) if p_match else re.sub(r"\D", "", value)
    return value


def _item_record(mart: str, item: Any, category_id: str = "", category_path: str = "") -> dict[str, Any] | None:
    attrs = dict(getattr(item, "attributes", {}) or {})
    name = str(getattr(item, "name", "") or attrs.get("name") or attrs.get("raw_name") or "").strip()
    if not name:
        return None
    detail_url = str(attrs.get("canonical_url") or attrs.get("source_url") or getattr(item, "detail_url", "") or "")
    native = _clean_native(mart, attrs.get("mart_native_code") or attrs.get("source_record_key"), detail_url)
    if not native:
        return None
    pack_qty = attrs.get("pack_qty") or attrs.get("package_quantity") or getattr(item, "package_quantity", None)
    pack_unit = attrs.get("pack_unit") or attrs.get("package_unit") or getattr(item, "package_unit", "")
    if not pack_qty or not pack_unit:
        pack_qty, pack_unit = _extract_pack(name)
    normalized_name = str(attrs.get("normalized_name") or getattr(item, "normalized_name", "") or re.sub(r"\s+", " ", name).strip())
    brand = attrs.get("brand")
    canon_hash = attrs.get("canon_hash") or compute_canon_hash(brand, normalized_name, pack_qty, pack_unit)
    path = str(attrs.get("mart_native_category_path") or category_path or "")
    if not path:
        cat_parts = attrs.get("category_path")
        if isinstance(cat_parts, list):
            path = " > ".join(str(x) for x in cat_parts if x)
        else:
            path = str(getattr(item, "category", "") or attrs.get("category_hint") or "")
    cat_id = str(attrs.get("mart_native_category_id") or category_id or (path.split(" > ")[0] if path else ""))
    source = str(attrs.get("source") or mart)
    return {
        "mart": mart,
        "mart_native_code": native,
        "canon_hash": str(canon_hash),
        "external_seller": bool(attrs.get("external_seller", False)),
        "unit_price_displayed": _to_float(attrs.get("unit_price_displayed") or attrs.get("unit_price")),
        "unit_price_basis_raw": str(attrs.get("unit_price_basis_raw") or attrs.get("unit_price_basis") or "")[:16] or None,
        "mart_native_category_id": cat_id[:64] or None,
        "mart_native_category_path": path[:500] or None,
        "canonical_url": detail_url[:500] or None,
        "source": source,
        "name": name,
        "normalized_name": normalized_name,
        "brand": str(brand)[:200] if brand else None,
        "pack_qty": _to_float(pack_qty),
        "pack_unit": str(pack_unit or "")[:50] or None,
        "sale_price": _to_float(getattr(item, "sale_price", None)),
        "original_price": _to_float(getattr(item, "original_price", None)),
        "image_url": str(attrs.get("image_url") or getattr(item, "image_url", "") or "")[:500] or None,
        "attributes": attrs,
    }


def _lottemart_records_from_initial_state(html: str, limit: int) -> list[dict[str, Any]]:
    match = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*;\s*</script>", html, re.S)
    if not match:
        return []
    try:
        state = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    entities = (((state.get("data") or {}).get("products") or {}).get("productEntities") or {})
    out: list[dict[str, Any]] = []
    for product in entities.values():
        if not isinstance(product, dict):
            continue
        raw_code = str(product.get("retailerProductId") or product.get("stdGoodsCd") or product.get("code") or "")
        native = _clean_native("lottemart", raw_code)
        if not native:
            continue
        name = re.sub(r"^\[.*?\]\s*", "", str(product.get("name") or "")).strip()
        price = product.get("price") if isinstance(product.get("price"), dict) else {}
        current = price.get("current") if isinstance(price.get("current"), dict) else {}
        original = price.get("original") if isinstance(price.get("original"), dict) else {}
        unit = price.get("unit") if isinstance(price.get("unit"), dict) else {}
        category_parts = product.get("categoryPath") if isinstance(product.get("categoryPath"), list) else []
        pack_qty, pack_unit = _extract_pack(name)
        brand = str(product.get("brand") or "") or None
        detail_url = normalize_lottemart_url(native)
        path = " > ".join(str(x) for x in category_parts if x)
        unit_amount = _to_float((unit.get("current") or {}).get("amount") if isinstance(unit.get("current"), dict) else None)
        basis = ""
        label = str(unit.get("label") or "")
        if "100gram" in label:
            basis = "100g"
        elif "each" in label:
            basis = "1개"
        rec = {
            "mart": "lottemart", "mart_native_code": native, "name": name,
            "normalized_name": name, "brand": brand, "pack_qty": pack_qty, "pack_unit": pack_unit,
            "canon_hash": compute_canon_hash(brand, name, pack_qty, pack_unit),
            "external_seller": False,
            "unit_price_displayed": unit_amount,
            "unit_price_basis_raw": basis or None,
            "mart_native_category_id": str(category_parts[0])[:64] if category_parts else None,
            "mart_native_category_path": path[:500] if path else None,
            "canonical_url": detail_url,
            "source": "lottemart",
            "sale_price": _to_float(current.get("amount")),
            "original_price": _to_float(original.get("amount")),
            "image_url": ((product.get("image") or {}).get("src") if isinstance(product.get("image"), dict) else None),
            "attributes": {"source": "lottemart", "mart_native_code": native, "canonical_url": detail_url, "category_path": category_parts},
        }
        out.append(rec)
        if len(out) >= limit:
            break
    return out


async def _seed_emart(use_fixtures_only: bool, fixture_fallback: bool, max_items: int) -> tuple[list[dict[str, Any]], MartRun]:
    crawler = EmartCrawler()
    cats = _limited(crawler.CATEGORY_IDS.items())
    run = MartRun("emart")
    html_pages: list[dict[str, Any]] = []
    if not use_fixtures_only:
        reqs = []
        for cat_id, cat_path in cats:
            for page in range(1, 3):
                url = crawler._category_url(cat_id, page)
                reqs.append({"url": url, "category_id": cat_id, "category_path": cat_path, "wait_selector": 'a[href*="itemView.ssg"]', "scroll_selector": 'a[href*="itemView.ssg"]', "referer": crawler.BASE_URL + "/"})
                run.attempted_urls.append(url)
        html_pages, reason = await _fetch_pages(reqs)
        run.reason = reason
    records: list[dict[str, Any]] = []
    for page in html_pages:
        items = await crawler.parse(str(page["html"]), category_id=str(page["category_id"]), category_path=str(page["category_path"]))
        records.extend(filter(None, (_item_record("emart", item, str(page["category_id"]), str(page["category_path"])) for item in items)))
        if len(records) >= max_items:
            break
    if records:
        run.mode = "live"
    elif use_fixtures_only or fixture_fallback:
        run.mode = "fixture"
        run.reason = run.reason or "live produced no parseable products (JS-required/blocked/empty)"
        fixture = (FIXTURES / "emart_category_sample.html").read_text(encoding="utf-8")
        # The checked-in fixture captures one category page. Reuse it once so
        # idempotent upserts do not oscillate the same native codes across paths.
        cat_id, cat_path = cats[0]
        items = await crawler.parse(fixture, category_id=str(cat_id), category_path=str(cat_path))
        records.extend(filter(None, (_item_record("emart", item, str(cat_id), str(cat_path)) for item in items)))
    else:
        run.mode = "live-blocked"
        run.reason = run.reason or "live produced no parseable products; rerun on user PC with headed browser or add --fixture-fallback"
    run.parsed = len(records[:max_items])
    return records[:max_items], run


async def _seed_homeplus(use_fixtures_only: bool, fixture_fallback: bool, max_items: int) -> tuple[list[dict[str, Any]], MartRun]:
    crawler = HomeplusCrawler(max_scroll_attempts=2)
    cat_ids = [1, 2]
    run = MartRun("homeplus")
    records: list[dict[str, Any]] = []
    if not use_fixtures_only:
        reqs = []
        for cat_id in cat_ids:
            for page in range(1, 3):
                url = f"{crawler.MFRONT_URL}/list?categoryDepth=0&categoryId={cat_id}&page={page}"
                reqs.append({"url": url, "category_id": str(cat_id), "category_path": str(cat_id), "wait_selector": ".unitItemInner", "scroll_selector": ".unitItemInner", "referer": crawler.MFRONT_URL + "/"})
                run.attempted_urls.append(url)
        html_pages, reason = await _fetch_pages(reqs)
        run.reason = reason
        for page in html_pages:
            items = await crawler.parse(str(page["html"]), store_type="HYPER")
            records.extend(filter(None, (_item_record("homeplus", item, str(page["category_id"]), str(getattr(item, "category", "") or page["category_path"])) for item in items)))
            if len(records) >= max_items:
                break
    if records:
        run.mode = "live"
    elif use_fixtures_only or fixture_fallback:
        run.mode = "fixture"
        run.reason = run.reason or "HTTP list page produced no .unitItemInner cards (JS-required/blocked/empty)"
        for fixture_name, store_type in (("homeplus_list_sample.html", "HYPER"), ("homeplus_express_list_sample.html", "EXP")):
            html = (FIXTURES / fixture_name).read_text(encoding="utf-8")
            items = await crawler.parse(html, store_type=store_type)
            records.extend(filter(None, (_item_record("homeplus", item, "1", str(getattr(item, "category", "") or "식품")) for item in items)))
            if len(records) >= max_items:
                break
    else:
        run.mode = "live-blocked"
        run.reason = run.reason or "live produced no .unitItemInner cards; rerun on user PC with headed browser or add --fixture-fallback"
    run.parsed = len(records[:max_items])
    return records[:max_items], run


async def _seed_lottemart(use_fixtures_only: bool, fixture_fallback: bool, max_items: int) -> tuple[list[dict[str, Any]], MartRun]:
    crawler = LottemartCrawler()
    queries = _limited(crawler.CATEGORY_QUERIES)
    run = MartRun("lottemart")
    records: list[dict[str, Any]] = []
    if not use_fixtures_only:
        reqs = []
        for query in queries:
            for page in range(1, 3):
                url = f"{crawler.ZETTA_BASE}/search?query={quote(query)}&page={page}"
                reqs.append({"url": url, "category_id": query, "category_path": query, "wait_selector": ".product-card-container", "scroll_selector": ".product-card-container", "referer": crawler.ZETTA_BASE + "/"})
                run.attempted_urls.append(url)
        html_pages, reason = await _fetch_pages(reqs)
        run.reason = reason
        for page in html_pages:
            direct = _lottemart_records_from_initial_state(str(page["html"]), max_items - len(records))
            records.extend(direct)
            if len(records) >= max_items:
                break
    if records:
        run.mode = "live"
    elif use_fixtures_only or fixture_fallback:
        run.mode = "fixture"
        run.reason = run.reason or "live produced no parseable productEntities (JS-required/blocked/empty)"
        for fixture_name in ("lottemart\\hydrated_5cards.html", "live_probe\\lottemart_hydrated_promotions.html"):
            path = FIXTURES / fixture_name
            if not path.exists():
                continue
            records.extend(_lottemart_records_from_initial_state(path.read_text(encoding="utf-8"), max_items - len(records)))
            if len(records) >= max_items:
                break
    else:
        run.mode = "live-blocked"
        run.reason = run.reason or "live produced no productEntities; rerun on user PC with headed browser or add --fixture-fallback"
    run.parsed = len(records[:max_items])
    return records[:max_items], run


async def _seed_costco(use_fixtures_only: bool, fixture_fallback: bool, max_items: int) -> tuple[list[dict[str, Any]], MartRun]:
    cats = [("cos_10", "식품"), ("cos_10.1", "식품 > 쌀/잡곡")]
    run = MartRun("costco")
    records: list[dict[str, Any]] = []
    if not use_fixtures_only:
        reqs = []
        for cat_id, cat_path in cats:
            for page in range(0, 2):
                suffix = f"?currentPage={page}" if page else ""
                url = f"{COSTCO_BASE_URL}/c/{cat_id}{suffix}"
                reqs.append({"url": url, "category_id": cat_id, "category_path": cat_path, "wait_selector": 'a[href*="/p/"]', "scroll_selector": 'a[href*="/p/"]', "referer": COSTCO_BASE_URL + "/"})
                run.attempted_urls.append(url)
        html_pages, reason = await _fetch_pages(reqs)
        run.reason = reason
        for page in html_pages:
            cards = parse_costco_listing(str(page["html"]), category_id=str(page["category_id"]), category_path=str(page["category_path"]))
            items = cards_to_discount_items(cards, source_url=str(page["url"]))
            records.extend(filter(None, (_item_record("costco", item, str(page["category_id"]), str(page["category_path"])) for item in items)))
            if len(records) >= max_items:
                break
    if records:
        run.mode = "live"
    elif use_fixtures_only or fixture_fallback:
        run.mode = "fixture"
        run.reason = run.reason or "live produced no parseable /p/ product cards (JS-required/blocked/empty)"
        occ_path = FIXTURES / "costco" / "occ_products_3items.json"
        data = json.loads(occ_path.read_text(encoding="utf-8"))
        cards = parse_costco_occ_response(data)
        for index, card in enumerate(cards):
            cat_id, cat_path = cats[min(index, len(cats) - 1)]
            card.mart_native_category_id = cat_id
            card.mart_native_category_path = cat_path
            if not card.canonical_url and card.mart_native_code:
                card.canonical_url = normalize_costco_url("/p", card.mart_native_code)
        items = cards_to_discount_items(cards, source_url=f"{COSTCO_BASE_URL}/c/cos_10")
        records = list(filter(None, (_item_record("costco", item, item.attributes.get("mart_native_category_id", "cos_10"), item.attributes.get("mart_native_category_path", "식품")) for item in items)))
    else:
        run.mode = "live-blocked"
        run.reason = run.reason or "live produced no /p/ cards; rerun on user PC with headed browser or add --fixture-fallback"
    run.parsed = len(records[:max_items])
    return records[:max_items], run


def _ensure_schema(storage: DBStorage) -> None:
    storage.init_db()
    existing = {col["name"] for col in inspect(storage.engine).get_columns("products")}
    ddl = {
        "mart": "ALTER TABLE products ADD COLUMN mart VARCHAR(20)",
        "mart_native_code": "ALTER TABLE products ADD COLUMN mart_native_code VARCHAR(64)",
        "canon_hash": "ALTER TABLE products ADD COLUMN canon_hash VARCHAR(40)",
        "external_seller": "ALTER TABLE products ADD COLUMN external_seller BOOLEAN",
        "unit_price_displayed": "ALTER TABLE products ADD COLUMN unit_price_displayed FLOAT",
        "unit_price_basis_raw": "ALTER TABLE products ADD COLUMN unit_price_basis_raw VARCHAR(16)",
        "mart_native_category_id": "ALTER TABLE products ADD COLUMN mart_native_category_id VARCHAR(64)",
        "mart_native_category_path": "ALTER TABLE products ADD COLUMN mart_native_category_path VARCHAR(500)",
        "canonical_url": "ALTER TABLE products ADD COLUMN canonical_url VARCHAR(500)",
        "mart_internal_seller_id": "ALTER TABLE products ADD COLUMN mart_internal_seller_id VARCHAR(64)",
    }
    with storage.engine.begin() as conn:
        for col, stmt in ddl.items():
            if col not in existing:
                conn.execute(text(stmt))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_products_mart_native ON products (mart, mart_native_code)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_products_mart ON products (mart)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_products_mart_native_category_id ON products (mart_native_category_id)"))


def _upsert_products(storage: DBStorage, records: list[dict[str, Any]]) -> dict[str, int]:
    saved: dict[str, int] = {mart: 0 for mart in MART_ORDER}
    with storage.SessionLocal() as session:
        for rec in records:
            product = session.query(Product).filter(
                Product.mart == rec["mart"], Product.mart_native_code == rec["mart_native_code"]
            ).one_or_none()
            created = product is None
            if product is None:
                product = Product(name=rec["name"], unit=rec.get("pack_unit") or "개")
                session.add(product)
            product.name = rec["name"]
            product.unit = rec.get("pack_unit") or product.unit or "개"
            product.image_url = rec.get("image_url")
            product.attributes = rec.get("attributes") or {}
            product.is_active = True
            product.source_type = "mart_crawl"
            product.categorization_method = "none"
            product.mart = rec["mart"]
            product.mart_native_code = rec["mart_native_code"]
            product.canon_hash = rec["canon_hash"]
            product.external_seller = rec["external_seller"]
            product.unit_price_displayed = rec.get("unit_price_displayed")
            product.unit_price_basis_raw = rec.get("unit_price_basis_raw")
            product.mart_native_category_id = rec.get("mart_native_category_id")
            product.mart_native_category_path = rec.get("mart_native_category_path")
            product.canonical_url = rec.get("canonical_url")
            product.brand = rec.get("brand") or rec["mart"]
            product.name_core = rec.get("normalized_name") or rec["name"]
            product.pack_qty = rec.get("pack_qty")
            product.pack_unit = rec.get("pack_unit")
            product.unit_kind = None
            product.display_name = rec["name"]
            product.source_marts = [rec["mart"]]
            product.updated_at = datetime.utcnow()
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                if created:
                    product = Product(name=rec["name"], unit=rec.get("pack_unit") or "개")
                    session.add(product)
                product.name_core = f"{rec.get('normalized_name') or rec['name']} [{rec['mart']}:{rec['mart_native_code']}]"
                product.name = rec["name"]
                product.unit = rec.get("pack_unit") or "개"
                product.image_url = rec.get("image_url")
                product.attributes = rec.get("attributes") or {}
                product.is_active = True
                product.source_type = "mart_crawl"
                product.categorization_method = "none"
                product.mart = rec["mart"]
                product.mart_native_code = rec["mart_native_code"]
                product.canon_hash = rec["canon_hash"]
                product.external_seller = rec["external_seller"]
                product.unit_price_displayed = rec.get("unit_price_displayed")
                product.unit_price_basis_raw = rec.get("unit_price_basis_raw")
                product.mart_native_category_id = rec.get("mart_native_category_id")
                product.mart_native_category_path = rec.get("mart_native_category_path")
                product.canonical_url = rec.get("canonical_url")
                product.brand = rec.get("brand") or rec["mart"]
                product.pack_qty = rec.get("pack_qty")
                product.pack_unit = rec.get("pack_unit")
                product.display_name = rec["name"]
                product.source_marts = [rec["mart"]]
                product.updated_at = datetime.utcnow()
                session.commit()
            saved[rec["mart"]] = saved.get(rec["mart"], 0) + 1
    return saved


def _query_rows(storage: DBStorage) -> dict[str, list[tuple[Any, ...]]]:
    queries = {
        "counts": "SELECT mart, COUNT(*) FROM products WHERE mart IS NOT NULL GROUP BY mart ORDER BY mart",
        "category_counts": "SELECT mart, COUNT(DISTINCT mart_native_category_path) FROM products WHERE mart IS NOT NULL GROUP BY mart ORDER BY mart",
        "sample": "SELECT mart, mart_native_code, mart_native_category_path, unit_price_displayed, unit_price_basis_raw FROM products WHERE mart IS NOT NULL ORDER BY mart, mart_native_code LIMIT 12",
    }
    out: dict[str, list[tuple[Any, ...]]] = {}
    with storage.engine.connect() as conn:
        for name, sql in queries.items():
            out[name] = [tuple(row) for row in conn.execute(text(sql)).all()]
    return out


def _rows_as_markdown(rows: list[tuple[Any, ...]], headers: list[str]) -> str:
    if not rows:
        return "_(no rows)_\n"
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(v) if v is not None else "" for v in row) + " |")
    return "\n".join(lines) + "\n"


def _write_report(runs: list[MartRun], validation: dict[str, list[tuple[Any, ...]]], db_url: str) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    live_table = [(r.mart, r.mode, r.reason or "-") for r in runs]
    text_body = f"""# Round R G1 Seed Report

Generated: {datetime.now().isoformat(timespec='seconds')}

## Live vs fixture
{_rows_as_markdown(live_table, ['mart', 'mode', 'reason'])}

## Counts per mart
{_rows_as_markdown(validation['counts'], ['mart', 'count'])}

## Distinct native category paths
{_rows_as_markdown(validation['category_counts'], ['mart', 'distinct_category_paths'])}

## Sample dump (new columns visible)
{_rows_as_markdown(validation['sample'][:10], ['mart', 'mart_native_code', 'mart_native_category_path', 'unit_price_displayed', 'unit_price_basis_raw'])}

## Reproduction one-liner
`py -3 packages\\crawler-admin\\backend\\scripts\\round_r_g1_seed.py --live --marts emart --limit 5`

DB URL used: `{db_url}`

## Blockers encountered
{'; '.join(f'{r.mart}: {r.reason}' for r in runs if r.reason) or 'None'}
"""
    REPORT_PATH.write_text(text_body, encoding="utf-8")


def _update_todo(status: str) -> None:
    for path in (REPO_ROOT / "ai_control.db", REPO_ROOT / "packages" / "ai-admin" / "backend" / "ai_control.db"):
        if not path.exists():
            continue
        try:
            conn = sqlite3.connect(path)
            try:
                tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if "todos" in tables:
                    conn.execute("UPDATE todos SET status=? WHERE id='g1-seed'", (status,))
                    conn.commit()
            finally:
                conn.close()
        except sqlite3.Error:
            continue


def _selected_marts(args: argparse.Namespace) -> list[str]:
    raw = args.marts or ([args.mart] if args.mart else [])
    if isinstance(raw, str):
        raw = [raw]
    selected: list[str] = []
    for value in raw:
        for mart in str(value).split(","):
            mart = mart.strip()
            if mart and mart not in selected:
                selected.append(mart)
    return selected or list(MART_ORDER)


async def run(args: argparse.Namespace) -> int:
    selected = _selected_marts(args)
    runners: dict[str, Callable[[bool, bool, int], Any]] = {
        "emart": _seed_emart,
        "homeplus": _seed_homeplus,
        "lottemart": _seed_lottemart,
        "costco": _seed_costco,
    }
    all_records: list[dict[str, Any]] = []
    runs: list[MartRun] = []
    for mart in MART_ORDER:
        if mart not in selected:
            continue
        records, run_info = await runners[mart](args.use_fixtures_only, args.fixture_fallback, args.max_items)
        all_records.extend(records)
        runs.append(run_info)
        print(f"{mart}: {run_info.mode}, parsed={run_info.parsed}, reason={run_info.reason or '-'}")

    db_url = _db_url()
    storage = DBStorage(db_url)
    _ensure_schema(storage)
    saved = _upsert_products(storage, all_records)
    for run_info in runs:
        run_info.saved = saved.get(run_info.mart, 0)
    validation = _query_rows(storage)
    _write_report(runs, validation, db_url)

    print("\nValidation: counts")
    for row in validation["counts"]:
        print(row)
    print("\nValidation: distinct category paths")
    for row in validation["category_counts"]:
        print(row)
    print("\nValidation: sample")
    for row in validation["sample"]:
        print(row)

    any_seeded = any(run.parsed for run in runs)
    _update_todo("done" if any_seeded else "blocked")
    print(f"\nReport written: {REPORT_PATH}")
    return 0 if any_seeded else 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Round R G1 limited live/fixture mart seeder")
    parser.add_argument("--mart", choices=MART_ORDER, help="Only seed one mart (legacy alias)")
    parser.add_argument("--marts", nargs="+", choices=MART_ORDER, help="Seed one or more marts")
    parser.add_argument("--max-items", "--limit", dest="max_items", type=int, default=50, help="Max products per mart")
    parser.add_argument("--live", action="store_true", help="Use live browser fetches (default)")
    parser.add_argument("--fixture-fallback", action="store_true", help="Fallback to fixtures when live browser fetch yields zero products")
    parser.add_argument("--use-fixtures-only", action="store_true", help="Skip live browser fetch and seed from fixtures")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.max_items < 1:
        raise SystemExit("--max-items must be >= 1")
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
