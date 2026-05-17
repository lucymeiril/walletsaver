"""WalletSavior Phase D2 — 원샷 공개 DB 스냅샷 빌더 (오케스트레이터).

역할:
    4사 마트 fixture(+운영자 캡처) → Livepass 파이프라인(C1+C2) → PriceObservation 누적
    → 분위수 기반 PriceGrade 산출 → 공개용 read-only SQLite 스냅샷 생성.

공개 스냅샷(public_snapshot.sqlite) 스키마:
    canonical_product  — CanonicalProduct (브랜드·명칭·팩 정보)
    price_grade        — 분위수 등급 (P10/P25/P50/P75)
    category_node      — 카테고리 트리 (Phase E 프론트 필터링용)
    mart_sku_alias     — 마트별 SKU ↔ canonical_id (autocomplete용)

    ReviewQueue·escalation 흔적·AI 내부 메타는 제외.

설계 원칙:
    - run_livepass는 의존성 주입(Callable) — CLI는 실제 함수, 테스트는 mock.
    - working_session은 호출자가 제공 (in-memory 또는 영구 DB).
    - 멱등: 같은 입력 두 번 → snapshot 파일은 덮어쓰기, canonical_id 그대로.
    - KAMIS 도입 절대 금지.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Literal, Optional

# ── 경로 보정 ─────────────────────────────────────────────────────────────────
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_SHARED_DIR = _BACKEND_DIR.parent.parent / "shared"
for _p in (str(_SHARED_DIR), str(_BACKEND_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core.price_grading import (  # noqa: E402
    PriceGrade,
    SUFFICIENT_SAMPLE_THRESHOLD,
    classify,
    compute_price_grade,
)

try:
    from sqlalchemy import text  # noqa: E402
    _HAS_SQLALCHEMY = True
except ImportError:
    _HAS_SQLALCHEMY = False


# ══════════════════════════════════════════════════════
# 공개 스냅샷 DDL
# ══════════════════════════════════════════════════════

_SNAPSHOT_DDL = [
    """
    CREATE TABLE IF NOT EXISTS canonical_product (
        id                          TEXT PRIMARY KEY,
        brand                       TEXT,
        name_core                   TEXT NOT NULL,
        pack_quantity               REAL NOT NULL DEFAULT 1.0,
        pack_unit                   TEXT NOT NULL DEFAULT '개',
        category_id                 TEXT,
        representative_image_url    TEXT,
        created_at                  TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS price_grade (
        canonical_id    TEXT PRIMARY KEY,
        window_months   INTEGER NOT NULL,
        sample_size     INTEGER NOT NULL,
        p10             REAL,
        p25             REAL,
        p50             REAL,
        p75             REAL,
        computed_at     TEXT NOT NULL,
        sufficient      INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS category_node (
        id              TEXT PRIMARY KEY,
        parent_id       TEXT,
        name_kr         TEXT NOT NULL,
        name_slug       TEXT NOT NULL,
        level           INTEGER NOT NULL,
        path            TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS mart_sku_alias (
        id                  TEXT PRIMARY KEY,
        canonical_id        TEXT NOT NULL,
        mart                TEXT NOT NULL,
        mart_item_id        TEXT NOT NULL,
        mart_item_name_raw  TEXT NOT NULL,
        source_url          TEXT,
        last_seen_at        TEXT
    )
    """,
]


# ══════════════════════════════════════════════════════
# 결과 DTO
# ══════════════════════════════════════════════════════

@dataclass
class SnapshotMeta:
    """공개 스냅샷 생성 메타데이터."""

    generated_at: str           # ISO 8601
    window_months: int
    input_counts: dict          # {mart_key: count}
    total_input: int
    livepass_pass_rate: float   # gate_passed / queue_initial
    ai_provider_kind: str
    total_canonical: int
    sufficient_grades: int
    insufficient_grades: int
    grade_sample: list          # 최대 5개 샘플 (콘솔 출력용)
    snapshot_path: str
    meta_json_path: str

    def as_dict(self) -> dict:
        return asdict(self)


# ══════════════════════════════════════════════════════
# 내부 헬퍼 — 작업 DB 조회
# ══════════════════════════════════════════════════════

def _exec(session: Any, sql: str, params: dict | None = None) -> list:
    """SQLAlchemy session에서 raw SQL 실행 후 fetchall."""
    if _HAS_SQLALCHEMY:
        result = session.execute(text(sql), params or {})
        return result.fetchall()
    raise RuntimeError("SQLAlchemy not available")


def _query_price_observations(
    session: Any,
    cutoff_dt: datetime,
) -> dict[str, list[float]]:
    """canonical_id별 가격 표본 수집 (unit_price_normalized 우선, 없으면 sale_price).

    Returns:
        {canonical_id: [price, price, ...]}
    """
    rows = _exec(
        session,
        "SELECT canonical_id, unit_price_normalized, sale_price "
        "FROM canonical_price_observations "
        "WHERE observed_at >= :cutoff "
        "ORDER BY canonical_id, observed_at",
        {"cutoff": cutoff_dt.isoformat()},
    )
    result: dict[str, list[float]] = {}
    for row in rows:
        cid = row[0]
        unit_price = row[1]
        sale_price = row[2]
        # unit_price_normalized 우선, 없으면 sale_price 폴백
        price = float(unit_price) if unit_price is not None else float(sale_price)
        if cid not in result:
            result[cid] = []
        result[cid].append(price)
    return result


def _query_canonical_products(session: Any) -> list[dict]:
    """canonical_products 전수 조회."""
    rows = _exec(
        session,
        "SELECT id, brand, name_core, pack_quantity, pack_unit, "
        "category_path_internal_id, representative_image_url, created_at "
        "FROM canonical_products",
    )
    products = []
    for row in rows:
        products.append({
            "id": row[0],
            "brand": row[1],
            "name_core": row[2],
            "pack_quantity": row[3] if row[3] is not None else 1.0,
            "pack_unit": row[4] if row[4] else "개",
            "category_id": row[5],
            "representative_image_url": row[6],
            "created_at": str(row[7]) if row[7] else datetime.now().isoformat(),
        })
    return products


def _query_category_nodes(session: Any) -> list[dict]:
    """canonical_category_nodes 전수 조회."""
    rows = _exec(
        session,
        "SELECT id, parent_id, name_kr, name_slug, level, path "
        "FROM canonical_category_nodes",
    )
    nodes = []
    for row in rows:
        nodes.append({
            "id": row[0],
            "parent_id": row[1],
            "name_kr": row[2],
            "name_slug": row[3],
            "level": row[4],
            "path": row[5],
        })
    return nodes


def _query_mart_sku_aliases(session: Any) -> list[dict]:
    """canonical_mart_sku_aliases 전수 조회."""
    rows = _exec(
        session,
        "SELECT id, canonical_id, mart, mart_item_id, mart_item_name_raw, "
        "source_url, last_seen_at "
        "FROM canonical_mart_sku_aliases",
    )
    aliases = []
    for row in rows:
        aliases.append({
            "id": row[0],
            "canonical_id": row[1],
            "mart": str(row[2]),
            "mart_item_id": row[3],
            "mart_item_name_raw": row[4],
            "source_url": row[5],
            "last_seen_at": str(row[6]) if row[6] else None,
        })
    return aliases


# ══════════════════════════════════════════════════════
# 내부 헬퍼 — 스냅샷 SQLite 빌드
# ══════════════════════════════════════════════════════

def _build_snapshot_sqlite(
    products: list[dict],
    grades: dict[str, PriceGrade],
    categories: list[dict],
    aliases: list[dict],
    snapshot_path: Path,
) -> None:
    """공개용 SQLite 스냅샷 파일 생성 (멱등 — 덮어쓰기).

    기존 파일이 있으면 삭제 후 재생성 (멱등성 보장).
    """
    if snapshot_path.exists():
        snapshot_path.unlink()

    snapshot_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(snapshot_path))
    try:
        cursor = conn.cursor()

        # 테이블 생성
        for ddl in _SNAPSHOT_DDL:
            cursor.execute(ddl)

        # canonical_product
        cursor.executemany(
            "INSERT OR REPLACE INTO canonical_product "
            "(id, brand, name_core, pack_quantity, pack_unit, category_id, "
            "representative_image_url, created_at) "
            "VALUES (:id, :brand, :name_core, :pack_quantity, :pack_unit, "
            ":category_id, :representative_image_url, :created_at)",
            products,
        )

        # price_grade
        grade_rows = []
        for cid, g in grades.items():
            grade_rows.append({
                "canonical_id": cid,
                "window_months": g.window_months,
                "sample_size": g.sample_size,
                "p10": g.p10,
                "p25": g.p25,
                "p50": g.p50,
                "p75": g.p75,
                "computed_at": g.computed_at.isoformat(),
                "sufficient": 1 if g.sufficient else 0,
            })
        cursor.executemany(
            "INSERT OR REPLACE INTO price_grade "
            "(canonical_id, window_months, sample_size, p10, p25, p50, p75, "
            "computed_at, sufficient) "
            "VALUES (:canonical_id, :window_months, :sample_size, :p10, :p25, "
            ":p50, :p75, :computed_at, :sufficient)",
            grade_rows,
        )

        # category_node
        cursor.executemany(
            "INSERT OR REPLACE INTO category_node "
            "(id, parent_id, name_kr, name_slug, level, path) "
            "VALUES (:id, :parent_id, :name_kr, :name_slug, :level, :path)",
            categories,
        )

        # mart_sku_alias
        cursor.executemany(
            "INSERT OR REPLACE INTO mart_sku_alias "
            "(id, canonical_id, mart, mart_item_id, mart_item_name_raw, "
            "source_url, last_seen_at) "
            "VALUES (:id, :canonical_id, :mart, :mart_item_id, :mart_item_name_raw, "
            ":source_url, :last_seen_at)",
            aliases,
        )

        conn.commit()
    finally:
        conn.close()


# ══════════════════════════════════════════════════════
# 공개 API
# ══════════════════════════════════════════════════════

def build_snapshot(
    mart_payloads: dict[str, list[dict]],
    working_session: Any,
    ai_router: Any,
    postcheck_gate: Any,
    snapshot_path: Path,
    meta_json_path: Path,
    run_livepass: Callable,
    window_months: int = 6,
    ai_provider_kind: Literal["mock", "live"] = "mock",
    write_files: bool = True,
) -> SnapshotMeta:
    """원샷 공개 DB 스냅샷 빌더.

    Args:
        mart_payloads:   {"emart": [...], "homeplus": [...], ...}
        working_session: SQLAlchemy Session (canonical 테이블 부트스트랩 완료)
        ai_router:       C1 QueueAiRouter 인스턴스
        postcheck_gate:  C2 PostcheckGate 인스턴스
        snapshot_path:   공개 스냅샷 SQLite 출력 경로
        meta_json_path:  메타 JSON 출력 경로
        run_livepass:    C3 run_livepass Callable (의존성 주입)
        window_months:   가격 집계 기간 (월)
        ai_provider_kind: 보고서 기록용 AI 제공자 종류
        write_files:     True → 파일 쓰기; False → 계산만 수행(dry-run 미리보기)

    Returns:
        SnapshotMeta — 생성 요약 정보.

    멱등성:
        같은 입력 두 번 실행 → snapshot 파일 덮어쓰기, canonical_id 동일.
    """
    now = datetime.now()
    cutoff_dt = now - timedelta(days=window_months * 30)

    # ── 단계 1: Livepass 파이프라인 실행 (C1+C2 → DB 반영) ──────────────────
    report = run_livepass(
        mart_payloads,
        working_session,
        ai_router,
        postcheck_gate,
        dry_run=False,
        ai_provider_kind=ai_provider_kind,
        observed_at=now,
    )

    # ── 단계 2: 데이터 전수 조회 ────────────────────────────────────────────
    products = _query_canonical_products(working_session)
    price_obs_by_cid = _query_price_observations(working_session, cutoff_dt)
    categories = _query_category_nodes(working_session)
    aliases = _query_mart_sku_aliases(working_session)

    # ── 단계 3: canonical_id별 PriceGrade 산출 ───────────────────────────────
    computed_at = datetime.now()
    grades: dict[str, PriceGrade] = {}

    # 모든 canonical product에 대해 grade 산출 (price_obs 없는 것도 포함)
    product_ids = {p["id"] for p in products}
    all_cids = product_ids | set(price_obs_by_cid.keys())

    for cid in all_cids:
        prices = price_obs_by_cid.get(cid, [])
        grades[cid] = compute_price_grade(
            cid,
            prices,
            window_months=window_months,
            computed_at=computed_at,
        )

    # ── 단계 4: 메타 집계 ───────────────────────────────────────────────────
    sufficient_count = sum(1 for g in grades.values() if g.sufficient)
    insufficient_count = len(grades) - sufficient_count

    queue_initial = report.queue_initial
    gate_passed = report.gate_passed
    pass_rate = gate_passed / queue_initial if queue_initial > 0 else 1.0

    input_counts = {
        mart: stats["input"]
        for mart, stats in report.by_mart.items()
    }

    # 분위수 샘플 (최대 5건 — sufficient=True 우선)
    grade_sample: list[dict] = []
    for g in sorted(grades.values(), key=lambda x: (not x.sufficient, x.canonical_id)):
        if len(grade_sample) >= 5:
            break
        grade_sample.append({
            "canonical_id": g.canonical_id[:12] + "…",
            "sample_size": g.sample_size,
            "p10": round(g.p10, 2) if g.p10 is not None else None,
            "p25": round(g.p25, 2) if g.p25 is not None else None,
            "p50": round(g.p50, 2) if g.p50 is not None else None,
            "p75": round(g.p75, 2) if g.p75 is not None else None,
            "sufficient": g.sufficient,
        })

    meta = SnapshotMeta(
        generated_at=now.isoformat(),
        window_months=window_months,
        input_counts=input_counts,
        total_input=report.total_input,
        livepass_pass_rate=round(pass_rate, 4),
        ai_provider_kind=ai_provider_kind,
        total_canonical=len(products),
        sufficient_grades=sufficient_count,
        insufficient_grades=insufficient_count,
        grade_sample=grade_sample,
        snapshot_path=str(snapshot_path),
        meta_json_path=str(meta_json_path),
    )

    # ── 단계 5: 파일 출력 ────────────────────────────────────────────────────
    if write_files:
        _build_snapshot_sqlite(products, grades, categories, aliases, snapshot_path)
        meta_json_path.parent.mkdir(parents=True, exist_ok=True)
        with open(meta_json_path, "w", encoding="utf-8") as f:
            json.dump(meta.as_dict(), f, ensure_ascii=False, indent=2)

    return meta
