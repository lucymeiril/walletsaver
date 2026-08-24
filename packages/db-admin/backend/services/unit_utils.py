"""unit_utils.py — RD8 D3: 단위 분류 + 정규화 단가 계산 유틸리티."""
from __future__ import annotations

from typing import Literal, Optional, Tuple

from core.match_key import NO_BRAND_SENTINEL

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
    if not pack_unit:
        return "count"
    unit = pack_unit.strip()
    if unit in _WEIGHT:
        return "weight"
    if unit in _VOLUME:
        return "volume"
    if unit in _COUNT:
        return "count"
    if unit in _PACK:
        return "pack"
    return "count"


def normalize_unit_price(
    price: float,
    qty: Optional[float],
    unit: Optional[str],
    unit_kind: UnitKind,
) -> Tuple[Optional[float], Optional[str]]:
    if not qty or qty <= 0:
        return None, None

    if unit_kind == "weight":
        unit_str = (unit or "").strip()
        qty_in_g = qty * 1000 if unit_str.lower() == "kg" else qty
        return round(price / qty_in_g * 100, 4), "g"

    if unit_kind == "volume":
        unit_str = (unit or "").strip()
        qty_in_ml = qty * 1000 if unit_str.lower() == "l" else qty
        return round(price / qty_in_ml * 100, 4), "ml"

    return None, None


_WEIGHT_TO_G: dict[str, float] = {
    "kg": 1000.0,
    "mg": 0.001,
    "t": 1_000_000.0,
    "ton": 1_000_000.0,
}
_VOLUME_TO_ML: dict[str, float] = {
    "L": 1000.0,
    "l": 1000.0,
    "dl": 100.0,
    "cc": 1.0,
}


def canonicalize_pack(qty: float, unit: str) -> tuple[float, str]:
    """weight/volume 단위를 기본 단위(g/ml)로 표준화."""
    if not unit:
        return qty, unit

    value = unit.strip()
    if value in _WEIGHT_TO_G:
        return round(qty * _WEIGHT_TO_G[value], 6), "g"
    if value in _VOLUME_TO_ML:
        return round(qty * _VOLUME_TO_ML[value], 6), "ml"
    return qty, value


def build_display_name(
    brand: Optional[str],
    name_core: Optional[str],
    pack_qty: Optional[float],
    pack_unit: Optional[str],
) -> str:
    """UI 표시명 합성. Internal no-brand sentinels are never exposed."""
    visible_brand = None if brand == NO_BRAND_SENTINEL else brand

    if visible_brand and name_core and name_core.startswith(visible_brand):
        name_part = name_core
    elif visible_brand and name_core:
        name_part = f"{visible_brand} {name_core}"
    else:
        name_part = name_core or visible_brand or ""

    if pack_qty and pack_unit:
        qty_str = str(int(pack_qty)) if pack_qty == int(pack_qty) else str(pack_qty)
        return f"{name_part} {qty_str}{pack_unit}".strip()
    return name_part.strip()
