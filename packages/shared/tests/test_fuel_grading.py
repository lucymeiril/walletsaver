"""WalletSavior Phase F4 TDD — 주유소 가격 등급 계산기 테스트.

시나리오:
    1. 충분한 표본 (n>=5) → P25/P50/P75 산출, sufficient=True
    2. 부족한 표본 (n<5) → sufficient=False, classify → INSUFFICIENT_DATA
    3. 빈 표본 → 모든 분위수 None
    4. classify 경계값 → P25/P75 경계에서 CHEAP/NORMAL/EXPENSIVE 판별
    5. compute_all_fuel_grades → (sido, sigungu, fuel_kind) 그룹 분리
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

_SHARED = Path(__file__).resolve().parents[1]
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

from core.fuel_grading import (
    SUFFICIENT_SAMPLE_THRESHOLD,
    FuelPriceGrade,
    classify_fuel,
    compute_all_fuel_grades,
    compute_fuel_grade,
)
from core.fuel_models import FuelKind


# ══════════════════════════════════════════════════════
# 시나리오 1: 충분한 표본
# ══════════════════════════════════════════════════════

def test_sufficient_sample_basic():
    """n=7, 단순 정수 가격 → P25/P50/P75 산출."""
    prices = [1500.0, 1550.0, 1600.0, 1620.0, 1650.0, 1700.0, 1800.0]
    grade = compute_fuel_grade("서울특별시", "강서구", FuelKind.GASOLINE_REGULAR, prices)

    assert grade.sufficient is True
    assert grade.sample_size == 7
    assert grade.p25 is not None
    assert grade.p50 is not None
    assert grade.p75 is not None
    assert grade.p25 < grade.p50 < grade.p75


def test_sufficient_sample_all_same_price():
    """동일 가격 N개 → 분위수 모두 같은 값."""
    prices = [1600.0] * 5
    grade = compute_fuel_grade("경기도", "수원시", FuelKind.DIESEL, prices)
    assert grade.sufficient is True
    assert grade.p25 == pytest.approx(1600.0)
    assert grade.p50 == pytest.approx(1600.0)
    assert grade.p75 == pytest.approx(1600.0)


# ══════════════════════════════════════════════════════
# 시나리오 2: 부족한 표본
# ══════════════════════════════════════════════════════

def test_insufficient_sample_n4():
    """n=4 (< 5) → sufficient=False, p25=p75=None."""
    prices = [1500.0, 1600.0, 1700.0, 1800.0]
    grade = compute_fuel_grade("서울특별시", "강서구", FuelKind.GASOLINE_REGULAR, prices)
    assert grade.sufficient is False
    assert grade.p25 is None
    assert grade.p75 is None
    assert grade.p50 is not None  # p50는 항상 산출


def test_insufficient_classify():
    """sufficient=False → classify는 항상 INSUFFICIENT_DATA."""
    prices = [1500.0, 1600.0, 1700.0]
    grade = compute_fuel_grade("서울특별시", "강서구", FuelKind.GASOLINE_REGULAR, prices)
    assert classify_fuel(1500.0, grade) == "INSUFFICIENT_DATA"
    assert classify_fuel(1700.0, grade) == "INSUFFICIENT_DATA"


# ══════════════════════════════════════════════════════
# 시나리오 3: 빈 표본
# ══════════════════════════════════════════════════════

def test_empty_sample():
    grade = compute_fuel_grade("서울특별시", "강서구", FuelKind.LPG, [])
    assert grade.sufficient is False
    assert grade.sample_size == 0
    assert grade.p25 is None
    assert grade.p50 is None
    assert grade.p75 is None


# ══════════════════════════════════════════════════════
# 시나리오 4: classify 경계값
# ══════════════════════════════════════════════════════

def test_classify_cheap_at_p25():
    """price == p25 → CHEAP."""
    prices = [1400.0, 1500.0, 1600.0, 1700.0, 1800.0, 1900.0, 2000.0]
    grade = compute_fuel_grade("서울특별시", "강서구", FuelKind.GASOLINE_REGULAR, prices)
    assert grade.p25 is not None
    assert classify_fuel(grade.p25, grade) == "CHEAP"


def test_classify_cheap_below_p25():
    """price < p25 → CHEAP."""
    prices = [1400.0, 1500.0, 1600.0, 1700.0, 1800.0, 1900.0, 2000.0]
    grade = compute_fuel_grade("서울특별시", "강서구", FuelKind.GASOLINE_REGULAR, prices)
    assert classify_fuel(1350.0, grade) == "CHEAP"


def test_classify_normal():
    """p25 < price <= p75 → NORMAL."""
    prices = [1400.0, 1500.0, 1600.0, 1700.0, 1800.0, 1900.0, 2000.0]
    grade = compute_fuel_grade("서울특별시", "강서구", FuelKind.GASOLINE_REGULAR, prices)
    mid_price = (grade.p25 + grade.p75) / 2
    assert classify_fuel(mid_price, grade) == "NORMAL"


def test_classify_expensive_above_p75():
    """price > p75 → EXPENSIVE."""
    prices = [1400.0, 1500.0, 1600.0, 1700.0, 1800.0, 1900.0, 2000.0]
    grade = compute_fuel_grade("서울특별시", "강서구", FuelKind.GASOLINE_REGULAR, prices)
    assert grade.p75 is not None
    assert classify_fuel(grade.p75 + 100, grade) == "EXPENSIVE"


# ══════════════════════════════════════════════════════
# 시나리오 5: compute_all_fuel_grades
# ══════════════════════════════════════════════════════

def test_compute_all_fuel_grades_grouping():
    """서로 다른 (sido, sigungu, fuel_kind) 는 독립적으로 집계."""
    observations = [
        ("서울특별시", "강서구", FuelKind.GASOLINE_REGULAR, 1500.0),
        ("서울특별시", "강서구", FuelKind.GASOLINE_REGULAR, 1600.0),
        ("서울특별시", "강서구", FuelKind.GASOLINE_REGULAR, 1700.0),
        ("서울특별시", "강서구", FuelKind.GASOLINE_REGULAR, 1800.0),
        ("서울특별시", "강서구", FuelKind.GASOLINE_REGULAR, 1900.0),
        ("서울특별시", "강서구", FuelKind.DIESEL, 1400.0),
        ("서울특별시", "강서구", FuelKind.DIESEL, 1450.0),
        ("경기도", "수원시", FuelKind.GASOLINE_REGULAR, 1550.0),
    ]
    grades = compute_all_fuel_grades(observations)

    key_gasoline = ("서울특별시", "강서구", "gasoline_regular")
    key_diesel = ("서울특별시", "강서구", "diesel")
    key_suwon = ("경기도", "수원시", "gasoline_regular")

    assert key_gasoline in grades
    assert key_diesel in grades
    assert key_suwon in grades

    # 서울 강서구 휘발유: n=5 → sufficient
    assert grades[key_gasoline].sufficient is True
    # 서울 강서구 경유: n=2 → insufficient
    assert grades[key_diesel].sufficient is False
    # 수원 휘발유: n=1 → insufficient
    assert grades[key_suwon].sufficient is False


def test_compute_all_fuel_grades_no_cross_contamination():
    """다른 지역 가격이 이 지역 등급에 영향을 주지 않아야 함."""
    observations = [
        ("서울특별시", "강서구", FuelKind.GASOLINE_REGULAR, 1500.0),
        ("서울특별시", "강서구", FuelKind.GASOLINE_REGULAR, 1550.0),
        ("서울특별시", "강서구", FuelKind.GASOLINE_REGULAR, 1600.0),
        ("서울특별시", "강서구", FuelKind.GASOLINE_REGULAR, 1650.0),
        ("서울특별시", "강서구", FuelKind.GASOLINE_REGULAR, 1700.0),
        # 다른 지역 — 비싼 가격
        ("부산광역시", "해운대구", FuelKind.GASOLINE_REGULAR, 9999.0),
        ("부산광역시", "해운대구", FuelKind.GASOLINE_REGULAR, 9998.0),
        ("부산광역시", "해운대구", FuelKind.GASOLINE_REGULAR, 9997.0),
        ("부산광역시", "해운대구", FuelKind.GASOLINE_REGULAR, 9996.0),
        ("부산광역시", "해운대구", FuelKind.GASOLINE_REGULAR, 9995.0),
    ]
    grades = compute_all_fuel_grades(observations)

    seoul_grade = grades[("서울특별시", "강서구", "gasoline_regular")]
    assert seoul_grade.p50 is not None
    assert seoul_grade.p50 < 2000  # 부산 가격에 오염되지 않아야 함
