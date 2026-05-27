from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from services.external_ai_export import export_unclassified_bundle
from services.external_ai_import import apply_import_bundle
from storage.models import Base, MartCategoryMapping, Product, UnifiedCategory

HASH_RICE = "0123456789abcdef0123456789abcdef01234567"
HASH_TOWEL = "1111111111111111111111111111111111111111"


def _session() -> Session:
    engine = create_engine("sqlite://", echo=False)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def _write_import_bundle(path: Path, *, matching_category: str = "instant_rice") -> None:
    _write_jsonl(
        path / "matching_updates.jsonl",
        [
            {
                "canon_hash": HASH_RICE,
                "category_id": matching_category,
                "keywords": ["즉석밥", "햇반"],
                "confidence": 0.94,
                "source": "external-ai",
                "reason": "상품명 기반 분류",
            }
        ],
    )
    (path / "category_keyword_updates.yaml").write_text(
        yaml.safe_dump(
            {
                "new_categories": [
                    {
                        "id": "instant_rice",
                        "name_kr": "즉석밥",
                        "parent_id": "processed_food",
                        "default_unit_kind": "GRAM_PER_100G",
                        "reason": "즉석밥 전용 분류 필요",
                    }
                ],
                "keywords": [{"keyword": "즉석밥", "category_id": "instant_rice", "synonyms": ["햇반"]}],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    _write_jsonl(
        path / "product_updates.jsonl",
        [
            {
                "canon_hash": HASH_RICE,
                "brand": "CJ",
                "normalized_name": "CJ 햇반 백미 210g 12개",
                "pack_qty": 210,
                "pack_unit": "g",
                "pack_count": 12,
                "notes": "외부 AI 보강",
            }
        ],
    )


def test_export_simulated_external_ai_import_updates_db(tmp_path: Path) -> None:
    session = _session()
    try:
        session.add(UnifiedCategory(id="processed_food", slug="processed_food", name_ko="가공식품", level=0, sort_order=0))
        session.add(
            Product(
                name="[행사] CJ 햇반 210g*12",
                brand="CJ",
                name_core="햇반",
                pack_qty=210,
                pack_unit="g",
                unit="g",
                mart="emart",
                mart_native_code="1000123456789",
                canon_hash=HASH_RICE,
                mart_native_category_id="emart-rice",
                mart_native_category_path="가공식품 > 즉석밥",
                unified_category_id=None,
            )
        )
        session.commit()

        manifest = export_unclassified_bundle(tmp_path / "export", session=session)
        assert manifest.counts["unclassified"] == 1
        assert json.loads((tmp_path / "export" / "unclassified.jsonl").read_text(encoding="utf-8").splitlines()[0])["canon_hash"] == HASH_RICE

        bundle = tmp_path / "import"
        bundle.mkdir()
        _write_import_bundle(bundle)

        report = apply_import_bundle(bundle, session=session, dry_run=False)
        session.commit()

        product = session.query(Product).filter_by(canon_hash=HASH_RICE).one()
        assert report["created"]["categories"] == 1
        assert report["created"]["mappings"] == 1
        assert product.unified_category_id == "instant_rice"
        assert product.display_name == "CJ 햇반 백미 210g 12개"
        mapping = session.query(MartCategoryMapping).filter_by(mart="emart", mart_native_id="emart-rice").one()
        assert mapping.trust == "external-ai"
        assert mapping.unified_category_id == "instant_rice"
    finally:
        session.close()


def test_import_preserves_human_mapping_trust(tmp_path: Path) -> None:
    session = _session()
    try:
        session.add_all([
            UnifiedCategory(id="processed_food", slug="processed_food", name_ko="가공식품", level=0, sort_order=0),
            UnifiedCategory(id="rice", slug="rice", name_ko="쌀", level=0, sort_order=1),
            Product(name="햇반", mart="emart", mart_native_code="p1", canon_hash=HASH_RICE, mart_native_category_id="native-1", unified_category_id="rice"),
            MartCategoryMapping(mart="emart", mart_native_id="native-1", unified_category_id="rice", trust="human", confidence=1.0, decided_by="operator"),
        ])
        session.commit()

        bundle = tmp_path / "import"
        bundle.mkdir()
        _write_import_bundle(bundle)
        report = apply_import_bundle(bundle, session=session, dry_run=False)
        session.commit()

        product = session.query(Product).filter_by(canon_hash=HASH_RICE).one()
        mapping = session.query(MartCategoryMapping).filter_by(mart="emart", mart_native_id="native-1").one()
        assert mapping.unified_category_id == "rice"
        assert product.unified_category_id == "rice"
        assert report["conflicts"]
    finally:
        session.close()


def test_import_partial_failure_rolls_back(tmp_path: Path) -> None:
    session = _session()
    try:
        session.add(UnifiedCategory(id="processed_food", slug="processed_food", name_ko="가공식품", level=0, sort_order=0))
        session.add(Product(name="햇반", mart="emart", mart_native_code="p1", canon_hash=HASH_RICE, mart_native_category_id="native-1"))
        session.commit()

        bundle = tmp_path / "import"
        bundle.mkdir()
        _write_import_bundle(bundle, matching_category="missing_category")

        with pytest.raises(ValueError):
            apply_import_bundle(bundle, session=session, dry_run=False)
        session.commit()

        assert session.get(UnifiedCategory, "instant_rice") is None
        assert session.query(MartCategoryMapping).count() == 0
        assert session.query(Product).filter_by(canon_hash=HASH_RICE).one().unified_category_id is None
    finally:
        session.close()
