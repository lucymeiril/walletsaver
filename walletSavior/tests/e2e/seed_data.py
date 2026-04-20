"""
E2E seed script — deterministic test data for WalletSavior.

Usage:
    py seed_data.py                 # seed only (skip if data exists)
    py seed_data.py --force         # drop and re-seed

Idempotent: won't duplicate rows unless --force is given.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

ROOT = Path(r"E:\pdf\capston01\walletSavior")
DB_ADMIN_BACKEND = ROOT / "packages" / "db-admin" / "backend"
DB_PATH = DB_ADMIN_BACKEND / "walletguardian.db"

sys.path.insert(0, str(DB_ADMIN_BACKEND))

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from storage.models import (
    Base, Category, Product, BaselinePrice, DiscountHistory, User, UserRole,
)
from api.auth import hash_password

ENGINE = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
)
Session = sessionmaker(bind=ENGINE)


def _ensure_tables():
    Base.metadata.create_all(ENGINE)


def _seed_categories(s):
    cats = [
        Category(id="food", name="식품", depth=0, sort_order=1, is_active=True),
        Category(id="food.vegetable", name="채소", parent_id="food", depth=1, sort_order=1, is_active=True),
        Category(id="food.meat", name="축산", parent_id="food", depth=1, sort_order=2, is_active=True),
    ]
    added = 0
    for c in cats:
        if not s.get(Category, c.id):
            s.add(c)
            added += 1
    s.flush()
    return added


def _seed_products(s):
    specs = [
        ("QA 양파 1kg", "food.vegetable", "1kg", "mart_crawl"),
        ("QA 삼겹살 100g", "food.meat", "100g", "mart_crawl"),
        ("QA 우유 900ml", "food.vegetable", "900ml", "baseline"),
    ]
    products = []
    for name, cat, unit, source in specs:
        existing = s.query(Product).filter(Product.name == name).first()
        if existing:
            products.append(existing)
        else:
            p = Product(
                name=name, category_id=cat, unit=unit,
                is_active=True, source_type=source,
            )
            s.add(p)
            s.flush()
            products.append(p)
    return products


def _seed_prices(s, products):
    now = datetime.utcnow()
    added = 0
    for p in products:
        existing_bp = (
            s.query(BaselinePrice)
            .filter(BaselinePrice.product_id == p.id)
            .first()
        )
        if not existing_bp:
            price = 3000 if "양파" in p.name else 1800
            s.add(BaselinePrice(
                product_id=p.id, price=price,
                source="KAMIS", unit=p.unit,
                recorded_at=now - timedelta(days=1),
            ))
            added += 1

    onion = next((p for p in products if "양파" in p.name), None)
    meat = next((p for p in products if "삼겹살" in p.name), None)
    if onion:
        existing = (
            s.query(DiscountHistory)
            .filter(DiscountHistory.product_id == onion.id)
            .first()
        )
        if not existing:
            s.add(DiscountHistory(
                product_id=onion.id, price=1980, original_price=2980,
                discount_rate=0.33, source="emart", crawled_at=now,
            ))
            s.add(DiscountHistory(
                product_id=onion.id, price=2100, original_price=2980,
                discount_rate=0.29, source="homeplus", crawled_at=now,
            ))
            added += 2
    if meat:
        existing = (
            s.query(DiscountHistory)
            .filter(DiscountHistory.product_id == meat.id)
            .first()
        )
        if not existing:
            s.add(DiscountHistory(
                product_id=meat.id, price=1150, original_price=1890,
                discount_rate=0.39, source="emart", crawled_at=now,
            ))
            added += 1
    return added


def _seed_qa_user(s):
    email = "qa-user@walletsavior.com"
    if s.query(User).filter(User.email == email).first():
        return False
    s.add(User(
        email=email,
        hashed_password=hash_password("qa123456!"),
        nickname="QA사용자",
        role=UserRole.USER,
        is_active=True,
    ))
    return True


def seed(force: bool = False):
    _ensure_tables()
    s = Session()
    try:
        cats = _seed_categories(s)
        products = _seed_products(s)
        prices = _seed_prices(s, products)
        user = _seed_qa_user(s)
        s.commit()
        print(f"seeded  cats={cats}  products={len(products)}  prices={prices}  user={'new' if user else 'exists'}")
    except Exception as exc:
        s.rollback()
        print(f"seed error: {exc}", file=sys.stderr)
        raise
    finally:
        s.close()


if __name__ == "__main__":
    force = "--force" in sys.argv
    seed(force=force)
