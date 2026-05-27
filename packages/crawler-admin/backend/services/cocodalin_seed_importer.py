"""Import Cocodalin Costco discount seed data into price_history.

Cocodalin currently emits Costco discount records as DiscountItem dictionaries
(name, original_price, sale_price, valid_from, valid_until, detail_url) or raw API
rows (product_name, normal_price, sale_price, from_date, to_date).  If future
exports include Costco /p/<digits> identifiers, those are preferred for matching;
otherwise names are normalized and fuzzy matched against existing Costco Product
rows.
"""
from __future__ import annotations

import asyncio
import csv
import json
import logging
import re
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_DB_ADMIN_BACKEND = _BACKEND_DIR.parents[1] / "db-admin" / "backend"
if str(_DB_ADMIN_BACKEND) not in sys.path:
    sys.path.insert(0, str(_DB_ADMIN_BACKEND))

from storage.models import PriceHistory, Product  # noqa: E402

logger = logging.getLogger(__name__)

MART = "costco"
FUZZY_THRESHOLD = 0.85
_NATIVE_CODE_RE = re.compile(r"(?:/p/)?(?P<code>\d{4,})(?:[/?#]|$)")
_BRACKET_RE = re.compile(r"\[[^\]]+\]|\([^)]*(?:행사|할인|쿠폰|특가|온라인)[^)]*\)")
_PROMO_RE = re.compile(r"\b(?:행사|할인|쿠폰|특가|온라인|코스트코|costco)\b", re.IGNORECASE)
_SPACE_RE = re.compile(r"\s+")


@dataclass
class ImportReport:
    total_input: int = 0
    matched_by_native_code: int = 0
    matched_by_name: int = 0
    unmatched: int = 0
    inserted: int = 0
    skipped_duplicates: int = 0
    errors: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def import_cocodalin_seed(
    db_session: Session,
    source_path: Path | None = None,
    dry_run: bool = False,
) -> ImportReport:
    """Import Cocodalin historical Costco discounts into PriceHistory.

    Args:
        db_session: SQLAlchemy session bound to the db-admin schema.
        source_path: Optional JSON or CSV export. If omitted, the live Cocodalin
            crawler is executed and its CrawlResult.items are imported.
        dry_run: When true, computes the report without writing rows.
    """
    report = ImportReport()
    rows = list(_load_source_rows(source_path))
    products = _load_costco_products(db_session)
    by_native = _products_by_native_code(products)
    by_name = _products_by_normalized_name(products)
    seen_new_keys: set[tuple[str, str, datetime]] = set()

    for row in rows:
        try:
            entries = list(_history_entries(row))
            if not entries:
                report.errors += 1
                logger.warning("[cocodalin-seed] no importable price entry: %s", row)
                continue

            for entry in entries:
                report.total_input += 1
                product, match_kind = _match_product(entry, by_native, by_name)
                if product is None:
                    report.unmatched += 1
                    logger.info(
                        "[cocodalin-seed] unmatched product native=%r name=%r",
                        _native_code_from_row(entry),
                        _name_from_row(entry),
                    )
                    continue

                if match_kind == "native_code":
                    report.matched_by_native_code += 1
                else:
                    report.matched_by_name += 1

                canon_key = product.mart_native_code or product.canon_hash
                if not canon_key:
                    report.errors += 1
                    logger.warning("[cocodalin-seed] matched product without canon key: id=%s", product.id)
                    continue

                observed_at = _observed_at(entry)
                key = (MART, str(canon_key), observed_at)
                if key in seen_new_keys or _price_history_exists(db_session, key):
                    report.skipped_duplicates += 1
                    continue
                seen_new_keys.add(key)

                if not dry_run:
                    db_session.add(
                        PriceHistory(
                            mart=MART,
                            canon_key=str(canon_key),
                            observed_at=observed_at,
                            price=float(_price_from_row(entry)),
                            sale_price=_optional_float(_sale_price_from_row(entry)),
                            unit_price=_optional_float(_first_present(entry, "unit_price", "price_per_100g")),
                            period_start=_datetime_from_any(_first_present(entry, "period_start", "from_date", "valid_from")),
                            period_end=_datetime_from_any(_first_present(entry, "period_end", "to_date", "valid_until")),
                            source_run_id=str(_first_present(entry, "source_run_id", "run_id", "crawl_run_id") or "cocodalin-seed"),
                        )
                    )
                    report.inserted += 1
                else:
                    report.inserted += 1
        except Exception as exc:  # keep batch import resilient
            report.errors += 1
            logger.exception("[cocodalin-seed] failed to process row: %s", exc)

    if not dry_run:
        try:
            db_session.commit()
        except IntegrityError:
            db_session.rollback()
            report.errors += 1
            logger.exception("[cocodalin-seed] commit failed due to integrity error")
            raise

    return report


def _load_source_rows(source_path: Path | None) -> Iterable[dict[str, Any]]:
    if source_path is None:
        yield from _load_live_cocodalin_rows()
        return

    path = Path(source_path)
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            yield from csv.DictReader(fh)
        return

    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    yield from _rows_from_json_payload(payload)


def _load_live_cocodalin_rows() -> list[dict[str, Any]]:
    from crawlers.marts.cocodalin.crawler import CocodalinCrawler

    result = asyncio.run(CocodalinCrawler().crawl())
    return [row for row in getattr(result, "items", []) if isinstance(row, dict)]


