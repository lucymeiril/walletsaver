"""TDD tests for rd-ai-live-run slice.

Tests:
1. empty_learned_tables() — backup file created, rows become 0
2. count_keyword_category_proposals() — adversarial v2 proposal counter
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def temp_ai_control_db(tmp_path: Path) -> Path:
    """Create a minimal in-memory-style SQLite DB with learned_knowledge and product_matches."""
    db_path = tmp_path / "test_ai_control.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE learned_knowledge (
            knowledge_id TEXT PRIMARY KEY,
            knowledge_type TEXT NOT NULL,
            source_name TEXT,
            pattern TEXT,
            target_value TEXT,
            negative_examples TEXT DEFAULT '[]',
            positive_examples TEXT DEFAULT '[]',
            is_active INTEGER DEFAULT 1,
            created_from_decision_id TEXT,
            applied_count INTEGER DEFAULT 0,
            success_count INTEGER DEFAULT 0
        );
        CREATE TABLE product_matches (
            match_id TEXT PRIMARY KEY,
            source_id TEXT,
            source_name TEXT,
            signature_key TEXT,
            target_type TEXT DEFAULT 'canonical_product',
            target_id TEXT,
            canonical_product_id TEXT,
            canonical_product_name TEXT,
            category_id TEXT,
            keywords TEXT DEFAULT '[]',
            unit_metadata TEXT DEFAULT '{}',
            allowed_title_patterns TEXT DEFAULT '[]',
            normalized_title_variants TEXT DEFAULT '[]',
            blocked_title_patterns TEXT DEFAULT '[]',
            package_signature TEXT,
            package_signature_required INTEGER DEFAULT 1,
            source_product_id_history TEXT DEFAULT '[]',
            provenance_source TEXT DEFAULT 'ai',
            provider_name TEXT,
            model_name TEXT,
            raw_record_id TEXT,
            batch_id TEXT,
            confidence REAL,
            status TEXT DEFAULT 'pending',
            audit_reason TEXT,
            audit_metadata TEXT DEFAULT '{}',
            reviewed_by TEXT,
            approved_by TEXT,
            approved_at DATETIME,
            version INTEGER DEFAULT 1,
            is_active INTEGER DEFAULT 1,
            disabled_reason TEXT,
            created_at DATETIME,
            updated_at DATETIME
        );
        INSERT INTO learned_knowledge (knowledge_id, knowledge_type, source_name, pattern, target_value)
            VALUES ('kw:001', 'keyword_alias_approved', 'emart', '두부', '{"word":"두부"}');
        INSERT INTO learned_knowledge (knowledge_id, knowledge_type, source_name, pattern, target_value)
            VALUES ('kw:002', 'keyword_alias_approved', 'homeplus', '달걀', '{"word":"달걀"}');
        INSERT INTO learned_knowledge (knowledge_id, knowledge_type, source_name, pattern, target_value)
            VALUES ('kw:003', 'other_type', 'emart', '우유', '{"word":"우유"}');
        INSERT INTO product_matches (match_id, source_id, source_name, signature_key, status)
            VALUES ('pm:001', 'emart', 'emart', '두부', 'approved');
        INSERT INTO product_matches (match_id, source_id, source_name, signature_key, status)
            VALUES ('pm:002', 'homeplus', 'homeplus', '달걀', 'approved');
    """)
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture()
def backup_dir(tmp_path: Path) -> Path:
    backup = tmp_path / "backup"
    backup.mkdir()
    return backup


# ---------------------------------------------------------------------------
# Import the module under test (after it exists)
# ---------------------------------------------------------------------------


def _import_module():
    import importlib
    import sys

    # Ensure tools/ is on path (conftest does this, but be safe)
    tools_dir = str(Path(__file__).resolve().parents[1])
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    return importlib.import_module("ai_live_run")


# ---------------------------------------------------------------------------
# Test: empty_learned_tables creates backup and zeros out rows
# ---------------------------------------------------------------------------


