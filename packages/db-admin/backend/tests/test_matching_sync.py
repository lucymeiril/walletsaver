"""test_matching_sync.py — matching_sync 서비스 단위 테스트.

테스트 전략:
    1. YAML/JSONL/CSV round-trip: export → import → DB 동일 검증
    2. dry_run rollback 보장: dry_run=True 후 DB 상태 변경 없음
    3. 충돌 시나리오 5종 (충돌 정책 정확성 검증):
       - human 보호 (crawler-auto import 거부)
       - human 보호 (external-ai import 거부)
       - crawler-auto → human 업그레이드 허용
       - crawler-auto → external-ai 업그레이드 허용
       - external-ai 보호 (crawler-auto import 거부)
    4. 잘못된 파일(스키마 위반) 거부 + 에러 메시지 포함 검증
    5. 빈 DB에서 import → to_add만 발생 (to_update/conflicts 없음)

왜 인메모리 SQLite인가:
    CI/CD에서 외부 DB 없이 실행 가능해야 한다.
    SQLite CHECK constraint가 실제로 활성화되므로 confidence/source 검증도 포함.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# backend/ 루트를 sys.path에 추가
BACKEND_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from storage.models import Base, MatchingEntry
from services.matching_sync import (
    ImportDiff,
    export_to_csv,
    export_to_jsonl,
    export_to_yaml,
    import_from_file,
)


# ══════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def engine():
    """인메모리 SQLite — matching_entries를 포함한 전체 스키마 생성."""
    eng = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def session(engine) -> Session:
    """각 테스트마다 새 세션 + 트랜잭션 rollback으로 격리."""
    SessionFactory = sessionmaker(bind=engine)
    with SessionFactory() as s:
        yield s
        s.rollback()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _utc(offset_seconds: int = 0) -> datetime:
    """UTC 기준 현재 시각 ± offset_seconds."""
    return datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)


def _make_entry(session: Session, **kwargs) -> MatchingEntry:
    """기본값을 가진 MatchingEntry 팩토리 — 세션에 add + flush."""
    defaults = dict(
        match_key="CJ|햇반|210.000000|g",
        brand="CJ",
        name_core="햇반",
        pack_qty=210.0,
        pack_unit="g",
        confidence=0.95,
        source="crawler-auto",
        created_at=_utcnow(),
        updated_at=_utcnow(),
        keyword_ids=[],
    )
    defaults.update(kwargs)
    entry = MatchingEntry(**defaults)
    session.add(entry)
    session.flush()
    return entry


# ══════════════════════════════════════════════════════
# 테스트 1: YAML round-trip
# ══════════════════════════════════════════════════════

def test_yaml_roundtrip(session: Session, tmp_path: Path) -> None:
    """YAML export → import → DB 값이 동일해야 한다."""
    _make_entry(
        session,
        match_key="농심|신라면|120.000000|g",
        brand="농심",
        name_core="신라면",
        pack_qty=120.0,
        pack_unit="g",
        confidence=0.9,
        source="human",
        hit_count=5,
        notes="수동 매칭",
        keyword_ids=[1, 2, 3],
    )

    out = tmp_path / "test.yaml"
    summary = export_to_yaml(session, out)
    assert summary.count == 1
    assert summary.format == "yaml"
    assert out.exists()

    # import (dry_run=False: 변경 적용)
    diff = import_from_file(session, out, dry_run=False)
    # 이미 동일한 데이터이므로 변경 없음 (unchanged)
    assert diff.unchanged == 1
    assert len(diff.to_add) == 0
    assert len(diff.to_update) == 0
    assert len(diff.conflicts) == 0
    assert diff.total_incoming == 1


def test_yaml_roundtrip_empty_db(session: Session, tmp_path: Path) -> None:
    """빈 DB에서 export하면 빈 YAML, import 후에도 0건."""
    out = tmp_path / "empty.yaml"
    summary = export_to_yaml(session, out)
    assert summary.count == 0

    diff = import_from_file(session, out, dry_run=True)
    assert diff.total_incoming == 0
    assert diff.unchanged == 0
    assert len(diff.to_add) == 0


# ══════════════════════════════════════════════════════
# 테스트 2: JSONL round-trip
# ══════════════════════════════════════════════════════

def test_jsonl_roundtrip(session: Session, tmp_path: Path) -> None:
    """JSONL export → import → DB 값이 동일해야 한다."""
    _make_entry(
        session,
        match_key="오뚜기|진라면|120.000000|g",
        brand="오뚜기",
        confidence=0.85,
        source="external-ai",
        keyword_ids=None,
    )

    out = tmp_path / "test.jsonl"
    summary = export_to_jsonl(session, out)
    assert summary.format == "jsonl"
    assert summary.count == 1

    # 내용 확인: 각 줄이 유효한 JSON인지
    lines = [l for l in out.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert obj["match_key"] == "오뚜기|진라면|120.000000|g"

    diff = import_from_file(session, out, dry_run=False)
    assert diff.unchanged == 1


# ══════════════════════════════════════════════════════
# 테스트 3: CSV round-trip
# ══════════════════════════════════════════════════════

def test_csv_roundtrip(session: Session, tmp_path: Path) -> None:
    """CSV export → import → DB 값이 동일해야 한다.
    keyword_ids는 JSON 직렬화/역직렬화가 정확해야 한다.
    """
    _make_entry(
        session,
        match_key="삼양|삼양라면|100.000000|g",
        brand="삼양",
        confidence=0.75,
        source="crawler-auto",
        keyword_ids=[10, 20, 30],
    )

    out = tmp_path / "test.csv"
    summary = export_to_csv(session, out)
    assert summary.format == "csv"
    assert summary.count == 1

    diff = import_from_file(session, out, dry_run=False)
    assert diff.unchanged == 1
    assert len(diff.to_add) == 0


# ══════════════════════════════════════════════════════
# 테스트 4: dry_run rollback 보장
# ══════════════════════════════════════════════════════

def test_dry_run_rollback(session: Session, tmp_path: Path) -> None:
    """dry_run=True이면 DB에 실제 변경이 없어야 한다.

    새 레코드를 담은 파일을 dry_run=True로 import하면
    to_add 목록에는 나타나지만 DB에는 추가되지 않아야 한다.
    """
    new_record = {
        "match_key":  "롯데|칸쵸|100.000000|g",
        "brand":      "롯데",
        "name_core":  "칸쵸",
        "pack_qty":   100.0,
        "pack_unit":  "g",
        "confidence": 0.8,
        "source":     "crawler-auto",
        "created_at": _utcnow().isoformat(),
        "updated_at": _utcnow().isoformat(),
        "keyword_ids": [],
        "hit_count":  0,
        "notes":      None,
        "canonical_product_id": None,
        "category_id": None,
        "last_used_at": None,
    }
    out = tmp_path / "new_entry.yaml"
    with out.open("w", encoding="utf-8") as f:
        yaml.safe_dump([new_record], f, allow_unicode=True)

    # dry_run=True → diff에는 추가 예정으로 표시되지만 DB에는 없어야 함
    diff = import_from_file(session, out, dry_run=True)
    assert len(diff.to_add) == 1
    assert diff.to_add[0]["match_key"] == "롯데|칸쵸|100.000000|g"

    # DB 실제 상태 확인 — rollback이므로 추가되지 않아야 함
    count = session.query(MatchingEntry).filter_by(
        match_key="롯데|칸쵸|100.000000|g"
    ).count()
    assert count == 0, "dry_run=True인데 DB에 레코드가 추가되었다!"


def test_dry_run_apply_compare(session: Session, tmp_path: Path) -> None:
    """dry_run=True와 False의 결과가 동일한 ImportDiff를 반환해야 한다."""
    record = {
        "match_key":  "해태|에이스|112.000000|g",
        "brand":      "해태",
        "name_core":  "에이스",
        "pack_qty":   112.0,
        "pack_unit":  "g",
        "confidence": 0.88,
        "source":     "external-ai",
        "created_at": _utcnow().isoformat(),
        "updated_at": _utcnow().isoformat(),
        "keyword_ids": None,
        "hit_count":  0,
        "notes":      None,
        "canonical_product_id": None,
        "category_id": None,
        "last_used_at": None,
    }
    out = tmp_path / "ace.yaml"
    with out.open("w", encoding="utf-8") as f:
        yaml.safe_dump([record], f, allow_unicode=True)

    dry_diff  = import_from_file(session, out, dry_run=True)
    apply_diff = import_from_file(session, out, dry_run=False)

    assert len(dry_diff.to_add)  == len(apply_diff.to_add)
    assert dry_diff.unchanged    == apply_diff.unchanged


# ══════════════════════════════════════════════════════
# 테스트 5: 충돌 시나리오 5종
# ══════════════════════════════════════════════════════
# ─── 충돌 정책 요약 ───────────────────────────────────────────────────────────
# 신뢰 우선순위: human(2) > external-ai(1) > crawler-auto(0)
# 낮은 신뢰도가 높은 신뢰도를 덮으려 하면 → REJECT (conflict)
# 높은 신뢰도가 낮은 신뢰도를 덮으려 하면 → ALLOW (update)
# 동일 source: incoming.updated_at이 더 최신이면 ALLOW, 아니면 UNCHANGED
# ─────────────────────────────────────────────────────────────────────────────

def _make_incoming(match_key: str, source: str, updated_at: datetime | None = None, **extra) -> dict:
    """충돌 테스트용 incoming record 생성 헬퍼."""
    base_time = updated_at or _utcnow()
    d = {
        "match_key":  match_key,
        "brand":      "테스트",
        "name_core":  "테스트상품",
        "pack_qty":   100.0,
        "pack_unit":  "g",
        "confidence": 0.9,
        "source":     source,
        "created_at": base_time.isoformat(),
        "updated_at": base_time.isoformat(),
        "keyword_ids": [],
        "hit_count":  0,
        "notes":      None,
        "canonical_product_id": None,
        "category_id": None,
        "last_used_at": None,
    }
    d.update(extra)
    return d


def test_conflict_human_protected_from_crawler_auto(session: Session, tmp_path: Path) -> None:
    """충돌 1: existing=human, incoming=crawler-auto → REJECT (conflict).

    human이 수동 검증한 매칭은 크롤러 자동화 import로 절대 덮어쓰면 안 된다.
    이것이 "human 보호" 원칙의 핵심 케이스.
    """
    mk = "conflict_test|human_vs_crawler|100.000000|g"
    _make_entry(session, match_key=mk, source="human", confidence=0.99, notes="수동 검증 완료")

    incoming = _make_incoming(mk, source="crawler-auto")
    incoming["notes"] = "크롤러 자동 매칭"  # 값 변경으로 변경 있음 유발

    out = tmp_path / "conflict1.yaml"
    with out.open("w", encoding="utf-8") as f:
        yaml.safe_dump([incoming], f, allow_unicode=True)

    diff = import_from_file(session, out, dry_run=True)

    assert len(diff.conflicts) == 1, f"conflict가 없음! diff={diff}"
    assert len(diff.to_update) == 0
    existing_dict, incoming_dict, reason = diff.conflicts[0]
    assert existing_dict["source"] == "human"
    assert incoming_dict["source"] == "crawler-auto"
    assert "crawler-auto" in reason
    assert "human" in reason


def test_conflict_human_protected_from_external_ai(session: Session, tmp_path: Path) -> None:
    """충돌 2: existing=human, incoming=external-ai → REJECT (conflict).

    human entry는 external-ai import도 덮을 수 없다.
    external-ai가 human보다 신뢰도가 낮기 때문.
    """
    mk = "conflict_test|human_vs_extai|100.000000|g"
    _make_entry(session, match_key=mk, source="human", confidence=0.99)

    incoming = _make_incoming(mk, source="external-ai")
    incoming["notes"] = "AI 분류 결과"

    out = tmp_path / "conflict2.yaml"
    with out.open("w", encoding="utf-8") as f:
        yaml.safe_dump([incoming], f, allow_unicode=True)

    diff = import_from_file(session, out, dry_run=True)

    assert len(diff.conflicts) == 1
    _, _, reason = diff.conflicts[0]
    assert "external-ai" in reason
    assert "human" in reason


def test_conflict_crawler_upgraded_by_human(session: Session, tmp_path: Path) -> None:
    """충돌 3: existing=crawler-auto, incoming=human → ALLOW (update).

    크롤러 자동 분류를 인간이 수동 검증으로 교체하는 것은 품질 향상이므로 허용.
    """
    mk = "upgrade_test|crawler_to_human|100.000000|g"
    _make_entry(session, match_key=mk, source="crawler-auto", confidence=0.7)

    incoming = _make_incoming(mk, source="human", confidence=0.99)
    incoming["notes"] = "수동 재검증"

    out = tmp_path / "upgrade1.yaml"
    with out.open("w", encoding="utf-8") as f:
        yaml.safe_dump([incoming], f, allow_unicode=True)

    diff = import_from_file(session, out, dry_run=True)

    assert len(diff.to_update) == 1, f"update가 없음! diff={diff}"
    assert len(diff.conflicts) == 0
    _old, new = diff.to_update[0]
    assert new["source"] == "human"


def test_conflict_crawler_upgraded_by_external_ai(session: Session, tmp_path: Path) -> None:
    """충돌 4: existing=crawler-auto, incoming=external-ai → ALLOW (update).

    AI 분류 결과가 크롤러 자동 분류를 대체하는 것도 품질 향상이므로 허용.
    """
    mk = "upgrade_test|crawler_to_extai|100.000000|g"
    _make_entry(session, match_key=mk, source="crawler-auto", confidence=0.6)

    incoming = _make_incoming(mk, source="external-ai", confidence=0.92)
    incoming["notes"] = "GPT-4 분류"

    out = tmp_path / "upgrade2.yaml"
    with out.open("w", encoding="utf-8") as f:
        yaml.safe_dump([incoming], f, allow_unicode=True)

    diff = import_from_file(session, out, dry_run=True)

    assert len(diff.to_update) == 1
    assert len(diff.conflicts) == 0


def test_conflict_external_ai_protected_from_crawler(session: Session, tmp_path: Path) -> None:
    """충돌 5: existing=external-ai, incoming=crawler-auto → REJECT (conflict).

    AI가 이미 분류한 항목을 낮은 신뢰도의 크롤러가 되돌리면 안 된다.
    """
    mk = "conflict_test|extai_vs_crawler|100.000000|g"
    _make_entry(session, match_key=mk, source="external-ai", confidence=0.88)

    incoming = _make_incoming(mk, source="crawler-auto", confidence=0.5)
    incoming["notes"] = "크롤러 재감지"

    out = tmp_path / "conflict5.yaml"
    with out.open("w", encoding="utf-8") as f:
        yaml.safe_dump([incoming], f, allow_unicode=True)

    diff = import_from_file(session, out, dry_run=True)

    assert len(diff.conflicts) == 1
    _, _, reason = diff.conflicts[0]
    assert "crawler-auto" in reason
    assert "external-ai" in reason


def test_same_source_newer_updated_at_wins(session: Session, tmp_path: Path) -> None:
    """동일 source: incoming.updated_at이 더 최신이면 update (allowed)."""
    mk = "same_source_test|newer_wins|100.000000|g"
    old_time = _utc(-3600)   # 1시간 전
    new_time = _utc(0)       # 현재

    _make_entry(session, match_key=mk, source="crawler-auto", updated_at=old_time)

    incoming = _make_incoming(mk, source="crawler-auto", updated_at=new_time)
    incoming["notes"] = "최신 업데이트"

    out = tmp_path / "same_source_newer.yaml"
    with out.open("w", encoding="utf-8") as f:
        yaml.safe_dump([incoming], f, allow_unicode=True)

    diff = import_from_file(session, out, dry_run=True)

    assert len(diff.to_update) == 1
    assert len(diff.conflicts) == 0


def test_same_source_older_updated_at_unchanged(session: Session, tmp_path: Path) -> None:
    """동일 source: incoming.updated_at이 더 오래됨 → unchanged (conflict 아님)."""
    mk = "same_source_test|older_ignored|100.000000|g"
    new_time = _utc(0)       # 현재 (더 최신)
    old_time = _utc(-3600)   # 1시간 전 (더 오래됨)

    _make_entry(session, match_key=mk, source="human", updated_at=new_time)

    incoming = _make_incoming(mk, source="human", updated_at=old_time)

    out = tmp_path / "same_source_older.yaml"
    with out.open("w", encoding="utf-8") as f:
        yaml.safe_dump([incoming], f, allow_unicode=True)

    diff = import_from_file(session, out, dry_run=True)

    assert diff.unchanged == 1
    assert len(diff.conflicts) == 0
    assert len(diff.to_update) == 0


# ══════════════════════════════════════════════════════
# 테스트 6: 잘못된 파일 스키마 위반 거부
# ══════════════════════════════════════════════════════

def test_invalid_missing_required_field(session: Session, tmp_path: Path) -> None:
    """필수 필드(match_key) 누락 → ValueError 발생 + DB 변경 없음."""
    bad_record = {
        # match_key 누락
        "source":     "crawler-auto",
        "confidence": 0.8,
        "created_at": _utcnow().isoformat(),
        "updated_at": _utcnow().isoformat(),
    }
    out = tmp_path / "bad_missing.yaml"
    with out.open("w", encoding="utf-8") as f:
        yaml.safe_dump([bad_record], f)

    with pytest.raises(ValueError, match="match_key"):
        import_from_file(session, out, dry_run=True)


def test_invalid_source_value(session: Session, tmp_path: Path) -> None:
    """source가 허용값 외 → ValueError 발생 + 에러 메시지에 source값 포함."""
    bad_record = {
        "match_key":  "bad|source|1.000000|개",
        "source":     "invalid-source",  # 허용 안 됨
        "confidence": 0.8,
        "created_at": _utcnow().isoformat(),
        "updated_at": _utcnow().isoformat(),
    }
    out = tmp_path / "bad_source.yaml"
    with out.open("w", encoding="utf-8") as f:
        yaml.safe_dump([bad_record], f)

    with pytest.raises(ValueError, match="source"):
        import_from_file(session, out, dry_run=True)


def test_invalid_confidence_out_of_range(session: Session, tmp_path: Path) -> None:
    """confidence > 1.0 → ValueError 발생."""
    bad_record = {
        "match_key":  "bad|confidence|1.000000|개",
        "source":     "crawler-auto",
        "confidence": 1.5,  # 범위 초과
        "created_at": _utcnow().isoformat(),
        "updated_at": _utcnow().isoformat(),
    }
    out = tmp_path / "bad_confidence.yaml"
    with out.open("w", encoding="utf-8") as f:
        yaml.safe_dump([bad_record], f)

    with pytest.raises(ValueError, match="confidence"):
        import_from_file(session, out, dry_run=True)


def test_invalid_jsonl_parse_error(session: Session, tmp_path: Path) -> None:
    """JSONL 파싱 오류 → ValueError 발생."""
    out = tmp_path / "bad.jsonl"
    out.write_text("{invalid json}\n", encoding="utf-8")

    with pytest.raises(ValueError):
        import_from_file(session, out, dry_run=True)


def test_unsupported_format_raises(session: Session, tmp_path: Path) -> None:
    """지원하지 않는 확장자 → ValueError 발생."""
    out = tmp_path / "data.xml"
    out.write_text("<root/>", encoding="utf-8")

    with pytest.raises(ValueError, match="지원하지 않는"):
        import_from_file(session, out, dry_run=True)


# ══════════════════════════════════════════════════════
# 테스트 7: 빈 DB에서 import → add만 발생
# ══════════════════════════════════════════════════════

def test_import_into_empty_db_all_adds(session: Session, tmp_path: Path) -> None:
    """빈 DB 상태에서 import하면 to_add만 발생하고 to_update, conflicts가 없어야 한다."""
    # 세션에 아무것도 없는 상태 확인
    existing_count = session.query(MatchingEntry).count()
    assert existing_count == 0, "빈 DB 테스트인데 이미 데이터가 있음"

    records = [
        {
            "match_key":  "신규|상품A|100.000000|g",
            "brand":      "신규브랜드",
            "name_core":  "상품A",
            "pack_qty":   100.0,
            "pack_unit":  "g",
            "confidence": 0.9,
            "source":     "crawler-auto",
            "created_at": _utcnow().isoformat(),
            "updated_at": _utcnow().isoformat(),
            "keyword_ids": [],
            "hit_count":  0,
            "notes":      None,
            "canonical_product_id": None,
            "category_id": None,
            "last_used_at": None,
        },
        {
            "match_key":  "신규|상품B|200.000000|ml",
            "brand":      "신규브랜드",
            "name_core":  "상품B",
            "pack_qty":   200.0,
            "pack_unit":  "ml",
            "confidence": 0.85,
            "source":     "external-ai",
            "created_at": _utcnow().isoformat(),
            "updated_at": _utcnow().isoformat(),
            "keyword_ids": [1, 2],
            "hit_count":  0,
            "notes":      "AI 초기 분류",
            "canonical_product_id": None,
            "category_id": None,
            "last_used_at": None,
        },
    ]

    out = tmp_path / "fresh_import.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    diff = import_from_file(session, out, dry_run=False)

    assert diff.total_incoming == 2
    assert len(diff.to_add) == 2
    assert len(diff.to_update) == 0
    assert len(diff.conflicts) == 0
    assert diff.unchanged == 0

    # DB에 실제로 추가되었는지 확인
    count = session.query(MatchingEntry).filter(
        MatchingEntry.match_key.in_(["신규|상품A|100.000000|g", "신규|상품B|200.000000|ml"])
    ).count()
    assert count == 2, "dry_run=False인데 DB에 레코드가 추가되지 않았다!"


# ══════════════════════════════════════════════════════
# 테스트 8: CSV 특수 케이스 (keyword_ids JSON 직렬화)
# ══════════════════════════════════════════════════════

def test_csv_keyword_ids_serialization(session: Session, tmp_path: Path) -> None:
    """CSV round-trip에서 keyword_ids JSON 직렬화/역직렬화가 정확해야 한다."""
    _make_entry(
        session,
        match_key="csv_test|keyword_json|100.000000|g",
        source="crawler-auto",
        keyword_ids=[100, 200, 300],
    )

    out = tmp_path / "kw_test.csv"
    export_to_csv(session, out)

    # CSV 내용에 JSON 문자열이 있는지 확인
    content = out.read_text(encoding="utf-8")
    assert "[100, 200, 300]" in content or "100" in content

    diff = import_from_file(session, out, dry_run=False)
    assert diff.unchanged == 1


def test_csv_null_keyword_ids(session: Session, tmp_path: Path) -> None:
    """CSV에서 keyword_ids=None이 None으로 복원되어야 한다."""
    _make_entry(
        session,
        match_key="csv_test|null_kw|100.000000|g",
        source="external-ai",
        keyword_ids=None,
    )

    out = tmp_path / "null_kw.csv"
    export_to_csv(session, out)
    diff = import_from_file(session, out, dry_run=False)
    assert diff.unchanged == 1
