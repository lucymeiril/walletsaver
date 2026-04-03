"""Category management service tests — SQLite in-memory"""
import sys
import os
import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from storage.models import Base, Category, Product
from services.category_mgmt import (
    get_category_tree,
    get_category,
    create_category,
    update_category,
    delete_category,
    get_category_products,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


@pytest.fixture
def seeded_session(session):
    session.add(Category(id="food", name="식품", depth=0, sort_order=0, is_active=True))
    session.add(Category(id="food.veg", name="채소류", parent_id="food", depth=1, sort_order=0, is_active=True))
    session.add(Category(id="food.meat", name="축산물", parent_id="food", depth=1, sort_order=1, is_active=True))
    session.add(Category(id="food.veg.onion", name="양파", parent_id="food.veg", depth=2, sort_order=0, is_active=True))
    session.add(Category(id="food.veg.potato", name="감자", parent_id="food.veg", depth=2, sort_order=1, is_active=True))

    session.add(Product(id=1, name="국산양파 1kg", category_id="food.veg.onion", unit="kg"))
    session.add(Product(id=2, name="수입양파 1kg", category_id="food.veg.onion", unit="kg"))
    session.add(Product(id=3, name="감자 1kg", category_id="food.veg.potato", unit="kg"))
    session.commit()
    return session


class TestGetCategoryTree:
    def test_returns_tree(self, seeded_session):
        tree = get_category_tree(seeded_session)
        assert len(tree) == 1  # root: 식품
        root = tree[0]
        assert root["name"] == "식품"
        assert len(root["children"]) == 2  # 채소류, 축산물

    def test_empty_tree(self, session):
        tree = get_category_tree(session)
        assert tree == []


class TestGetCategory:
    def test_single_with_children(self, seeded_session):
        result = get_category(seeded_session, "food.veg")
        assert result is not None
        assert result["name"] == "채소류"
        assert len(result["children"]) == 2  # 양파, 감자

    def test_not_found(self, seeded_session):
        result = get_category(seeded_session, "nonexistent")
        assert result is None


class TestCreateCategory:
    def test_create_new(self, seeded_session):
        result = create_category(
            seeded_session, "food.veg.carrot", "당근",
            parent_id="food.veg",
        )
        assert result["id"] == "food.veg.carrot"
        assert result["name"] == "당근"
        assert result["depth"] == 2

    def test_create_root(self, session):
        result = create_category(session, "drink", "음료")
        assert result["depth"] == 0
        assert result["parent_id"] is None


class TestUpdateCategory:
    def test_update_name(self, seeded_session):
        result = update_category(seeded_session, "food.veg", {"name": "야채류"})
        assert result is not None
        assert result["name"] == "야채류"

    def test_update_nonexistent(self, seeded_session):
        result = update_category(seeded_session, "nonexistent", {"name": "x"})
        assert result is None


class TestDeleteCategory:
    def test_delete_leaf(self, seeded_session):
        ok = delete_category(seeded_session, "food.veg.potato")
        assert ok is True
        # Verify deleted
        assert get_category(seeded_session, "food.veg.potato") is None
        # Product should have category_id=None
        p = seeded_session.get(Product, 3)
        assert p.category_id is None

    def test_delete_with_children(self, seeded_session):
        ok = delete_category(seeded_session, "food.veg")
        assert ok is True
        # Children should be reparented to food
        onion = seeded_session.get(Category, "food.veg.onion")
        assert onion is not None
        assert onion.parent_id == "food"

    def test_delete_nonexistent(self, seeded_session):
        ok = delete_category(seeded_session, "nonexistent")
        assert ok is False


class TestGetCategoryProducts:
    def test_with_products(self, seeded_session):
        products = get_category_products(seeded_session, "food.veg.onion")
        assert len(products) == 2
        names = {p["name"] for p in products}
        assert "국산양파 1kg" in names

    def test_empty_category(self, seeded_session):
        products = get_category_products(seeded_session, "food.meat")
        assert products == []
