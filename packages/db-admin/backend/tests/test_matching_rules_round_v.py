from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.routes.ingestion import _insert_items
from storage.models import Base, Category, DiscountHistory, Product, ProductMatchRule, UnifiedCategory


def _session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return engine, Session


def test_matching_rules_api_lists_and_stats(monkeypatch):
    engine, Session = _session_factory()
    with Session.begin() as session:
        session.add(UnifiedCategory(id="food.rice", slug="rice", name_ko="쌀/밥", level=1))
        session.add(Product(name="CJ 햇반 210g", unit="개"))
        session.flush()
        product_id = session.execute(select(Product.id)).scalar_one()
        session.add(ProductMatchRule(
            pattern_type="normalized",
            pattern_value="cj 햇반 210g",
            canonical_category_id="food.rice",
            canonical_product_id=product_id,
            trust=2,
            created_by="tester",
        ))

    def get_test_session():
        return Session()

    @contextmanager
    def managed_test_session():
        sess = Session()
        try:
            yield sess
            sess.commit()
        except Exception:
            sess.rollback()
            raise
        finally:
            sess.close()

    import api.routes.matching_rules as routes
    monkeypatch.setattr(routes, "get_session", get_test_session)
    monkeypatch.setattr(routes, "managed_session", managed_test_session)
    monkeypatch.setattr(routes, "get_engine", lambda: engine)

    from config import settings
    settings.REQUIRE_AUTH = False
    from api.app import create_app

    client = TestClient(create_app())
    response = client.get("/api/matching-rules")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["canonical_category_name"] == "쌀/밥"

    stats = client.get("/api/matching-rules/stats")
    assert stats.status_code == 200
    assert stats.json()["by_pattern_type"]["normalized"] == 1


def test_ingestion_uses_product_match_rule_and_preserves_unit_price_display():
    _, Session = _session_factory()
    with Session.begin() as session:
        session.add(Category(id="축산", name="축산", depth=0, is_active=True))
        session.add(UnifiedCategory(id="meat.pork", slug="pork", name_ko="돼지고기", level=1))
        session.add(ProductMatchRule(
            pattern_type="regex",
            pattern_value="삼겹살",
            canonical_category_id="meat.pork",
            trust=2,
            created_by="tester",
        ))
        saved = _insert_items(session, [{
            "name": "국내산 삼겹살 500g",
            "source": "emart",
            "store": "이마트",
            "sale_price": 9920,
            "unit": "500g",
            "unit_price_display": "100g당 1,984원",
            "category_id": "축산",
        }], "DiscountItem")
        assert saved == 1

    with Session() as session:
        product = session.execute(select(Product).where(Product.name == "국내산 삼겹살 500g")).scalar_one()
        history = session.execute(select(DiscountHistory).where(DiscountHistory.product_id == product.id)).scalar_one()
        rule = session.execute(select(ProductMatchRule)).scalar_one()

        assert product.unified_category_id == "meat.pork"
        assert product.attributes["unit_price_display"] == "100g당 1,984원"
        assert history.price == 9920
        assert history.raw_data["unit_price_display"] == "100g당 1,984원"
        assert rule.hit_count == 1
