"""
test_import_validator.py — import_validator 서비스 단위 테스트.

테스트 전략:
    - 인메모리 SQLite + categories/keywords 시드 데이터 사용
    - validate_strict, validate_lenient 두 모드 모두 검증
    - 각 오류 조건 독립 검증 (category_id 미존재, keyword_id 미존재,
      confidence 범위, source enum, 필수 필드, 중복 key 등)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from storage.models import Base, Category, Keyword
from services.import_validator import (
    IMPORT_ALLOWED_SOURCES,
    ValidationResult,
    _build_match_key,
    _deduplicate_by_match_key,
    validate_strict,
    validate_lenient,
)


# ══════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture(scope="module")
def seeded_session(engine) -> Session:
    """categories 와 keywords 를 미리 채운 세션 (module 범위 — 읽기 전용)."""
    Session = sessionmaker(bind=engine)
    s = Session()
    s.add(Category(id="food", name="식품", depth=0, is_active=True))
    s.add(Category(id="food.rice", name="쌀", parent_id="food", depth=1, is_active=True))
    s.add(Category(id="inactive.cat", name="비활성", depth=0, is_active=False))
    s.add(Keyword(id=1, word="밥", is_active=True))
    s.add(Keyword(id=2, word="국수", is_active=True))
    s.commit()
    yield s
    s.close()


def _good_row(**overrides) -> dict:
    """기본적으로 유효한 row — override 로 특정 필드를 변경하여 오류 테스트 가능."""
    base = {
        "match_key": "CJ|햇반|210.000000|g",
        "brand": "CJ",
        "name_core": "햇반",
        "pack_qty": 210.0,
        "pack_unit": "g",
        "category_id": "food.rice",
        "confidence": 0.9,
        "source": "external-ai",
        "keyword_ids": [1, 2],
    }
    base.update(overrides)
    return base


# ══════════════════════════════════════════════════════
# _build_match_key 헬퍼
# ══════════════════════════════════════════════════════

class TestBuildMatchKey:
    def test_builds_correct_key(self):
        row = {"brand": "CJ", "name_core": "햇반", "pack_qty": 210.0, "pack_unit": "g"}
        assert _build_match_key(row) == "CJ|햇반|210.000000|g"

    def test_returns_none_when_missing_field(self):
        assert _build_match_key({"brand": "CJ", "name_core": "햇반"}) is None

    def test_returns_none_when_empty_string(self):
        assert _build_match_key({"brand": "", "name_core": "햇반", "pack_qty": 1.0, "pack_unit": "g"}) is None


# ══════════════════════════════════════════════════════
# _deduplicate_by_match_key
# ══════════════════════════════════════════════════════

class TestDeduplication:
    def test_no_duplicates(self):
        rows = [_good_row(match_key="A|B|1.0|g"), _good_row(match_key="X|Y|2.0|g")]
        deduped, warnings = _deduplicate_by_match_key(rows)
        assert len(deduped) == 2
        assert warnings == []

    def test_duplicate_last_wins(self):
        row1 = _good_row(match_key="A|B|1.0|g", confidence=0.5)
        row2 = _good_row(match_key="A|B|1.0|g", confidence=0.9)
        deduped, warnings = _deduplicate_by_match_key([row1, row2])
        assert len(deduped) == 1
        assert deduped[0]["confidence"] == 0.9
        assert len(warnings) == 1
        assert "A|B|1.0|g" in warnings[0]

    def test_triple_duplicate_last_wins(self):
        rows = [
            _good_row(match_key="K|K|1.0|g", confidence=0.1),
            _good_row(match_key="K|K|1.0|g", confidence=0.5),
            _good_row(match_key="K|K|1.0|g", confidence=0.9),
        ]
        deduped, warnings = _deduplicate_by_match_key(rows)
        assert len(deduped) == 1
        assert deduped[0]["confidence"] == 0.9
        # 두 번 중복 경고 (행 0 vs 1, 행 0/1 vs 2)
        assert len(warnings) == 2


# ══════════════════════════════════════════════════════
# validate_strict
# ══════════════════════════════════════════════════════

class TestValidateStrict:
    def test_valid_row_passes(self, seeded_session):
        result = validate_strict([_good_row()], seeded_session)
        assert result.is_valid
        assert len(result.valid_rows) == 1
        assert result.errors == []

    def test_valid_multiple_rows(self, seeded_session):
        rows = [
            _good_row(match_key="A|B|1.0|g"),
            _good_row(match_key="C|D|2.0|g", source="human"),
        ]
        result = validate_strict(rows, seeded_session)
        assert result.is_valid
        assert len(result.valid_rows) == 2

    def test_single_error_causes_full_reject(self, seeded_session):
        rows = [
            _good_row(match_key="good_row|A|1.0|g"),
            _good_row(match_key="bad_row|B|2.0|g", category_id="nonexistent.cat"),
        ]
        result = validate_strict(rows, seeded_session)
        assert not result.is_valid
        assert result.valid_rows == []    # 전체 reject
        assert len(result.errors) >= 1

    def test_missing_match_key_and_compound(self, seeded_session):
        row = _good_row()
        row.pop("match_key")
        row.pop("brand")
        result = validate_strict([row], seeded_session)
        assert not result.is_valid
        assert any("match_key" in m or "필수" in m for _, m in result.errors)

    def test_missing_category_id(self, seeded_session):
        row = _good_row()
        row["category_id"] = None
        result = validate_strict([row], seeded_session)
        assert not result.is_valid
        assert any("category_id" in m for _, m in result.errors)

    def test_missing_confidence(self, seeded_session):
        row = _good_row()
        row["confidence"] = None
        result = validate_strict([row], seeded_session)
        assert not result.is_valid

    def test_missing_source(self, seeded_session):
        row = _good_row()
        row["source"] = None
        result = validate_strict([row], seeded_session)
        assert not result.is_valid

    def test_nonexistent_category_id(self, seeded_session):
        row = _good_row(category_id="does.not.exist")
        result = validate_strict([row], seeded_session)
        assert not result.is_valid
        assert any("categories" in m for _, m in result.errors)

    def test_inactive_category_rejected(self, seeded_session):
        row = _good_row(category_id="inactive.cat")
        result = validate_strict([row], seeded_session)
        assert not result.is_valid

    def test_nonexistent_keyword_id(self, seeded_session):
        row = _good_row(keyword_ids=[999])
        result = validate_strict([row], seeded_session)
        assert not result.is_valid
        assert any("keywords" in m for _, m in result.errors)

    def test_confidence_below_zero(self, seeded_session):
        row = _good_row(confidence=-0.1)
        result = validate_strict([row], seeded_session)
        assert not result.is_valid

    def test_confidence_above_one(self, seeded_session):
        row = _good_row(confidence=1.1)
        result = validate_strict([row], seeded_session)
        assert not result.is_valid

    @pytest.mark.parametrize("conf", [0.0, 0.5, 1.0])
    def test_confidence_boundary_valid(self, seeded_session, conf):
        row = _good_row(match_key=f"X|Y|{conf}|g", confidence=conf)
        result = validate_strict([row], seeded_session)
        assert result.is_valid, f"confidence={conf} 는 유효해야 함"

    def test_source_crawler_auto_rejected(self, seeded_session):
        row = _good_row(source="crawler-auto")
        result = validate_strict([row], seeded_session)
        assert not result.is_valid
        assert any("crawler-auto" in m or "허용 안 됨" in m for _, m in result.errors)

    def test_source_unknown_rejected(self, seeded_session):
        row = _good_row(source="unknown-source")
        result = validate_strict([row], seeded_session)
        assert not result.is_valid

    @pytest.mark.parametrize("src", ["human", "external-ai"])
    def test_source_allowed_passes(self, seeded_session, src):
        row = _good_row(match_key=f"T|S|1.0|g|{src}", source=src)
        result = validate_strict([row], seeded_session)
        assert result.is_valid

    def test_duplicate_key_warning(self, seeded_session):
        row1 = _good_row(match_key="DUP|test|1.0|g", confidence=0.5)
        row2 = _good_row(match_key="DUP|test|1.0|g", confidence=0.9)
        result = validate_strict([row1, row2], seeded_session)
        assert result.is_valid          # 중복 자체는 오류가 아님 — 마지막 행 우선
        assert len(result.valid_rows) == 1
        assert result.valid_rows[0]["confidence"] == 0.9
        assert len(result.warnings) >= 1

    def test_compound_fields_without_match_key(self, seeded_session):
        """match_key 없이 compound 필드만으로도 통과해야 한다."""
        row = {
            "brand": "농심",
            "name_core": "신라면",
            "pack_qty": 120.0,
            "pack_unit": "g",
            "category_id": "food.rice",
            "confidence": 0.8,
            "source": "human",
        }
        result = validate_strict([row], seeded_session)
        assert result.is_valid


# ══════════════════════════════════════════════════════
# validate_lenient
# ══════════════════════════════════════════════════════

class TestValidateLenient:
    def test_mixed_rows_separates_errors(self, seeded_session):
        valid = _good_row(match_key="V|A|1.0|g")
        invalid = _good_row(match_key="B|A|1.0|g", category_id="nonexistent")
        result = validate_lenient([valid, invalid], seeded_session)
        assert len(result.valid_rows) == 1
        assert len(result.errors) >= 1
        assert result.valid_rows[0]["match_key"] == "V|A|1.0|g"

    def test_all_valid_passes(self, seeded_session):
        rows = [
            _good_row(match_key="L1|A|1.0|g"),
            _good_row(match_key="L2|B|2.0|g"),
        ]
        result = validate_lenient(rows, seeded_session)
        assert len(result.valid_rows) == 2
        assert result.errors == []

    def test_all_invalid_empty_valid_rows(self, seeded_session):
        rows = [
            _good_row(match_key="INV|A|1.0|g", confidence=-0.5),
            _good_row(match_key="INV|B|2.0|g", source="crawler-auto"),
        ]
        result = validate_lenient(rows, seeded_session)
        assert result.valid_rows == []
        assert len(result.errors) >= 2

    def test_partial_pass_returns_valid_subset(self, seeded_session):
        rows = [
            _good_row(match_key="GOOD|A|1.0|g"),
            _good_row(match_key="BAD|B|2.0|g", source="crawler-auto"),
            _good_row(match_key="GOOD2|C|3.0|g"),
        ]
        result = validate_lenient(rows, seeded_session)
        assert len(result.valid_rows) == 2
        assert any(r["match_key"] == "GOOD|A|1.0|g" for r in result.valid_rows)
        assert any(r["match_key"] == "GOOD2|C|3.0|g" for r in result.valid_rows)

    def test_duplicate_in_lenient_last_wins_with_warning(self, seeded_session):
        row1 = _good_row(match_key="DUP2|x|1.0|g", confidence=0.3)
        row2 = _good_row(match_key="DUP2|x|1.0|g", confidence=0.8)
        result = validate_lenient([row1, row2], seeded_session)
        assert len(result.valid_rows) == 1
        assert result.valid_rows[0]["confidence"] == 0.8
        assert any("DUP2|x|1.0|g" in w for w in result.warnings)

    def test_keyword_ids_none_allowed(self, seeded_session):
        """keyword_ids=None 은 유효 (키워드 미지정)."""
        row = _good_row(keyword_ids=None)
        result = validate_strict([row], seeded_session)
        assert result.is_valid

    def test_keyword_ids_empty_list_allowed(self, seeded_session):
        """keyword_ids=[] 은 유효."""
        row = _good_row(keyword_ids=[])
        result = validate_strict([row], seeded_session)
        assert result.is_valid

    def test_string_keyword_id_converted(self, seeded_session):
        """keyword_ids 안의 string 정수도 처리된다 (CSV 경유 시 string으로 들어옴)."""
        row = _good_row(keyword_ids=["1", "2"])
        result = validate_strict([row], seeded_session)
        assert result.is_valid
