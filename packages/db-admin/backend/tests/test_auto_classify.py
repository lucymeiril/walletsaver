from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from services.auto_classify import auto_classify_products, week_start
from storage.models import Base, MartCategoryMapping, PriceHistory, Product, UnifiedCategory


def _session() -> Session:
    engine = create_engine("sqlite://", echo=False)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed_category_mapping(session: Session, mart: str, native_id: str, unified_id: str = "food.dairy") -> None:
    if session.get(UnifiedCategory, unified_id) is None:
        session.add(UnifiedCategory(id=unified_id, slug=unified_id.split(".")[-1], name_ko="우유/유제품", level=1, sort_order=0))
    session.add(
        MartCategoryMapping(
            mart=mart,
            mart_native_id=native_id,
            mart_native_path="식품 > 우유",
            unified_category_id=unified_id,
            trust="auto-aggregate",
            confidence=0.9,
            decided_by="test",
        )
    )
    session.commit()


def _raw(mart: str, code: str, *, category: str = "milk", canon_hash: str = "hash-milk", observed_at: datetime | None = None, url: str | None = None) -> dict:
    return {
        "mart": mart,
        "mart_native_code": code,
        "raw_name": f"{mart} 우유 1L",
        "brand": "테스트",
        "normalized_name": "우유",
        "canon_hash": canon_hash,
        "mart_native_category_id": category,
        "mart_native_category_path": "식품 > 우유",
        "canonical_url": url or f"https://example.test/{mart}/{code}",
        "price": 3000,
        "sale_price": 2800,
        "unit_price": 280,
        "unit_price_basis": "100ml",
        "pack_qty": 1,
        "pack_unit": "L",
        "observed_at": observed_at or datetime(2026, 5, 4, 9, 0, 0),
    }


def test_same_canon_hash_groups_four_marts() -> None:
    session = _session()
    try:
        for mart in ("emart", "homeplus", "lottemart", "costco"):
            _seed_category_mapping(session, mart, "milk")

        rows = [_raw(mart, f"code-{mart}") for mart in ("emart", "homeplus", "lottemart", "costco")]
        summary = auto_classify_products(session, rows).as_dict()

        assert summary["new_products"] == 4
        assert summary["classified"] == 4
        assert summary["canon_groups"] == 1
        assert {p.canon_hash for p in session.query(Product).all()} == {"hash-milk"}
    finally:
        session.close()


def test_mapped_native_category_fills_unified_category() -> None:
    session = _session()
    try:
        _seed_category_mapping(session, "emart", "milk")
        auto_classify_products(session, [_raw("emart", "100")])
        product = session.query(Product).one()
        assert product.unified_category_id == "food.dairy"
        assert product.categorization_method == "auto-aggregate"
    finally:
        session.close()


def test_unmapped_native_category_remains_unclassified() -> None:
    session = _session()
    try:
        summary = auto_classify_products(session, [_raw("emart", "100", category="unknown")]).as_dict()
        product = session.query(Product).one()
        assert summary["unclassified"] == 1
        assert product.unified_category_id is None
    finally:
        session.close()


def test_human_unified_category_is_not_overwritten_by_auto_aggregate() -> None:
    session = _session()
    try:
        session.add_all([
            UnifiedCategory(id="food.dairy", slug="dairy", name_ko="우유", level=1, sort_order=0),
            UnifiedCategory(id="food.snack", slug="snack", name_ko="과자", level=1, sort_order=1),
            MartCategoryMapping(mart="emart", mart_native_id="milk", unified_category_id="food.dairy", trust="auto-aggregate", confidence=0.9),
            Product(
                name="수동 과자",
                unit="개",
                mart="emart",
                mart_native_code="100",
                unified_category_id="food.snack",
                categorization_method="manual",
            ),
        ])
        session.commit()

        summary = auto_classify_products(session, [_raw("emart", "100")]).as_dict()
        product = session.query(Product).one()
        assert summary["human_preserved"] == 1
        assert product.unified_category_id == "food.snack"
        assert product.categorization_method == "manual"
    finally:
        session.close()


def test_weekly_price_history_is_idempotent_and_accumulates_next_week() -> None:
    session = _session()
    try:
        _seed_category_mapping(session, "emart", "milk")
        first = datetime(2026, 5, 4, 9, 0, 0)
        same_week = first + timedelta(days=2)
        next_week = first + timedelta(days=7)

        auto_classify_products(session, [_raw("emart", "100", observed_at=first)])
        auto_classify_products(session, [_raw("emart", "100", observed_at=same_week)])
        assert session.query(PriceHistory).count() == 1

        auto_classify_products(session, [_raw("emart", "100", observed_at=next_week)])
        histories = session.query(PriceHistory).order_by(PriceHistory.week_of).all()
        assert len(histories) == 2
        assert [h.week_of for h in histories] == [week_start(first), week_start(next_week)]
    finally:
        session.close()


def test_mart_native_code_identifies_same_product_when_url_slug_changes() -> None:
    session = _session()
    try:
        _seed_category_mapping(session, "costco", "milk")
        auto_classify_products(session, [_raw("costco", "999", url="https://costco.test/old-slug/p/999")])
        auto_classify_products(session, [_raw("costco", "999", url="https://costco.test/new-slug/p/999")])

        assert session.query(Product).count() == 1
        assert session.query(Product).one().canonical_url == "https://costco.test/new-slug/p/999"
    finally:
        session.close()
