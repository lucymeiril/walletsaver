"""dedup_audit.py 단위 테스트.

검증 항목:
  - MartDedupAuditor: 3축 중복 카운트
  - dict 입력 / DiscountItem-like 객체 입력 모두 지원
  - 중복 없는 clean 판정
  - 중복 있는 has_duplicates / suspicious 판정
  - recommend_minimum_rows 공식 검증
  - audit() 종합 보고서 구조 검증
"""

from __future__ import annotations

import pytest

from pipeline.dedup_audit import (
    MartDedupAuditor,
    audit_mart_records,
    recommend_minimum_rows,
)


# ---------------------------------------------------------------------------
# 테스트 픽스처
# ---------------------------------------------------------------------------

def _make_dict(
    source_key: str = "",
    detail_url: str = "",
    name: str = "상품",
    sale_price: int = 10000,
) -> dict:
    """테스트용 DiscountItem dict 생성."""
    attrs: dict = {"source_name": "testmart"}
    if source_key:
        attrs["source_record_key"] = source_key
    if detail_url:
        attrs["source_url"] = detail_url
    return {
        "name": name,
        "sale_price": sale_price,
        "detail_url": detail_url,
        "attributes": attrs,
    }


class _FakeItem:
    """DiscountItem 유사 객체 (dict 대신 속성 접근 방식)."""

    def __init__(
        self,
        name: str,
        sale_price: int,
        detail_url: str = "",
        source_key: str = "",
    ):
        self.name = name
        self.sale_price = sale_price
        self.detail_url = detail_url
        self.attributes = {
            "source_name": "testmart",
            **({"source_record_key": source_key} if source_key else {}),
            **({"source_url": detail_url} if detail_url else {}),
        }


# ---------------------------------------------------------------------------
# recommend_minimum_rows
# ---------------------------------------------------------------------------

def test_recommend_minimum_rows_80_percent():
    assert recommend_minimum_rows(995.0) == 796


def test_recommend_minimum_rows_custom_factor():
    assert recommend_minimum_rows(1000.0, safety_factor=0.90) == 900


def test_recommend_minimum_rows_zero():
    assert recommend_minimum_rows(0.0) == 0


def test_recommend_minimum_rows_rounds_down():
    # 300 × 0.80 = 240.0 → 240
    assert recommend_minimum_rows(300.0) == 240


# ---------------------------------------------------------------------------
# count_by_source_record_key
# ---------------------------------------------------------------------------

def test_count_by_source_record_key_no_duplicates():
    records = [
        _make_dict(source_key=f"costco:prod{i}", detail_url=f"https://x.com/p/{i}")
        for i in range(5)
    ]
    auditor = MartDedupAuditor(records)
    result = auditor.count_by_source_record_key()
    assert result["total"] == 5
    assert result["unique"] == 5
    assert result["duplicate"] == 0


def test_count_by_source_record_key_with_duplicates():
    records = [
        _make_dict(source_key="costco:prod1"),
        _make_dict(source_key="costco:prod1"),  # 중복
        _make_dict(source_key="costco:prod2"),
    ]
    auditor = MartDedupAuditor(records)
    result = auditor.count_by_source_record_key()
    assert result["total"] == 3
    assert result["unique"] == 2
    assert result["duplicate"] == 1


def test_count_by_source_record_key_missing_keys():
    records = [
        _make_dict(detail_url="https://x.com/p/1"),   # source_key 없음
        _make_dict(detail_url="https://x.com/p/2"),   # source_key 없음
    ]
    auditor = MartDedupAuditor(records)
    result = auditor.count_by_source_record_key()
    assert result["records_without_key"] == 2
    assert result["unique"] == 0


# ---------------------------------------------------------------------------
# count_by_detail_url
# ---------------------------------------------------------------------------

def test_count_by_detail_url_no_duplicates():
    records = [
        _make_dict(detail_url=f"https://www.costco.co.kr/p/{i}")
        for i in range(10)
    ]
    auditor = MartDedupAuditor(records)
    result = auditor.count_by_detail_url()
    assert result["unique"] == 10
    assert result["duplicate"] == 0