def _rows_from_json_payload(payload: Any) -> Iterable[dict[str, Any]]:
    if isinstance(payload, list):
        for row in payload:
            if isinstance(row, dict):
                yield row
        return
    if isinstance(payload, dict):
        for key in ("items", "data", "products", "rows", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                for row in value:
                    if isinstance(row, dict):
                        yield row
                return
        yield payload


def _history_entries(row: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for key in ("price_history", "history", "prices", "discount_history"):
        value = row.get(key)
        if isinstance(value, list):
            for child in value:
                if isinstance(child, dict):
                    merged = dict(row)
                    merged.pop(key, None)
                    merged.update(child)
                    yield merged
            return
    yield row


def _load_costco_products(db_session: Session) -> list[Product]:
    return list(db_session.scalars(select(Product).where(Product.mart == MART)).all())


def _products_by_native_code(products: Iterable[Product]) -> dict[str, Product]:
    out: dict[str, Product] = {}
    for product in products:
        code = _normalize_native_code(product.mart_native_code)
        if code:
            out.setdefault(code, product)
    return out


def _products_by_normalized_name(products: Iterable[Product]) -> dict[str, Product]:
    out: dict[str, Product] = {}
    for product in products:
        for raw_name in (product.name, product.display_name, product.name_core):
            norm = normalize_cocodalin_name(raw_name or "")
            if norm:
                out.setdefault(norm, product)
    return out


def _match_product(
    row: dict[str, Any],
    by_native: dict[str, Product],
    by_name: dict[str, Product],
) -> tuple[Product | None, str | None]:
    native = _normalize_native_code(_native_code_from_row(row))
    if native and native in by_native:
        return by_native[native], "native_code"

    name = normalize_cocodalin_name(_name_from_row(row) or "")
    if not name:
        return None, None
    if name in by_name:
        return by_name[name], "name"

    best_product: Product | None = None
    best_score = 0.0
    for candidate, product in by_name.items():
        score = token_set_ratio(name, candidate)
        if score > best_score:
            best_score = score
            best_product = product
    if best_product is not None and best_score >= FUZZY_THRESHOLD:
        return best_product, "name"
    return None, None


def normalize_cocodalin_name(name: str) -> str:
    text = str(name or "").lower()
    text = _BRACKET_RE.sub(" ", text)
    text = _PROMO_RE.sub(" ", text)
    text = re.sub(r"[^0-9a-z가-힣]+", " ", text)
    return _SPACE_RE.sub(" ", text).strip()


def token_set_ratio(left: str, right: str) -> float:
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if not left_tokens or not right_tokens:
        return 0.0
    common = left_tokens & right_tokens
    left_diff = left_tokens - common
    right_diff = right_tokens - common
    sorted_common = " ".join(sorted(common))
    left_combined = " ".join(sorted(common | left_diff))
    right_combined = " ".join(sorted(common | right_diff))
    scores = [
        SequenceMatcher(None, left_combined, right_combined).ratio(),
    ]
    if sorted_common:
        scores.extend(
            SequenceMatcher(None, sorted_common, value).ratio()
            for value in (left_combined, right_combined)
            if value
        )
    return max(scores)


def _native_code_from_row(row: dict[str, Any]) -> str:
    attrs = row.get("attributes") if isinstance(row.get("attributes"), dict) else {}
    for source in (row, attrs):
        for key in (
            "mart_native_code",
            "cocodalin_join_key",
            "costco_product_code",
            "costco_code",
            "native_code",
            "product_code",
            "p_code",
            "code",
        ):
            value = source.get(key)
            if value:
                return str(value)
    for key in ("canonical_url", "detail_url", "url", "product_url"):
        value = row.get(key)
        if value and "/p/" in str(value):
            return str(value)
    return ""


def _normalize_native_code(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = _NATIVE_CODE_RE.search(text)
    return match.group("code") if match else text.removeprefix("/p/")


def _name_from_row(row: dict[str, Any]) -> str:
    for key in ("name", "product_name", "raw_name", "title", "normalized_name"):
        value = row.get(key)
        if value:
            return str(value)
    return ""


def _price_from_row(row: dict[str, Any]) -> float:
    value = _first_present(row, "price", "normal_price", "original_price", "regular_price", "sale_price")
    number = _optional_float(value)
    if number is None or number <= 0:
        raise ValueError(f"missing positive price: {row}")
    return number


def _sale_price_from_row(row: dict[str, Any]) -> Any:
    return _first_present(row, "sale_price", "discount_price", "price")


def _observed_at(row: dict[str, Any]) -> datetime:
    value = _first_present(row, "observed_at", "crawled_at", "date", "from_date", "valid_from", "period_start")
    parsed = _datetime_from_any(value)
    if parsed is None:
        return datetime.utcnow()
    return datetime.combine(parsed.date(), time.min)


def _price_history_exists(db_session: Session, key: tuple[str, str, datetime]) -> bool:
    mart, canon_key, observed_at = key
    return db_session.scalar(
        select(PriceHistory.id).where(
            PriceHistory.mart == mart,
            PriceHistory.canon_key == canon_key,
            PriceHistory.observed_at == observed_at,
        )
    ) is not None


def _first_present(row: dict[str, Any], *keys: str) -> Any:
    attrs = row.get("attributes") if isinstance(row.get("attributes"), dict) else {}
    for source in (row, attrs):
        for key in keys:
            value = source.get(key)
            if value not in (None, ""):
                return value
    return None


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").replace("원", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def _datetime_from_any(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    for parser in (datetime.fromisoformat,):
        try:
            return parser(text)
        except ValueError:
            pass
    for fmt in ("%Y.%m.%d", "%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None
