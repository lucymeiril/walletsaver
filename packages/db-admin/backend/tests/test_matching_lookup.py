"""test_matching_lookup.py — MatchingLookup 서비스 + build_match_key 통합 테스트.

테스트 범위:
    1. build_match_key 정규화 일관성 (match_key.py)
    2. lookup_one hit / miss
    3. lookup_bulk 다중 조회 정확성
    4. LRU 캐시 동작 — 같은 key 재호출 시 DB 쿼리 1회만
    5. record_hit / record_hits_batch → last_used_at, hit_count 갱신
    6. classify_raw_record happy path + 각 miss reason

왜 인메모리 SQLite인가:
    CI/CD에서 외부 DB 없이 실행 가능해야 한다.
    Base.metadata.create_all로 matching_entries 포함 전체 스키마를 생성한다.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, call

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

# ── 경로 구성 (conftest.py 없이 단독 실행 시에도 동작하도록) ──
BACKEND_ROOT = Path(__file__).parent.parent
SHARED_ROOT = BACKEND_ROOT.parent.parent / "shared"
for p in (str(BACKEND_ROOT), str(SHARED_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from storage.models import Base, MatchingEntry
import services.matching_lookup as svc
from core.match_key import build_match_key


# ══════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def engine():
    """인메모리 SQLite — 모듈 단위 공유."""
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        echo=False,
    )
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def session(engine) -> Session:
    """테스트마다 새 세션, 끝나면 rollback으로 격리."""
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as s:
        yield s
        s.rollback()


@pytest.fixture(autouse=True)
def clear_cache():
    """각 테스트 전·후 LRU 캐시 초기화."""
    svc.invalidate()
    yield
    svc.invalidate()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _make_entry(session: Session, match_key: str, **kwargs) -> MatchingEntry:
    """MatchingEntry를 생성하고 flush."""
    defaults = dict(
        match_key=match_key,
        brand=kwargs.pop("brand", "테스트브랜드"),
        name_core=kwargs.pop("name_core", "테스트상품"),
        pack_qty=kwargs.pop("pack_qty", 100.0),
        pack_unit=kwargs.pop("pack_unit", "g"),
        confidence=kwargs.pop("confidence", 0.9),
        source=kwargs.pop("source", "crawler-auto"),
        created_at=_utcnow(),
        updated_at=_utcnow(),
        hit_count=kwargs.pop("hit_count", 0),
    )
    defaults.update(kwargs)
    entry = MatchingEntry(**defaults)
    session.add(entry)
    session.flush()
    return entry


# ══════════════════════════════════════════════════════
# 1. build_match_key 정규화 일관성
# ══════════════════════════════════════════════════════

class TestBuildMatchKey:
    def test_same_input_same_output(self):
        """동일 입력은 반드시 동일 출력을 반환한다."""
        k1 = build_match_key("CJ", "햇반", 210.0, "g")
        k2 = build_match_key("CJ", "햇반", 210.0, "g")
        assert k1 == k2

    def test_case_insensitive_brand(self):
        """brand 대소문자 무관 — 소문자 정규화."""
        assert build_match_key("CJ", "햇반", 100.0, "g") == build_match_key("cj", "햇반", 100.0, "g")

    def test_brand_whitespace_trim(self):
        """brand 양쪽 공백 trim."""
        assert build_match_key("  CJ  ", "햇반", 100.0, "g") == build_match_key("CJ", "햇반", 100.0, "g")

    def test_name_core_special_chars_removed(self):
        """name_core 특수기호 제거 — 영문/한글/숫자/공백만 유지."""
        k1 = build_match_key("농심", "신라면!!!", 120.0, "g")
        k2 = build_match_key("농심", "신라면", 120.0, "g")
        assert k1 == k2

    def test_name_core_whitespace_normalized(self):
        """name_core 연속 공백 단일화."""
        k1 = build_match_key("농심", "신   라   면", 120.0, "g")
        k2 = build_match_key("농심", "신 라 면", 120.0, "g")
        assert k1 == k2

    def test_pack_qty_rounded_to_1_decimal(self):
        """pack_qty 소수점 1자리 round — 미세 차이 무시."""
        k1 = build_match_key("A", "상품", 100.04, "g")
        k2 = build_match_key("A", "상품", 100.0, "g")
        assert k1 == k2

    def test_pack_unit_lowercase(self):
        """pack_unit 소문자 정규화."""
        assert build_match_key("A", "상품", 100.0, "G") == build_match_key("A", "상품", 100.0, "g")

    def test_none_brand(self):
        """brand=None → '' 처리."""
        k = build_match_key(None, "상품", 100.0, "g")
        assert k.startswith("|")

    def test_none_name_core(self):
        """name_core=None → '' 처리."""
        k = build_match_key("A", None, 100.0, "g")
        assert "||" in k

    def test_none_pack_qty(self):
        """pack_qty=None → '' 처리."""
        k = build_match_key("A", "상품", None, "g")
        assert "||" in k

    def test_none_pack_unit(self):
        """pack_unit=None → '' 처리."""
        k = build_match_key("A", "상품", 100.0, None)
        assert k.endswith("|")

    def test_all_none(self):
        """모든 파라미터 None → '|||'."""
        k = build_match_key(None, None, None, None)
        assert k == "|||"

    def test_separator_format(self):
        """구분자 '|' 4-파트 구조 확인."""
        k = build_match_key("CJ", "햇반", 210.0, "g")
        parts = k.split("|")
        assert len(parts) == 4


# ══════════════════════════════════════════════════════
# 2. lookup_one hit / miss
# ══════════════════════════════════════════════════════

class TestLookupOne:
    def test_hit(self, session: Session):
        """존재하는 match_key 조회 → MatchingEntry 반환."""
        key = build_match_key("CJ", "햇반", 210.0, "g")
        entry = _make_entry(session, key, brand="CJ", name_core="햇반")

        result = svc.lookup_one(session, key)

        assert result is not None
        assert result.id == entry.id
        assert result.match_key == key

    def test_miss(self, session: Session):
        """존재하지 않는 match_key 조회 → None 반환."""
        result = svc.lookup_one(session, "존재하지않는|키|0.0|개")
        assert result is None

    def test_hit_returns_correct_entry(self, session: Session):
        """복수 항목 중 정확한 entry 반환."""
        key_a = build_match_key("A브랜드", "상품A", 100.0, "g")
        key_b = build_match_key("B브랜드", "상품B", 200.0, "ml")
        entry_a = _make_entry(session, key_a, brand="A브랜드", name_core="상품A")
        _make_entry(session, key_b, brand="B브랜드", name_core="상품B")

        result = svc.lookup_one(session, key_a)
        assert result is not None
        assert result.id == entry_a.id


# ══════════════════════════════════════════════════════
# 3. lookup_bulk 다중 조회 정확성 (5개 중 3 hit)
# ══════════════════════════════════════════════════════

class TestLookupBulk:
    def test_five_keys_three_hits(self, session: Session):
        """5개 키 중 3개만 DB에 존재 → 결과 dict에 3개만 포함."""
        keys_hit = [
            build_match_key("브랜드1", "상품1", 100.0, "g"),
            build_match_key("브랜드2", "상품2", 200.0, "ml"),
            build_match_key("브랜드3", "상품3", 300.0, "개"),
        ]
        keys_miss = [
            "없는키A|상품|0.0|개",
            "없는키B|상품|0.0|개",
        ]
        for i, k in enumerate(keys_hit, 1):
            _make_entry(session, k, brand=f"브랜드{i}", name_core=f"상품{i}")

        result = svc.lookup_bulk(session, keys_hit + keys_miss)

        assert len(result) == 3
        for k in keys_hit:
            assert k in result
        for k in keys_miss:
            assert k not in result

    def test_empty_keys(self, session: Session):
        """빈 리스트 입력 → 빈 dict 반환."""
        result = svc.lookup_bulk(session, [])
        assert result == {}

    def test_all_miss(self, session: Session):
        """모두 miss → 빈 dict 반환."""
        result = svc.lookup_bulk(session, ["없는|키|1.0|개", "없는|키2|1.0|개"])
        assert result == {}

    def test_duplicate_keys_in_input(self, session: Session):
        """중복 키 입력 시 결과에 한 번만 포함."""
        key = build_match_key("중복", "상품", 100.0, "g")
        _make_entry(session, key, brand="중복", name_core="상품")

        result = svc.lookup_bulk(session, [key, key, key])
        assert len(result) == 1
        assert key in result


# ══════════════════════════════════════════════════════
# 4. LRU 캐시 동작 — 같은 key 재호출 시 DB 쿼리 1회만
# ══════════════════════════════════════════════════════

class TestLRUCache:
    def test_cache_hit_on_second_call(self, session: Session):
        """두 번째 lookup_one 호출 시 DB 쿼리 없이 캐시에서 반환."""
        key = build_match_key("캐시", "테스트", 100.0, "g")
        _make_entry(session, key, brand="캐시", name_core="테스트")

        original_query = session.query

        call_count = [0]

        def counting_query(model):
            call_count[0] += 1
            return original_query(model)

        # 첫 번째 호출 → DB 조회
        result1 = svc.lookup_one(session, key)
        assert result1 is not None

        # 캐시에 올라간 상태에서 세션 query를 패치해 두 번째 호출이 DB를 건드리지 않는지 확인
        with patch.object(session, "query", side_effect=counting_query):
            result2 = svc.lookup_one(session, key)

        assert result2 is not None
        assert result2.id == result1.id
        assert call_count[0] == 0, "캐시 히트 시 DB 쿼리가 발생하면 안 됩니다"

    def test_miss_is_cached(self, session: Session):
        """miss(None) 도 캐시에 저장 — 반복 조회 시 DB 쿼리 없음."""
        key = "없는|캐시|테스트|개"

        # 첫 번째 호출 → DB miss, None 캐시
        r1 = svc.lookup_one(session, key)
        assert r1 is None

        call_count = [0]
        with patch.object(session, "query", side_effect=lambda m: (_ for _ in ()).throw(AssertionError("DB 쿼리 발생"))):
            # 두 번째 호출 → 캐시에서 None 반환, DB 쿼리 없음
            r2 = svc.lookup_one(session, key)
        assert r2 is None

    def test_invalidate_clears_cache(self, session: Session):
        """invalidate() 후 캐시 비워짐 → 다음 조회는 DB 접근."""
        key = build_match_key("무효화", "테스트", 50.0, "ml")
        _make_entry(session, key, brand="무효화", name_core="테스트")

        svc.lookup_one(session, key)  # 캐시 채움
        svc.invalidate()              # 무효화

        # 무효화 후 내부 캐시가 비어야 한다
        assert len(svc._cache) == 0

    def test_bulk_uses_cache_for_already_cached_keys(self, session: Session):
        """lookup_one으로 캐시된 키를 lookup_bulk에서 재조회 시 DB 쿼리 최소화."""
        key = build_match_key("벌크캐시", "상품", 100.0, "g")
        _make_entry(session, key, brand="벌크캐시", name_core="상품")

        # 먼저 lookup_one으로 캐시에 올린다
        svc.lookup_one(session, key)

        call_count = [0]
        with patch.object(session, "query", side_effect=lambda m: (_ for _ in ()).throw(AssertionError("DB 쿼리 발생"))):
            result = svc.lookup_bulk(session, [key])

        assert key in result


# ══════════════════════════════════════════════════════
# 5. record_hit / record_hits_batch → last_used_at, hit_count 갱신
# ══════════════════════════════════════════════════════

class TestRecordHit:
    def test_record_hit_increments_hit_count(self, session: Session):
        """record_hit 호출 후 hit_count가 1 증가해야 한다."""
        key = build_match_key("히트", "카운트", 100.0, "g")
        entry = _make_entry(session, key, brand="히트", name_core="카운트", hit_count=5)
        initial_count = entry.hit_count

        svc.record_hit(session, entry.id)
        session.flush()
        session.expire(entry)  # ORM 캐시 만료 후 DB에서 재조회

        refreshed = session.get(MatchingEntry, entry.id)
        assert refreshed.hit_count == initial_count + 1

    def test_record_hit_updates_last_used_at(self, session: Session):
        """record_hit 호출 후 last_used_at이 갱신되어야 한다."""
        key = build_match_key("히트", "날짜", 100.0, "g")
        entry = _make_entry(session, key, brand="히트", name_core="날짜")
        assert entry.last_used_at is None  # 초기 미설정

        svc.record_hit(session, entry.id)
        session.flush()
        session.expire(entry)

        refreshed = session.get(MatchingEntry, entry.id)
        assert refreshed.last_used_at is not None

    def test_record_hits_batch_multiple(self, session: Session):
        """record_hits_batch로 복수 entry hit_count 일괄 갱신."""
        key_a = build_match_key("배치A", "상품", 100.0, "g")
        key_b = build_match_key("배치B", "상품", 200.0, "g")
        entry_a = _make_entry(session, key_a, brand="배치A", name_core="상품", hit_count=0)
        entry_b = _make_entry(session, key_b, brand="배치B", name_core="상품", hit_count=10)

        svc.record_hits_batch(session, [entry_a.id, entry_b.id])
        session.flush()
        session.expire(entry_a)
        session.expire(entry_b)

        ra = session.get(MatchingEntry, entry_a.id)
        rb = session.get(MatchingEntry, entry_b.id)
        assert ra.hit_count == 1
        assert rb.hit_count == 11

    def test_record_hits_batch_empty(self, session: Session):
        """빈 리스트 입력 시 오류 없이 노-옵 처리."""
        svc.record_hits_batch(session, [])  # 예외 없이 통과


# ══════════════════════════════════════════════════════
# 6. classify_raw_record happy path + miss reasons
# ══════════════════════════════════════════════════════

class TestClassifyRawRecord:
    def test_happy_path(self, session: Session):
        """brand/name 있는 raw record → entry 반환, miss_reason=None."""
        key = build_match_key("농심", "신라면", 120.0, "g")
        entry = _make_entry(session, key, brand="농심", name_core="신라면",
                            pack_qty=120.0, pack_unit="g")

        raw = {"brand": "농심", "name": "신라면", "pack_qty": 120.0, "pack_unit": "g"}
        result_entry, reason = svc.classify_raw_record(session, raw)

        assert result_entry is not None
        assert result_entry.id == entry.id
        assert reason is None

    def test_happy_path_increments_hit_count(self, session: Session):
        """classify_raw_record hit 시 hit_count 증가."""
        key = build_match_key("오뚜기", "진라면", 120.0, "g")
        entry = _make_entry(session, key, brand="오뚜기", name_core="진라면",
                            pack_qty=120.0, pack_unit="g", hit_count=3)

        raw = {"brand": "오뚜기", "name": "진라면", "pack_qty": 120.0, "pack_unit": "g"}
        svc.classify_raw_record(session, raw)
        session.flush()
        session.expire(entry)

        refreshed = session.get(MatchingEntry, entry.id)
        assert refreshed.hit_count == 4

    def test_miss_no_brand(self, session: Session):
        """brand 없는 raw record → (None, 'no_brand')."""
        raw = {"name": "상품이름", "pack_qty": 100.0}
        result, reason = svc.classify_raw_record(session, raw)
        assert result is None
        assert reason == "no_brand"

    def test_miss_no_name(self, session: Session):
        """name 없는 raw record → (None, 'no_name')."""
        raw = {"brand": "브랜드"}
        result, reason = svc.classify_raw_record(session, raw)
        assert result is None
        assert reason == "no_name"

    def test_miss_key_not_found(self, session: Session):
        """brand/name 있지만 DB에 없는 key → (None, 'key_not_found')."""
        raw = {"brand": "없는브랜드", "name": "없는상품", "pack_qty": 1.0, "pack_unit": "개"}
        result, reason = svc.classify_raw_record(session, raw)
        assert result is None
        assert reason == "key_not_found"

    def test_alternative_field_keys(self, session: Session):
        """brandName/itemName 등 대체 필드명도 정상 처리."""
        key = build_match_key("삼성", "전자레인지", 1.0, "개")
        entry = _make_entry(session, key, brand="삼성", name_core="전자레인지",
                            pack_qty=1.0, pack_unit="개")

        raw = {"brandName": "삼성", "itemName": "전자레인지", "packQty": 1.0, "packUnit": "개"}
        result_entry, reason = svc.classify_raw_record(session, raw)

        assert result_entry is not None
        assert result_entry.id == entry.id
        assert reason is None

    def test_empty_brand_string(self, session: Session):
        """brand가 빈 문자열 → 'no_brand' miss."""
        raw = {"brand": "   ", "name": "상품"}
        result, reason = svc.classify_raw_record(session, raw)
        assert result is None
        assert reason == "no_brand"
