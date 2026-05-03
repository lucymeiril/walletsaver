"""핫딜 투표/댓글 안정성 회귀 테스트."""
import os
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _prefer_website_backend_api():
    if _BACKEND_DIR in sys.path:
        sys.path.remove(_BACKEND_DIR)
    sys.path.insert(0, _BACKEND_DIR)
    loaded_api = sys.modules.get("api")
    if loaded_api and not str(getattr(loaded_api, "__file__", "")).startswith(_BACKEND_DIR):
        for name in list(sys.modules):
            if name == "api" or name.startswith("api."):
                sys.modules.pop(name, None)


@pytest.fixture(autouse=True)
def setup_test_db():
    from services.db import get_engine, managed_session, reset_engine
    from storage.models import Base, HotdealPrice, Product
    _prefer_website_backend_api()
    import api.routes.hotdeals as hotdeals

    reset_engine()
    engine = get_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    hotdeals._rate_limit_store.clear()
    hotdeals._listing_cache.clear()

    with managed_session() as session:
        product = Product(name="테스트 상품", unit="개")
        session.add(product)
        session.flush()
        session.add(HotdealPrice(
            product_id=product.id,
            price=1000,
            source="test",
            title="테스트 핫딜",
        ))

    yield

    hotdeals._rate_limit_store.clear()
    hotdeals._listing_cache.clear()
    reset_engine()


@pytest.fixture
def client():
    _prefer_website_backend_api()
    from api.routes.hotdeals import router as hotdeals_router

    app = FastAPI()
    app.state.storage = None
    app.include_router(hotdeals_router, prefix="/api/hotdeals")
    return TestClient(app)


def _vote(client, vote_type, user_agent="pytest-voter"):
    return client.post(
        "/api/hotdeals/1/vote",
        json={"vote_type": vote_type},
        headers={"user-agent": user_agent},
    )


def _counts():
    from services.db import managed_session
    from storage.models import HotDealVote, HotdealPrice

    with managed_session() as session:
        deal = session.get(HotdealPrice, 1)
        vote_rows = session.query(HotDealVote).filter(HotDealVote.hotdeal_id == 1).all()
        return deal.votes_hot, deal.votes_not, len(vote_rows)


def test_repeated_same_vote_is_idempotent(client):
    first = _vote(client, "hot")
    second = _vote(client, "hot")

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["data"] == {"votes_hot": 1, "votes_not": 0, "user_vote": "hot"}
    assert _counts() == (1, 0, 1)


def test_alternating_vote_updates_existing_vote_without_inflating(client):
    assert _vote(client, "hot").status_code == 200
    switched = _vote(client, "not")

    assert switched.status_code == 200
    assert switched.json()["data"] == {"votes_hot": 0, "votes_not": 1, "user_vote": "not"}
    assert _counts() == (0, 1, 1)


def test_cold_alias_and_cancel_do_not_raise_400_or_leave_counts(client):
    cold = _vote(client, "cold")
    cancel = _vote(client, "cancel")

    assert cold.status_code == 200
    assert cold.json()["data"] == {"votes_hot": 0, "votes_not": 1, "user_vote": "not"}
    assert cancel.status_code == 200
    assert cancel.json()["data"] == {"votes_hot": 0, "votes_not": 0, "user_vote": None}
    assert _counts() == (0, 0, 0)