class TestEmptyLearnedTables:
    def test_backup_file_created(self, temp_ai_control_db: Path, backup_dir: Path):
        """empty_learned_tables() must write a JSON backup file."""
        mod = _import_module()
        result = mod.empty_learned_tables(
            db_path=str(temp_ai_control_db),
            backup_dir=str(backup_dir),
        )
        backup_path = Path(result["backup_path"])
        assert backup_path.exists(), "backup file must be created"
        assert backup_path.suffix == ".json", "backup must be JSON"

    def test_backup_contains_original_rows(self, temp_ai_control_db: Path, backup_dir: Path):
        """Backup JSON must preserve both keyword_alias_approved rows and product_matches."""
        mod = _import_module()
        result = mod.empty_learned_tables(
            db_path=str(temp_ai_control_db),
            backup_dir=str(backup_dir),
        )
        backup_data = json.loads(Path(result["backup_path"]).read_text(encoding="utf-8"))
        # Both keyword_alias_approved rows should be in backup (not other_type)
        alias_rows = backup_data.get("learned_knowledge_keyword_alias_approved", [])
        assert len(alias_rows) == 2, f"Expected 2 keyword_alias rows, got {len(alias_rows)}"
        # All product_match rows
        pm_rows = backup_data.get("product_matches", [])
        assert len(pm_rows) == 2, f"Expected 2 product_match rows, got {len(pm_rows)}"

    def test_keyword_alias_rows_zeroed_after_empty(
        self, temp_ai_control_db: Path, backup_dir: Path
    ):
        """keyword_alias_approved rows must be 0 after empty."""
        mod = _import_module()
        result = mod.empty_learned_tables(
            db_path=str(temp_ai_control_db),
            backup_dir=str(backup_dir),
        )
        assert result["keyword_alias_before"] == 2
        assert result["keyword_alias_after"] == 0

    def test_product_matches_zeroed_after_empty(
        self, temp_ai_control_db: Path, backup_dir: Path
    ):
        """product_matches rows must be 0 after empty."""
        mod = _import_module()
        result = mod.empty_learned_tables(
            db_path=str(temp_ai_control_db),
            backup_dir=str(backup_dir),
        )
        assert result["product_matches_before"] == 2
        assert result["product_matches_after"] == 0

    def test_other_knowledge_types_preserved(
        self, temp_ai_control_db: Path, backup_dir: Path
    ):
        """Non-keyword_alias_approved rows in learned_knowledge must NOT be deleted."""
        mod = _import_module()
        mod.empty_learned_tables(
            db_path=str(temp_ai_control_db),
            backup_dir=str(backup_dir),
        )
        conn = sqlite3.connect(str(temp_ai_control_db))
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM learned_knowledge WHERE knowledge_type != 'keyword_alias_approved'"
        )
        count = cur.fetchone()[0]
        conn.close()
        assert count == 1, "Non-alias knowledge types must be preserved"

    def test_idempotent_on_empty_tables(self, temp_ai_control_db: Path, backup_dir: Path):
        """Calling empty_learned_tables twice must not crash."""
        mod = _import_module()
        mod.empty_learned_tables(db_path=str(temp_ai_control_db), backup_dir=str(backup_dir))
        result2 = mod.empty_learned_tables(
            db_path=str(temp_ai_control_db), backup_dir=str(backup_dir)
        )
        assert result2["keyword_alias_after"] == 0
        assert result2["product_matches_after"] == 0


# ---------------------------------------------------------------------------
# Test: count_keyword_category_proposals from proposal rows
# ---------------------------------------------------------------------------


class TestCountKeywordCategoryProposals:
    @pytest.fixture()
    def proposal_rows_sample(self) -> list[dict]:
        return [
            {"raw_record_id": "r1", "source": "emart", "category": "food.dairy", "keywords": ["우유"], "ai_confidence": 0.95},
            {"raw_record_id": "r2", "source": "emart", "category": "food.dairy", "keywords": ["치즈", "우유"], "ai_confidence": 0.88},
            {"raw_record_id": "r3", "source": "homeplus", "category": "retail.general", "keywords": ["상품"], "ai_confidence": 0.42},
            {"raw_record_id": "r4", "source": "homeplus", "category": "food.snack", "keywords": ["과자"], "ai_confidence": 0.91},
            {"raw_record_id": "r5", "source": "lottemart", "category": "produce.fruit", "keywords": ["사과", "과일"], "ai_confidence": 0.85},
            {"raw_record_id": "r6", "source": "costco", "category": "retail.general", "keywords": ["상품"], "ai_confidence": 0.42},
        ]

    def test_total_keyword_proposals(self, proposal_rows_sample):
        mod = _import_module()
        result = mod.count_keyword_category_proposals(proposal_rows_sample)
        # r1:1, r2:2, r3:1, r4:1, r5:2, r6:1 = 8 total keyword tokens
        assert result["total_keyword_proposals"] == 8

    def test_unique_category_proposals(self, proposal_rows_sample):
        mod = _import_module()
        result = mod.count_keyword_category_proposals(proposal_rows_sample)
        # food.dairy, retail.general, food.snack, produce.fruit = 4 unique
        assert result["unique_categories_proposed"] == 4

    def test_retail_general_count(self, proposal_rows_sample):
        mod = _import_module()
        result = mod.count_keyword_category_proposals(proposal_rows_sample)
        assert result["retail_general_count"] == 2
        assert result["retail_general_ratio"] == pytest.approx(2 / 6, rel=0.01)

    def test_per_mart_keyword_counts(self, proposal_rows_sample):
        mod = _import_module()
        result = mod.count_keyword_category_proposals(proposal_rows_sample)
        per_mart = result["per_mart_keyword_counts"]
        assert per_mart["emart"] == 3  # r1:1 + r2:2
        assert per_mart["homeplus"] == 2  # r3:1 + r4:1
        assert per_mart["lottemart"] == 2  # r5:2
        assert per_mart["costco"] == 1  # r6:1

    def test_empty_proposals(self):
        mod = _import_module()
        result = mod.count_keyword_category_proposals([])
        assert result["total_keyword_proposals"] == 0
        assert result["unique_categories_proposed"] == 0
        assert result["retail_general_count"] == 0
        assert result["retail_general_ratio"] == 0.0


# ---------------------------------------------------------------------------
# Test: build_confidence_histogram
# ---------------------------------------------------------------------------


class TestBuildConfidenceHistogram:
    def test_buckets(self):
        mod = _import_module()
        rows = [
            {"ai_confidence": 0.95},
            {"ai_confidence": 0.92},
            {"ai_confidence": 0.80},
            {"ai_confidence": 0.65},
            {"ai_confidence": 0.42},
        ]
        hist = mod.build_confidence_histogram(rows)
        assert hist["ge_0_9"]["count"] == 2
        assert hist["ge_0_7_lt_0_9"]["count"] == 1
        assert hist["lt_0_7"]["count"] == 2
        # Percentages
        assert hist["ge_0_9"]["pct"] == pytest.approx(40.0, rel=0.01)

    def test_empty_rows(self):
        mod = _import_module()
        hist = mod.build_confidence_histogram([])
        assert hist["ge_0_9"]["count"] == 0
        assert hist["ge_0_9"]["pct"] == 0.0
