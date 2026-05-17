"""WalletSavior Phase F4 TDD — FuelStation/FuelPriceObservation 모델 테스트.

시나리오:
    1. FuelStation.make_id → 결정적 SHA1 (같은 입력 → 같은 id)
    2. FuelStation.build → id 자동 계산
    3. normalize_address → 공백 정규화
    4. FuelKind enum 값 검증
    5. FuelPriceObservation.build → 가격 단위 (원/L 정수)
    6. 잘못된 입력 → Pydantic validation 에러
"""

from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime

import pytest

_SHARED = Path(__file__).resolve().parents[1]
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

from core.fuel_models import FuelKind, FuelPriceObservation, FuelStation, normalize_address


# ══════════════════════════════════════════════════════
# normalize_address
# ══════════════════════════════════════════════════════

def test_normalize_address_strips_whitespace():
    assert normalize_address("  서울특별시  강서구  허준로  57  ") == "서울특별시 강서구 허준로 57"


def test_normalize_address_collapses_multiple_spaces():
    assert normalize_address("서울특별시   강서구") == "서울특별시 강서구"


def test_normalize_address_empty():
    assert normalize_address("") == ""


# ══════════════════════════════════════════════════════
# FuelStation.make_id
# ══════════════════════════════════════════════════════

def test_make_id_deterministic():
    """같은 입력은 항상 같은 id."""
    id1 = FuelStation.make_id("알뜰주유소", "서울특별시 강서구 허준로 57")
    id2 = FuelStation.make_id("알뜰주유소", "서울특별시 강서구 허준로 57")
    assert id1 == id2


def test_make_id_different_brand_different_id():
    id1 = FuelStation.make_id("SK에너지", "서울특별시 강서구 허준로 57")
    id2 = FuelStation.make_id("GS칼텍스", "서울특별시 강서구 허준로 57")
    assert id1 != id2


def test_make_id_different_address_different_id():
    id1 = FuelStation.make_id("SK에너지", "서울특별시 강서구 허준로 57")
    id2 = FuelStation.make_id("SK에너지", "서울특별시 강서구 마곡중앙8로 111")
    assert id1 != id2


def test_make_id_address_whitespace_insensitive():
    """주소 앞뒤 공백은 id에 영향 없어야 함."""
    id1 = FuelStation.make_id("SK에너지", "서울특별시 강서구 허준로 57")
    id2 = FuelStation.make_id("SK에너지", "  서울특별시 강서구 허준로 57  ")
    assert id1 == id2


def test_make_id_is_sha1_hex():
    """id는 40자 16진수 문자열이어야 함."""
    station_id = FuelStation.make_id("SK에너지", "서울특별시 강서구 허준로 57")
    assert len(station_id) == 40
    assert all(c in "0123456789abcdef" for c in station_id)


# ══════════════════════════════════════════════════════
# FuelStation.build
# ══════════════════════════════════════════════════════

def test_build_computes_id():
    station = FuelStation.build(
        brand="알뜰주유소",
        name="강서알뜰주유소",
        address="서울특별시 강서구 허준로 57",
        sido="서울특별시",
        sigungu="강서구",
    )
    expected_id = FuelStation.make_id("알뜰주유소", "서울특별시 강서구 허준로 57")
    assert station.id == expected_id
    assert station.brand == "알뜰주유소"
    assert station.name == "강서알뜰주유소"
    assert station.sido == "서울특별시"
    assert station.sigungu == "강서구"
    assert station.self_service is False  # 기본값


def test_build_with_self_service():
    station = FuelStation.build(
        brand="SK에너지",
        name="마곡SK",
        address="서울특별시 강서구 마곡중앙8로 111",
        sido="서울특별시",
        sigungu="강서구",
        self_service=True,
    )
    assert station.self_service is True


def test_build_with_coordinates():
    station = FuelStation.build(
        brand="GS칼텍스",
        name="화곡GS",
        address="서울특별시 강서구 화곡로 321",
        sido="서울특별시",
        sigungu="강서구",
        lat=37.548,
        lng=126.849,
    )
    assert station.lat == pytest.approx(37.548)
    assert station.lng == pytest.approx(126.849)


# ══════════════════════════════════════════════════════
# FuelKind enum
# ══════════════════════════════════════════════════════

def test_fuel_kind_values():
    assert FuelKind.GASOLINE_REGULAR.value == "gasoline_regular"
    assert FuelKind.GASOLINE_PREMIUM.value == "gasoline_premium"
    assert FuelKind.DIESEL.value == "diesel"
    assert FuelKind.LPG.value == "lpg"


def test_fuel_kind_from_string():
    assert FuelKind("gasoline_regular") == FuelKind.GASOLINE_REGULAR
    assert FuelKind("diesel") == FuelKind.DIESEL


def test_fuel_kind_invalid():
    with pytest.raises(ValueError):
        FuelKind("benzene")


# ══════════════════════════════════════════════════════
# FuelPriceObservation
# ══════════════════════════════════════════════════════

def test_fuel_price_observation_build():
    station = FuelStation.build(
        brand="SK에너지", name="마곡SK",
        address="서울특별시 강서구 마곡중앙8로 111",
        sido="서울특별시", sigungu="강서구",
    )
    obs_at = datetime(2025, 1, 15, 6, 0, 0)
    obs = FuelPriceObservation.build(
        station_id=station.id,
        fuel_kind=FuelKind.GASOLINE_REGULAR,
        price=1625,
        observed_at=obs_at,
    )
    assert obs.station_id == station.id
    assert obs.fuel_kind == FuelKind.GASOLINE_REGULAR
    assert obs.price == 1625
    assert obs.observed_at == obs_at


def test_fuel_price_observation_id_deterministic():
    station_id = "abc123"
    obs_at = datetime(2025, 1, 15)
    id1 = FuelPriceObservation.make_id(station_id, FuelKind.DIESEL, obs_at)
    id2 = FuelPriceObservation.make_id(station_id, FuelKind.DIESEL, obs_at)
    assert id1 == id2


def test_fuel_price_observation_id_different_kinds():
    station_id = "abc123"
    obs_at = datetime(2025, 1, 15)
    id_gas = FuelPriceObservation.make_id(station_id, FuelKind.GASOLINE_REGULAR, obs_at)
    id_diesel = FuelPriceObservation.make_id(station_id, FuelKind.DIESEL, obs_at)
    assert id_gas != id_diesel


def test_fuel_price_observation_price_integer():
    """가격은 정수 (원/L)."""
    obs = FuelPriceObservation.build(
        station_id="abc", fuel_kind=FuelKind.LPG, price=990
    )
    assert isinstance(obs.price, int)
    assert obs.price == 990
