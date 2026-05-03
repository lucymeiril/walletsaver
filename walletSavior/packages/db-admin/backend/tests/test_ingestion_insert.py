import os
import sys

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "shared"))

from api.routes.ingestion import _insert_items
from storage.models import Base, HotdealPrice


def test_hotdeal_insert_keeps_valid_rows_when_one_price_is_missing():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    with Session.begin() as session:
        saved = _insert_items(
            session,
            [
                {
                    "title": "저장되는 알구몬 핫딜 19,900원",
                    "url": "https://www.algumon.com/l/d/ok",
                    "source_community": "알구몬",
                    "price": 19900,
                },
                {
                    "title": "가격 없는 알구몬 핫딜",
                    "url": "https://www.algumon.com/l/d/no-price",
                    "source_community": "알구몬",
                    "price": None,
                },
            ],
            "HotdealPost",
        )

    with Session() as session:
        rows = session.execute(select(HotdealPrice)).scalars().all()

    assert saved == 1
    assert len(rows) == 1
    assert rows[0].title == "저장되는 알구몬 핫딜 19,900원"
    assert rows[0].price == 19900
