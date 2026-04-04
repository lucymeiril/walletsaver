"""Dead letter queue tests."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch

from pipeline.dead_letter import (
    write_dead_letter,
    list_dead_letters,
    read_dead_letter,
    remove_dead_letter,
)


@pytest.fixture
def dlq_dir(tmp_path):
    with patch("pipeline.dead_letter._DLQ_DIR", tmp_path):
        yield tmp_path


class TestDeadLetterQueue:
    def test_write_creates_file(self, dlq_dir):
        records = [{"name": "사과", "price": 3000}]
        path = write_dead_letter(records, crawler_name="emart", target="db_admin")
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["record_count"] == 1
        assert data["crawler_name"] == "emart"
        assert data["records"] == records

    def test_list_returns_sorted(self, dlq_dir):
        write_dead_letter([{"a": 1}], crawler_name="a", target="x")
        write_dead_letter([{"b": 2}], crawler_name="b", target="x")
        files = list_dead_letters()
        assert len(files) == 2
        assert files[0].name < files[1].name  # alphabetical/timestamp order

    def test_read_round_trip(self, dlq_dir):
        records = [{"x": 42}]
        path = write_dead_letter(records, crawler_name="test", target="store")
        data = read_dead_letter(path)
        assert data["records"] == records

    def test_remove_deletes_file(self, dlq_dir):
        path = write_dead_letter([{"x": 1}], crawler_name="test", target="store")
        assert path.exists()
        remove_dead_letter(path)
        assert not path.exists()

    def test_list_empty_when_no_dir(self, tmp_path):
        with patch("pipeline.dead_letter._DLQ_DIR", tmp_path / "nonexistent"):
            assert list_dead_letters() == []
