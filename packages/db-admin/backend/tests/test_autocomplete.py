"""Autocomplete keyword service tests — SQLite in-memory"""
import sys
import os
import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from storage.models import Base, Keyword, Category
from services.autocomplete import (
    search_keywords,
    add_keyword,
    update_search_count,
    get_popular_keywords,
    suggest_categories,
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
    session.add(Category(id="veg", name="채소류", depth=0, sort_order=0, is_active=True))
    session.add(Category(id="meat", name="축산물", depth=0, sort_order=1, is_active=True))

    session.add(Keyword(id=1, word="양파", synonyms=["onion", "어니언"], category_id="veg", search_count=100, is_active=True))
    session.add(Keyword(id=2, word="양배추", synonyms=["cabbage"], category_id="veg", search_count=50, is_active=True))
    session.add(Keyword(id=3, word="삼겹살", synonyms=["pork belly", "삼겹"], category_id="meat", search_count=200, is_active=True))
    session.add(Keyword(id=4, word="감자", synonyms=["potato"], category_id="veg", search_count=30, is_active=True))
    session.add(Keyword(id=5, word="당근", synonyms=["carrot"], category_id="veg", search_count=10, is_active=True))
    session.commit()
    return session


class TestSearchKeywords:
    def test_prefix_match(self, seeded_session):
        results = search_keywords(seeded_session, "양")
        assert len(results) >= 2
        words = {r["word"] for r in results}
        assert "양파" in words
        assert "양배추" in words

    def test_synonym_match(self, seeded_session):
        results = search_keywords(seeded_session, "onion")
        assert len(results) >= 1
        assert results[0]["word"] == "양파"
        assert results[0]["match_type"] == "synonym"

    def test_empty_query(self, seeded_session):
        results = search_keywords(seeded_session, "")
        assert results == []

    def test_no_match(self, seeded_session):
        results = search_keywords(seeded_session, "xyz없는검색어")
        assert results == []

    def test_limit(self, seeded_session):
        results = search_keywords(seeded_session, "양", limit=1)
        assert len(results) <= 1


class TestAddKeyword:
    def test_add_new(self, seeded_session):
        result = add_keyword(seeded_session, "토마토", synonyms=["tomato"], category_id="veg")
        assert result["word"] == "토마토"
        assert result["synonyms"] == ["tomato"]
        assert result["id"] is not None

    def test_add_without_synonyms(self, session):
        session.add(Category(id="misc", name="기타", depth=0, sort_order=0, is_active=True))
        session.commit()
        result = add_keyword(session, "기타키워드")
        assert result["word"] == "기타키워드"
        assert result["synonyms"] == []


class TestUpdateSearchCount:
    def test_increment(self, seeded_session):
        kw = seeded_session.get(Keyword, 1)
        old_count = kw.search_count
        ok = update_search_count(seeded_session, 1)
        assert ok is True
        seeded_session.refresh(kw)
        assert kw.search_count == old_count + 1

    def test_nonexistent(self, seeded_session):
        ok = update_search_count(seeded_session, 999)
        assert ok is False


class TestGetPopularKeywords:
    def test_ordered_by_count(self, seeded_session):
        popular = get_popular_keywords(seeded_session, limit=3)
        assert len(popular) == 3
        # Should be ordered desc
        assert popular[0]["search_count"] >= popular[1]["search_count"]
        assert popular[0]["word"] == "삼겹살"  # highest count

    def test_limit(self, seeded_session):
        popular = get_popular_keywords(seeded_session, limit=2)
        assert len(popular) == 2


class TestSuggestCategories:
    def test_suggest_from_keyword(self, seeded_session):
        results = suggest_categories(seeded_session, "양파")
        assert len(results) >= 1
        assert results[0]["id"] == "veg"

    def test_suggest_from_category_name(self, seeded_session):
        results = suggest_categories(seeded_session, "축산")
        assert len(results) >= 1
        ids = {r["id"] for r in results}
        assert "meat" in ids

    def test_empty_query(self, seeded_session):
        results = suggest_categories(seeded_session, "")
        assert results == []
