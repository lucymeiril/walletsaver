from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from services.auto_classify import auto_classify_products
from services.external_ai_export import export_unclassified_bundle
from services.name_normalize import compute_canon_hash, normalize_name_core
from services.unmatched_isolation import isolate_unmatched_products
from storage.models import Base, MartCategoryMapping, Product, UnifiedCategory


def _session() -> Session:
    engine = create_engine("sqlite://", echo=False)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed_mapping(session: Session, native_id: str = "milk") -> None:
    session.add(UnifiedCategory(id="food.dairy", slug="dairy", name_ko="우유", level=1, sort_order=0))
    session.add(MartCategoryMapping(mart="emart", mart_native_id=native_id, unified_category_id="food.dairy", trust="auto-aggregate", confidence=0.9))
    session.commit()


def _raw(code: str, *, name: str = "테스트 우유 1L", category: str = "milk", price: float = 3000, observed_at: datetime | None = None) -> dict:
    name_core = normalize_name_core(name)
    return {
        "mart": "emart",
        "mart_native_code": code,
        "raw_name": name,
        "normalized_name": name_core,
        "brand": "테스트",
        "canon_hash": compute_canon_hash("테스트", name_core, 1, "L"),
        "mart_native_category_id": category,
        "mart_native_category_path": f"식품 > {category}",
        "price": price,
        "pack_qty": 1,
        "pack_unit": "L",
        "observed_at": observed_at or datetime(2026, 5, 4, 9, 0, 0),
    }


def test_case_a_new_native_code_isolated() -> None:
    session = _session()
    try:
        _seed_mapping(session)
        auto_classify_products(session, [_raw("new-100")])

        result = isolate_unmatched_products(session).as_dict()

        assert result["counts"]["case_a_new_native_code"] == 1
        assert result["cases"]["case_a_new_native_code"]["items"][0]["mart_native_code"] == "new-100"
    finally:
        session.close()


def test_case_b_name_variant_keeps_stable_canon_hash() -> None:
    session = _session()
    try:
        _seed_mapping(session)
        plain_hash = compute_canon_hash("테스트", "테스트 우유 1L", 1, "L")
        marker_variants = [
            "[행사] 테스트 우유 1L",
            "[1+1] 테스트 우유 1L",
            "(NEW) 테스트 우유 1L",
            "{신상} 테스트 우유 1L",
            "【한정】 테스트 우유 1L",
            "<특가> 테스트 우유 1L",
            "★무배★ 테스트 우유 1L",
            "테스트 우유 1L 행사상품",
            "테스트 우유 1L 2+1",
        ]
        assert all(compute_canon_hash("테스트", name, 1, "L") == plain_hash for name in marker_variants)
        assert normalize_name_core("  [NEW]  Test   Milk  ", fold_case=True) == "test milk"

        auto_classify_products(session, [_raw("event-100", name="[행사] 테스트 우유 1L")])
        result = isolate_unmatched_products(session).as_dict()

        item = result["cases"]["case_b_name_variant"]["items"][0]
        assert item["name_core"] == "테스트 우유 1L"
        assert item["canon_hash_stable"] is True
        assert session.query(Product).one().unified_category_id == "food.dairy"
    finally:
        session.close()


def test_case_c_unmapped_native_category_isolated() -> None:
    session = _session()
    try:
        _seed_mapping(session)
        auto_classify_products(session, [_raw("cat-100", category="new-native")])

        result = isolate_unmatched_products(session).as_dict()

        assert result["counts"]["case_c_unmapped_native_category"] == 1
        assert result["cases"]["case_c_unmapped_native_category"]["items"][0]["unified_category_id"] is None
    finally:
        session.close()


def test_case_d_price_drop_flagged() -> None:
    session = _session()
    try:
        _seed_mapping(session)
        first = datetime(2026, 5, 4, 9, 0, 0)
        second = first + timedelta(days=7)
        auto_classify_products(session, [_raw("price-100", price=4000, observed_at=first)])
        auto_classify_products(session, [_raw("price-100", price=1900, observed_at=second)])

        result = isolate_unmatched_products(session).as_dict()

        item = result["cases"]["case_d_price_suspicious"]["items"][0]
        assert item["direction"] == "down"
        assert item["price_ratio"] == 0.475
    finally:
        session.close()


def test_export_manifest_separates_unmatched_cases(tmp_path: Path) -> None:
    session = _session()
    try:
        _seed_mapping(session)
        auto_classify_products(session, [_raw("new-100"), _raw("cat-100", category="new-native")])

        manifest = export_unclassified_bundle(tmp_path / "bundle", session=session)
        manifest_json = json.loads((tmp_path / "bundle" / "manifest.json").read_text(encoding="utf-8"))

        assert manifest.counts["case_a_new_native_code"] == 2
        assert manifest.counts["case_c_unmapped_native_category"] == 1
        assert manifest_json["files"]["case_a_new_native_code"]["rows"] == 2
        assert (tmp_path / "bundle" / "case_c_unmapped_native_category.jsonl").exists()
        assert "recommendations" in manifest_json
    finally:
        session.close()
