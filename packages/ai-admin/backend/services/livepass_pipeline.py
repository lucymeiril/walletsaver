"""WalletSavior Phase C3 — E2E Livepass Pipeline (Orchestrator).

역할:
    Phase B6 시드 → C1 AI 라우터 → C2 사후검증 게이트 → DB 반영까지의
    전체 파이프라인을 end-to-end로 실행하고 측정 결과(LivepassReport)를 반환한다.

단계:
    1. Ingest:      mart_payloads → seed_from_raw_batch → SeedResult (마트별)
    2. Queue:       canonical_product_review_queue 미해결 항목 수집
    3. AI route:    QueueAiRouter.route_batch → list[QueueRouterDecision]
    4. Postcheck:   PostcheckGate.check_batch → list[GateVerdict]
    5. Apply:       PASS→DB 반영, ESCALATE→큐 잔존 + 사유 기록
    6. Metrics:     단계별 경과시간 + 마트별 통과율 + escalation 사유 분포

dry_run=True 동작:
    모든 단계를 실행하되 최종 session.rollback()으로 DB 변경을 취소한다.
    metrics는 트랜잭션 내부 snapshot 기준이다.

dry_run=False 동작:
    session.commit()으로 모든 변경을 확정한다.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Literal, Optional

from sqlalchemy import text

# ── 경로 보정 ─────────────────────────────────────────────────────────────────
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_SHARED_DIR = _BACKEND_DIR.parent.parent / "shared"
_DB_ADMIN_BACKEND = _BACKEND_DIR.parent.parent / "db-admin" / "backend"

for _p in (str(_SHARED_DIR), str(_BACKEND_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# db-admin backend은 ai-admin의 storage/ 패키지와 이름 충돌이 있으므로
# sys.path에 넣지 않고 importlib로 canonical_seed 모듈을 직접 로드한다.
def _load_canonical_seed():
    """db-admin/backend/storage/canonical_seed 모듈을 importlib로 직접 로드.

    ai-admin/backend/storage/ 패키지 충돌을 피하기 위해
    db-admin storage 패키지를 sys.modules에 별도 이름으로 등록한다.
    """
    db_storage_dir = _DB_ADMIN_BACKEND / "storage"
    db_str = str(_DB_ADMIN_BACKEND)

    # db-admin backend를 sys.path에 임시 추가
    _added = db_str not in sys.path
    if _added:
        sys.path.insert(0, db_str)

    try:
        # storage 패키지를 db_admin_storage 이름으로 등록
        storage_init = db_storage_dir / "__init__.py"
        pkg_spec = importlib.util.spec_from_file_location(
            "db_admin_storage",
            storage_init,
            submodule_search_locations=[str(db_storage_dir)],
        )
        pkg_mod = importlib.util.module_from_spec(pkg_spec)  # type: ignore[arg-type]
        sys.modules.setdefault("db_admin_storage", pkg_mod)
        pkg_spec.loader.exec_module(pkg_mod)  # type: ignore[union-attr]

        # canonical_models 서브모듈 먼저 로드 (canonical_seed의 상대 import 해결)
        for sub in ("canonical_models", "canonical_seed"):
            sub_spec = importlib.util.spec_from_file_location(
                f"db_admin_storage.{sub}",
                db_storage_dir / f"{sub}.py",
                submodule_search_locations=[str(db_storage_dir)],
            )
            sub_mod = importlib.util.module_from_spec(sub_spec)  # type: ignore[arg-type]
            sub_mod.__package__ = "db_admin_storage"
            sys.modules.setdefault(f"db_admin_storage.{sub}", sub_mod)
            setattr(pkg_mod, sub, sub_mod)
            sub_spec.loader.exec_module(sub_mod)  # type: ignore[union-attr]

        return sys.modules["db_admin_storage.canonical_seed"]
    finally:
        if _added and db_str in sys.path:
            sys.path.remove(db_str)


_canonical_seed_mod = _load_canonical_seed()
seed_categories_from_yaml = _canonical_seed_mod.seed_categories_from_yaml
seed_from_raw_batch = _canonical_seed_mod.seed_from_raw_batch
SeedResult = _canonical_seed_mod.SeedResult

from core.canonical_models import (  # noqa: E402
    MartKind,
    PriceObservation as PriceObservationDTO,
    ProductReviewQueue as QueueEntryDTO,
    ReviewReason,
    UnitPriceBasis,
)
from services.postcheck_gate import GateVerdict, PostcheckGate  # noqa: E402
from services.queue_ai_router import QueueAiRouter, QueueRouterDecision  # noqa: E402


# ══════════════════════════════════════════════════════
# DTO
# ══════════════════════════════════════════════════════

@dataclass
class LivepassReport:
    """C3 파이프라인 실행 결과 보고서.

    by_mart 구조:
        {
            "emart": {
                "input": 5,             # 입력 raw 건수
                "canonical_created": 5, # 새로 생성된 canonical product 수
                "queue_initial": 5,     # 큐에 진입한(미해결) 항목 수
                "ai_resolved": 5,       # C1 RESOLVED 건수
                "ai_escalated": 0,      # C1 ESCALATED 건수
                "gate_passed": 5,       # C2 PASS 건수 (= 자동 분류 성공)
                "gate_escalated": 0,    # C2 ESCALATE 건수
                "final_db_rows": 5,     # resolved_at 채워진 큐 행 수
            }
        }
    """
    total_input: int
    by_mart: dict[str, dict]
    canonical_created: int
    queue_initial: int
    ai_resolved: int
    ai_escalated: int
    gate_passed: int
    gate_escalated: int
    final_db_resolved: int
    final_db_pending: int
    escalation_reasons_distribution: dict[str, int]
    elapsed_ms: dict[str, int]
    mode: Literal["dry_run", "commit"]
    ai_provider_kind: Literal["mock", "live"]

    def as_dict(self) -> dict:
        return asdict(self)


# ══════════════════════════════════════════════════════
# 내부 헬퍼
# ══════════════════════════════════════════════════════

def _collect_unresolved_entries(session: Any) -> list[QueueEntryDTO]:
    """canonical_product_review_queue에서 미해결 항목을 모두 DTO로 반환."""
    rows = session.execute(
        text(
            "SELECT id, raw_payload, source_mart, reason, suggested_canonical_id "
            "FROM canonical_product_review_queue "
            "WHERE resolved_at IS NULL"
        )
    ).fetchall()

    entries: list[QueueEntryDTO] = []
    for row in rows:
        queue_id, raw_payload_raw, source_mart_str, reason_str, suggested_id = row

        if isinstance(raw_payload_raw, str):
            try:
                raw_payload: dict = json.loads(raw_payload_raw)
            except (json.JSONDecodeError, TypeError):
                raw_payload = {"_parse_error": True}
        elif isinstance(raw_payload_raw, dict):
            raw_payload = raw_payload_raw
        else:
            raw_payload = {}

        try:
            source_mart = MartKind(source_mart_str)
            reason = ReviewReason(reason_str)
        except ValueError:
            continue  # 알 수 없는 enum 값은 skip

        entries.append(QueueEntryDTO(
            id=queue_id,
            raw_payload=raw_payload,
            source_mart=source_mart,
            reason=reason,
            suggested_canonical_id=suggested_id,
        ))

    return entries


def _fetch_price_observation(
    session: Any,
    entry: QueueEntryDTO,
) -> Optional[PriceObservationDTO]:
    """큐 항목의 canonical_id로 가장 최신 PriceObservation DTO를 조회한다.
    없으면 None 반환 (Gate4 PASS).
    """
    if not entry.suggested_canonical_id:
        return None

    row = session.execute(
        text(
            "SELECT id, canonical_id, mart, regular_price, sale_price, on_sale, "
            "discount_rate, unit_price_normalized, unit_price_basis, raw_payload_hash "
            "FROM canonical_price_observations "
            "WHERE canonical_id = :cid "
            "ORDER BY observed_at DESC LIMIT 1"
        ),
        {"cid": entry.suggested_canonical_id},
    ).fetchone()

    if row is None:
        return None

    try:
        return PriceObservationDTO(
            id=str(row[0]),
            canonical_id=str(row[1]),
            mart=MartKind(str(row[2])),
            regular_price=row[3],
            sale_price=int(row[4]),
            on_sale=bool(row[5]),
            discount_rate=row[6],
            unit_price_normalized=row[7],
            unit_price_basis=(
                UnitPriceBasis(str(row[8]))
                if row[8] and row[8] in {e.value for e in UnitPriceBasis}
                else UnitPriceBasis.UNKNOWN
            ),
            raw_payload_hash=str(row[9]) if row[9] else "a" * 40,
        )
    except Exception:
        return None


def _count_queue_rows(session: Any, resolved: bool) -> int:
    """resolved_at 기준으로 큐 행 수 반환."""
    if resolved:
        q = "SELECT COUNT(*) FROM canonical_product_review_queue WHERE resolved_at IS NOT NULL"
    else:
        q = "SELECT COUNT(*) FROM canonical_product_review_queue WHERE resolved_at IS NULL"
    return session.execute(text(q)).scalar() or 0


def _count_queue_rows_by_mart(session: Any, mart_value: str, resolved: bool) -> int:
    """특정 마트의 큐 행 수 반환."""
    if resolved:
        q = (
            "SELECT COUNT(*) FROM canonical_product_review_queue "
            "WHERE source_mart = :m AND resolved_at IS NOT NULL"
        )
    else:
        q = (
            "SELECT COUNT(*) FROM canonical_product_review_queue "
            "WHERE source_mart = :m AND resolved_at IS NULL"
        )
    return session.execute(text(q), {"m": mart_value}).scalar() or 0


def _build_empty_mart_stats() -> dict:
    return {
        "input": 0,
        "canonical_created": 0,
        "queue_initial": 0,
        "ai_resolved": 0,
        "ai_escalated": 0,
        "gate_passed": 0,
        "gate_escalated": 0,
        "final_db_rows": 0,
    }


# ══════════════════════════════════════════════════════
# 공개 API
# ══════════════════════════════════════════════════════

def run_livepass(
    mart_payloads: dict[str, list[dict]],
    session: Any,
    ai_router: QueueAiRouter,
    postcheck_gate: PostcheckGate,
    dry_run: bool = True,
    ai_provider_kind: Literal["mock", "live"] = "mock",
    observed_at: Optional[datetime] = None,
) -> LivepassReport:
    """
    E2E Livepass 파이프라인 실행.

    Args:
        mart_payloads: {"emart": [...raw items...], "homeplus": [...], ...}
        session: SQLAlchemy Session (canonical 테이블이 있어야 함)
        ai_router: C1 QueueAiRouter 인스턴스
        postcheck_gate: C2 PostcheckGate 인스턴스
        dry_run: True → 모든 단계 실행 후 rollback. False → commit.
        ai_provider_kind: 보고서에 기록할 AI 제공자 종류.
        observed_at: 가격 관측 시각 (None이면 현재 시각).

    Returns:
        LivepassReport — 단계별 카운트 + 마트별 통과율 + escalation 분포.
    """
    if observed_at is None:
        observed_at = datetime.now()

    elapsed: dict[str, int] = {}

    # ── by_mart 초기화 ─────────────────────────────────────────────────────
    by_mart: dict[str, dict] = {
        mart_key: _build_empty_mart_stats()
        for mart_key in mart_payloads
    }

    total_input = sum(len(items) for items in mart_payloads.values())
    for mart_key, items in mart_payloads.items():
        by_mart[mart_key]["input"] = len(items)

    # ══════════════════════════════════════════════════════
    # 단계 1: Ingest (마트별 시드)
    # ══════════════════════════════════════════════════════
    t0 = time.perf_counter()

    # 카테고리 트리 시드 (멱등)
    try:
        seed_categories_from_yaml(session)
    except Exception:
        pass  # 카테고리 테이블 없음 → 계속 진행 (테스트 환경)

    total_canonical_created = 0

    for mart_key, items in mart_payloads.items():
        if not items:
            continue
        try:
            seed_result: SeedResult = seed_from_raw_batch(
                {mart_key: items},
                session,
                dry_run=True,   # flush-only; 최종 commit/rollback은 파이프라인 끝에
                observed_at=observed_at,
            )
            by_mart[mart_key]["canonical_created"] = seed_result.canonical_inserted
            total_canonical_created += seed_result.canonical_inserted
        except Exception as exc:
            # 개별 마트 시드 실패는 계속 진행
            by_mart[mart_key]["canonical_created"] = 0

    elapsed["ingest"] = int((time.perf_counter() - t0) * 1000)

    # ══════════════════════════════════════════════════════
    # 단계 2: Queue collect
    # ══════════════════════════════════════════════════════
    t1 = time.perf_counter()

    # flush로 시드된 데이터를 세션 내에서 queryable하게
    try:
        session.flush()
    except Exception:
        pass

    entries = _collect_unresolved_entries(session)

    # 마트별 queue_initial 집계
    for entry in entries:
        mk = entry.source_mart.value.lower()
        if mk in by_mart:
            by_mart[mk]["queue_initial"] += 1

    queue_initial = len(entries)
    elapsed["queue"] = int((time.perf_counter() - t1) * 1000)

    # ══════════════════════════════════════════════════════
    # 단계 3: AI route
    # ══════════════════════════════════════════════════════
    t2 = time.perf_counter()

    entry_by_id: dict[str, QueueEntryDTO] = {e.id: e for e in entries}

    decisions: list[QueueRouterDecision] = ai_router.route_batch(entries)

    ai_resolved = 0
    ai_escalated = 0
    for dec in decisions:
        if dec.decision == "RESOLVED":
            ai_resolved += 1
            entry = entry_by_id.get(dec.queue_id)
            if entry:
                mk = entry.source_mart.value.lower()
                if mk in by_mart:
                    by_mart[mk]["ai_resolved"] += 1
        else:
            ai_escalated += 1
            entry = entry_by_id.get(dec.queue_id)
            if entry:
                mk = entry.source_mart.value.lower()
                if mk in by_mart:
                    by_mart[mk]["ai_escalated"] += 1

    elapsed["ai"] = int((time.perf_counter() - t2) * 1000)

    # ══════════════════════════════════════════════════════
    # 단계 4: Postcheck
    # ══════════════════════════════════════════════════════
    t3 = time.perf_counter()

    # 각 큐 항목에 대한 PriceObservation 조회 (Gate4 가격 이상 탐지용)
    observations: list[Optional[PriceObservationDTO]] = [
        _fetch_price_observation(session, e) for e in entries
    ]

    verdicts: list[GateVerdict] = postcheck_gate.check_batch(
        decisions, entries, observations
    )

    gate_passed = 0
    gate_escalated = 0
    escalation_reasons: dict[str, int] = defaultdict(int)

    for verdict, entry in zip(verdicts, entries):
        mk = entry.source_mart.value.lower()
        if verdict.verdict == "PASS":
            gate_passed += 1
            if mk in by_mart:
                by_mart[mk]["gate_passed"] += 1
        else:
            gate_escalated += 1
            if mk in by_mart:
                by_mart[mk]["gate_escalated"] += 1
            for reason in verdict.failed_gates:
                escalation_reasons[reason] += 1

    elapsed["postcheck"] = int((time.perf_counter() - t3) * 1000)

    # ══════════════════════════════════════════════════════
    # 단계 5: Apply to DB
    # ══════════════════════════════════════════════════════
    t4 = time.perf_counter()

    postcheck_gate.apply_to_db(verdicts, session)

    elapsed["apply"] = int((time.perf_counter() - t4) * 1000)

    # ══════════════════════════════════════════════════════
    # 단계 6: Metrics — 트랜잭션 내부 snapshot 쿼리
    # ══════════════════════════════════════════════════════
    try:
        session.flush()
    except Exception:
        pass

    final_db_resolved = _count_queue_rows(session, resolved=True)
    final_db_pending = _count_queue_rows(session, resolved=False)

    for mart_key in by_mart:
        mart_value = mart_key.upper()
        by_mart[mart_key]["final_db_rows"] = _count_queue_rows_by_mart(
            session, mart_value, resolved=True
        )

    # ── Commit 또는 Rollback ──────────────────────────────────────────────
    if dry_run:
        try:
            session.rollback()
        except Exception:
            pass
    else:
        try:
            session.commit()
        except Exception:
            session.rollback()

    return LivepassReport(
        total_input=total_input,
        by_mart=by_mart,
        canonical_created=total_canonical_created,
        queue_initial=queue_initial,
        ai_resolved=ai_resolved,
        ai_escalated=ai_escalated,
        gate_passed=gate_passed,
        gate_escalated=gate_escalated,
        final_db_resolved=final_db_resolved,
        final_db_pending=final_db_pending,
        escalation_reasons_distribution=dict(escalation_reasons),
        elapsed_ms=elapsed,
        mode="dry_run" if dry_run else "commit",
        ai_provider_kind=ai_provider_kind,
    )


def emit_run_to_control_db(
    report: "LivepassReport",
    control_session: Any,
    *,
    product_match_total: int = 0,
    learned_knowledge_total: int = 0,
) -> str:
    """Save a LivepassReport as a LabelingRunLog in the ai_control DB.

    Call this after run_livepass to persist run stats for the monitor dashboard.
    Returns the generated run_id.
    """
    import uuid
    from storage.repositories import LabelingRunLogRepository

    run_id = f"run-{uuid.uuid4().hex[:16]}"
    repo = LabelingRunLogRepository(control_session)
    repo.save(
        run_id=run_id,
        run_at=datetime.now(),
        mode=report.mode,
        ai_provider_kind=report.ai_provider_kind,
        total_input=report.total_input,
        queue_initial=report.queue_initial,
        ai_called=report.queue_initial,
        ai_resolved=report.ai_resolved,
        ai_escalated=report.ai_escalated,
        gate_passed=report.gate_passed,
        gate_escalated=report.gate_escalated,
        canonical_created=report.canonical_created,
        product_match_total_snapshot=product_match_total,
        learned_knowledge_total_snapshot=learned_knowledge_total,
        by_mart=report.by_mart,
    )
    try:
        control_session.commit()
    except Exception:
        control_session.rollback()
        raise
    return run_id
