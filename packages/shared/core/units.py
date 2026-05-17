"""WalletSavior: 마트별 단위 표기 표준화 라이브러리
=================================================
4사(이마트, 홈플러스, 롯데마트, 코스트코) + 쿠팡의 raw 단위 표기를
표준 enum + base_quantity float 으로 변환하는 순수 파서.

이 모듈은 DB/스키마 의존성 없이 단독으로 동작한다.
단위 모호 시 UNKNOWN 반환 + raw_text 보존. 추측으로 0이나 1을 채우지 않는다.

【팩 vs 개 구분 정책】
단위 파서는 raw kind 를 보존한다:
  "1팩" → PACK,  "1개" → EACH,  "1봉" → BUNDLE
카테고리에 따라 이들을 동일하게 취급할지는 to_standard_basis() 가 담당한다.
예: 라면 카테고리 category_default=BUNDLE 이면 PACK/EACH 도 BUNDLE 로 재매핑 가능.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class UnitKind(Enum):
    GRAM = "gram"
    KILOGRAM = "kilogram"
    MILLILITER = "milliliter"
    LITER = "liter"
    EACH = "each"
    PACK = "pack"
    ROLL = "roll"
    SHEET = "sheet"
    METER = "meter"
    PIECE = "piece"
    BUNDLE = "bundle"
    UNKNOWN = "unknown"


@dataclass
class NormalizedUnit:
    """정규화된 단위 정보."""
    kind: UnitKind
    quantity: float
    basis: str      # 비교 기준 표기, 예: "per_100g", "per_each", "per_10m"
    raw_text: str   # 원본 문자열 (추적/디버깅용)


# ─────────────────────────────────────────────────────────────────────────────
# 한국어 단위어 사전 (모듈 상수로 노출)
# 소문자/원문 키 → UnitKind 매핑
# 중요: 팩/봉 은 PACK/BUNDLE 로 별도 처리 (카테고리에 따라 per_each 와 달리 취급 가능)
# ─────────────────────────────────────────────────────────────────────────────
KOREAN_UNIT_MAP: dict[str, UnitKind] = {
    # 무게
    "g": UnitKind.GRAM,
    "그램": UnitKind.GRAM,
    "kg": UnitKind.KILOGRAM,
    "킬로": UnitKind.KILOGRAM,
    "킬로그램": UnitKind.KILOGRAM,
    # 부피
    "ml": UnitKind.MILLILITER,
    "mL": UnitKind.MILLILITER,
    "㎖": UnitKind.MILLILITER,
    "밀리": UnitKind.MILLILITER,
    "밀리리터": UnitKind.MILLILITER,
    "l": UnitKind.LITER,
    "L": UnitKind.LITER,
    "리터": UnitKind.LITER,
    # 낱장
    "매": UnitKind.SHEET,
    "장": UnitKind.SHEET,
    # 롤
    "롤": UnitKind.ROLL,
    # 거리
    "m": UnitKind.METER,
    "미터": UnitKind.METER,
    # 포장 단위 (카테고리에 따라 달리 표준화됨 — to_standard_basis 담당)
    "팩": UnitKind.PACK,
    "봉": UnitKind.BUNDLE,
    "봉지": UnitKind.BUNDLE,
    # 낱개
    "개": UnitKind.EACH,
    "입": UnitKind.PIECE,
    "병": UnitKind.EACH,
    "캔": UnitKind.EACH,
    "포기": UnitKind.EACH,
    "단": UnitKind.EACH,
    "마리": UnitKind.EACH,
    "구": UnitKind.EACH,
    "통": UnitKind.EACH,
}

# 홈플러스 API unitMeasure 필드 → UnitKind (대문자 코드로 전달됨)
_HOMEPLUS_MEASURE_MAP: dict[str, UnitKind] = {
    "G": UnitKind.GRAM,
    "KG": UnitKind.KILOGRAM,
    "ML": UnitKind.MILLILITER,
    "L": UnitKind.LITER,
    # 한글 코드도 혼용됨 (실측 fixture 확인)
    "매": UnitKind.SHEET,
    "개": UnitKind.EACH,
    "입": UnitKind.PIECE,
    "팩": UnitKind.PACK,
    "봉": UnitKind.BUNDLE,
}

# 코스트코 "한 개당" 패턴의 한국어 수사 → 숫자
_KOREAN_NUMBER_WORDS: dict[str, float] = {
    "한": 1.0,
    "두": 2.0,
    "세": 3.0,
    "네": 4.0,
    "다섯": 5.0,
    "여섯": 6.0,
    "일곱": 7.0,
    "여덟": 8.0,
    "아홉": 9.0,
    "열": 10.0,
}

# UnitKind → basis 단위 접미사 (EACH 는 별도 처리)
_KIND_BASIS_SUFFIX: dict[UnitKind, str] = {
    UnitKind.GRAM: "g",
    UnitKind.KILOGRAM: "kg",
    UnitKind.MILLILITER: "ml",
    UnitKind.LITER: "l",
    UnitKind.SHEET: "매",
    UnitKind.ROLL: "롤",
    UnitKind.PACK: "팩",
    UnitKind.BUNDLE: "봉",
    UnitKind.METER: "m",
    UnitKind.PIECE: "입",
}

# 카테고리별 표준 기준 수량 (to_standard_basis 에서 사용)
_CATEGORY_STD_BASIS_QTY: dict[UnitKind, float] = {
    UnitKind.GRAM: 100.0,        # 육류: 100g 당
    UnitKind.KILOGRAM: 1.0,      # 쌀 등: 1kg 당
    UnitKind.MILLILITER: 100.0,  # 음료: 100ml 당
    UnitKind.LITER: 1.0,         # 생수: 1L 당
    UnitKind.EACH: 1.0,          # 계란/생선: 1개 당
    UnitKind.SHEET: 1.0,         # 키친타월: 1매 당
    UnitKind.ROLL: 1.0,
    UnitKind.PACK: 1.0,
    UnitKind.BUNDLE: 1.0,        # 라면: 1봉 당
    UnitKind.METER: 10.0,        # 화장지: 10m 당 (코스트코 실측)
    UnitKind.PIECE: 1.0,
}


# ─────────────────────────────────────────────────────────────────────────────
# 내부 헬퍼
# ─────────────────────────────────────────────────────────────────────────────

def _make_basis(kind: UnitKind, basis_qty: float) -> str:
    """basis 문자열 생성.
    EACH 는 항상 'per_each', 나머지는 'per_{qty}{suffix}'.
    """
    if kind == UnitKind.EACH:
        return "per_each"
    suffix = _KIND_BASIS_SUFFIX.get(kind)
    if suffix is None:
        return "per_unknown"
    qty_int: int | float = int(basis_qty) if basis_qty == int(basis_qty) else basis_qty
    return f"per_{qty_int}{suffix}"


def _basis_qty(basis: str) -> float:
    """basis 문자열에서 참조 수량 추출.
    'per_100g' → 100.0,  'per_each' → 1.0,  'per_10m' → 10.0.
    """
    if basis in ("per_each", "per_unknown", "unknown"):
        return 1.0
    m = re.match(r"per_(\d+(?:\.\d+)?)", basis)
    if m:
        return float(m.group(1))
    return 1.0


def _lookup_unit(raw: str) -> UnitKind:
    """KOREAN_UNIT_MAP 에서 단위 문자열을 찾는다. 대소문자 변형 포함."""
    # 원문 그대로
    if raw in KOREAN_UNIT_MAP:
        return KOREAN_UNIT_MAP[raw]
    # 소문자 비교 (g/G, kg/KG, ml/ML 등)
    lower = raw.lower()
    for k, v in KOREAN_UNIT_MAP.items():
        if k.lower() == lower:
            return v
    return UnitKind.UNKNOWN


# ─────────────────────────────────────────────────────────────────────────────
# 마트별 파서
# ─────────────────────────────────────────────────────────────────────────────

def parse_emart_capacity(text: str | None) -> NormalizedUnit | None:
    """이마트 sellUnitCapacity 문자열 파싱.

    None → None (필드 자체가 없음, 상품에 단위 정보 미존재).
    빈 문자열 → UNKNOWN (값은 있지만 파싱 불가).
    음수 → UNKNOWN (물리적으로 의미 없음).

    예::

        parse_emart_capacity("100g")  → (GRAM, 100.0, "per_100g")
        parse_emart_capacity("1개")   → (EACH, 1.0,   "per_each")
        parse_emart_capacity("1kg")   → (KILOGRAM, 1.0, "per_1kg")
        parse_emart_capacity(None)    → None
        parse_emart_capacity("")      → NormalizedUnit(UNKNOWN, ...)
    """
    if text is None:
        return None

    text_stripped = text.strip()
    if not text_stripped:
        return NormalizedUnit(kind=UnitKind.UNKNOWN, quantity=0.0, basis="unknown", raw_text="")

    # noise 문자 제거(≒, ~, 약, 공백 등)
    cleaned = re.sub(r"[≒~약\s]+", "", text_stripped)

    # 숫자 + 단위 패턴: "100g", "1개", "1.5kg", "1봉"
    m = re.match(r"^(\d+(?:\.\d+)?)\s*([가-힣a-zA-Z㎖]+)$", cleaned)
    if m:
        qty = float(m.group(1))
        if qty < 0:
            return NormalizedUnit(kind=UnitKind.UNKNOWN, quantity=qty, basis="unknown", raw_text=text)
        unit_str = m.group(2)
        kind = _lookup_unit(unit_str)
        if kind == UnitKind.UNKNOWN:
            return NormalizedUnit(kind=UnitKind.UNKNOWN, quantity=qty, basis="unknown", raw_text=text)
        return NormalizedUnit(kind=kind, quantity=qty, basis=_make_basis(kind, qty), raw_text=text)

    return NormalizedUnit(kind=UnitKind.UNKNOWN, quantity=0.0, basis="unknown", raw_text=text)


def parse_homeplus_unit(measure: str, qty: float, total_qty: float) -> NormalizedUnit:
    """홈플러스 API의 unitMeasure / unitQty / totalUnitQty 세 필드 파싱.

    Args:
        measure:   unitMeasure — "G", "ML", "매", "개" 등
        qty:       unitQty     — 비교 기준 수량 (예: 100g 비교면 100)
        total_qty: totalUnitQty — 상품 총량 (예: 800g 패키지면 800)

    홈플러스는 unitMeasure 를 대문자 코드("G", "ML")와 한글("매", "개")로 혼용한다.
    먼저 _HOMEPLUS_MEASURE_MAP, 없으면 KOREAN_UNIT_MAP fallback.

    unitQty 가 0 또는 None 이면 basis_qty=1 로 처리 (unitDispYn="N" 상품 안전 처리).
    """
    measure_stripped = (measure or "").strip()
    kind = _HOMEPLUS_MEASURE_MAP.get(measure_stripped)
    if kind is None:
        kind = _lookup_unit(measure_stripped)

    # unitQty=None 또는 0 일 때: 단위가격 표시 비활성 상품이므로 basis=1로 안전 처리
    safe_qty = float(qty) if qty else 1.0

    raw_text = f"{measure}/{qty}/{total_qty}"
    return NormalizedUnit(kind=kind, quantity=float(total_qty), basis=_make_basis(kind, safe_qty), raw_text=raw_text)


def parse_lottemart_unit_label(label: str, amount: int) -> NormalizedUnit:
    """롯데마트 Zetta API price.unit.label 파싱.

    "fop.price.per.*" prefix 를 제거하는 이유:
    롯데마트 API 는 FOP(Front Of Pack) 가격 표시 규격 레이블을 사용한다.
    비교 로직은 순수 단위/수량 정보만 필요하므로 prefix 를 제거한 suffix 만 파싱.

    Args:
        label:  price.unit.label — "fop.price.per.100gram", "fop.price.per.each" 등
        amount: price.unit.current.amount — 단위당 현재가 (원), NormalizedUnit 에는 미저장

    알 수 없는 레이블은 UNKNOWN 반환 + raw_text 보존.
    """
    _FOP_PREFIX = "fop.price.per."
    suffix = label.removeprefix(_FOP_PREFIX) if label.startswith(_FOP_PREFIX) else label

    _LABEL_MAP: dict[str, NormalizedUnit] = {
        "100gram": NormalizedUnit(kind=UnitKind.GRAM, quantity=100.0, basis="per_100g", raw_text=label),
        "each":    NormalizedUnit(kind=UnitKind.EACH, quantity=1.0,   basis="per_each",  raw_text=label),
        "1kg":     NormalizedUnit(kind=UnitKind.KILOGRAM, quantity=1.0, basis="per_1kg", raw_text=label),
        "100ml":   NormalizedUnit(kind=UnitKind.MILLILITER, quantity=100.0, basis="per_100ml", raw_text=label),
        "10meter": NormalizedUnit(kind=UnitKind.METER, quantity=10.0, basis="per_10m",  raw_text=label),
    }
    if suffix in _LABEL_MAP:
        return _LABEL_MAP[suffix]

    # 알 수 없는 레이블 → UNKNOWN 보존
    return NormalizedUnit(kind=UnitKind.UNKNOWN, quantity=float(amount), basis="unknown", raw_text=label)


def parse_costco_unit_text(text: str) -> NormalizedUnit:
    """코스트코 단위가격 문자열 파싱.

    코스트코는 단위와 가격이 한 문장에 섞인 한글 서술 형식을 사용::

        "100㎖당 3,099원"  → MILLILITER, quantity=100, basis="per_100ml"
        "한 개당 318원"    → EACH,        quantity=1,   basis="per_each"
        "10미터당 162원"   → METER,       quantity=10,  basis="per_10m"

    한국어 수사(한/두/세...)와 아라비아 숫자를 모두 처리.
    가격 추출은 부가 정보로만 사용하며 NormalizedUnit 에 저장하지 않음
    (basis 문자열에 충분한 비교 정보가 있다).

    단위가 없거나 파싱 불가시 UNKNOWN 반환.
    """
    text_clean = (text or "").strip()
    if not text_clean:
        return NormalizedUnit(kind=UnitKind.UNKNOWN, quantity=0.0, basis="unknown", raw_text=text or "")

    # 한국어 수사를 아라비아 숫자로 치환 (긴 단어 먼저)
    unit_part = text_clean
    for word in sorted(_KOREAN_NUMBER_WORDS, key=len, reverse=True):
        num = _KOREAN_NUMBER_WORDS[word]
        unit_part = unit_part.replace(word + " ", str(int(num)) + " ")

    # 패턴: (숫자) + (단위어) + 당 + [선택: 가격]
    # "100㎖당", "1 개당", "10미터당"
    m = re.search(
        r"(\d+(?:\.\d+)?)\s*([가-힣a-zA-Z㎖]+)\s*당",
        unit_part,
    )
    if not m:
        return NormalizedUnit(kind=UnitKind.UNKNOWN, quantity=0.0, basis="unknown", raw_text=text)

    qty = float(m.group(1))
    unit_str = m.group(2).strip()
    kind = _lookup_unit(unit_str)

    if kind == UnitKind.UNKNOWN:
        return NormalizedUnit(kind=UnitKind.UNKNOWN, quantity=qty, basis="unknown", raw_text=text)

    return NormalizedUnit(kind=kind, quantity=qty, basis=_make_basis(kind, qty), raw_text=text)


def parse_generic_korean(text: str) -> NormalizedUnit:
    """쿠팡/커뮤니티/algumon 등 다양한 소스의 fallback 파서.

    fallback 파서를 별도로 두는 이유:
    각 마트 파서는 해당 API 의 특정 필드 구조를 기대하지만,
    쿠팡 등은 동적 라벨로 다양한 자유 형식 문자열이 오므로
    순서대로 여러 패턴을 시도하는 범용 파서가 필요하다.

    시도 순서:
    1. 코스트코 스타일 "N당" 패턴
    2. 이마트 스타일 "숫자+단위" 패턴
    3. 모두 실패 시 UNKNOWN
    """
    text_clean = (text or "").strip()
    if not text_clean:
        return NormalizedUnit(kind=UnitKind.UNKNOWN, quantity=0.0, basis="unknown", raw_text=text or "")

    # 1차: "N당" 코스트코 스타일
    costco_result = parse_costco_unit_text(text_clean)
    if costco_result.kind != UnitKind.UNKNOWN:
        return costco_result

    # 2차: 이마트 capacity 스타일
    emart_result = parse_emart_capacity(text_clean)
    if emart_result is not None and emart_result.kind != UnitKind.UNKNOWN:
        return emart_result

    return NormalizedUnit(kind=UnitKind.UNKNOWN, quantity=0.0, basis="unknown", raw_text=text)


# ─────────────────────────────────────────────────────────────────────────────
# 표준화 / 단위가격 계산
# ─────────────────────────────────────────────────────────────────────────────

def to_standard_basis(unit: NormalizedUnit, category_default: UnitKind) -> NormalizedUnit:
    """카테고리 기본 단위로 변환.

    예:
        양배추 EACH/1 + category_default=EACH    → EACH/1,    "per_each"
        소고기 GRAM/800 + category_default=GRAM  → GRAM/800,  "per_100g"
        쌀     KILOGRAM/1.5 + category_default=GRAM → GRAM/1500, "per_100g"

    단위 변환 규칙:
    - KILOGRAM → GRAM (카테고리 GRAM 일 때): 1kg = 1000g
    - LITER    → MILLILITER (카테고리 MILLILITER 일 때): 1L = 1000ml
    나머지 변환은 아직 미구현 (모호한 경우 raw kind 유지).
    """
    result_kind = unit.kind
    result_qty = unit.quantity

    # KILOGRAM → GRAM 변환 (카테고리가 GRAM 기준일 때)
    if category_default == UnitKind.GRAM and unit.kind == UnitKind.KILOGRAM:
        result_kind = UnitKind.GRAM
        result_qty = unit.quantity * 1000.0

    # LITER → MILLILITER 변환 (카테고리가 MILLILITER 기준일 때)
    elif category_default == UnitKind.MILLILITER and unit.kind == UnitKind.LITER:
        result_kind = UnitKind.MILLILITER
        result_qty = unit.quantity * 1000.0

    std_basis_qty = _CATEGORY_STD_BASIS_QTY.get(category_default, 1.0)
    # 변환된 kind 또는 카테고리 kind 기준으로 basis 생성
    effective_kind = result_kind if result_kind != UnitKind.UNKNOWN else category_default
    new_basis = _make_basis(effective_kind, std_basis_qty)

    return NormalizedUnit(kind=result_kind, quantity=result_qty, basis=new_basis, raw_text=unit.raw_text)


def unit_price(total_price: int, unit: NormalizedUnit) -> float:
    """상품 총 가격을 기준 단위당 가격으로 환산.

    공식: total_price * basis_qty / unit.quantity

    예::

        unit_price(9980, NormalizedUnit(GRAM, 800, "per_100g", ...))
            → 9980 * 100 / 800 = 1247.5

        unit_price(30000, NormalizedUnit(EACH, 1, "per_each", ...))
            → 30000 * 1 / 1 = 30000.0

    Raises:
        ValueError: unit.quantity 가 0 이하인 경우 (물리적으로 불가)
    """
    if unit.quantity <= 0:
        raise ValueError(f"unit.quantity must be positive, got {unit.quantity}")
    basis = _basis_qty(unit.basis)
    return total_price * basis / unit.quantity
