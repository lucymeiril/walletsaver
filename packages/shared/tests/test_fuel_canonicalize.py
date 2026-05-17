"""WalletSavior Phase F4 TDD — fuel_canonicalize 테스트.

시나리오:
    1. canonicalize_opinet → FuelStation + observations
    2. 브랜드 정규화 (알뜰(자영) → 알뜰주유소)
    3. sido/sigungu 추출
    4. 가격 파싱 ('-' → None, '1,598' → 1598)
    5. 필수 필드 누락 → error 반환
    6. 결정적 id (같은 raw → 같은 station.id)
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

_SHARED = Path(__file__).resolve().parents[1]
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

from core.fuel_canonicalize import (
    FuelCanonicalizationResult,
    canonicalize_opinet,
    extract_sido_sigungu,
    normalize_brand,
    parse_price,
)
from core.fuel_models import FuelKind, FuelStation


# ── 단위 함수 테스트 ──────────────────────────────────────────────────────────

def test_normalize_brand_sk():
    assert normalize_brand("SK에너지") == "SK에너지"
    assert normalize_brand("SK") == "SK에너지"


def test_normalize_brand_gs():
    assert normalize_brand("GS칼텍스") == "GS칼텍스"
    assert normalize_brand("GS") == "GS칼텍스"


def test_normalize_brand_smart():
    assert normalize_brand("알뜰(자영)") == "알뜰주유소"
    assert normalize_brand("자영알뜰") == "알뜰주유소"
    assert normalize_brand("알뜰주유소") == "알뜰주유소"


def test_normalize_brand_unknown():
    """매핑 없는 브랜드는 원본 그대로."""
    assert normalize_brand("독립브랜드") == "독립브랜드"


def test_parse_price_comma():
    assert parse_price("1,598") == 1598
    assert parse_price("1,448") == 1448


def test_parse_price_plain():
    assert parse_price("1625") == 1625


def test_parse_price_dash():
    assert parse_price("-") is None


def test_parse_price_empty():
    assert parse_price("") is None


def test_parse_price_zero():
    assert parse_price("0") is None


def test_extract_sido_sigungu_seoul():
    sido, sigungu = extract_sido_sigungu("서울특별시 강서구 허준로 57")
    assert sido == "서울특별시"
    assert sigungu == "강서구"


def test_extract_sido_sigungu_gyeonggi():
    sido, sigungu = extract_sido_sigungu("경기도 수원시 팔달구 인계로 123")
    assert sido == "경기도"
    assert sigungu == "수원시"


# ── canonicalize_opinet 통합 테스트 ──────────────────────────────────────────

def _make_raw(
    name="강서알뜰주유소",
    brand="알뜰(자영)",
    address="서울특별시 강서구 허준로 57",
    self_service=True,
    gasoline_regular="1,598",
    gasoline_premium="-",
    diesel="1,448",
    lpg=None,
    opinet_id="A0003461",
) -> dict:
    return {
        "name": name,
        "brand": brand,
        "address": address,
        "self_service": self_service,
        "gasoline_regular": gasoline_regular,
        "gasoline_premium": gasoline_premium,
        "diesel": diesel,
        "lpg": lpg,
        "opinet_id": opinet_id,
        "source_url": "https://www.opinet.co.kr/searRgSelect.do",
    }


def test_canonicalize_basic_station():
    raw = _make_raw()
    result = canonicalize_opinet(raw, observed_at=datetime(2025, 1, 15))

    assert result.error is None
    assert result.station is not None
    assert result.station.name == "강서알뜰주유소"
    assert result.station.brand == "알뜰주유소"  # 정규화됨
    assert result.station.sido == "서울특별시"
    assert result.station.sigungu == "강서구"
    assert result.station.self_service is True
    assert result.station.opinet_id == "A0003461"


def test_canonicalize_observations():
    """휘발유 + 경유 가격 → 2개 observation."""
    raw = _make_raw()
    result = canonicalize_opinet(raw, observed_at=datetime(2025, 1, 15))

    assert len(result.price_observations) == 2
    kinds = {obs.fuel_kind for obs in result.price_observations}
    assert FuelKind.GASOLINE_REGULAR in kinds
    assert FuelKind.DIESEL in kinds


def test_canonicalize_prices_correct():
    raw = _make_raw()
    result = canonicalize_opinet(raw, observed_at=datetime(2025, 1, 15))

    gas_obs = next(o for o in result.price_observations if o.fuel_kind == FuelKind.GASOLINE_REGULAR)
    diesel_obs = next(o for o in result.price_observations if o.fuel_kind == FuelKind.DIESEL)
    assert gas_obs.price == 1598
    assert diesel_obs.price == 1448


def test_canonicalize_skips_dash_prices():
    """'-' 가격은 observation 생성 안 함."""
    raw = _make_raw(gasoline_premium="-", lpg=None)
    result = canonicalize_opinet(raw)
    kinds = {obs.fuel_kind for obs in result.price_observations}
    assert FuelKind.GASOLINE_PREMIUM not in kinds
    assert FuelKind.LPG not in kinds


def test_canonicalize_id_deterministic():
    """같은 brand+address → 같은 station.id."""
    raw1 = _make_raw()
    raw2 = _make_raw()
    r1 = canonicalize_opinet(raw1, observed_at=datetime(2025, 1, 15))
    r2 = canonicalize_opinet(raw2, observed_at=datetime(2025, 1, 16))  # 날짜 달라도
    assert r1.station.id == r2.station.id


def test_canonicalize_missing_name_returns_error():
    raw = _make_raw(name="")
    result = canonicalize_opinet(raw)
    assert result.error is not None
    assert result.station is None


def test_canonicalize_missing_address_returns_error():
    raw = _make_raw(address="")
    result = canonicalize_opinet(raw)
    assert result.error is not None


def test_canonicalize_station_id_matches_make_id():
    """station.id == FuelStation.make_id(brand, address)."""
    raw = _make_raw()
    result = canonicalize_opinet(raw)
    expected = FuelStation.make_id("알뜰주유소", "서울특별시 강서구 허준로 57")
    assert result.station.id == expected