def test_count_by_detail_url_normalizes_www():
    """www 유무 차이를 정규화해 같은 URL로 처리해야 한다."""
    records = [
        _make_dict(detail_url="https://www.costco.co.kr/p/12345"),
        _make_dict(detail_url="https://costco.co.kr/p/12345"),  # www 없음 → 동일
    ]
    auditor = MartDedupAuditor(records)
    result = auditor.count_by_detail_url()
    assert result["unique"] == 1
    assert result["duplicate"] == 1


def test_count_by_detail_url_trailing_slash():
    """trailing slash 차이를 정규화해야 한다."""
    records = [
        _make_dict(detail_url="https://www.costco.co.kr/p/12345/"),
        _make_dict(detail_url="https://www.costco.co.kr/p/12345"),
    ]
    auditor = MartDedupAuditor(records)
    result = auditor.count_by_detail_url()
    assert result["unique"] == 1


def test_count_by_detail_url_missing():
    records = [_make_dict()]  # detail_url 없음
    auditor = MartDedupAuditor(records)
    result = auditor.count_by_detail_url()
    assert result["records_without_url"] == 1
    assert result["unique"] == 0


# ---------------------------------------------------------------------------
# count_by_name_price
# ---------------------------------------------------------------------------

def test_count_by_name_price_no_duplicates():
    records = [
        _make_dict(name=f"상품{i}", sale_price=1000 * i + 1000)
        for i in range(5)
    ]
    auditor = MartDedupAuditor(records)
    result = auditor.count_by_name_price()
    assert result["unique"] == 5
    assert result["duplicate"] == 0


def test_count_by_name_price_with_duplicates():
    records = [
        _make_dict(name="바이오더마 세럼", sale_price=35990),
        _make_dict(name="바이오더마 세럼", sale_price=35990),  # 중복
        _make_dict(name="다른 상품", sale_price=35990),   # 같은 가격, 다른 이름
    ]
    auditor = MartDedupAuditor(records)
    result = auditor.count_by_name_price()
    assert result["unique"] == 2
    assert result["duplicate"] == 1


def test_count_by_name_price_normalizes_whitespace():
    """이름의 공백 차이를 정규화해야 한다."""
    records = [
        _make_dict(name="상품 A", sale_price=10000),
        _make_dict(name="상품  A", sale_price=10000),   # 공백 2개
    ]
    auditor = MartDedupAuditor(records)
    result = auditor.count_by_name_price()
    assert result["unique"] == 1


# ---------------------------------------------------------------------------
# audit() 종합
# ---------------------------------------------------------------------------

def test_audit_clean_verdict():
    """중복 없는 clean 데이터셋은 verdict='clean'을 반환해야 한다."""
    records = [
        _make_dict(
            source_key=f"costco:p{i}",
            detail_url=f"https://www.costco.co.kr/p/{i}",
            name=f"상품{i}",
            sale_price=10000 + i,
        )
        for i in range(20)
    ]
    result = audit_mart_records(records)
    assert result["verdict"] == "clean"
    assert result["total_records"] == 20
    assert result["primary_unique"] == 20
    assert result["conservative_unique"] >= 20
    assert result["minimum_rows_recommendation"] == 16  # 20 × 0.80


def test_audit_has_duplicates_verdict():
    """중복이 있지만 5% 미만이면 'has_duplicates'."""
    records = [
        _make_dict(
            source_key=f"costco:p{i}",
            detail_url=f"https://x.com/p/{i}",
            name=f"상품{i}",
            sale_price=10000 + i,
        )
        for i in range(100)
    ]
    # 2건 중복 추가 (2% < 5%)
    records.append(_make_dict(source_key="costco:p0", detail_url="https://x.com/p/0", name="상품0", sale_price=10000))
    records.append(_make_dict(source_key="costco:p1", detail_url="https://x.com/p/1", name="상품1", sale_price=10001))
    result = audit_mart_records(records)
    assert result["total_records"] == 102
    assert result["verdict"] in ("has_duplicates", "clean")  # by_key duplicate=2, < 5%


def test_audit_suspicious_verdict():
    """중복이 5% 이상이면 'suspicious'."""
    records = [
        _make_dict(source_key=f"costco:p{i}", detail_url=f"https://x.com/p/{i}")
        for i in range(20)
    ]
    # 5건 중복 추가 (5/25 = 20% > 5%)
    for j in range(5):
        records.append(_make_dict(source_key=f"costco:p{j}", detail_url=f"https://x.com/p/{j}"))
    result = audit_mart_records(records)
    assert result["verdict"] == "suspicious"


