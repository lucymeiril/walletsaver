"""test_export_unmatched.py — POST /api/export/unmatched 통합 테스트.

시나리오:
    1. 기본 export — raw 10건, matching 3건 hit → miss_count=7, JSONL/CSV/manifest 검증
    2. captured_since 필터 작동 확인
    3. limit 필터 작동 확인
    4. 재호출 시 manifest previous_batch_id 채워짐 (이력 연결)
    5. download 엔드포인트 — jsonl / csv / zip 정상 응답
    6. /recent 정렬(최신 우선) + 개수 제한

설계 원칙: "miss만 export"
    hit된 레코드는 어떤 파일에도 포함되지 않아야 한다.
    이 테스트는 그 원칙의 회귀 차단 역할을 한다.
"""
from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# ── 경로 보정 ──────────────────────────────────────────────────────────────────
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_SHARED_DIR = _BACKEND_DIR.parent.parent / "shared"
for _p in (str(_SHARED_DIR), str(_BACKEND_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from storage.models import Base as AiAdminBase, RawCrawlBatch, RawCrawlRecord
from services.matching_db import get_matching_session


# ── matching_entries 테이블 DDL ────────────────────────────────────────────────
# db-admin ORM 모델과 이름 충돌을 피하기 위해 raw DDL로 테이블을 생성한다.
_MATCHING_DDL = """
CREATE TABLE IF NOT EXISTS matching_entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    match_key   TEXT    UNIQUE NOT NULL,
    brand       VARCHAR(200),
    name_core   VARCHAR(500),
    pack_qty    FLOAT,
    pack_unit   VARCHAR(50),
    canonical_product_id VARCHAR(40),
    category_id VARCHAR(100),
    keyword_ids JSON,
    confidence  FLOAT   NOT NULL DEFAULT 1.0,
    source      VARCHAR(20) NOT NULL DEFAULT 'human',
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_used_at DATETIME,
    hit_count   INTEGER NOT NULL DEFAULT 0,
    notes       TEXT
)
"""


# ── 픽스처 ────────────────────────────────────────────────────────────────────

@pytest.fixture()
def ai_db(tmp_path):
    """ai-admin file-based SQLite — RawCrawlBatch / RawCrawlRecord 테이블.

    TestClient는 sync 엔드포인트를 thread pool에서 실행하므로,
    :memory: 대신 file-based DB를 사용해 스레드 간 공유를 보장한다.
    """
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'ai_admin.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    AiAdminBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = factory()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def matching_db(tmp_path):
    """matching file-based SQLite — matching_entries 테이블 (raw DDL)."""
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'matching.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    with engine.begin() as conn:
        conn.execute(text(_MATCHING_DDL))
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = factory()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def export_dir(tmp_path, monkeypatch):
    """export 아티팩트를 tmp_path로 리다이렉트 — 실제 artifacts 디렉토리 오염 방지."""
    d = tmp_path / "exports"
    d.mkdir()
    import api.routes.export as export_mod
    monkeypatch.setattr(export_mod, "_EXPORT_BASE_DIR", d)
    return d


@pytest.fixture()
def client(ai_db, matching_db, export_dir):
    """FastAPI TestClient — 두 DB 세션을 모두 override."""
    from api.app import create_app
    from api.deps import get_db_session

    app = create_app()

    def _ai_session() -> Iterator[Session]:
        yield ai_db

    def _matching_session() -> Iterator[Session]:
        yield matching_db

    app.dependency_overrides[get_db_session] = _ai_session
    app.dependency_overrides[get_matching_session] = _matching_session

    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


# ── 시드 헬퍼 ────────────────────────────────────────────────────────────────

_BASE_TIME = datetime(2026, 5, 10, 0, 0, 0)  # timezone-naive (SQLite 저장 형식)


def _seed_batch(session: Session, batch_id: str = "batch-001") -> RawCrawlBatch:
    """테스트용 RawCrawlBatch 레코드 생성."""
    b = RawCrawlBatch(
        batch_id=batch_id,
        source_name="emart",
        crawler_name="test_crawler",
        item_count=0,
        schema_type="mart_discount",
        status="raw_ingested",
        created_at=_BASE_TIME,
    )
    session.add(b)
    session.flush()
    return b


def _seed_records(
    session: Session,
    batch_id: str,
    count: int,
    source_name: str = "emart",
    base_time: datetime = _BASE_TIME,
    time_step_minutes: int = 1,
) -> list[RawCrawlRecord]:
    """raw_payload에 brand/name 포함된 테스트용 RawCrawlRecord 10건 생성."""
    records = []
    for i in range(count):
        rec = RawCrawlRecord(
            raw_record_id=f"{batch_id}-rec-{i:03d}",
            batch_id=batch_id,
            source_name=source_name,
            raw_title=f"테스트상품{i}",
            raw_price=1000 + i * 100,
            raw_payload={
                "brand": f"브랜드{i % 5}",   # 0~4 → 5가지 브랜드
                "name": f"상품명{i}",
                "pack_qty": float(i + 1),
                "pack_unit": "g",
            },
            crawled_at=base_time + timedelta(minutes=i * time_step_minutes),
        )
        session.add(rec)
        records.append(rec)
    session.flush()
    return records


def _seed_matching_entries(
    matching_session: Session,
    match_keys: list[str],
) -> None:
    """지정된 match_key 목록을 matching_entries에 삽입."""
    for key in match_keys:
        matching_session.execute(
            text(
                "INSERT INTO matching_entries (match_key, source) VALUES (:k, 'human')"
            ),
            {"k": key},
        )
    matching_session.flush()


def _compute_match_key(brand: str, name: str, qty: float, unit: str) -> str:
    """테스트용 match_key 계산 — shared build_match_key 직접 호출."""
    from core.match_key import build_match_key
    return build_match_key(brand, name, qty, unit)


# ── 테스트 1: 기본 export ────────────────────────────────────────────────────

class TestBasicExport:
    """raw 10건, matching 3건 hit → miss_count=7 검증."""

    def _setup(self, ai_db, matching_db):
        """시드 데이터 적재 후 hit가 될 3개 match_key 반환."""
        _seed_batch(ai_db)
        records = _seed_records(ai_db, "batch-001", count=10)
        ai_db.commit()

        # records[0], [1], [2] → hit 대상 match_key 계산
        hit_keys = [
            _compute_match_key(
                f"브랜드{i % 5}", f"상품명{i}", float(i + 1), "g"
            )
            for i in range(3)
        ]
        _seed_matching_entries(matching_db, hit_keys)
        matching_db.commit()
        return hit_keys

    def test_miss_count_is_seven(self, client, ai_db, matching_db):
        self._setup(ai_db, matching_db)
        r = client.post("/api/export/unmatched", json={})
        assert r.status_code == 200
        body = r.json()
        # hit 3건 → miss 7건
        assert body["hit_count"] == 3
        assert body["miss_count"] == 7

    def test_jsonl_file_created(self, client, ai_db, matching_db, export_dir):
        self._setup(ai_db, matching_db)
        body = client.post("/api/export/unmatched", json={}).json()
        batch_id = body["batch_id"]
        jsonl_path = export_dir / batch_id / "unmatched.jsonl"
        assert jsonl_path.exists(), "unmatched.jsonl 파일이 생성되어야 한다"
        lines = [json.loads(l) for l in jsonl_path.read_text(encoding="utf-8").strip().splitlines()]
        assert len(lines) == 7

    def test_csv_file_created(self, client, ai_db, matching_db, export_dir):
        self._setup(ai_db, matching_db)
        body = client.post("/api/export/unmatched", json={}).json()
        batch_id = body["batch_id"]
        csv_path = export_dir / batch_id / "unmatched.csv"
        assert csv_path.exists(), "unmatched.csv 파일이 생성되어야 한다"

    def test_manifest_created(self, client, ai_db, matching_db, export_dir):
        self._setup(ai_db, matching_db)
        body = client.post("/api/export/unmatched", json={}).json()
        batch_id = body["batch_id"]
        manifest_path = export_dir / batch_id / "manifest.json"
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["batch_id"] == batch_id
        assert manifest["row_count"] == 7
        assert manifest["schema_version"] == 1

    def test_manifest_sha256_matches_jsonl(self, client, ai_db, matching_db, export_dir):
        """manifest의 sha256['unmatched.jsonl']이 실제 파일 hash와 일치해야 한다."""
        self._setup(ai_db, matching_db)
        body = client.post("/api/export/unmatched", json={}).json()
        batch_id = body["batch_id"]
        manifest = json.loads(
            (export_dir / batch_id / "manifest.json").read_text(encoding="utf-8")
        )
        jsonl_path = export_dir / batch_id / "unmatched.jsonl"
        h = hashlib.sha256(jsonl_path.read_bytes()).hexdigest()
        assert manifest["sha256"]["unmatched.jsonl"] == h

    def test_manifest_sha256_matches_csv(self, client, ai_db, matching_db, export_dir):
        """manifest의 sha256['unmatched.csv']이 실제 파일 hash와 일치해야 한다."""
        self._setup(ai_db, matching_db)
        body = client.post("/api/export/unmatched", json={}).json()
        batch_id = body["batch_id"]
        manifest = json.loads(
            (export_dir / batch_id / "manifest.json").read_text(encoding="utf-8")
        )
        csv_path = export_dir / batch_id / "unmatched.csv"
        h = hashlib.sha256(csv_path.read_bytes()).hexdigest()
        assert manifest["sha256"]["unmatched.csv"] == h

    def test_hit_records_not_in_jsonl(self, client, ai_db, matching_db, export_dir):
        """hit된 레코드(rec-000~002)는 JSONL에 포함되지 않아야 한다 ("miss만 export" 원칙)."""
        self._setup(ai_db, matching_db)
        body = client.post("/api/export/unmatched", json={}).json()
        batch_id = body["batch_id"]
        jsonl_path = export_dir / batch_id / "unmatched.jsonl"
        ids = [json.loads(l)["raw_record_id"] for l in jsonl_path.read_text().strip().splitlines()]
        for i in range(3):
            assert f"batch-001-rec-{i:03d}" not in ids, f"hit 레코드 rec-{i:03d}가 export에 포함됨"


# ── 테스트 2: captured_since 필터 ────────────────────────────────────────────

class TestCapturedSinceFilter:
    def test_since_filters_old_records(self, client, ai_db, matching_db):
        """captured_since 이전 레코드는 export 대상에서 제외된다."""
        _seed_batch(ai_db)
        # 첫 5건: _BASE_TIME + 0~4분, 나머지 5건: _BASE_TIME + 5~9분
        _seed_records(ai_db, "batch-001", count=10)
        ai_db.commit()

        # _BASE_TIME + 5분 이후만 포함
        since = (_BASE_TIME + timedelta(minutes=5)).isoformat()
        r = client.post("/api/export/unmatched", json={"captured_since": since})
        assert r.status_code == 200
        body = r.json()
        # hit 없음 → miss = 필터된 레코드 수 (5건)
        assert body["miss_count"] == 5

    def test_since_iso_with_z_suffix(self, client, ai_db, matching_db):
        """'Z' 접미사가 붙은 ISO 형식도 파싱돼야 한다."""
        _seed_batch(ai_db)
        _seed_records(ai_db, "batch-001", count=3)
        ai_db.commit()
        since = (_BASE_TIME + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        r = client.post("/api/export/unmatched", json={"captured_since": since})
        assert r.status_code == 200
        # 10분 이후 레코드가 없으므로 miss=0
        assert r.json()["miss_count"] == 0


# ── 테스트 3: limit 필터 ─────────────────────────────────────────────────────

class TestLimitFilter:
    def test_limit_caps_records(self, client, ai_db, matching_db):
        """limit 지정 시 처리 레코드 수가 limit를 초과하지 않는다."""
        _seed_batch(ai_db)
        _seed_records(ai_db, "batch-001", count=10)
        ai_db.commit()

        r = client.post("/api/export/unmatched", json={"limit": 4})
        assert r.status_code == 200
        body = r.json()
        # hit 없음 → miss = limit 그대로
        assert body["miss_count"] == 4

    def test_limit_one(self, client, ai_db, matching_db):
        _seed_batch(ai_db)
        _seed_records(ai_db, "batch-001", count=5)
        ai_db.commit()

        r = client.post("/api/export/unmatched", json={"limit": 1})
        assert r.json()["miss_count"] == 1


# ── 테스트 4: previous_batch_id 이력 연결 ────────────────────────────────────

class TestPreviousBatchId:
    def test_first_call_has_no_previous(self, client, ai_db, matching_db, export_dir):
        """첫 번째 호출에서는 previous_batch_id가 None이어야 한다."""
        _seed_batch(ai_db)
        _seed_records(ai_db, "batch-001", count=3)
        ai_db.commit()

        body = client.post("/api/export/unmatched", json={}).json()
        manifest = json.loads(
            (export_dir / body["batch_id"] / "manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["previous_batch_id"] is None

    def test_second_call_links_previous(self, client, ai_db, matching_db, export_dir):
        """두 번째 호출의 manifest.previous_batch_id가 첫 번째 batch_id를 가리켜야 한다."""
        _seed_batch(ai_db)
        _seed_records(ai_db, "batch-001", count=3)
        ai_db.commit()

        first = client.post("/api/export/unmatched", json={}).json()
        first_batch_id = first["batch_id"]

        second = client.post("/api/export/unmatched", json={}).json()
        second_batch_id = second["batch_id"]

        manifest = json.loads(
            (export_dir / second_batch_id / "manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["previous_batch_id"] == first_batch_id

    def test_third_call_links_second(self, client, ai_db, matching_db, export_dir):
        """세 번째 호출의 previous_batch_id는 두 번째 batch를 가리켜야 한다."""
        _seed_batch(ai_db)
        _seed_records(ai_db, "batch-001", count=2)
        ai_db.commit()

        client.post("/api/export/unmatched", json={})
        second = client.post("/api/export/unmatched", json={}).json()
        third = client.post("/api/export/unmatched", json={}).json()

        manifest = json.loads(
            (export_dir / third["batch_id"] / "manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["previous_batch_id"] == second["batch_id"]


# ── 테스트 5: download 엔드포인트 ────────────────────────────────────────────

class TestDownload:
    def _create_export(self, client, ai_db, matching_db) -> str:
        _seed_batch(ai_db)
        _seed_records(ai_db, "batch-001", count=5)
        ai_db.commit()
        return client.post("/api/export/unmatched", json={}).json()["batch_id"]

    def test_download_jsonl(self, client, ai_db, matching_db, export_dir):
        batch_id = self._create_export(client, ai_db, matching_db)
        r = client.get(f"/api/export/unmatched/download?batch_id={batch_id}&format=jsonl")
        assert r.status_code == 200
        assert "application/x-ndjson" in r.headers.get("content-type", "")

    def test_download_csv(self, client, ai_db, matching_db, export_dir):
        batch_id = self._create_export(client, ai_db, matching_db)
        r = client.get(f"/api/export/unmatched/download?batch_id={batch_id}&format=csv")
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "")

    def test_download_zip(self, client, ai_db, matching_db, export_dir):
        batch_id = self._create_export(client, ai_db, matching_db)
        r = client.get(f"/api/export/unmatched/download?batch_id={batch_id}&format=zip")
        assert r.status_code == 200
        assert "application/zip" in r.headers.get("content-type", "")
        # ZIP 파일임을 검증
        zf = zipfile.ZipFile(BytesIO(r.content))
        names = zf.namelist()
        assert "unmatched.jsonl" in names
        assert "unmatched.csv" in names
        assert "manifest.json" in names

    def test_download_unknown_format(self, client, ai_db, matching_db, export_dir):
        batch_id = self._create_export(client, ai_db, matching_db)
        r = client.get(f"/api/export/unmatched/download?batch_id={batch_id}&format=xml")
        assert r.status_code == 422

    def test_download_nonexistent_batch(self, client, export_dir):
        r = client.get("/api/export/unmatched/download?batch_id=no-such-batch&format=jsonl")
        assert r.status_code == 404


# ── 테스트 6: /recent 엔드포인트 ─────────────────────────────────────────────

class TestRecent:
    def test_empty_when_no_exports(self, client, export_dir):
        r = client.get("/api/export/unmatched/recent")
        assert r.status_code == 200
        body = r.json()
        assert body["exports"] == []
        assert body["total"] == 0

    def test_returns_all_exports(self, client, ai_db, matching_db, export_dir):
        _seed_batch(ai_db)
        _seed_records(ai_db, "batch-001", count=3)
        ai_db.commit()

        client.post("/api/export/unmatched", json={})
        client.post("/api/export/unmatched", json={})
        client.post("/api/export/unmatched", json={})

        r = client.get("/api/export/unmatched/recent")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 3
        assert len(body["exports"]) == 3

    def test_sorted_newest_first(self, client, ai_db, matching_db, export_dir):
        """exports 목록은 generated_at 기준 최신 우선 정렬이어야 한다."""
        _seed_batch(ai_db)
        _seed_records(ai_db, "batch-001", count=2)
        ai_db.commit()

        first = client.post("/api/export/unmatched", json={}).json()
        second = client.post("/api/export/unmatched", json={}).json()

        body = client.get("/api/export/unmatched/recent").json()
        ids = [e["batch_id"] for e in body["exports"]]
        # 두 번째(더 최신)가 첫 번째(인덱스 0)에 와야 한다
        assert ids[0] == second["batch_id"]
        assert ids[1] == first["batch_id"]

    def test_n_limit(self, client, ai_db, matching_db, export_dir):
        """n 파라미터로 반환 개수를 제한할 수 있어야 한다."""
        _seed_batch(ai_db)
        _seed_records(ai_db, "batch-001", count=2)
        ai_db.commit()

        for _ in range(5):
            client.post("/api/export/unmatched", json={})

        body = client.get("/api/export/unmatched/recent?n=3").json()
        assert len(body["exports"]) == 3
        assert body["total"] == 5
