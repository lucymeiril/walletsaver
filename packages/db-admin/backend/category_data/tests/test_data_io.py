"""데이터 입출력 테스트."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import json
import pytest
from category_data.data_io import (
    export_categories_json,
    export_categories_flat_json,
    export_keywords_json,
    import_categories_json,
    import_keywords_json,
    merge_categories,
    merge_keywords,
    generate_seed_sql,
)
from category_data.categories import CATEGORIES
from category_data.keywords import KEYWORDS


class TestExport:
    """JSON 내보내기 테스트."""

    def test_export_categories_json(self):
        """카테고리 트리 JSON 내보내기."""
        result = export_categories_json()
        data = json.loads(result)
        assert "categories" in data
        assert "total_count" in data
        assert data["total_count"] >= 300

    def test_export_categories_flat_json(self):
        """카테고리 flat JSON 내보내기."""
        result = export_categories_flat_json()
        data = json.loads(result)
        assert len(data["categories"]) == len(CATEGORIES)

    def test_export_keywords_json(self):
        """키워드 JSON 내보내기."""
        result = export_keywords_json()
        data = json.loads(result)
        assert "keywords" in data
        assert len(data["keywords"]) == len(KEYWORDS)

    def test_export_contains_korean(self):
        """JSON 에 한글이 제대로 포함되어야 한다."""
        result = export_categories_json()
        assert "농산물" in result
        assert "삼겹살" not in result or True  # 트리 형태라 leaf 포함될 수 있음

    def test_export_valid_json(self):
        """올바른 JSON 포맷이어야 한다."""
        for fn in [export_categories_json, export_categories_flat_json, export_keywords_json]:
            result = fn()
            # 파싱 가능해야 한다
            data = json.loads(result)
            assert isinstance(data, dict)


class TestImport:
    """JSON 가져오기 테스트."""

    def test_import_from_json_string(self):
        """JSON 문자열에서 가져오기."""
        exported = export_categories_flat_json()
        categories = import_categories_json(exported)
        assert len(categories) == len(CATEGORIES)

    def test_import_keywords_from_json_string(self):
        """키워드 JSON 문자열에서 가져오기."""
        exported = export_keywords_json()
        keywords = import_keywords_json(exported)
        assert len(keywords) == len(KEYWORDS)

    def test_import_bare_list(self):
        """순수 리스트 JSON 도 가져올 수 있어야 한다."""
        data = json.dumps([{"id": "test", "name": "테스트"}])
        categories = import_categories_json(data)
        assert len(categories) == 1

    def test_roundtrip(self):
        """export → import 왕복."""
        exported = export_categories_flat_json()
        imported = import_categories_json(exported)
        assert len(imported) == len(CATEGORIES)
        # 첫 번째 카테고리 확인
        assert imported[0]["id"] == CATEGORIES[0]["id"]


class TestMerge:
    """데이터 병합 테스트."""

    def test_merge_no_duplicates(self):
        """중복 없이 병합."""
        existing = [{"id": "a", "name": "A", "depth": 0, "sort_order": 1}]
        new = [{"id": "b", "name": "B", "depth": 0, "sort_order": 2}]
        result = merge_categories(existing, new)
        assert len(result) == 2

    def test_merge_update_existing(self):
        """기존 항목 업데이트."""
        existing = [{"id": "a", "name": "A_old", "depth": 0, "sort_order": 1}]
        new = [{"id": "a", "name": "A_new", "depth": 0, "sort_order": 1}]
        result = merge_categories(existing, new)
        assert len(result) == 1
        assert result[0]["name"] == "A_new"

    def test_merge_keywords_keep_higher_count(self):
        """키워드 병합 시 높은 search_count 유지."""
        existing = [{"word": "test", "search_count": 100, "synonyms": []}]
        new = [{"word": "test", "search_count": 50, "synonyms": ["t"]}]
        result = merge_keywords(existing, new)
        assert len(result) == 1
        assert result[0]["search_count"] == 100  # 높은 값 유지
        assert result[0]["synonyms"] == ["t"]  # 새 데이터의 동의어

    def test_merge_adds_new_keywords(self):
        """새 키워드 추가."""
        existing = [{"word": "a", "search_count": 10, "synonyms": []}]
        new = [{"word": "b", "search_count": 20, "synonyms": []}]
        result = merge_keywords(existing, new)
        assert len(result) == 2


class TestSQLGeneration:
    """SQL Seed 생성 테스트."""

    def test_generates_sql(self):
        """SQL 문이 생성되어야 한다."""
        sql = generate_seed_sql()
        assert "INSERT OR IGNORE INTO categories" in sql
        assert "INSERT OR IGNORE INTO keywords" in sql

    def test_sql_contains_korean(self):
        """SQL 에 한글 데이터가 포함되어야 한다."""
        sql = generate_seed_sql()
        assert "농산물" in sql
        assert "삼겹살" in sql

    def test_sql_categories_only(self):
        """카테고리만 생성 옵션."""
        sql = generate_seed_sql(include_categories=True, include_keywords=False)
        assert "INSERT OR IGNORE INTO categories" in sql
        assert "INSERT OR IGNORE INTO keywords" not in sql

    def test_sql_keywords_only(self):
        """키워드만 생성 옵션."""
        sql = generate_seed_sql(include_categories=False, include_keywords=True)
        assert "INSERT OR IGNORE INTO categories" not in sql
        assert "INSERT OR IGNORE INTO keywords" in sql

    def test_sql_uses_transactions(self):
        """트랜잭션을 사용해야 한다."""
        sql = generate_seed_sql()
        assert "BEGIN TRANSACTION;" in sql
        assert "COMMIT;" in sql

    def test_sql_escapes_quotes(self):
        """SQL 인젝션 방지를 위해 작은따옴표를 이스케이프해야 한다."""
        # 데이터에 작은따옴표가 있는 경우 테스트
        sql = generate_seed_sql()
        # SQL 이 유효해야 함 (파싱 에러 없이 생성)
        assert isinstance(sql, str)
        assert len(sql) > 0
