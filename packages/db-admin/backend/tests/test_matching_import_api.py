"""
test_matching_import_api.py — POST /api/import/classified/* 엔드포인트 통합 테스트.

테스트 케이스:
    1. preview 해피패스 — JSONL
    2. preview 해피패스 — CSV
    3. strict 모드 1 row error → 전체 reject
    4. lenient 모드 valid 행만 통과
    5. confirm 후 DB 반영 (matching_entries row count 증가)
    6. 동일 trace_id 재confirm = 멱등 (no double-write)
    7. 잘못된 multipart (file 필드 누락)
    8. 빈 파일 거부
    9. 파일 크기 초과 거부
"""

from __future__ import annotations

import io
import json
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from storage.models import Base, Category, Keyword, MatchingEntry


# ══════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════

@pytest.fixture
def db_fixture(monkeypatch):
    """인메모리 SQLite + 시드 데이터 + 라우트 모듈 monkeypatch."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    # 시드 데이터
    s = Session()
    s.add(Category(id="food", name="식품", depth=0, is_active=True))
    s.add(Category(id="food.rice", name="쌀", parent_id="food", depth=1, is_active=True))
    s.add(Keyword(id=1, word="밥", is_active=True))
    s.add(Keyword(id=2, word="국수", is_active=True))
    s.commit()
    s.close()

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

    import api.routes.matching_import as mi_routes
    monkeypatch.setattr(mi_routes, "get_session", get_test_session)
    monkeypatch.setattr(mi_routes, "managed_session", managed_test_session)

    import services.import_validator as iv_module
    # validator 내부에서 직접 import_validator 를 사용하므로,
    # matching_sync 내부 _compute_diff 도 동일 Session 을 통해 동작해야 함.
    # 여기서는 모든 DB 작업이 같은 engine 을 공유하도록 monkeypatch 적용.

    # _confirmed_traces 초기화 (테스트 격리)
    monkeypatch.setattr(mi_routes, "_confirmed_traces", {})
    monkeypatch.setattr(mi_routes, "_failure_rows_store", {})

    yield Session, engine


@pytest.fixture
def client(db_fixture):
    """DB monkeypatch 가 적용된 TestClient."""
    from config import settings
    settings.REQUIRE_AUTH = False

    from api.app import create_app
    app = create_app()
    return TestClient(app)


# ── JSONL 파일 생성 헬퍼 ──────────────────────────────────────────────────────

def _make_jsonl(*rows: dict) -> bytes:
    lines = [json.dumps(r, ensure_ascii=False) for r in rows]
    return "\n".join(lines).encode("utf-8")


def _make_csv_bytes(rows: list[dict]) -> bytes:
    import csv, io
    fields = list(rows[0].keys()) if rows else []
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        serialized = {}
        for k, v in row.items():
            if isinstance(v, list):
                serialized[k] = json.dumps(v, ensure_ascii=False)
            elif v is None:
                serialized[k] = ""
            else:
                serialized[k] = v
        writer.writerow(serialized)
    return buf.getvalue().encode("utf-8")


def _good_row(**overrides) -> dict:
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
# 1. Preview 해피패스 — JSONL
# ══════════════════════════════════════════════════════

class TestPreviewJsonl:
    def test_happy_path(self, client):
        content = _make_jsonl(_good_row())
        resp = client.post(
            "/api/import/classified/preview",
            files={"file": ("data.jsonl", io.BytesIO(content), "application/octet-stream")},
            data={"mode": "strict"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["total_rows"] == 1
        assert body["valid_rows"] == 1
        assert "diff" in body
        assert body["diff"]["added"] == 1     # 신규 추가
        assert "batch_id" in body
        assert "trace_id" in body
        assert body["errors"] == []

    def test_preview_does_not_write_to_db(self, db_fixture, client):
        Session, _ = db_fixture
        content = _make_jsonl(_good_row())
        client.post(
            "/api/import/classified/preview",
            files={"file": ("data.jsonl", io.BytesIO(content), "application/octet-stream")},
            data={"mode": "strict"},
        )
        s = Session()
        count = s.query(MatchingEntry).count()
        s.close()
        assert count == 0   # preview 는 DB 에 쓰지 않음


# ══════════════════════════════════════════════════════
# 2. Preview 해피패스 — CSV
# ══════════════════════════════════════════════════════

class TestPreviewCsv:
    def test_happy_path_csv(self, client):
        content = _make_csv_bytes([_good_row(match_key="CSV|A|1.0|g")])
        resp = client.post(
            "/api/import/classified/preview",
            files={"file": ("data.csv", io.BytesIO(content), "text/csv")},
            data={"mode": "strict"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["total_rows"] == 1
        assert body["valid_rows"] == 1

    def test_csv_multi_rows(self, client):
        rows = [
            _good_row(match_key="CSV|A|1.0|g"),
            _good_row(match_key="CSV|B|2.0|g", source="human"),
        ]
        content = _make_csv_bytes(rows)
        resp = client.post(
            "/api/import/classified/preview",
            files={"file": ("data.csv", io.BytesIO(content), "text/csv")},
            data={"mode": "lenient"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["valid_rows"] == 2


# ══════════════════════════════════════════════════════
# 3. Strict 모드 — 1 row error → 전체 reject
# ══════════════════════════════════════════════════════

class TestStrictModeReject:
    def test_one_bad_row_rejects_all(self, client):
        rows = [
            _good_row(match_key="GOOD|A|1.0|g"),
            _good_row(match_key="BAD|B|2.0|g", category_id="does.not.exist"),
        ]
        content = _make_jsonl(*rows)
        resp = client.post(
            "/api/import/classified/preview",
            files={"file": ("data.jsonl", io.BytesIO(content), "application/octet-stream")},
            data={"mode": "strict"},
        )
        assert resp.status_code == 422
        body = resp.json()
        assert body["ok"] is False
        assert body["valid_rows"] == 0
        assert len(body["errors"]) >= 1

    def test_crawler_auto_source_rejected(self, client):
        content = _make_jsonl(_good_row(source="crawler-auto"))
        resp = client.post(
            "/api/import/classified/preview",
            files={"file": ("data.jsonl", io.BytesIO(content), "application/octet-stream")},
            data={"mode": "strict"},
        )
        assert resp.status_code == 422
        body = resp.json()
        assert body["ok"] is False

    def test_confidence_out_of_range(self, client):
        content = _make_jsonl(_good_row(confidence=1.5))
        resp = client.post(
            "/api/import/classified/preview",
            files={"file": ("data.jsonl", io.BytesIO(content), "application/octet-stream")},
            data={"mode": "strict"},
        )
        assert resp.status_code == 422


# ══════════════════════════════════════════════════════
# 4. Lenient 모드 — valid 행만 통과
# ══════════════════════════════════════════════════════

class TestLenientMode:
    def test_valid_only_passes(self, client):
        rows = [
            _good_row(match_key="GOOD|L|1.0|g"),
            _good_row(match_key="BAD|L|2.0|g", source="crawler-auto"),
        ]
        content = _make_jsonl(*rows)
        resp = client.post(
            "/api/import/classified/preview",
            files={"file": ("data.jsonl", io.BytesIO(content), "application/octet-stream")},
            data={"mode": "lenient"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["valid_rows"] == 1
        assert len(body["errors"]) >= 1

    def test_all_invalid_returns_200_empty_valid(self, client):
        rows = [
            _good_row(match_key="ALL_INV|A|1.0|g", source="crawler-auto"),
            _good_row(match_key="ALL_INV|B|2.0|g", confidence=-1.0),
        ]
        content = _make_jsonl(*rows)
        resp = client.post(
            "/api/import/classified/preview",
            files={"file": ("data.jsonl", io.BytesIO(content), "application/octet-stream")},
            data={"mode": "lenient"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["valid_rows"] == 0
        assert len(body["errors"]) >= 2


# ══════════════════════════════════════════════════════
# 5. Confirm 후 DB 반영
# ══════════════════════════════════════════════════════

class TestConfirmWritesToDb:
    def test_confirm_increases_row_count(self, db_fixture, client):
        Session, _ = db_fixture
        s = Session()
        count_before = s.query(MatchingEntry).count()
        s.close()

        content = _make_jsonl(
            _good_row(match_key="CONFIRM|A|1.0|g"),
            _good_row(match_key="CONFIRM|B|2.0|g", source="human"),
        )
        resp = client.post(
            "/api/import/classified/confirm",
            files={"file": ("data.jsonl", io.BytesIO(content), "application/octet-stream")},
            data={"mode": "strict"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["inserted"] == 2

        s = Session()
        count_after = s.query(MatchingEntry).count()
        s.close()
        assert count_after == count_before + 2

    def test_confirm_response_has_required_fields(self, client):
        content = _make_jsonl(_good_row(match_key="RESP|FIELDS|1.0|g"))
        resp = client.post(
            "/api/import/classified/confirm",
            files={"file": ("data.jsonl", io.BytesIO(content), "application/octet-stream")},
            data={"mode": "strict"},
        )
        assert resp.status_code == 200
        body = resp.json()
        for key in ("ok", "trace_id", "mode", "inserted", "updated", "errors", "warnings",
                    "failure_csv_url", "idempotent"):
            assert key in body, f"응답에 '{key}' 필드가 없음"

    def test_confirm_strict_bad_row_rejected(self, db_fixture, client):
        Session, _ = db_fixture
        s = Session()
        count_before = s.query(MatchingEntry).count()
        s.close()

        content = _make_jsonl(_good_row(category_id="does.not.exist"))
        resp = client.post(
            "/api/import/classified/confirm",
            files={"file": ("data.jsonl", io.BytesIO(content), "application/octet-stream")},
            data={"mode": "strict"},
        )
        assert resp.status_code == 422
        # DB 에 아무것도 쓰이지 않음
        s = Session()
        count_after = s.query(MatchingEntry).count()
        s.close()
        assert count_after == count_before


# ══════════════════════════════════════════════════════
# 6. 멱등성 — 동일 trace_id 재confirm = no double-write
# ══════════════════════════════════════════════════════

class TestIdempotency:
    def test_same_file_twice_no_double_write(self, db_fixture, client):
        Session, _ = db_fixture
        content = _make_jsonl(_good_row(match_key="IDEM|A|1.0|g"))

        resp1 = client.post(
            "/api/import/classified/confirm",
            files={"file": ("data.jsonl", io.BytesIO(content), "application/octet-stream")},
            data={"mode": "strict"},
        )
        assert resp1.status_code == 200
        assert resp1.json()["idempotent"] is False

        s = Session()
        count_after_first = s.query(MatchingEntry).count()
        s.close()

        # 동일 파일 재전송
        resp2 = client.post(
            "/api/import/classified/confirm",
            files={"file": ("data.jsonl", io.BytesIO(content), "application/octet-stream")},
            data={"mode": "strict"},
        )
        assert resp2.status_code == 200
        assert resp2.json()["idempotent"] is True

        s = Session()
        count_after_second = s.query(MatchingEntry).count()
        s.close()
        # DB row count 가 변하지 않아야 함
        assert count_after_second == count_after_first

    def test_explicit_trace_id_idempotent(self, db_fixture, client):
        Session, _ = db_fixture
        content = _make_jsonl(_good_row(match_key="EXPLICT|TRACE|1.0|g"))

        resp1 = client.post(
            "/api/import/classified/confirm",
            files={"file": ("data.jsonl", io.BytesIO(content), "application/octet-stream")},
            data={"mode": "strict", "trace_id": "my-custom-trace-123"},
        )
        assert resp1.status_code == 200
        assert resp1.json()["trace_id"] == "my-custom-trace-123"

        resp2 = client.post(
            "/api/import/classified/confirm",
            files={"file": ("data.jsonl", io.BytesIO(content), "application/octet-stream")},
            data={"mode": "strict", "trace_id": "my-custom-trace-123"},
        )
        assert resp2.status_code == 200
        assert resp2.json()["idempotent"] is True


# ══════════════════════════════════════════════════════
# 7. 엣지 케이스
# ══════════════════════════════════════════════════════

class TestEdgeCases:
    def test_missing_file_field_returns_422(self, client):
        """file 필드 없이 요청 → 422"""
        resp = client.post(
            "/api/import/classified/preview",
            data={"mode": "strict"},
        )
        assert resp.status_code == 422

    def test_empty_file_rejected(self, client):
        """빈 파일 → 422"""
        resp = client.post(
            "/api/import/classified/preview",
            files={"file": ("data.jsonl", io.BytesIO(b""), "application/octet-stream")},
            data={"mode": "strict"},
        )
        assert resp.status_code == 422

    def test_unsupported_file_format_rejected(self, client):
        """.txt 파일 → 422"""
        content = b'{"match_key": "A|B|1.0|g"}'
        resp = client.post(
            "/api/import/classified/preview",
            files={"file": ("data.txt", io.BytesIO(content), "text/plain")},
            data={"mode": "strict"},
        )
        assert resp.status_code == 422

    def test_file_too_large_rejected(self, monkeypatch, client):
        """파일 크기 초과 → 413"""
        import api.routes.matching_import as mi_routes
        monkeypatch.setattr(mi_routes, "MAX_IMPORT_FILE_BYTES", 50)  # 50 바이트 임계치
        large_content = _make_jsonl(_good_row())  # 일반 row 는 50 바이트 초과
        resp = client.post(
            "/api/import/classified/preview",
            files={"file": ("data.jsonl", io.BytesIO(large_content), "application/octet-stream")},
            data={"mode": "strict"},
        )
        assert resp.status_code == 413

    def test_invalid_mode_rejected(self, client):
        """mode=invalid → 422"""
        content = _make_jsonl(_good_row())
        resp = client.post(
            "/api/import/classified/preview",
            files={"file": ("data.jsonl", io.BytesIO(content), "application/octet-stream")},
            data={"mode": "invalid"},
        )
        assert resp.status_code == 422

    def test_empty_jsonl_no_rows(self, client):
        """줄바꿈만 있는 JSONL (유효 행 0개) → 422"""
        content = b"\n\n\n"
        resp = client.post(
            "/api/import/classified/preview",
            files={"file": ("data.jsonl", io.BytesIO(content), "application/octet-stream")},
            data={"mode": "strict"},
        )
        assert resp.status_code == 422

    def test_malformed_jsonl(self, client):
        """잘못된 JSON → 422"""
        content = b'{"match_key": "A|B|1.0|g"\n{broken json\n'
        resp = client.post(
            "/api/import/classified/preview",
            files={"file": ("data.jsonl", io.BytesIO(content), "application/octet-stream")},
            data={"mode": "strict"},
        )
        assert resp.status_code == 422

    def test_failure_csv_download(self, client):
        """confirm 실패 row 가 있을 때 failure_csv_url 이 작동해야 한다 (lenient 모드)."""
        rows = [
            _good_row(match_key="CSV_DL|A|1.0|g"),
            _good_row(match_key="CSV_DL|B|2.0|g", source="crawler-auto"),  # invalid
        ]
        content = _make_jsonl(*rows)
        resp = client.post(
            "/api/import/classified/confirm",
            files={"file": ("data.jsonl", io.BytesIO(content), "application/octet-stream")},
            data={"mode": "lenient"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["failure_csv_url"] is not None

        # CSV 다운로드 엔드포인트 동작 확인
        csv_resp = client.get(body["failure_csv_url"])
        assert csv_resp.status_code == 200
        assert "text/csv" in csv_resp.headers["content-type"]

    def test_confirm_csv_format(self, db_fixture, client):
        """CSV 형식 파일로도 confirm 가능해야 한다."""
        Session, _ = db_fixture
        row = _good_row(match_key="CSV_CONFIRM|A|1.0|g")
        content = _make_csv_bytes([row])
        resp = client.post(
            "/api/import/classified/confirm",
            files={"file": ("data.csv", io.BytesIO(content), "text/csv")},
            data={"mode": "strict"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["inserted"] >= 1
