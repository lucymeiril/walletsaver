"""WalletSavior Phase D1 TDD — 가격 분위수 계산기 테스트.

시나리오:
    1. 충분한 표본 (n>=5) → 정확한 P10/P25/P50/P75 산출.
    2. 부족한 표본 (n<5) → sufficient=False, p10=None, classify → INSUFFICIENT_DATA.
    3. canonical_id 격리 → 다른 canonical_id 가격이 혼입되지 않아야 함.
    4. 동률(tie) 처리 → 동일 가격 표본에서 분위수 산출 안정성.
    5. classify 경계값 → P10 경계에서 HOT_DEAL/SALE 정확 판별.
    6. 빈 표본 → 모든 분위수 None.
"""

from __future__ import annotations

import pytest
from datetime import datetime

# shared core 는 sys.path 없이도 상대 import로 테스트 가능
# pytest 실행 위치에 따라 shared/가 sys.path에 있어야 함
import sys
from pathlib import Path

_SHARED = Path(__file__).resolve().parents[1]
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

from core.price_grading import (
    SUFFICIENT_SAMPLE_THRESHOLD,
    PriceGrade,
    classify,
    compute_price_grade,
)


# ══════════════════════════════════════════════════════
# 시나리오 1: 충분한 표본 → 정확한 분위수
# ══════════════════════════════════════════════════════

def test_sufficient_sample_basic_quantiles():
    """n=10, 균등 분포 → P10/P25/P50/P75 선형 보간 정확값."""
    # 1, 2, ..., 10 → sorted
    prices = [float(i) for i in range(1, 11)]
    grade = compute_price_grade("cid-001", prices, window_months=6)

    assert grade.sufficient is True
    assert grade.sample_size == 10
    assert grade.canonical_id == "cid-001"
    assert grade.window_months == 6

    # P10: idx = 0.1 * 9 = 0.9 → lo=0, hi=1, frac=0.9 → 1 + 0.9 * (2-1) = 1.9
    assert abs(grade.p10 - 1.9) < 1e-9
    # P25: idx = 0.25 * 9 = 2.25 → lo=2, hi=3, frac=0.25 → 3 + 0.25*(4-3) = 3.25
    assert abs(grade.p25 - 3.25) < 1e-9
    # P50: idx = 0.5 * 9 = 4.5 → lo=4, hi=5, frac=0.5 → 5 + 0.5*(6-5) = 5.5
    assert abs(grade.p50 - 5.5) < 1e-9
    # P75: idx = 0.75 * 9 = 6.75 → lo=6, hi=7, frac=0.75 → 7 + 0.75*(8-7) = 7.75
    assert abs(grade.p75 - 7.75) < 1e-9


def test_sufficient_sample_min_boundary():
    """n == SUFFICIENT_SAMPLE_THRESHOLD (=5) → sufficient=True."""
    prices = [100.0, 200.0, 300.0, 400.0, 500.0]
    grade = compute_price_grade("cid-min", prices)
    assert grade.sufficient is True
    assert grade.p10 is not None
    assert grade.p25 is not None
    assert grade.p75 is not None
    # P50: idx=0.5*4=2.0 → 300.0
    assert abs(grade.p50 - 300.0) < 1e-9


def test_sufficient_sample_custom_computed_at():
    """computed_at이 명시되면 그대로 저장."""
    ts = datetime(2025, 1, 15, 12, 0, 0)
    prices = [100.0] * 10
    grade = compute_price_grade("cid-ts", prices, computed_at=ts)
    assert grade.computed_at == ts


# ══════════════════════════════════════════════════════
# 시나리오 2: 표본 부족 → INSUFFICIENT_DATA
# ══════════════════════════════════════════════════════

def test_insufficient_sample_n4():
    """n=4 (< 5) → sufficient=False, p10/p25/p75 = None, p50 산출."""
    prices = [100.0, 200.0, 300.0, 400.0]
    grade = compute_price_grade("cid-002", prices)

    assert grade.sufficient is False
    assert grade.sample_size == 4
    assert grade.p10 is None
    assert grade.p25 is None
    assert grade.p75 is None
    # p50는 항상 산출 (n >= 1)
    assert grade.p50 is not None
    assert abs(grade.p50 - 250.0) < 1e-9  # (200+300)/2


def test_insufficient_sample_n1():
    """n=1 → sufficient=False, p50=단일값."""
    grade = compute_price_grade("cid-one", [999.0])
    assert grade.sufficient is False
    assert grade.p50 == 999.0
    assert grade.p10 is None


def test_insufficient_sample_n0():
    """n=0 → sufficient=False, 모든 분위수 None."""
    grade = compute_price_grade("cid-empty", [])
    assert grade.sufficient is False
    assert grade.sample_size == 0
    assert grade.p10 is None
    assert grade.p25 is None
    assert grade.p50 is None
    assert grade.p75 is None


def test_classify_insufficient_data():
    """sufficient=False인 grade → classify는 항상 INSUFFICIENT_DATA."""
    prices = [100.0, 200.0, 300.0]
    grade = compute_price_grade("cid-ins", prices)
    assert grade.sufficient is False
    for price in [50.0, 150.0, 250.0, 350.0]:
        assert classify(price, grade) == "INSUFFICIENT_DATA"


