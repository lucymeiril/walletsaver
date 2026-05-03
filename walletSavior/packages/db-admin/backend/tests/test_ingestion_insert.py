import os
import sys
import json
from contextlib import contextmanager

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "shared"))

from api.routes.ingestion import (
    IngestionRowUpdateRequest,
    _calculate_quality,
    _find_problem_items,
    _insert_items,
    remove_ingestion_item,
    update_ingestion_item,
)
from storage.models import Base, HotdealPrice, IngestionStatus, PendingIngestion, Product


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
    assert rows[0].source == "algumon"
    with Session() as session:
        product = session.get(Product, rows[0].product_id)
        assert product.source_type == "algumon"


def _make_session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _patch_managed_session(monkeypatch, Session):
    @contextmanager
    def managed_test_session():
        session = Session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    import api.routes.ingestion as ingestion_routes

    monkeypatch.setattr(ingestion_routes, "managed_session", managed_test_session)


def _create_pending_ingestion(Session, items):
    quality_score, quality_details = _calculate_quality(items, "HotdealPost")
    with Session.begin() as session:
        row = PendingIngestion(
            crawler_name="algumon",
            crawl_status="success",
            items_count=len(items),
            items_json=json.dumps(items, ensure_ascii=False),
            schema_type="HotdealPost",
            quality_score=quality_score,
            quality_details=quality_details,
            status=IngestionStatus.PENDING,
        )
        session.add(row)
        session.flush()
        return row.id


def test_update_ingestion_row_persists_items_and_recomputes_quality(monkeypatch):
    Session = _make_session_factory()
    _patch_managed_session(monkeypatch, Session)
    ingestion_id = _create_pending_ingestion(
        Session,
        [
            {"title": "정상 핫딜", "url": "https://example.com/ok", "price": 1000},
            {"title": "가격 누락", "url": "https://example.com/missing", "price": None},
        ],
    )

    detail = update_ingestion_item(
        ingestion_id,
        1,
        IngestionRowUpdateRequest(
            item={"title": "가격 보정", "url": "https://example.com/missing", "price": 2500},
            notes="가격 보정",
        ),
        request=None,
        identity={"email": "admin@example.com"},
    )

    assert detail["items"][1]["price"] == 2500
    assert detail["items_count"] == 2
    assert detail["quality_details"]["missing_fields"] == 0
    assert detail["problem_indices"] == []
    assert "가격 보정" in detail["crawler_reviewer_notes"]

    with Session() as session:
        row = session.get(PendingIngestion, ingestion_id)
        saved_items = json.loads(row.items_json)
        assert saved_items[1]["title"] == "가격 보정"
        assert row.items_count == 2
        assert row.quality_details["missing_fields"] == 0


def test_remove_ingestion_row_recomputes_indices_and_approve_uses_corrected_rows(monkeypatch):
    Session = _make_session_factory()
    _patch_managed_session(monkeypatch, Session)
    ingestion_id = _create_pending_ingestion(
        Session,
        [
            {"title": "저장 A", "url": "https://example.com/a", "price": 1000},
            {"title": "삭제 대상", "url": "https://example.com/b", "price": None},
            {"title": "저장 C", "url": "https://example.com/c", "price": 3000},
        ],
    )

    detail = remove_ingestion_item(
        ingestion_id,
        1,
        request=None,
        notes="누락 행 제외",
        identity={"email": "admin@example.com"},
    )

    assert [item["title"] for item in detail["items"]] == ["저장 A", "저장 C"]
    assert detail["items_count"] == 2
    assert detail["quality_details"]["missing_fields"] == 0
    assert _find_problem_items(detail["items"], "HotdealPost") == []

    with Session.begin() as session:
        row = session.get(PendingIngestion, ingestion_id)
        row.status = IngestionStatus.CRAWLER_APPROVED
        corrected_items = json.loads(row.items_json)
        saved = _insert_items(session, corrected_items, row.schema_type)
        row.status = IngestionStatus.APPROVED

    with Session() as session:
        rows = session.execute(select(HotdealPrice).order_by(HotdealPrice.title)).scalars().all()
        assert saved == 2
        assert [row.title for row in rows] == ["저장 A", "저장 C"]
