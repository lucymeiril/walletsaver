"""Round R G3 auto classification pipeline for mart crawler products."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone, timedelta
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.name_normalize import compute_canon_hash, normalize_name_core
from storage.models import MartCategoryMapping, PriceHistory, Product

MARTS = {"emart", "homeplus", "lottemart", "costco"}
AUTO_TRUST = "auto-aggregate"
HUMAN_CATEGORY_METHODS = {"human", "manual", "corrected"}


@dataclass(slots=True)
class RawProduct:
    mart: str
    mart_native_code: str
    raw_name: str
    canon_hash: str | None = None
    mart_native_category_id: str | None = None
    mart_native_category_path: str | None = None
    canonical_url: str | None = None
    tracking_url: str | None = None
    brand: str | None = None
    normalized_name: str | None = None
    price: float | None = None
    sale_price: float | None = None
    unit_price: float | None = None
    unit_price_basis: str | None = None
    observed_at: datetime | None = None
    crawled_at: datetime | None = None
    pack_qty: float | None = None
    pack_unit: str | None = None
    pack_count: int | None = None
    external_seller: bool | None = None
    mart_internal_seller_id: str | None = None
    promo_label: str | None = None
    promo_type: str | None = None
    source_run_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "RawProduct":
        payload = dict(data)
        aliases = {
            "source": "mart",
            "name": "raw_name",
            "product_name": "raw_name",
            "title": "raw_name",
            "native_code": "mart_native_code",
            "item_id": "mart_native_code",
            "itemNo": "mart_native_code",
            "native_category_id": "mart_native_category_id",
            "native_category_path": "mart_native_category_path",
            "unit_price_displayed": "unit_price",
            "unit_price_basis_raw": "unit_price_basis",
            "promotion_type": "promo_type",
        }
        for src, dst in aliases.items():
            if src in payload and dst not in payload:
                payload[dst] = payload[src]

        field_names = set(cls.__dataclass_fields__) - {"extra"}
        known = {key: payload.pop(key) for key in list(payload.keys()) if key in field_names}
        for dt_key in ("observed_at", "crawled_at"):
            if isinstance(known.get(dt_key), str):
                known[dt_key] = _parse_datetime(known[dt_key])
        if not known.get("raw_name"):
            known["raw_name"] = known.get("normalized_name") or known.get("mart_native_code") or "unknown"
        known["mart"] = str(known.get("mart") or "").strip()
        known["mart_native_code"] = str(known.get("mart_native_code") or "").strip()
        known["extra"] = payload
        return cls(**known)


@dataclass(slots=True)
class AutoClassifySummary:
    total: int = 0
    classified: int = 0
    unclassified: int = 0
    new_products: int = 0
    updated_products: int = 0
    unchanged_products: int = 0
    human_preserved: int = 0
    price_history_inserted: int = 0
    price_history_skipped: int = 0
    canon_groups: int = 0
    dry_run: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "classified": self.classified,
            "unclassified": self.unclassified,
            "new_products": self.new_products,
            "updated_products": self.updated_products,
            "unchanged_products": self.unchanged_products,
            "human_preserved": self.human_preserved,
            "price_history_inserted": self.price_history_inserted,
            "price_history_skipped": self.price_history_skipped,
            "canon_groups": self.canon_groups,
            "dry_run": self.dry_run,
        }


def _parse_datetime(value: str) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _as_utc_naive(dt: datetime | None) -> datetime:
    if dt is None:
        return datetime.now(timezone.utc).replace(tzinfo=None)
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def week_start(value: datetime | date) -> date:
    base = value.date() if isinstance(value, datetime) else value
    return base - timedelta(days=base.weekday())


def _canon_key(raw: RawProduct) -> str:
    return raw.mart_native_code or raw.canon_hash or f"{raw.mart}:{raw.raw_name}"


def _has_human_category(product: Product) -> bool:
    return bool(product.unified_category_id and product.categorization_method in HUMAN_CATEGORY_METHODS)


def _find_mapping(session: Session, raw: RawProduct) -> MartCategoryMapping | None:
    if not raw.mart_native_category_id:
        return None
    return session.scalar(
        select(MartCategoryMapping).where(
            MartCategoryMapping.mart == raw.mart,
            MartCategoryMapping.mart_native_id == raw.mart_native_category_id,
        )
    )


def _find_product(session: Session, raw: RawProduct) -> Product | None:
    product = session.scalar(
        select(Product).where(
            Product.mart == raw.mart,
            Product.mart_native_code == raw.mart_native_code,
        )
    )
    if product is not None:
        return product
    if raw.canon_hash:
        return session.scalar(
            select(Product).where(
                Product.mart == raw.mart,
                Product.canon_hash == raw.canon_hash,
                Product.mart_native_code.is_(None),
            )
        )
    return None


def _upsert_product(session: Session, raw: RawProduct, unified_category_id: str | None, summary: AutoClassifySummary) -> Product:
    now = _as_utc_naive(raw.crawled_at or raw.observed_at)
    product = _find_product(session, raw)
    is_new = product is None
    if is_new:
        product = Product(name=raw.raw_name, unit=raw.pack_unit or "개", source_type="mart_crawl")
        session.add(product)
        summary.new_products += 1
    else:
        summary.updated_products += 1

    product.name = raw.raw_name or product.name
    product.display_name = raw.normalized_name or raw.raw_name or product.display_name
    product.brand = raw.brand or product.brand
    product.pack_qty = raw.pack_qty if raw.pack_qty is not None else product.pack_qty
    product.pack_unit = raw.pack_unit or product.pack_unit
    product.unit = raw.pack_unit or product.unit or "개"
    product.mart = raw.mart
    product.mart_native_code = raw.mart_native_code
    product.canon_hash = raw.canon_hash or product.canon_hash
    product.external_seller = raw.external_seller if raw.external_seller is not None else (product.external_seller or False)
    product.unit_price_displayed = raw.unit_price if raw.unit_price is not None else product.unit_price_displayed
    product.unit_price_basis_raw = raw.unit_price_basis or product.unit_price_basis_raw
    product.mart_native_category_id = raw.mart_native_category_id or product.mart_native_category_id
    product.mart_native_category_path = raw.mart_native_category_path or product.mart_native_category_path
    product.canonical_url = raw.canonical_url or product.canonical_url
    product.mart_internal_seller_id = raw.mart_internal_seller_id or product.mart_internal_seller_id
    product.promo_label = raw.promo_label or product.promo_label
    product.promo_type = raw.promo_type or product.promo_type
    product.updated_at = now

    if unified_category_id:
        if _has_human_category(product) and product.unified_category_id != unified_category_id:
            summary.human_preserved += 1
        else:
            product.unified_category_id = unified_category_id
            product.categorization_method = AUTO_TRUST
            product.categorization_confidence = 1.0
            summary.classified += 1
    else:
        summary.unclassified += 1

    return product


def _record_price_history(session: Session, product: Product, raw: RawProduct, summary: AutoClassifySummary) -> None:
    if raw.price is None:
        return
    observed_at = _as_utc_naive(raw.observed_at or raw.crawled_at)
    week_of = week_start(observed_at)
    existing = session.scalar(
        select(PriceHistory).where(
            PriceHistory.product_id == product.id,
            PriceHistory.mart == raw.mart,
            PriceHistory.week_of == week_of,
        )
    )
    if existing is not None:
        summary.price_history_skipped += 1
        return
    session.add(
        PriceHistory(
            product_id=product.id,
            mart=raw.mart,
            canon_key=_canon_key(raw),
            week_of=week_of,
            observed_at=observed_at,
            price=float(raw.price),
            sale_price=float(raw.sale_price) if raw.sale_price is not None else None,
            unit_price=float(raw.unit_price) if raw.unit_price is not None else None,
            source_run_id=raw.source_run_id,
        )
    )
    summary.price_history_inserted += 1


def auto_classify_products(session: Session, raw_products: Iterable[RawProduct | dict[str, Any]], *, dry_run: bool = False) -> AutoClassifySummary:
    rows = [item if isinstance(item, RawProduct) else RawProduct.from_mapping(item) for item in raw_products]
    summary = AutoClassifySummary(total=len(rows), dry_run=dry_run)
    summary.canon_groups = len({row.canon_hash for row in rows if row.canon_hash})

    try:
        for raw in rows:
            if raw.mart not in MARTS:
                raise ValueError(f"지원하지 않는 mart: {raw.mart!r}")
            if not raw.mart_native_code:
                raise ValueError("mart_native_code는 필수입니다.")
            raw.normalized_name = normalize_name_core(raw.normalized_name or raw.raw_name)
            if not raw.canon_hash:
                raw.canon_hash = compute_canon_hash(raw.brand, raw.normalized_name, raw.pack_qty, raw.pack_unit)
            mapping = _find_mapping(session, raw)
            product = _upsert_product(
                session,
                raw,
                mapping.unified_category_id if mapping else None,
                summary,
            )
            session.flush()
            _record_price_history(session, product, raw, summary)

        if dry_run:
            session.rollback()
        else:
            session.commit()
    except Exception:
        session.rollback()
        raise
    return summary