def test_audit_empty_records():
    """빈 입력은 예외 없이 0을 반환해야 한다."""
    result = audit_mart_records([])
    assert result["total_records"] == 0
    assert result["primary_unique"] == 0
    assert result["minimum_rows_recommendation"] == 0


def test_audit_accepts_fake_discount_items():
    """DiscountItem 유사 객체(속성 접근)도 처리할 수 있어야 한다."""
    items = [
        _FakeItem(
            name=f"상품{i}",
            sale_price=10000 + i,
            detail_url=f"https://www.costco.co.kr/p/{i}",
            source_key=f"costco:p{i}",
        )
        for i in range(10)
    ]
    result = audit_mart_records(items)
    assert result["total_records"] == 10
    assert result["verdict"] == "clean"


def test_audit_report_has_all_required_keys():
    """audit() 결과에 모든 필수 키가 존재해야 한다."""
    records = [_make_dict(source_key="k1", detail_url="https://x.com/p/1")]
    result = audit_mart_records(records)
    for key in (
        "total_records",
        "by_source_record_key",
        "by_detail_url",
        "by_name_price",
        "key_coverage_ratio",
        "conservative_unique",
        "liberal_unique",
        "primary_unique",
        "verdict",
        "minimum_rows_recommendation",
        "audit_policy",
    ):
        assert key in result, f"필수 키 '{key}' 없음"


def test_recommend_minimum_rows_in_audit_matches_formula():
    """audit()의 minimum_rows_recommendation = primary_unique × 0.80."""
    records = [
        _make_dict(
            source_key=f"costco:p{i}",
            detail_url=f"https://www.costco.co.kr/p/{i}",
            name=f"상품{i}",
            sale_price=10000,
        )
        for i in range(100)
    ]
    result = audit_mart_records(records)
    expected = int(result["primary_unique"] * 0.80)
    assert result["minimum_rows_recommendation"] == expected


# ---------------------------------------------------------------------------
# 코스트코 실증 시나리오 (rd2-costco-playwright 데이터 기반)
# ---------------------------------------------------------------------------

def test_costco_live_scenario_no_duplicates():
    """코스트코 실 수집 시뮬: SpecialPriceOffers(732) + OnlineDeals(263)
    = 995건, 중복 없음.
    """
    # Special 732건
    special = [
        _make_dict(
            source_key=f"https://www.costco.co.kr/p/SP{i:04d}",
            detail_url=f"https://www.costco.co.kr/p/SP{i:04d}",
            name=f"특가상품{i}",
            sale_price=10000 + i,
        )
        for i in range(732)
    ]
    # OnlineDeals 263건 (별개 상품)
    online = [
        _make_dict(
            source_key=f"https://www.costco.co.kr/p/OD{i:04d}",
            detail_url=f"https://www.costco.co.kr/p/OD{i:04d}",
            name=f"온라인딜{i}",
            sale_price=20000 + i,
        )
        for i in range(263)
    ]
    all_records = special + online
    result = audit_mart_records(all_records)
    assert result["total_records"] == 995
    assert result["verdict"] == "clean"
    assert result["primary_unique"] == 995
    # minimum_rows 권고: 995 × 0.80 = 796
    assert result["minimum_rows_recommendation"] == 796


def test_homeplus_cap_simulation():
    """홈플러스 캡 시뮬: MAX_ITEMS=300으로 잘린 결과 감사.
    300건이어도 중복이 없으면 'clean'이지만 cap에 막혔을 수 있음.
    """
    records = [
        _make_dict(
            source_key=f"homeplus:p{i}",
            detail_url=f"https://mfront.homeplus.co.kr/item?itemNo={i:09d}",
            name=f"홈플러스상품{i}",
            sale_price=5000 + i,
        )
        for i in range(300)
    ]
    result = audit_mart_records(records)
    assert result["total_records"] == 300
    assert result["verdict"] == "clean"
    assert result["primary_unique"] == 300
    # cap=300이지만 minimum_rows 권고는 240 (300 × 0.80)
    assert result["minimum_rows_recommendation"] == 240
