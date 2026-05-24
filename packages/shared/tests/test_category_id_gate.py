"""category_id_gate.py 단위 테스트.

검증 항목:
- tree ID 직접 통과
- dot-notation legacy ID 마이그레이션
- 정수 ID 마이그레이션
- 한글 ID 마이그레이션
- 미등록 ID escalation
- 빈 입력
- migrate_category_ids() 배치 처리 통계
"""

from __future__ import annotations

import pytest
import sys
import os

# shared/core를 직접 임포트할 수 있도록 경로 추가
_PACKAGES = os.path.join(os.path.dirname(__file__), "..", "..")
if _PACKAGES not in sys.path:
    sys.path.insert(0, _PACKAGES)

_SHARED_CORE = os.path.join(os.path.dirname(__file__), "..", "core")
if _SHARED_CORE not in sys.path:
    sys.path.insert(0, _SHARED_CORE)

from shared.core.category_id_gate import (
    validate_category_id,
    migrate_category_id,
    is_valid_tree_category,
    canonical_tree_id,
    get_escalation_queue,
    clear_escalation_queue,
    REASON_EMPTY_INPUT,
    REASON_MIGRATED,
    REASON_ESCALATED,
)
from shared.core.category_migration import migrate_category_ids


@pytest.fixture(autouse=True)
def _clean_queue():
    """각 테스트 전후 escalation 큐 초기화."""
    clear_escalation_queue()
    yield
    clear_escalation_queue()


class TestDirectTreeIdPass:
    """category_tree.yaml에 존재하는 ID는 바로 통과."""

    def test_fresh_food(self):
        r = validate_category_id("fresh_food")
        assert r.is_valid
        assert r.canonical_id == "fresh_food"
        assert not r.was_migrated
        assert not r.escalated

    def test_meal_kit(self):
        r = validate_category_id("meal_kit")
        assert r.is_valid
        assert r.canonical_id == "meal_kit"

    def test_processed_food(self):
        assert is_valid_tree_category("processed_food")

    def test_canonical_tree_id_returns_same(self):
        assert canonical_tree_id("fruit") == "fruit"

    def test_rice_tree_id(self):
        r = validate_category_id("rice")
        assert r.is_valid
        assert r.canonical_id == "rice"


class TestDotNotationMigration:
    """dot-notation AI-admin/db-admin ID → tree ID 마이그레이션."""

    def test_produce_fruit_migrates(self):
        r = validate_category_id("produce.fruit")
        assert r.is_valid
        assert r.canonical_id == "fruit"
        assert r.was_migrated
        assert r.reason == REASON_MIGRATED

    def test_produce_vegetable_migrates(self):
        r = validate_category_id("produce.vegetable")
        assert r.is_valid
        assert r.was_migrated

    def test_meat_beef_migrates(self):
        r = validate_category_id("meat.beef")
        assert r.is_valid
        assert r.canonical_id == "beef"
        assert r.was_migrated

    def test_dairy_milk_migrates(self):
        r = validate_category_id("dairy.milk")
        assert r.is_valid
        assert r.was_migrated

    def test_electronics_mobile_migrates(self):
        r = validate_category_id("electronics.mobile")
        assert r.is_valid
        assert r.canonical_id == "mobile_phone"
        assert r.was_migrated

    def test_grain_rice_migrates(self):
        r = validate_category_id("grain.rice")
        assert r.is_valid
        assert r.canonical_id == "rice"
        assert r.was_migrated

    def test_migrate_category_id_returns_tuple(self):
        cid, migrated = migrate_category_id("produce.fruit")
        assert cid == "fruit"
        assert migrated is True


class TestIntegerIdMigration:
    """정수 ID 마이그레이션 (legacy DB 시드)."""

    def test_integer_8_migrates(self):
        r = validate_category_id("8")
        assert r.is_valid
        assert r.was_migrated

    def test_integer_29_migrates(self):
        r = validate_category_id("29")
        assert r.is_valid
        assert r.was_migrated

    def test_integer_1_migrates(self):
        r = validate_category_id("1")
        assert r.is_valid
        assert r.was_migrated


class TestKoreanIdMigration:
    """한글 ID 마이그레이션."""

    def test_korean_meat_migrates(self):
        r = validate_category_id("정육")
        assert r.is_valid
        assert r.was_migrated

    def test_korean_appliance_migrates(self):
        r = validate_category_id("가전")
        assert r.is_valid
        assert r.was_migrated


class TestEscalation:
    """미등록 ID는 escalation 큐로."""

    def test_service_voucher_escalates(self):
        r = validate_category_id("service.voucher")
        assert not r.is_valid
        assert r.escalated
        assert r.reason == REASON_ESCALATED

    def test_escalation_queue_grows(self):
        clear_escalation_queue()
        validate_category_id("unknown.category.xyz")
        validate_category_id("pet.general")
        q = get_escalation_queue()
        assert len(q) == 2

    def test_escalated_ids_in_queue(self):
        validate_category_id("sports.general")
        q = get_escalation_queue()
        original_ids = [item["original_id"] for item in q]
        assert "sports.general" in original_ids

    def test_canonical_tree_id_none_for_unknown(self):
        assert canonical_tree_id("not.in.tree") is None

    def test_migrate_category_id_none_for_unknown(self):
        cid, migrated = migrate_category_id("not.in.tree")
        assert cid is None
        assert migrated is False


class TestEmptyInput:
    """빈/None 입력 처리."""

    def test_none_input(self):
        r = validate_category_id(None)
        assert not r.is_valid
        assert r.reason == REASON_EMPTY_INPUT
        assert not r.escalated

    def test_empty_string(self):
        r = validate_category_id("")
        assert not r.is_valid
        assert r.reason == REASON_EMPTY_INPUT

    def test_whitespace_only(self):
        r = validate_category_id("   ")
        assert not r.is_valid
        assert r.reason == REASON_EMPTY_INPUT


class TestBatchMigration:
    """migrate_category_ids() 배치 처리 및 통계."""

    def test_batch_stats_counts(self):
        records = [
            {"id": 1, "category_id": "fresh_food"},     # 직접 통과
            {"id": 2, "category_id": "produce.fruit"},  # 마이그
            {"id": 3, "category_id": "grain.rice"},     # 마이그
            {"id": 4, "category_id": "service.voucher"}, # escalation
            {"id": 5, "category_id": ""},               # 빈 입력
        ]
        migrated_records, stats = migrate_category_ids(records, category_key="category_id")
        assert stats.total == 5
        assert stats.already_valid >= 1
        assert stats.migrated >= 2
        assert stats.escalated >= 1
        assert len(migrated_records) == 5

    def test_batch_migrated_values_updated(self):
        records = [{"cat": "produce.fruit"}]
        results, _ = migrate_category_ids(records, category_key="cat")
        assert results[0]["cat"] == "fruit"

    def test_batch_valid_id_unchanged(self):
        records = [{"cat": "meal_kit"}]
        results, _ = migrate_category_ids(records, category_key="cat")
        assert results[0]["cat"] == "meal_kit"
