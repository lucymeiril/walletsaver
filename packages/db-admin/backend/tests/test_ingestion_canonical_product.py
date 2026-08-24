"""Canonical MatchingEntry hits must reuse Product IDs during final approval."""
from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from api.routes import ingestion
from storage.models import Base, BaselinePrice, Product


def test_insert_items_prefers_canonical_product_id_over_duplicate_name():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    with Session() as session:
        canonical = Product(name="동일 상품명", unit="개", source_type="mart_crawl")
        duplicate = Product(name="동일 상품명", unit="개", source_type="mart_crawl")
        session.add_all([canonical, duplicate])
        session.commit()

        saved = ingestion._insert_items(
            session,
            [
                {
                    "name": "동일 상품명",
                    "sale_price": 1000,
                    "source": "mart_regular",
                    "canonical_product_id": canonical.id,
                    "unit": "개",
                }
            ],
            "DiscountItem",
        )
        session.commit()

        assert saved == 1
        price = session.query(BaselinePrice).one()
        assert price.product_id == canonical.id
        assert session.query(Product).count() == 2

    engine.dispose()