# ══════════════════════════════════════════════════════
# 시나리오 3: canonical_id 격리
# ══════════════════════════════════════════════════════

def test_canonical_id_isolation():
    """compute_price_grade는 전달된 prices 리스트만 처리 — 다른 canonical의 가격 혼입 방지.

    이 테스트는 호출자가 canonical_id별로 가격을 올바르게 그룹화해야 함을
    명시적으로 검증한다. compute_price_grade 자체는 canonical_id를 메타 정보로만 저장한다.
    """
    prices_a = [1000.0, 2000.0, 3000.0, 4000.0, 5000.0, 6000.0]
    prices_b = [10000.0, 20000.0, 30000.0, 40000.0, 50000.0, 60000.0]

    grade_a = compute_price_grade("cid-A", prices_a)
    grade_b = compute_price_grade("cid-B", prices_b)

    # A는 B의 가격 범위에 영향받지 않는다
    assert grade_a.p50 < 10000.0
    assert grade_b.p50 > 9000.0

    # canonical_id 기록 확인
    assert grade_a.canonical_id == "cid-A"
    assert grade_b.canonical_id == "cid-B"


def test_canonical_id_is_stored():
    """PriceGrade.canonical_id가 입력과 동일하게 저장된다."""
    cid = "sha1-test-canonical-id-40chars-abcde"
    grade = compute_price_grade(cid, [100.0] * 10)
    assert grade.canonical_id == cid


# ══════════════════════════════════════════════════════
# 시나리오 4: 동률(tie) 처리
# ══════════════════════════════════════════════════════

def test_tie_all_same_price():
    """모든 표본이 동일한 가격 → 모든 분위수가 해당 값."""
    price = 1234.0
    prices = [price] * 10
    grade = compute_price_grade("cid-tie", prices)

    assert grade.sufficient is True
    assert abs(grade.p10 - price) < 1e-9
    assert abs(grade.p25 - price) < 1e-9
    assert abs(grade.p50 - price) < 1e-9
    assert abs(grade.p75 - price) < 1e-9


def test_tie_partial():
    """일부 동률 포함 → 분위수 안정성."""
    prices = [100.0, 100.0, 100.0, 200.0, 300.0, 300.0, 400.0, 500.0, 500.0, 600.0]
    grade = compute_price_grade("cid-partial-tie", prices)
    assert grade.sufficient is True
    # P10 계산: sorted=[100,100,100,200,300,300,400,500,500,600]
    # idx = 0.1 * 9 = 0.9 → lo=0, hi=1, frac=0.9 → 100 + 0.9*(100-100) = 100.0
    assert abs(grade.p10 - 100.0) < 1e-9
    # 단조 증가 확인
    assert grade.p10 <= grade.p25
    assert grade.p25 <= grade.p50
    assert grade.p50 <= grade.p75


# ══════════════════════════════════════════════════════
# 시나리오 5: classify 경계값
# ══════════════════════════════════════════════════════

def test_classify_hot_deal_exactly_p10():
    """observed_price == p10 → HOT_DEAL (경계 포함)."""
    prices = [float(i * 100) for i in range(1, 11)]
    grade = compute_price_grade("cid-boundary", prices)
    assert grade.p10 is not None
    # p10 정확히 = HOT_DEAL
    assert classify(grade.p10, grade) == "HOT_DEAL"
    # p10 + epsilon = SALE
    assert classify(grade.p10 + 0.01, grade) == "SALE"


def test_classify_sale_range():
    """p10 < price <= p25 → SALE."""
    prices = [100.0, 200.0, 300.0, 400.0, 500.0, 600.0, 700.0, 800.0, 900.0, 1000.0]
    grade = compute_price_grade("cid-sale", prices)
    assert grade.p10 is not None and grade.p25 is not None
    midpoint = (grade.p10 + grade.p25) / 2.0
    assert classify(midpoint, grade) == "SALE"


def test_classify_normal_range():
    """p25 < price <= p75 → NORMAL."""
    prices = [100.0, 200.0, 300.0, 400.0, 500.0, 600.0, 700.0, 800.0, 900.0, 1000.0]
    grade = compute_price_grade("cid-normal", prices)
    assert grade.p25 is not None and grade.p75 is not None
    midpoint = (grade.p25 + grade.p75) / 2.0
    assert classify(midpoint, grade) == "NORMAL"


def test_classify_overpriced():
    """price > p75 → OVERPRICED."""
    prices = [100.0, 200.0, 300.0, 400.0, 500.0, 600.0, 700.0, 800.0, 900.0, 1000.0]
    grade = compute_price_grade("cid-over", prices)
    assert grade.p75 is not None
    assert classify(grade.p75 + 0.01, grade) == "OVERPRICED"
    assert classify(9999999.0, grade) == "OVERPRICED"


def test_classify_exactly_p75_is_normal():
    """observed_price == p75 → NORMAL (경계 포함)."""
    prices = [100.0, 200.0, 300.0, 400.0, 500.0, 600.0, 700.0, 800.0, 900.0, 1000.0]
    grade = compute_price_grade("cid-p75", prices)
    assert grade.p75 is not None
    assert classify(grade.p75, grade) == "NORMAL"
