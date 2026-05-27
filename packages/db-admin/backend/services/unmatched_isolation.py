"""Identify and isolate mart-native products that need external AI review."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from services.name_normalize import compute_canon_hash, normalize_name_core
from storage.models import MartCategoryMapping, PriceHistory, Product

CASE_RECOMMENDATIONS = {
    "case_a_new_native_code": "신규 mart_native_code입니다. 외부 AI가 기존 카테고리/키워드로 신규 매칭 후보를 제안하게 합니다.",
    "case_b_name_variant": "행사/신상품 마커만 제거한 name_core와 canon_hash 안정성을 확인하고 기존 매칭을 유지합니다.",
    "case_c_unmapped_native_category": "mart_category_mappings에 native category 매핑을 추가하거나 기존 unified_category_id로 연결합니다.",
    "case_d_price_suspicious": "직전 관측가 대비 50% 이상 급변했습니다. 가격 오기/행사 가격 여부를 검수합니다.",
}


@dataclass(frozen=True)
class IsolationCase:
    count: int = 0
    items: list[dict[str, Any]] = field(default_factory=list)
    recommendation: str = ""


@dataclass(frozen=True)
class IsolationResult:
    generated_at: str
    week_of: str | None
    cases: dict[str, IsolationCase]

    @property
    def counts(self) -> dict[str, int]:
        return {key: value.count for key, value in self.cases.items()}

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["counts"] = self.counts
        return data


def _row(product: Product, **extra: Any) -> dict[str, Any]:
    attrs = product.attributes if isinstance(product.attributes, dict) else {}
    name_core = normalize_name_core(product.display_name or product.name_core or product.name)
    row = {
        "product_id": product.id,
        "canon_hash": product.canon_hash,
        "mart": product.mart,
        "mart_native_code": product.mart_native_code,
        "raw_name": product.name,
        "name_core": name_core,
        "normalized_name": product.display_name or product.name_core or product.name,
        "brand": product.brand,
        "pack_qty": product.pack_qty,
        "pack_unit": product.pack_unit or product.unit,
        "pack_count": attrs.get("pack_count"),
        "mart_native_category_id": product.mart_native_category_id,
        "mart_native_category_path": product.mart_native_category_path,
        "unified_category_id": product.unified_category_id,
        "canonical_url": product.canonical_url,
    }
    row.update(extra)
    return row


def _latest_week(session: Session) -> date | None:
    return session.scalar(select(func.max(PriceHistory.week_of)).where(PriceHistory.week_of.is_not(None)))


def _products_for_week(session: Session, week_of: date | None) -> list[Product]:
    if week_of is None:
        return session.scalars(select(Product).where(Product.mart_native_code.is_not(None)).order_by(Product.id)).all()
    return session.scalars(
        select(Product)
        .join(PriceHistory, PriceHistory.product_id == Product.id)
        .where(PriceHistory.week_of == week_of, Product.mart_native_code.is_not(None))
        .order_by(Product.id)
    ).unique().all()


def _observed_price(session: Session, product_id: int, week_of: date) -> PriceHistory | None:
    return session.scalar(
        select(PriceHistory)
        .where(PriceHistory.product_id == product_id, PriceHistory.week_of == week_of)
        .order_by(PriceHistory.observed_at.desc(), PriceHistory.id.desc())
        .limit(1)
    )


def _previous_price(session: Session, product_id: int, week_of: date) -> PriceHistory | None:
    return session.scalar(
        select(PriceHistory)
        .where(PriceHistory.product_id == product_id, PriceHistory.week_of < week_of)
        .order_by(PriceHistory.week_of.desc(), PriceHistory.observed_at.desc(), PriceHistory.id.desc())
        .limit(1)
    )


def isolate_unmatched_products(session: Session, *, week_of: date | None = None) -> IsolationResult:
    """Return separated A~D isolation cases for the selected crawl week."""
    selected_week = week_of or _latest_week(session)
    products = _products_for_week(session, selected_week)

    cases: dict[str, list[dict[str, Any]]] = {key: [] for key in CASE_RECOMMENDATIONS}
    seen_case_keys: dict[str, set[tuple[Any, ...]]] = {key: set() for key in CASE_RECOMMENDATIONS}

    for product in products:
        if selected_week is not None and product.id is not None:
            has_previous = session.scalar(
                select(PriceHistory.id)
                .where(PriceHistory.product_id == product.id, PriceHistory.week_of < selected_week)
                .limit(1)
            )
            if has_previous is None:
                key = (product.mart, product.mart_native_code)
                seen_case_keys["case_a_new_native_code"].add(key)
                cases["case_a_new_native_code"].append(_row(product, first_seen_week=selected_week.isoformat()))

        name_source = product.name or product.display_name or ""
        name_core = normalize_name_core(name_source)
        if name_source and name_core and name_core != name_source.strip():
            stable_hash = compute_canon_hash(product.brand, name_core, product.pack_qty, product.pack_unit or product.unit)
            cases["case_b_name_variant"].append(
                _row(
                    product,
                    marker_stripped=True,
                    recomputed_canon_hash=stable_hash,
                    canon_hash_stable=(product.canon_hash == stable_hash if product.canon_hash else None),
                )
            )

        if product.unified_category_id is None and product.mart and product.mart_native_category_id:
            mapping_id = session.scalar(
                select(MartCategoryMapping.id).where(
                    MartCategoryMapping.mart == product.mart,
                    MartCategoryMapping.mart_native_id == product.mart_native_category_id,
                )
            )
            if mapping_id is None:
                cases["case_c_unmapped_native_category"].append(_row(product, reason="mart_category_mappings 미적용"))

        if selected_week is not None and product.id is not None:
            current = _observed_price(session, product.id, selected_week)
            previous = _previous_price(session, product.id, selected_week)
            if current is not None and previous is not None and previous.price > 0:
                ratio = current.price / previous.price
                if ratio <= 0.5 or ratio >= 1.5:
                    cases["case_d_price_suspicious"].append(
                        _row(
                            product,
                            current_week=selected_week.isoformat(),
                            current_price=current.price,
                            previous_week=previous.week_of.isoformat() if previous.week_of else None,
                            previous_price=previous.price,
                            price_ratio=round(ratio, 4),
                            direction="down" if ratio <= 0.5 else "up",
                        )
                    )

    case_payload = {
        key: IsolationCase(count=len(items), items=items, recommendation=CASE_RECOMMENDATIONS[key])
        for key, items in cases.items()
    }
    return IsolationResult(
        generated_at=datetime.now(timezone.utc).isoformat(),
        week_of=selected_week.isoformat() if selected_week else None,
        cases=case_payload,
    )
