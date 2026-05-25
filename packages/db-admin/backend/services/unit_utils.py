"""unit_utils.py — RD8 D3: 단위 분류 + 정규화 단가 계산 유틸리티.

분류 정책 (schema_redesign.md §B-3 기준):
  weight : g, kg, mg, 근, ton
  volume : ml, L, l, cc, dl
  count  : 개, EA, 알, 마리, 미, 모, 두, 포기
  pack   : 봉, 개입, 세트, 팩, 캔, 병, 포, 매, 구, 입, 장, 구성, 단, 망, 롤,
           컵, 통, 박스, 줄, 판, 쌍, 켤레, 다스, T, P, 박
"""
from __future__ import annotations

from typing import Literal, Optional, Tuple

# ──────────────────────────────────────────────────────────────────────────────
# 단위 셋
# ──────────────────────────────────────────────────────────────────────────────

_WEIGHT: frozenset[str] = frozenset({"g", "kg", "mg", "근", "ton"})
_VOLUME: frozenset[str] = frozenset({"ml", "L", "l", "cc", "dl"})
_COUNT: frozenset[str] = frozenset({"개", "EA", "알", "마리", "미", "모", "두", "포기"})
_PACK: frozenset[str] = frozenset({
    "봉", "개입", "세트", "팩", "캔", "병", "포", "매", "구", "입",
    "장", "구성", "단", "망", "롤", "컵", "통", "박스", "줄", "판",
    "쌍", "켤레", "다스", "T", "P", "박",
})

UnitKind = Literal["weight", "volume", "count", "pack"]


def classify_unit_kind(pack_unit: Optional[str]) -> UnitKind:
    """pack_unit 문자열 → unit_kind 분류.

    Args:
        pack_unit: 단위 문자열. None이면 "count" 반환.

    Returns:
        "weight" | "volume" | "count" | "pack"

    Examples:
        >>> classify_unit_kind("g")
        'weight'
        >>> classify_unit_kind("ml")
        'volume'
        >>> classify_unit_kind("봉")
        'pack'
        >>> classify_unit_kind("개")
        'count'
    """
    if not pack_unit:
        return "count"
    u = pack_unit.strip()
    if u in _WEIGHT:
        return "weight"
    if u in _VOLUME:
        return "volume"
    if u in _COUNT:
        return "count"
    if u in _PACK:
        return "pack"
    return "count"  # 미분류 기본값


def normalize_unit_price(
    price: float,
    qty: Optional[float],
    unit: Optional[str],
    unit_kind: UnitKind,
) -> Tuple[Optional[float], Optional[str]]:
    """정규화 단가 계산.

    Args:
        price: 상품 가격 (원)
        qty: 용량/수량 숫자 (예: 120.0)
        unit: 단위 문자열 (예: "g", "ml", "kg", "L")
        unit_kind: classify_unit_kind() 결과

    Returns:
        (normalized_price, basis_unit)
        - weight → (원/100g, "g")
        - volume → (원/100ml, "ml")
        - count/pack → (None, None) — 환산 불가

    Examples:
        >>> normalize_unit_price(1200, 120, "g", "weight")
        (1000.0, 'g')
        >>> normalize_unit_price(2000, 500, "ml", "volume")
        (400.0, 'ml')
        >>> normalize_unit_price(3000, 3, "개", "count")
        (None, None)
    """
    if not qty or qty <= 0:
        return None, None

    if unit_kind == "weight":
        unit_str = (unit or "").strip()
        qty_in_g = qty * 1000 if unit_str.lower() == "kg" else qty
        normalized = round(price / qty_in_g * 100, 4)
        return normalized, "g"

    if unit_kind == "volume":
        unit_str = (unit or "").strip()
        qty_in_ml = qty * 1000 if unit_str.lower() == "l" else qty
        normalized = round(price / qty_in_ml * 100, 4)
        return normalized, "ml"

    return None, None


# ──────────────────────────────────────────────────────────────────────────────
# 단위 표준화 (canonicalize_pack)
# ──────────────────────────────────────────────────────────────────────────────

# weight → g 변환 계수 (g 자체는 factor=1 이므로 포함 불필요)
_WEIGHT_TO_G: dict[str, float] = {
    "kg": 1000.0,
    "mg": 0.001,
    "t": 1_000_000.0,
    "ton": 1_000_000.0,
}

# volume → ml 변환 계수 (ml 자체는 factor=1 이므로 포함 불필요)
_VOLUME_TO_ML: dict[str, float] = {
    "L": 1000.0,
    "l": 1000.0,
    "dl": 100.0,
    "cc": 1.0,
}


def canonicalize_pack(qty: float, unit: str) -> tuple[float, str]:
    """weight/volume 단위를 기본 단위(g/ml)로 표준화.

    - kg → g (×1000), mg → g (×0.001), t/ton → g (×1_000_000)
    - L/l → ml (×1000), dl → ml (×100), cc → ml (×1)
    - count/pack 단위(봉, 개 등)는 변환하지 않는다.

    부동소수점 정밀도: round(qty * factor, 6)으로 1.8 * 1000 = 1800.0 보장.

    Args:
        qty: 수량 숫자
        unit: 단위 문자열

    Returns:
        (canonicalized_qty, canonicalized_unit)

    Examples:
        >>> canonicalize_pack(1.8, "kg")
        (1800.0, 'g')
        >>> canonicalize_pack(1800.0, "g")
        (1800.0, 'g')
        >>> canonicalize_pack(1.0, "L")
        (1000.0, 'ml')
        >>> canonicalize_pack(5.0, "봉")
        (5.0, '봉')
        >>> canonicalize_pack(1.8, "kg") == canonicalize_pack(1800.0, "g")
        True
    """
    if not unit:
        return qty, unit

    u = unit.strip()

    if u in _WEIGHT_TO_G:
        factor = _WEIGHT_TO_G[u]
        return round(qty * factor, 6), "g"

    if u in _VOLUME_TO_ML:
        factor = _VOLUME_TO_ML[u]
        return round(qty * factor, 6), "ml"

    # g, ml, count/pack 단위는 그대로
    return qty, u


def build_display_name(
    brand: Optional[str],
    name_core: Optional[str],
    pack_qty: Optional[float],
    pack_unit: Optional[str],
) -> str:
    """UI 표시명 합성.

    brand가 name_core 첫 부분에 포함되면 중복 제거.
    예: brand="코카콜라", name_core="코카콜라 콜라" → "코카콜라 콜라 500ml"
    """
    if brand and name_core and name_core.startswith(brand):
        name_part = name_core
    elif brand and name_core:
        name_part = f"{brand} {name_core}"
    else:
        name_part = name_core or brand or ""

    if pack_qty and pack_unit:
        qty_str = str(int(pack_qty)) if pack_qty == int(pack_qty) else str(pack_qty)
        return f"{name_part} {qty_str}{pack_unit}".strip()
    return name_part.strip()
