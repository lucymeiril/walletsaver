"""matching_sync.py — MatchingEntry DB ↔ 외부 파일(YAML/JSONL/CSV) 양방향 동기화 서비스.

충돌 정책 (의도 명시 — 다음 AI가 임의로 변경하지 않도록):
    ★★★ 신뢰 우선순위: human(2) > external-ai(1) > crawler-auto(0) ★★★

    [핵심 원칙]
    낮은 신뢰도 source는 높은 신뢰도 source가 기록한 entry를 절대 덮어쓸 수 없다.
    "human도 import로 overwrite 허용"으로 단순화하면 안 된다 — 그것은 의도적 보호를 파괴한다.

    [케이스별 규칙]
    1. existing='human',       incoming='crawler-auto'  → REJECT (conflict)
       existing='human',       incoming='external-ai'   → REJECT (conflict)
       ─ human이 수동 검증한 매칭은 자동/AI 파이프라인이 되돌릴 수 없다.

    2. existing='external-ai', incoming='crawler-auto'  → REJECT (conflict)
       ─ 더 낮은 신뢰도(크롤러 자동)가 AI 분류 결과를 덮을 수 없다.

    3. existing='crawler-auto', incoming='human'        → ALLOW (update)
       existing='crawler-auto', incoming='external-ai'  → ALLOW (update)
       existing='external-ai',  incoming='human'        → ALLOW (update)
       ─ 더 높은 신뢰도가 낮은 신뢰도를 대체하는 것은 품질 향상이므로 허용.

    4. 동일 source끼리 (예: human vs human):
       → incoming.updated_at > existing.updated_at 이면 ALLOW (update)
       → 아니면 UNCHANGED (conflict 아님, 그냥 skip)

    [잘못된 단순화 예시]
    ✗ "source가 다르면 무조건 최신 updated_at이 이긴다" — human 보호가 깨짐
    ✗ "human도 외부 파일 import로 덮을 수 있다" — 수동 검증 결과가 사라짐
    ✓ 신뢰 우선순위를 먼저 체크하고, 동일 신뢰도일 때만 updated_at을 비교한다
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml
from sqlalchemy.orm import Session

from storage.models import MatchingEntry


# ── 신뢰 우선순위 맵 ────────────────────────────────────────────────────────
# 이 숫자를 변경하면 충돌 정책 전체가 바뀌므로 주의.
# human=2 가 가장 높은 신뢰도 → 어떤 import도 덮을 수 없음.
_SOURCE_TRUST: dict[str, int] = {
    "crawler-auto": 0,
    "external-ai":  1,
    "human":        2,
}

# 내보내기/불러오기 대상 필드 (id 제외 — 자동 생성 PK이므로 파일에 포함하지 않음)
_EXPORT_FIELDS: list[str] = [
    "match_key", "brand", "name_core", "pack_qty", "pack_unit",
    "canonical_product_id", "public_product_id", "public_variant_id",
    "category_id", "keyword_ids",
    "confidence", "source",
    "created_at", "updated_at", "last_used_at",
    "hit_count", "notes",
]

# 검증 대상 분류
_REQUIRED_FIELDS:  frozenset[str] = frozenset({"match_key", "confidence", "source"})
_JSON_FIELDS:      frozenset[str] = frozenset({"keyword_ids"})
_FLOAT_FIELDS:     frozenset[str] = frozenset({"pack_qty", "confidence"})
_INT_FIELDS:       frozenset[str] = frozenset({"hit_count"})
_DT_FIELDS:        frozenset[str] = frozenset({"created_at", "updated_at", "last_used_at"})


# ── 공개 데이터 클래스 ────────────────────────────────────────────────────────

@dataclass
class ExportSummary:
    """export 함수의 반환값."""
    path:   Path
    count:  int
    format: str


@dataclass
class ImportDiff:
    """import_from_file의 반환값 — dry-run 포함.

    to_add:    신규 추가될 dict 목록
    to_update: (기존 dict, 새 dict) 튜플 목록
    conflicts: (기존 dict, 들어온 dict, 거부 이유) 튜플 목록
                ── 충돌 정책에 의해 적용되지 않은 레코드들
    unchanged: 변경 없이 pass된 레코드 수
    total_incoming: 파일에서 읽은 전체 레코드 수
    """
    to_add:         list[dict]                     = field(default_factory=list)
    to_update:      list[tuple[dict, dict]]        = field(default_factory=list)  # (old, new)
    conflicts:      list[tuple[dict, dict, str]]   = field(default_factory=list)  # (existing, incoming, reason)
    unchanged:      int                            = 0
    total_incoming: int                            = 0


# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────────

def _entry_to_dict(entry: MatchingEntry) -> dict:
    """ORM 객체 → dict. datetime은 ISO 8601 문자열로 직렬화."""
    d: dict = {}
    for f in _EXPORT_FIELDS:
        val = getattr(entry, f, None)
        if isinstance(val, datetime):
            # timezone-aware ISO 8601 (예: 2024-01-15T10:00:00+00:00)
            if val.tzinfo is None:
                val = val.replace(tzinfo=timezone.utc)
            val = val.isoformat()
        d[f] = val
    return d


def _parse_dt(val: Any) -> Optional[datetime]:
    """datetime, str(ISO 8601), None을 timezone-aware datetime으로 변환."""
    if val is None:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val
    if isinstance(val, str) and val:
        try:
            dt = datetime.fromisoformat(val)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return None
    return None


def _validate_record(d: dict, index: int) -> None:
    """스키마 검증: 필수 필드·source·confidence 범위 확인.

    잘못된 레코드가 DB에 들어오기 전에 차단한다.
    ValueError를 raise하면 import_from_file이 전체를 중단한다.
    """
    missing = _REQUIRED_FIELDS - set(d.keys())
    if missing:
        raise ValueError(f"레코드[{index}]: 필수 필드 누락 — {sorted(missing)}")

    src = d.get("source")
    if src not in _SOURCE_TRUST:
        raise ValueError(
            f"레코드[{index}]: source 허용값은 {sorted(_SOURCE_TRUST)}, 받은 값: {src!r}"
        )

    conf = d.get("confidence")
    try:
        conf_f = float(conf)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ValueError(
            f"레코드[{index}]: confidence는 float이어야 합니다, 받은 값: {conf!r}"
        )
    if not (0.0 <= conf_f <= 1.0):
        raise ValueError(
            f"레코드[{index}]: confidence는 [0.0, 1.0] 범위여야 합니다, 받은 값: {conf_f}"
        )

    mk = d.get("match_key")
    if not isinstance(mk, str) or not mk.strip():
        raise ValueError(
            f"레코드[{index}]: match_key는 비어 있지 않은 문자열이어야 합니다, 받은 값: {mk!r}"
        )


def _has_changes(existing: dict, incoming: dict) -> bool:
    """두 dict 사이에 실질적인 필드 변경이 있는지 확인.

    match_key는 키이므로 비교 제외.
    datetime 필드는 timezone-aware로 정규화 후 비교.
    생략 필드는 기존 값을 유지하며, 명시적인 None만 초기화로 비교한다.
    """
    for f in _EXPORT_FIELDS:
        if f == "match_key" or f not in incoming:
            continue
        ex_val = existing.get(f)
        in_val = incoming.get(f)

        if f in _DT_FIELDS:
            ex_val = _parse_dt(ex_val)
            in_val = _parse_dt(in_val)
        elif f in _FLOAT_FIELDS:
            ex_val = float(ex_val) if ex_val is not None else None
            in_val = float(in_val) if in_val is not None else None
        elif f in _INT_FIELDS:
            ex_val = int(ex_val) if ex_val is not None else None
            in_val = int(in_val) if in_val is not None else None

        if ex_val != in_val:
            return True
    return False


def _classify_update(existing: dict, incoming: dict) -> tuple[str, str]:
    """충돌 정책 적용 → (action, reason) 반환.

    action:
        'update'    — 덮어쓰기 허용
        'unchanged' — 정책상 불필요 (동일 source + incoming이 더 오래됨)
        'conflict'  — 거부 (낮은 신뢰도가 높은 신뢰도를 덮으려 함)

    ★★★ 이 함수가 충돌 정책의 핵심 구현체입니다 ★★★
    모듈 docstring의 충돌 정책을 변경하지 않고는 이 함수를 단순화해서는 안 됩니다.
    """
    ex_src = existing["source"]
    in_src = incoming["source"]
    ex_trust = _SOURCE_TRUST[ex_src]
    in_trust = _SOURCE_TRUST[in_src]

    if ex_src == in_src:
        # 동일 source: updated_at 비교
        # ─ 같은 신뢰 수준끼리는 최신 데이터가 이김
        ex_dt = _parse_dt(existing.get("updated_at"))
        in_dt = _parse_dt(incoming.get("updated_at"))
        if ex_dt is not None and in_dt is not None and in_dt > ex_dt:
            return "update", f"same_source({in_src})_incoming_newer"
        else:
            return "unchanged", f"same_source({in_src})_incoming_not_newer"

    elif in_trust > ex_trust:
        # 더 높은 신뢰도가 낮은 신뢰도를 대체 → ALLOW
        # ─ 예: human이 crawler-auto를 교체, external-ai가 crawler-auto를 교체
        return "update", f"{in_src}(trust={in_trust})_upgrades_{ex_src}(trust={ex_trust})"

    else:
        # 낮은 신뢰도가 높은 신뢰도를 덮으려 함 → REJECT (conflict)
        # ─ 이 분기가 "human 보호" 핵심 안전장치:
        #   human entry는 crawler-auto/external-ai import로 절대 변경되지 않음
        #   external-ai entry는 crawler-auto import로 변경되지 않음
        return "conflict", f"reject_{in_src}(trust={in_trust})_cannot_override_{ex_src}(trust={ex_trust})"


def _dict_to_entry(d: dict) -> MatchingEntry:
    """dict → MatchingEntry ORM 객체 생성."""
    kwargs: dict = {}
    for f in _EXPORT_FIELDS:
        if f not in d:
            continue
        val = d[f]
        if f in _DT_FIELDS:
            val = _parse_dt(val)
        elif f in _FLOAT_FIELDS and val is not None:
            val = float(val)
        elif f in _INT_FIELDS and val is not None:
            val = int(val)
        kwargs[f] = val
    return MatchingEntry(**kwargs)


def _update_entry(entry: MatchingEntry, d: dict) -> None:
    """기존 MatchingEntry를 dict의 값으로 업데이트 (match_key 제외)."""
    for f in _EXPORT_FIELDS:
        if f == "match_key":
            continue
        if f not in d:
            continue
        val = d[f]
        if f in _DT_FIELDS:
            val = _parse_dt(val)
        elif f in _FLOAT_FIELDS and val is not None:
            val = float(val)
        elif f in _INT_FIELDS and val is not None:
            val = int(val)
        setattr(entry, f, val)


def _compute_diff(session: Session, records: list[dict]) -> ImportDiff:
    """DB 현재 상태와 incoming records를 비교하여 ImportDiff를 계산한다.

    변경 없음 → unchanged 카운트 증가
    신규 → to_add
    변경 있고 정책상 허용 → to_update
    변경 있고 정책상 거부 → conflicts
    """
    diff = ImportDiff(total_incoming=len(records))

    # match_key → dict 매핑으로 O(1) 조회
    existing_map: dict[str, dict] = {
        e.match_key: _entry_to_dict(e)
        for e in session.query(MatchingEntry).all()
    }

    for record in records:
        mk = record["match_key"]
        if mk not in existing_map:
            diff.to_add.append(record)
        else:
            existing = existing_map[mk]
            if not _has_changes(existing, record):
                diff.unchanged += 1
            else:
                action, reason = _classify_update(existing, record)
                if action == "update":
                    diff.to_update.append((existing, record))
                elif action == "unchanged":
                    diff.unchanged += 1
                else:  # conflict
                    diff.conflicts.append((existing, record, reason))

    return diff


def _apply_diff(session: Session, diff: ImportDiff) -> None:
    """ImportDiff를 세션에 반영 (flush 포함). 커밋은 호출자가 담당."""
    for record in diff.to_add:
        session.add(_dict_to_entry(record))

    for _old, new in diff.to_update:
        entry = session.query(MatchingEntry).filter_by(
            match_key=new["match_key"]
        ).one()
        _update_entry(entry, new)

    session.flush()


# ── 파일 로드 ─────────────────────────────────────────────────────────────────

def _load_yaml(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if data is None:
        return []
    if not isinstance(data, list):
        raise ValueError(f"YAML 파일 최상위 구조는 list여야 합니다: {path}")
    return data  # type: ignore[return-value]


def _load_jsonl(path: Path) -> list[dict]:
    records: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"JSONL 파싱 오류 (라인 {lineno}): {exc}") from exc
            if not isinstance(obj, dict):
                raise ValueError(f"JSONL 라인 {lineno}은 object(dict)여야 합니다")
            records.append(obj)
    return records


def _load_csv(path: Path) -> list[dict]:
    """CSV 로드: keyword_ids(JSON), 숫자, 빈 문자열(→ None) 처리 포함."""
    records: list[dict] = []
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            d: dict = {}
            for f_name in _EXPORT_FIELDS:
                # An older CSV may have no normalized-target columns. Missing
                # columns mean "leave unchanged", not an explicit NULL update.
                # A present but empty cell still intentionally clears a field.
                if f_name not in row:
                    continue
                raw = row[f_name]
                if raw == "" or raw is None:
                    d[f_name] = None
                    continue
                if f_name in _JSON_FIELDS:
                    try:
                        d[f_name] = json.loads(raw)
                    except json.JSONDecodeError:
                        d[f_name] = None
                elif f_name in _FLOAT_FIELDS:
                    try:
                        d[f_name] = float(raw)
                    except (ValueError, TypeError):
                        d[f_name] = None
                elif f_name in _INT_FIELDS:
                    try:
                        d[f_name] = int(raw)
                    except (ValueError, TypeError):
                        d[f_name] = None
                else:
                    d[f_name] = raw
            records.append(d)
    return records


def _load_file(path: Path) -> list[dict]:
    """확장자로 포맷 자동 감지하여 로드."""
    suffix = path.suffix.lower()
    if suffix in (".yaml", ".yml"):
        return _load_yaml(path)
    elif suffix == ".jsonl":
        return _load_jsonl(path)
    elif suffix == ".csv":
        return _load_csv(path)
    else:
        raise ValueError(
            f"지원하지 않는 파일 형식: {suffix!r}. 허용: .yaml/.yml/.jsonl/.csv"
        )


# ── 공개 API ──────────────────────────────────────────────────────────────────

def export_to_yaml(session: Session, path: Path) -> ExportSummary:
    """DB의 모든 MatchingEntry를 YAML 파일로 내보낸다."""
    entries = session.query(MatchingEntry).order_by(MatchingEntry.match_key).all()
    records = [_entry_to_dict(e) for e in entries]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(
            records,
            stream=f,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )
    return ExportSummary(path=path, count=len(records), format="yaml")


def export_to_jsonl(session: Session, path: Path) -> ExportSummary:
    """DB의 모든 MatchingEntry를 JSONL 파일로 내보낸다. 각 줄이 하나의 JSON 객체."""
    entries = session.query(MatchingEntry).order_by(MatchingEntry.match_key).all()
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as f:
        for entry in entries:
            d = _entry_to_dict(entry)
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
            count += 1
    return ExportSummary(path=path, count=count, format="jsonl")


def export_to_csv(session: Session, path: Path) -> ExportSummary:
    """DB의 모든 MatchingEntry를 CSV 파일로 내보낸다.

    keyword_ids는 JSON 직렬화 문자열로 저장.
    """
    entries = session.query(MatchingEntry).order_by(MatchingEntry.match_key).all()
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_EXPORT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for entry in entries:
            d = _entry_to_dict(entry)
            row: dict = {}
            for fn in _EXPORT_FIELDS:
                val = d.get(fn)
                if fn in _JSON_FIELDS:
                    row[fn] = json.dumps(val, ensure_ascii=False) if val is not None else ""
                elif val is None:
                    row[fn] = ""
                else:
                    row[fn] = val
            writer.writerow(row)
            count += 1
    return ExportSummary(path=path, count=count, format="csv")


def import_from_file(
    session: Session,
    path: Path,
    dry_run: bool = True,
) -> ImportDiff:
    """파일(YAML/JSONL/CSV)에서 MatchingEntry를 DB로 가져온다.

    Args:
        session:  SQLAlchemy 세션. dry_run=False 후 session.commit()은 호출자 책임.
        path:     가져올 파일 경로. 확장자로 포맷 자동 감지.
        dry_run:  True이면 SAVEPOINT로 적용 후 ROLLBACK (변경 없음, diff만 반환).
                  False이면 outer transaction에 직접 적용 (호출자가 session.commit() 책임).

    Returns:
        ImportDiff — 추가/업데이트/충돌/변경없음 분류 결과.

    Raises:
        ValueError: 파일 형식 오류 또는 레코드 스키마 위반.
    """
    records = _load_file(path)

    # 전체 스키마 검증 — 하나라도 실패하면 DB에 아무것도 쓰지 않음
    for i, record in enumerate(records):
        _validate_record(record, i)

    diff = _compute_diff(session, records)

    if diff.to_add or diff.to_update:
        if dry_run:
            # ── dry-run: SAVEPOINT → 적용 → ROLLBACK TO SAVEPOINT ──
            # DB 제약(CHECK, UNIQUE)까지 실제로 검증한 뒤 되돌린다.
            # sp.commit() (RELEASE SAVEPOINT)은 사용하지 않는다:
            # SQLAlchemy 2.x에서 savepoint를 commit(release)하면 outer session의
            # 트랜잭션 상태가 모호해져 fixture rollback이 실패할 수 있다.
            sp = session.begin_nested()
            try:
                _apply_diff(session, diff)
            except Exception:
                sp.rollback()
                raise
            else:
                sp.rollback()  # ROLLBACK TO SAVEPOINT → DB 상태 그대로
        else:
            # ── apply: outer transaction에 직접 적용 ──
            # 호출자가 session.commit()으로 영속화하거나 session.rollback()으로 취소.
            try:
                _apply_diff(session, diff)
            except Exception:
                session.rollback()
                raise

    return diff


def import_from_rows(
    session: Session,
    rows: list[dict],
    dry_run: bool = True,
    source_override: Optional[str] = None,
) -> ImportDiff:
    """이미 파싱·검증된 row dict 목록에서 MatchingEntry 를 import한다.

    HTTP 업로드 endpoint(matching_import.py)에서 호출한다.
    파일 파싱과 matching_sync 자체 스키마 검증을 건너뛰고,
    import_validator.py가 선처리한 valid_rows 를 직접 받는다.

    Args:
        session:         SQLAlchemy 세션.
        rows:            import_validator 가 승인한 row dict 목록.
                         각 row 에 match_key 또는 compound 필드가 있어야 한다.
        dry_run:         True 이면 SAVEPOINT rollback (DB 변경 없음, diff 만 반환).
                         False 이면 outer transaction 에 반영 (호출자가 commit 책임).
        source_override: 설정 시 모든 row 의 source 를 이 값으로 덮어씀.

    Returns:
        ImportDiff — 추가/업데이트/충돌/변경없음 분류 결과.
    """
    from services.import_validator import _build_match_key as _build_key  # noqa: PLC0415

    # source_override 적용 + match_key 보정
    normalized: list[dict] = []
    for row in rows:
        r = dict(row)
        if source_override:
            r["source"] = source_override
        # match_key 미지정이면 compound 필드로 구성
        if not r.get("match_key"):
            mk = _build_key(r)
            if mk:
                r["match_key"] = mk
        if r.get("match_key"):
            normalized.append(r)

    diff = _compute_diff(session, normalized)

    if diff.to_add or diff.to_update:
        sp = session.begin_nested()
        try:
            _apply_diff(session, diff)
            if dry_run:
                sp.rollback()
            else:
                sp.commit()
        except Exception:
            sp.rollback()
            raise

    return diff
