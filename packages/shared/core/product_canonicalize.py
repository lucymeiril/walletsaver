"""
WalletSavior Phase B4 — 마트 raw item → CanonicalProduct 정규화기.

역할:
    4사(이마트·홈플러스·롯데마트·코스트코) raw 수집 데이터를 받아
    (a) 결정적(deterministic) 규칙으로 같은 상품이면 같은 canonical_id 부여,
    (b) 모호하거나 카테고리 불명인 경우 ProductReviewQueue 항목 생성.

설계 원칙:
    - B1/B2/B3 모듈을 import해 사용. 재구현 금지.
    - AI/fuzzy 라이브러리 의존 없음 — deterministic rule only (Phase C에서 통합).
    - canonical과 queue 항목은 양립 가능 (이마트 카테고리 없음 케이스).
    - 같은 raw를 두 번 통과하면 같은 canonical_id (멱등성).

단위 정책:
    - "N unit1 × M unit2" 에서 unit2가 count(입/개)이면 N*M unit1.
    - "N1 unit1 × N2 unit2 × N3" 에서 unit1=METER, unit2=ROLL이면 N2*N3 ROLL.
    - 그 외 이중 곱셈은 N1*N2 unit1 (첫 번째 단위 우선).

메가롤 정책 결정 (워크로그 요약):
    "40m x 30롤 x 2" → qty=60(30×2), unit=ROLL.
    이유: 소비자는 "몇 롤"로 화장지를 비교. 40m는 롤당 길이(속성).
    단위가 비교는 per-meter 기준이지만 canonical SKU 단위는 ROLL이 직관적.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml

from .canonical_models import (
    CanonicalProduct,
    MartKind,
    MartSkuAlias,
    PriceObservation,
    ProductReviewQueue,
    ReviewReason,
    UnitPriceBasis,
)
from .category_mapper import (
    REASON_EMART_NO_CATEGORY,
    map_costco,
    map_emart,
    map_homeplus,
    map_lottemart,
)
from .units import (
    KOREAN_UNIT_MAP,
    NormalizedUnit,
    UnitKind,
    _lookup_unit,
    unit_price,
)

# ─────────────────────────────────────────────────────────────────────────────
# 상수 / 로딩
# ─────────────────────────────────────────────────────────────────────────────

_DATA_DIR = Path(__file__).parent.parent / "data"
_BRAND_DICT_FILE = _DATA_DIR / "brand_dictionary.yaml"


@lru_cache(maxsize=1)
def _load_brands() -> list[str]:
    """brand_dictionary.yaml 로드 (길이 역순 — 긴 브랜드 먼저 매칭)."""
    with open(_BRAND_DICT_FILE, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    brands = raw.get("brands", [])
    return sorted(brands, key=len, reverse=True)


# 정규식에 없는 추가 단위어 (B2 units.py 를 수정하지 않고 로컬 확장)
# 주의: "인분" (인분 = serving portion)은 제외 — 용량(GRAM/KG) 보다 우선하면 안 됨
_EXTRA_UNIT_MAP: dict[str, UnitKind] = {
    "정": UnitKind.PIECE,    # 정 = tablet/pill
    "ct": UnitKind.PIECE,    # ct = count (영문)
}

# 대괄호 프로모션 헤드태그 패턴: "[냉장]", "[농할 20%쿠폰 상세 다운]", "[농할할인가 6,990원]"
_PROMO_BRACKET_RE = re.compile(r"^\s*\[[^\]]*\]\s*")

# 꼬리 포장어 (standalone word, 공백 또는 괄호 앞)
# "개" 포함: "(개)" 단독 괄호는 포장 단위 지시어이므로 fallback 처리
_TAIL_WORDS = frozenset(["통", "박스", "팩", "봉", "묶음", "포장", "행사", "세트", "set", "개"])

# 꼬리 포장어 패턴 (공백+단어 또는 괄호 단어만)
_TAIL_WORD_RE = re.compile(
    r"\s+(" + "|".join(_TAIL_WORDS) + r")\s*$",
    re.IGNORECASE,
)

# 숫자+단위 패턴 (공백 허용)
_QTY_UNIT_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*([가-힣a-zA-Z㎖]+)"
)

# 괄호 내부 qty 패턴 — 끝에 붙은 "(340G)", "(30입)", "(1.8KG)", "(봉)", "(EA)"
_PAREN_END_RE = re.compile(r"\s*\(([^)]+)\)\s*$")

# 이중/삼중 곱셈 패턴
_TRIPLE_MULT_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*([가-힣a-zA-Z㎖]+)\s*[x×]\s*(\d+(?:\.\d+)?)\s*([가-힣a-zA-Z㎖]+)\s*[x×]\s*(\d+(?:\.\d+)?)"
)
_DOUBLE_MULT_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*([가-힣a-zA-Z㎖]+)\s*[*×x]\s*(\d+(?:\.\d+)?)\s*([가-힣a-zA-Z㎖]*)"
)
# 단일 인라인 qty — 단어 경계 고려
_INLINE_QTY_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*([가-힣a-zA-Z㎖]+)"
)


# ─────────────────────────────────────────────────────────────────────────────
# CanonicalizationResult
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CanonicalizationResult:
    """단일 raw item 정규화 결과."""
    canonical: Optional[CanonicalProduct]      # 성공 시 채워짐
    sku_alias: Optional[MartSkuAlias]          # 성공 시 채워짐
    price_obs: Optional[PriceObservation]      # 성공 시 채워짐
    queue_entry: Optional[ProductReviewQueue]  # 모호 시 채워짐 (canonical과 양립 가능)
    confidence: float                          # 0.0~1.0
    reasons: list[str] = field(default_factory=list)  # 매칭/모호 이유 코드


# ─────────────────────────────────────────────────────────────────────────────
# 이름 파싱 헬퍼
# ─────────────────────────────────────────────────────────────────────────────

def strip_promo_brackets(name: str) -> str:
    """앞의 [...] 프로모션 괄호 제거."""
    return _PROMO_BRACKET_RE.sub("", name).strip()


def extract_pack_tail(name: str) -> str:
    """끝의 포장 꼬리어(통, 박스, 팩, 봉, 행사 등) 제거."""
    return _TAIL_WORD_RE.sub("", name).strip()


def _lookup_extended(raw: str) -> UnitKind:
    """B2 KOREAN_UNIT_MAP + 로컬 확장 테이블에서 단위 조회."""
    kind = _lookup_unit(raw)
    if kind != UnitKind.UNKNOWN:
        return kind
    lower = raw.lower().strip()
    for k, v in _EXTRA_UNIT_MAP.items():
        if k.lower() == lower:
            return v
    return UnitKind.UNKNOWN


def _resolve_double_multiply(
    qty1: float, kind1: UnitKind,
    qty2: float, kind2: UnitKind,
) -> tuple[float, UnitKind]:
    """
    N unit1 × M unit2 → 총량과 기준 단위 결정.

    규칙:
      - unit2 == PIECE/EACH → count 배수: qty1*qty2 unit1
      - unit1 == METER and unit2 == ROLL → roll count만 반환: qty2 ROLL
      - 그 외 → qty1*qty2 unit1
    """
    if kind2 in (UnitKind.PIECE, UnitKind.EACH):
        return qty1 * qty2, kind1
    if kind1 == UnitKind.METER and kind2 == UnitKind.ROLL:
        return qty2, UnitKind.ROLL
    # 기본: 첫 단위 기준으로 곱셈
    return qty1 * qty2, kind1


def _try_parse_qty_from_text(text: str) -> tuple[float, UnitKind] | None:
    """
    문자열에서 qty+unit 쌍 추출 시도.
    성공: (qty, UnitKind) / 실패: None
    """
    # 삼중 곱셈: "40m x 30롤 x 2"
    m = _TRIPLE_MULT_RE.search(text)
    if m:
        q1, u1s, q2, u2s, q3 = float(m.group(1)), m.group(2), float(m.group(3)), m.group(4), float(m.group(5))
        k1, k2 = _lookup_extended(u1s), _lookup_extended(u2s)
        inner_qty, inner_kind = _resolve_double_multiply(q1, k1, q2, k2)
        if inner_kind != UnitKind.UNKNOWN:
            return inner_qty * q3, inner_kind
        # fallback: q2*q3 with k2
        if k2 != UnitKind.UNKNOWN:
            return q2 * q3, k2

    # 이중 곱셈: "150매*6롤", "500ml x 2입"
    m = _DOUBLE_MULT_RE.search(text)
    if m:
        q1, u1s, q2, u2s = float(m.group(1)), m.group(2), float(m.group(3)), m.group(4).strip()
        k1, k2 = _lookup_extended(u1s), _lookup_extended(u2s if u2s else u1s)
        if k1 != UnitKind.UNKNOWN:
            result_qty, result_kind = _resolve_double_multiply(q1, k1, q2, k2)
            if result_kind != UnitKind.UNKNOWN:
                return result_qty, result_kind

    # 단일 qty+unit
    for m in _QTY_UNIT_RE.finditer(text):
        qty = float(m.group(1))
        kind = _lookup_extended(m.group(2))
        if kind != UnitKind.UNKNOWN and qty > 0:
            return qty, kind

    return None


def extract_quantity_token(name: str) -> tuple[float, UnitKind, str]:
    """
    이름 문자열에서 용량/수량 추출.

    우선순위:
      1) 삼중·이중 곱셈 패턴 (인라인)
      2) 끝의 괄호 qty — 복수 괄호 시 PIECE 우선 (EACH는 우선하지 않음)
      3) 인라인 qty+unit
      4) 포장어 단독 괄호 fallback — (봉), (개), (통) 등
      5) 모두 실패 → (1.0, UNKNOWN, name)

    반환: (qty, unit_kind, cleaned_name)
    """
    # 1. 곱셈 패턴 (삼중·이중) — 먼저 시도
    triple_m = _TRIPLE_MULT_RE.search(name)
    if triple_m:
        q1, u1s, q2, u2s, q3 = (
            float(triple_m.group(1)), triple_m.group(2),
            float(triple_m.group(3)), triple_m.group(4),
            float(triple_m.group(5)),
        )
        k1, k2 = _lookup_extended(u1s), _lookup_extended(u2s)
        inner_qty, inner_kind = _resolve_double_multiply(q1, k1, q2, k2)
        if inner_kind != UnitKind.UNKNOWN:
            result_qty = inner_qty * q3
            cleaned = name[:triple_m.start()].rstrip(" \t-") + name[triple_m.end():].lstrip(" \t-")
            return result_qty, inner_kind, cleaned.strip()
        if k2 != UnitKind.UNKNOWN:
            result_qty = q2 * q3
            cleaned = name[:triple_m.start()].rstrip() + name[triple_m.end():].lstrip()
            return result_qty, k2, cleaned.strip()

    double_m = _DOUBLE_MULT_RE.search(name)
    if double_m:
        q1, u1s = float(double_m.group(1)), double_m.group(2)
        q2, u2s = float(double_m.group(3)), double_m.group(4).strip()
        k1 = _lookup_extended(u1s)
        k2 = _lookup_extended(u2s) if u2s else k1
        if k1 != UnitKind.UNKNOWN:
            result_qty, result_kind = _resolve_double_multiply(q1, k1, q2, k2)
            if result_kind != UnitKind.UNKNOWN:
                cleaned = name[:double_m.start()].rstrip() + name[double_m.end():].lstrip()
                return result_qty, result_kind, cleaned.strip()

    # 2. 끝 괄호에서 qty 추출 — 복수 괄호 반복
    # paren_results_raw: qty+unit 쌍 (처리 순서 = 가장 안쪽 괄호 먼저)
    # tail_fallback: 포장어 단독 괄호의 unit (숫자 없는 경우) — 최저 우선순위
    working = name
    paren_results_raw: list[tuple[float, UnitKind]] = []
    tail_fallback_unit: Optional[UnitKind] = None

    while True:
        pm = _PAREN_END_RE.search(working)
        if not pm:
            break
        content = pm.group(1).strip()
        paren_result = _try_parse_qty_from_paren_content(content)
        if paren_result is not None:
            paren_results_raw.append(paren_result)
        elif content.upper() in ("EA",):
            paren_results_raw.append((1.0, UnitKind.EACH))
        elif content in _TAIL_WORDS:
            # 숫자 없는 포장어 → fallback (우선순위 최저)
            tail_unit = _lookup_extended(content)
            if tail_unit != UnitKind.UNKNOWN and tail_fallback_unit is None:
                tail_fallback_unit = tail_unit
        # 어떤 경우든 괄호 제거 후 계속
        working = working[:pm.start()].strip()

    # 모든 괄호 제거 후 남은 이름이 최종 cleaned base
    final_cleaned = working

    if paren_results_raw:
        # PIECE 우선 (EACH는 우선하지 않음 — "인분" 같은 서빙 단위가 GRAM 보다 높아지지 않도록)
        for qty_r, unit_r in paren_results_raw:
            if unit_r == UnitKind.PIECE:
                return qty_r, unit_r, final_cleaned
        # PIECE 없으면 첫 번째 결과 (= 가장 안쪽 괄호)
        return paren_results_raw[0][0], paren_results_raw[0][1], final_cleaned

    # 3. 인라인 qty+unit — paren 제거된 이름에서 스캔 (원본 이름의 포장어 괄호가 오염 방지)
    best: tuple[float, UnitKind, str] | None = None
    for m in _QTY_UNIT_RE.finditer(final_cleaned):
        qty = float(m.group(1))
        kind = _lookup_extended(m.group(2))
        if kind != UnitKind.UNKNOWN and qty > 0:
            cleaned = (final_cleaned[:m.start()].rstrip() + " " + final_cleaned[m.end():].lstrip()).strip()
            best = (qty, kind, cleaned)
    if best is not None:
        return best

    # 4. 포장어 단독 괄호 fallback — (봉), (개), (통) 등
    if tail_fallback_unit is not None:
        return 1.0, tail_fallback_unit, final_cleaned

    return 1.0, UnitKind.UNKNOWN, name


def _try_parse_qty_from_paren_content(content: str) -> tuple[float, UnitKind] | None:
    """
    괄호 내부 문자열에서 qty+unit 추출.
    "(340G)" → (340, GRAM)
    "(특란, 30입)" → 콤마 구분 후 각 토큰 시도
    "(1.0kg내외/20마리)" → / 구분 후 각 토큰 시도, EACH 우선
    """
    # 슬래시·콤마 분리 후 각 후보에서 qty 추출
    separators = re.split(r"[/,]", content)
    candidates: list[tuple[float, UnitKind]] = []
    for seg in separators:
        seg = seg.strip()
        # 단일 qty+unit 매칭
        for m in _INLINE_QTY_RE.finditer(seg):
            qty = float(m.group(1))
            kind = _lookup_extended(m.group(2))
            if kind != UnitKind.UNKNOWN and qty > 0:
                candidates.append((qty, kind))
    if not candidates:
        return None
    # PIECE 우선 (EACH는 우선하지 않음)
    for c in candidates:
        if c[1] == UnitKind.PIECE:
            return c
    return candidates[0]


def extract_brand_token(name: str) -> tuple[Optional[str], str]:
    """
    브랜드 사전에서 이름 앞의 브랜드 토큰 추출.
    반환: (brand_or_None, name_without_brand)
    """
    brands = _load_brands()
    for brand in brands:
        if name.startswith(brand + " ") or name == brand:
            remaining = name[len(brand):].strip()
            return brand, remaining
    return None, name


@dataclass
class _ParsedName:
    brand: Optional[str]
    name_core: str
    pack_quantity: float
    pack_unit: UnitKind


def parse_product_name(
    raw_name: str,
    api_qty: Optional[float] = None,
    api_unit: Optional[UnitKind] = None,
) -> _ParsedName:
    """
    마트 raw 상품명에서 (brand, name_core, pack_quantity, pack_unit) 추출.

    api_qty / api_unit: 마트 API가 용량을 별도 필드로 제공하는 경우 힌트로 사용.
    이름 파싱에 성공하면 이름 파싱 결과 우선. API 힌트는 fallback.
    """
    # 1. 프로모션 괄호 제거
    name = strip_promo_brackets(raw_name)
    # 2. 브랜드 추출
    brand, after_brand = extract_brand_token(name)
    # 3. 용량 추출 (곱셈 → 끝 괄호 → 인라인 순)
    qty, unit, after_qty = extract_quantity_token(after_brand)
    # 4. API 힌트로 보강 — 이름 파싱 실패 시만
    if unit == UnitKind.UNKNOWN and api_qty is not None and api_unit is not None:
        qty, unit = api_qty, api_unit
    # 5. 꼬리 정리
    name_core = extract_pack_tail(after_qty).strip()
    # 6. 나머지 괄호/공백 정리
    name_core = re.sub(r"\s{2,}", " ", name_core)
    name_core = name_core.strip(" ()")

    return _ParsedName(
        brand=brand,
        name_core=name_core,
        pack_quantity=qty,
        pack_unit=unit,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 공개 API — canonical key
# ─────────────────────────────────────────────────────────────────────────────

def derive_canonical_key(
    brand: Optional[str],
    name_core: str,
    pack_quantity: float,
    pack_unit: UnitKind,
) -> str:
    """
    결정적 canonical_id 생성.
    CanonicalProduct.make_id를 그대로 사용 (중복 구현 금지).
    pack_unit 은 UnitKind enum → .value 로 변환해서 전달.
    """
    return CanonicalProduct.make_id(brand, name_core, pack_quantity, pack_unit.value)


# ─────────────────────────────────────────────────────────────────────────────
# 내부 헬퍼
# ─────────────────────────────────────────────────────────────────────────────

def _payload_hash(raw: dict) -> str:
    return hashlib.sha1(
        json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def _alias_id(mart: str, mart_item_id: str) -> str:
    return hashlib.sha1(f"{mart}|{mart_item_id}".encode()).hexdigest()


def _price_obs_id(canonical_id: str, mart: str, observed_at: datetime) -> str:
    return hashlib.sha1(
        f"{canonical_id}|{mart}|{observed_at.isoformat()}".encode()
    ).hexdigest()


def _queue_id(mart: str, mart_item_id: str, reason: str) -> str:
    return hashlib.sha1(f"{mart}|{mart_item_id}|{reason}".encode()).hexdigest()


def _int_price(raw_str: str) -> int:
    """"2,784" 또는 "2,784원" → 2784"""
    cleaned = re.sub(r"[,원\s]", "", str(raw_str))
    return int(cleaned) if cleaned.isdigit() else 0


def _unit_price_basis(kind: UnitKind) -> UnitPriceBasis:
    mapping = {
        UnitKind.GRAM: UnitPriceBasis.PER_100G,
        UnitKind.KILOGRAM: UnitPriceBasis.PER_1KG,
        UnitKind.MILLILITER: UnitPriceBasis.PER_100ML,
        UnitKind.LITER: UnitPriceBasis.PER_1L,
    }
    return mapping.get(kind, UnitPriceBasis.PER_EACH)


def _basis_qty_for_kind(kind: UnitKind) -> float:
    """단위가 계산 기준 수량."""
    return {
        UnitKind.GRAM: 100.0,
        UnitKind.KILOGRAM: 1.0,
        UnitKind.MILLILITER: 100.0,
        UnitKind.LITER: 1.0,
    }.get(kind, 1.0)


def _compute_unit_price(sale_price: int, qty: float, kind: UnitKind) -> Optional[float]:
    """단위가 계산. qty=0이거나 UNKNOWN이면 None."""
    if qty <= 0 or kind == UnitKind.UNKNOWN:
        return None
    basis = _basis_qty_for_kind(kind)
    try:
        nu = NormalizedUnit(
            kind=kind,
            quantity=qty,
            basis=f"per_{int(basis)}{kind.value[0]}",  # rough basis text
            raw_text="",
        )
        return unit_price(sale_price, nu)
    except Exception:
        return None


def _reasons_to_review_reason(reasons: list[str]) -> ReviewReason:
    """reasons 리스트에서 가장 대표적인 ReviewReason 반환."""
    if any(r in ("EMART_NO_CATEGORY", "CATEGORY_UNMAPPED") for r in reasons):
        return ReviewReason.CATEGORY_UNKNOWN
    if any(r in ("UNIT_UNKNOWN",) for r in reasons):
        return ReviewReason.UNIT_UNPARSABLE
    return ReviewReason.PRODUCT_AMBIGUOUS


def _build_result(
    mart: MartKind,
    mart_item_id: str,
    mart_item_name_raw: str,
    brand: Optional[str],
    name_core: str,
    pack_quantity: float,
    pack_unit: UnitKind,
    sale_price: int,
    regular_price: Optional[int],
    on_sale: bool,
    discount_rate: Optional[int],
    event_labels: list[str],
    observed_at: datetime,
    raw: dict,
    reasons: list[str],
    source_url: Optional[str],
    category_path_internal: Optional[str],
    representative_image_url: Optional[str] = None,
) -> CanonicalizationResult:
    """
    파싱 결과로 CanonicalizationResult 구성.
    canonical/queue 생성 여부 결정 포함.
    """
    # 파싱 실패 시 canonical 미생성
    blocking = {"QUANTITY_UNPARSEABLE", "UNIT_UNKNOWN", "NAME_CORE_TOO_SHORT"}
    can_create_canonical = not any(r in blocking for r in reasons)

    # name_core 길이 검사
    if len(name_core) < 2:
        reasons = list(reasons) + ["NAME_CORE_TOO_SHORT"]
        can_create_canonical = False

    canonical = None
    sku_alias = None
    price_obs = None

    if can_create_canonical:
        cid = derive_canonical_key(brand, name_core, pack_quantity, pack_unit)
        canonical = CanonicalProduct.build(
            brand=brand,
            name_core=name_core,
            pack_quantity=pack_quantity,
            pack_unit=pack_unit.value,
            category_path_internal=category_path_internal,
            representative_image_url=representative_image_url,
        )
        sku_alias = MartSkuAlias(
            id=_alias_id(mart.value, mart_item_id),
            canonical_id=cid,
            mart=mart,
            mart_item_id=mart_item_id,
            mart_item_name_raw=mart_item_name_raw,
            source_url=source_url,
        )
        upn = _compute_unit_price(sale_price, pack_quantity, pack_unit)
        upb = _unit_price_basis(pack_unit)
        price_obs = PriceObservation(
            id=_price_obs_id(cid, mart.value, observed_at),
            canonical_id=cid,
            mart=mart,
            regular_price=regular_price,
            sale_price=sale_price,
            on_sale=on_sale,
            discount_rate=discount_rate,
            unit_price_normalized=upn,
            unit_price_basis=upb,
            observed_at=observed_at,
            source_url=source_url,
            raw_payload_hash=_payload_hash(raw),
            event_labels=event_labels,
        )

    queue_entry = None
    if reasons:
        primary_reason = _reasons_to_review_reason(reasons)
        queue_entry = ProductReviewQueue(
            id=_queue_id(mart.value, mart_item_id, primary_reason.value),
            raw_payload=raw,
            source_mart=mart,
            reason=primary_reason,
        )

    confidence = 1.0 if (canonical is not None and not reasons) else (
        0.8 if (canonical is not None and reasons) else 0.0
    )

    return CanonicalizationResult(
        canonical=canonical,
        sku_alias=sku_alias,
        price_obs=price_obs,
        queue_entry=queue_entry,
        confidence=confidence,
        reasons=list(reasons),
    )


# ─────────────────────────────────────────────────────────────────────────────
# 이마트
# ─────────────────────────────────────────────────────────────────────────────

def canonicalize_emart(raw_item: dict, observed_at: datetime) -> CanonicalizationResult:
    """
    이마트 raw item dict → CanonicalizationResult.

    raw_item 키: itemId, itemName, brandName, finalPrice, strikeOutPrice,
                 discountRate, sellUnitCapacity, itemImgUrl, itemUrl
    이마트는 카테고리 정보가 없어 항상 EMART_NO_CATEGORY reason 추가.
    canonical은 생성되지만 queue_entry도 함께 생성됨.
    """
    item_name = raw_item.get("itemName", "")
    item_id = str(raw_item.get("itemId", ""))
    brand_name = (raw_item.get("brandName") or "").strip() or None

    # 가격 파싱
    final_price_str = raw_item.get("finalPrice", "0")
    strike_price_str = raw_item.get("strikeOutPrice", "")
    discount_rate_str = raw_item.get("discountRate", "")

    sale_price = _int_price(final_price_str)
    regular_price: Optional[int] = _int_price(strike_price_str) if strike_price_str else None
    on_sale = bool(regular_price and regular_price > sale_price)
    discount_rate: Optional[int] = int(discount_rate_str) if discount_rate_str else None

    # 카테고리 — 이마트는 없음
    _, cat_reason = map_emart(item_name, raw_item.get("siteNo"))
    reasons: list[str] = ["EMART_NO_CATEGORY"]

    # 이름 파싱 (sellUnitCapacity 는 per-unit basis 용 → 총량 파싱은 itemName에서)
    parsed = parse_product_name(item_name)
    brand = parsed.brand or (brand_name if brand_name else None)

    if parsed.pack_unit == UnitKind.UNKNOWN:
        reasons.append("UNIT_UNKNOWN")
    name_core = parsed.name_core

    return _build_result(
        mart=MartKind.EMART,
        mart_item_id=item_id,
        mart_item_name_raw=item_name,
        brand=brand,
        name_core=name_core,
        pack_quantity=parsed.pack_quantity,
        pack_unit=parsed.pack_unit,
        sale_price=sale_price,
        regular_price=regular_price,
        on_sale=on_sale,
        discount_rate=discount_rate,
        event_labels=[],
        observed_at=observed_at,
        raw=raw_item,
        reasons=reasons,
        source_url=raw_item.get("itemUrl"),
        category_path_internal=None,
        representative_image_url=raw_item.get("itemImgUrl"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# 홈플러스
# ─────────────────────────────────────────────────────────────────────────────

def canonicalize_homeplus(raw_row: dict, observed_at: datetime) -> CanonicalizationResult:
    """
    홈플러스 API 응답 row → CanonicalizationResult.

    raw_row 키: itemNm, itemNo, brandNm, salePrice, dcPrice, dcRate,
                totalUnitQty, unitMeasure, unitQty, unitDispYn,
                rcateNm, lcateNm, mcateNm, scateNm, dcateNm,
                eventFlagList, imgChgDt
    """
    item_name = raw_row.get("itemNm", "")
    item_id = str(raw_row.get("itemNo", ""))
    brand_api = (raw_row.get("brandNm") or "").strip() or None

    # 가격
    sale_price_raw = raw_row.get("dcPrice") or raw_row.get("salePrice", 0)
    regular_price_raw = raw_row.get("salePrice", 0)
    sale_price = int(sale_price_raw or 0)
    regular_price = int(regular_price_raw or 0)
    dc_rate = raw_row.get("dcRate")
    on_sale = bool(raw_row.get("dcPrice") is not None and dc_rate)
    discount_rate = int(dc_rate) if dc_rate else None

    # 이벤트 레이블
    event_labels = [
        flag.get("label", "")
        for flag in (raw_row.get("eventFlagList") or [])
        if flag.get("label")
    ]

    # 카테고리
    rcate = raw_row.get("rcateNm", "")
    lcate = raw_row.get("lcateNm", "")
    mcate = raw_row.get("mcateNm", "")
    scate = raw_row.get("scateNm", "")
    dcate = raw_row.get("dcateNm", "")
    mapped_cat, cat_reason = map_homeplus(rcate, lcate, mcate, scate, dcate)
    reasons: list[str] = []
    category_path_internal: Optional[str] = None
    if mapped_cat:
        category_path_internal = "/".join(mapped_cat.internal_path)
    else:
        reasons.append("CATEGORY_UNMAPPED")

    # 용량 — API totalUnitQty + unitMeasure 우선
    total_qty = float(raw_row.get("totalUnitQty") or 0)
    unit_measure = (raw_row.get("unitMeasure") or "").strip()
    unit_disp_yn = raw_row.get("unitDispYn", "Y")

    api_unit: Optional[UnitKind] = None
    api_qty: Optional[float] = None
    if total_qty > 0 and unit_disp_yn == "Y":
        api_unit = _lookup_extended(unit_measure) if unit_measure else UnitKind.UNKNOWN
        api_qty = total_qty

    # 이름 파싱 (API qty hint 전달)
    parsed = parse_product_name(item_name, api_qty=api_qty, api_unit=api_unit)
    brand = parsed.brand or brand_api

    # API qty 가 있고 이름 파싱이 UNKNOWN 이면 API 값 사용
    final_qty = parsed.pack_quantity
    final_unit = parsed.pack_unit
    if final_unit == UnitKind.UNKNOWN and api_qty is not None and api_unit is not None:
        final_qty = api_qty
        final_unit = api_unit
    # 여전히 UNKNOWN → fallback to EACH/1
    if final_unit == UnitKind.UNKNOWN or final_qty <= 0:
        final_qty = 1.0
        final_unit = UnitKind.EACH

    return _build_result(
        mart=MartKind.HOMEPLUS,
        mart_item_id=item_id,
        mart_item_name_raw=item_name,
        brand=brand,
        name_core=parsed.name_core,
        pack_quantity=final_qty,
        pack_unit=final_unit,
        sale_price=sale_price,
        regular_price=regular_price if regular_price != sale_price else None,
        on_sale=on_sale,
        discount_rate=discount_rate,
        event_labels=event_labels,
        observed_at=observed_at,
        raw=raw_row,
        reasons=reasons,
        source_url=None,
        category_path_internal=category_path_internal,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 롯데마트
# ─────────────────────────────────────────────────────────────────────────────

def canonicalize_lottemart(entity: dict, observed_at: datetime) -> CanonicalizationResult:
    """
    롯데마트 Zetta productEntity dict → CanonicalizationResult.

    entity 키: name, retailerProductId, categoryPath, price.current.amount,
               price.original.amount, brand, image.src, offers
    """
    item_name = (entity.get("name") or "").strip()
    item_id = str(entity.get("retailerProductId", ""))
    brand_api = (entity.get("brand") or "").strip()
    # "단독기획" 같은 비브랜드 표기 제외
    if brand_api in ("단독기획", "PB", "자체상표"):
        brand_api = ""

    # 가격
    price_block = entity.get("price") or {}
    current_block = price_block.get("current") or {}
    original_block = price_block.get("original")
    sale_price = int(current_block.get("amount", 0))
    regular_price: Optional[int] = int(original_block["amount"]) if original_block else None
    on_sale = bool(regular_price and regular_price > sale_price)
    discount_rate: Optional[int] = None
    if on_sale and regular_price:
        discount_rate = round((regular_price - sale_price) / regular_price * 100)

    # 이벤트
    event_labels = [
        o.get("description", "")
        for o in (entity.get("offers") or [])
        if o.get("description")
    ]

    # 카테고리
    category_path = entity.get("categoryPath") or []
    mapped_cat, cat_reason = map_lottemart(category_path) if category_path else (None, "INVALID_INPUT")
    reasons: list[str] = []
    category_path_internal: Optional[str] = None
    if mapped_cat:
        category_path_internal = "/".join(mapped_cat.internal_path)
    else:
        reasons.append("CATEGORY_UNMAPPED")

    # 이름 파싱
    parsed = parse_product_name(item_name)
    brand = parsed.brand or (brand_api if brand_api else None)

    final_qty = parsed.pack_quantity
    final_unit = parsed.pack_unit
    if final_unit == UnitKind.UNKNOWN:
        final_qty = 1.0
        final_unit = UnitKind.EACH

    img_url = (entity.get("image") or {}).get("src")

    return _build_result(
        mart=MartKind.LOTTEMART,
        mart_item_id=item_id,
        mart_item_name_raw=item_name,
        brand=brand,
        name_core=parsed.name_core,
        pack_quantity=final_qty,
        pack_unit=final_unit,
        sale_price=sale_price,
        regular_price=regular_price,
        on_sale=on_sale,
        discount_rate=discount_rate,
        event_labels=event_labels,
        observed_at=observed_at,
        raw=entity,
        reasons=reasons,
        source_url=None,
        category_path_internal=category_path_internal,
        representative_image_url=img_url,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 코스트코
# ─────────────────────────────────────────────────────────────────────────────

def parse_costco_cards_from_html(html_content: str) -> list[dict]:
    """
    코스트코 특가 페이지 HTML → 카드 dict 리스트.

    반환 dict 키:
      title, url_path, product_id, sale_price_raw, unit_price_text
    """
    li_blocks = re.findall(
        r"<li[^>]*product-list-item[^>]*>(.*?)</li>",
        html_content,
        re.DOTALL,
    )
    cards = []
    for block in li_blocks:
        href_m = re.search(r'href="([^"]+)"', block)
        title_m = re.search(r'title="([^"]+)"', block)
        price_m = re.search(r'notranslate[^>]*>([^<]+)</span>', block)
        unit_m = re.search(r'product-price-pre-unit-amount[^>]*>\s*([^<]+)', block)

        if not (href_m and title_m):
            continue

        url_path = href_m.group(1)
        title = html.unescape(title_m.group(1))
        sale_price_raw = price_m.group(1).strip() if price_m else ""
        unit_price_text = unit_m.group(1).strip() if unit_m else ""

        # product_id from URL /p/NNN
        pid_m = re.search(r"/p/(\d+)$", url_path)
        product_id = pid_m.group(1) if pid_m else ""

        cards.append({
            "title": title,
            "url_path": url_path,
            "product_id": product_id,
            "sale_price_raw": sale_price_raw,
            "unit_price_text": unit_price_text,
        })
    return cards


def canonicalize_costco(card: dict, observed_at: datetime) -> CanonicalizationResult:
    """
    코스트코 카드 dict → CanonicalizationResult.

    card 키: title, url_path, product_id, sale_price_raw, unit_price_text
    코스트코 특가 페이지는 original_price 미노출 → regular_price=None.
    """
    item_name = (card.get("title") or "").strip()
    item_id = str(card.get("product_id", ""))
    url_path = card.get("url_path", "")
    sale_price = _int_price(card.get("sale_price_raw", "0"))

    # 카테고리
    mapped_cat, _ = map_costco(url_path) if url_path else (None, "INVALID_INPUT")
    reasons: list[str] = []
    category_path_internal: Optional[str] = None
    if mapped_cat:
        category_path_internal = "/".join(mapped_cat.internal_path)
    else:
        reasons.append("CATEGORY_UNMAPPED")

    # 이름 파싱
    parsed = parse_product_name(item_name)
    brand = parsed.brand
    final_qty = parsed.pack_quantity
    final_unit = parsed.pack_unit

    if final_unit == UnitKind.UNKNOWN:
        # unit_price_text 에서 단위 힌트 추출 시도 ("100㎖당 3,099원")
        from .units import parse_costco_unit_text
        unit_info = parse_costco_unit_text(card.get("unit_price_text", ""))
        if unit_info.kind != UnitKind.UNKNOWN:
            # unit_price_text 의 kind 를 기준으로 qty=1 fallback
            final_qty = 1.0
            final_unit = unit_info.kind
        else:
            final_qty = 1.0
            final_unit = UnitKind.EACH

    return _build_result(
        mart=MartKind.COSTCO,
        mart_item_id=item_id,
        mart_item_name_raw=item_name,
        brand=brand,
        name_core=parsed.name_core,
        pack_quantity=final_qty,
        pack_unit=final_unit,
        sale_price=sale_price,
        regular_price=None,   # 특가 페이지는 original_price 미노출
        on_sale=True,          # 특가 페이지이므로 항상 on_sale
        discount_rate=None,
        event_labels=[],
        observed_at=observed_at,
        raw=card,
        reasons=reasons,
        source_url=url_path,
        category_path_internal=category_path_internal,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 묶음 검증
# ─────────────────────────────────────────────────────────────────────────────

def merge_into_canonical(
    results: list[CanonicalizationResult],
) -> dict[str, list[CanonicalizationResult]]:
    """
    CanonicalizationResult 리스트를 canonical_id 기준으로 그루핑.
    canonical이 None 인 항목은 제외.
    """
    groups: dict[str, list[CanonicalizationResult]] = {}
    for result in results:
        if result.canonical is not None:
            cid = result.canonical.id
            groups.setdefault(cid, []).append(result)
    return groups


# ─────────────────────────────────────────────────────────────────────────────
# 알구몬 / 아카라이브 — 핫딜 게시글 best-effort 정규화
# ─────────────────────────────────────────────────────────────────────────────

def canonicalize_algumon(raw_post: dict, observed_at: datetime) -> CanonicalizationResult:
    """
    알구몬 핫딜 게시글 dict → CanonicalizationResult (best-effort).

    raw_post 키: title, url, price (Optional[int]), source_community, category_hints
    """
    from .category_mapper import map_algumon
    from .canonical_models import MartKind

    title = (raw_post.get("title") or "").strip()
    item_id = raw_post.get("source_record_key") or raw_post.get("url") or title
    price = raw_post.get("price")
    sale_price = int(price) if price is not None and price >= 0 else 0
    hints: list[str] = raw_post.get("category_hints") or []

    reasons: list[str] = []

    if not price or sale_price <= 0:
        reasons.append("PRICE_INVALID")

    category_path_internal: Optional[str] = None
    for hint in hints:
        mapped_cat, _ = map_algumon(hint)
        if mapped_cat:
            category_path_internal = "/".join(mapped_cat.internal_path)
            break
    if not category_path_internal:
        reasons.append("CATEGORY_UNMAPPED")

    parsed = parse_product_name(title)
    brand = parsed.brand
    name_core = parsed.name_core
    final_qty = parsed.pack_quantity
    final_unit = parsed.pack_unit

    if final_unit == UnitKind.UNKNOWN:
        final_qty = 1.0
        final_unit = UnitKind.EACH

    return _build_result(
        mart=MartKind.ALGUMON,
        mart_item_id=str(item_id),
        mart_item_name_raw=title,
        brand=brand,
        name_core=name_core,
        pack_quantity=final_qty,
        pack_unit=final_unit,
        sale_price=sale_price,
        regular_price=None,
        on_sale=False,
        discount_rate=None,
        event_labels=[],
        observed_at=observed_at,
        raw=raw_post,
        reasons=reasons,
        source_url=raw_post.get("url"),
        category_path_internal=category_path_internal,
    )


def canonicalize_arcalive(raw_post: dict, observed_at: datetime) -> CanonicalizationResult:
    """아카라이브 핫딜 게시글 dict → CanonicalizationResult (best-effort)."""
    from .category_mapper import map_algumon
    from .canonical_models import MartKind

    title = (raw_post.get("title") or "").strip()
    item_id = raw_post.get("source_record_key") or raw_post.get("url") or title
    price = raw_post.get("price")
    sale_price = int(price) if price is not None and price >= 0 else 0
    hints: list[str] = raw_post.get("category_hints") or []
    store_category = raw_post.get("category") or ""
    if store_category and store_category not in hints:
        hints = [store_category] + hints

    reasons: list[str] = []

    if not price or sale_price <= 0:
        reasons.append("PRICE_INVALID")

    category_path_internal: Optional[str] = None
    for hint in hints:
        mapped_cat, _ = map_algumon(hint)
        if mapped_cat:
            category_path_internal = "/".join(mapped_cat.internal_path)
            break
    if not category_path_internal:
        reasons.append("CATEGORY_UNMAPPED")

    parsed = parse_product_name(title)
    brand = parsed.brand
    name_core = parsed.name_core
    final_qty = parsed.pack_quantity
    final_unit = parsed.pack_unit

    if final_unit == UnitKind.UNKNOWN:
        final_qty = 1.0
        final_unit = UnitKind.EACH

    return _build_result(
        mart=MartKind.ARCALIVE,
        mart_item_id=str(item_id),
        mart_item_name_raw=title,
        brand=brand,
        name_core=name_core,
        pack_quantity=final_qty,
        pack_unit=final_unit,
        sale_price=sale_price,
        regular_price=None,
        on_sale=False,
        discount_rate=None,
        event_labels=[],
        observed_at=observed_at,
        raw=raw_post,
        reasons=reasons,
        source_url=raw_post.get("url"),
        category_path_internal=category_path_internal,
    )


def canonicalize_kokodalin(api_item: dict, observed_at: datetime) -> CanonicalizationResult:
    """코코달인 API 상품 dict → CanonicalizationResult."""
    from .category_mapper import map_kokodalin
    from .canonical_models import MartKind

    item_name = (api_item.get("product_name") or "").strip()
    item_id = str(api_item.get("product_id", ""))

    def _safe_int(val) -> int:
        try:
            return int(val) if val is not None else 0
        except (ValueError, TypeError):
            return 0

    sale_price = _safe_int(api_item.get("sale_price"))
    normal_price = _safe_int(api_item.get("normal_price"))
    regular_price: Optional[int] = normal_price if normal_price > sale_price else None
    on_sale = bool(regular_price and regular_price > sale_price)
    discount_pct: Optional[int] = None
    if on_sale and regular_price:
        discount_pct = round((regular_price - sale_price) / regular_price * 100)

    reasons: list[str] = []

    category_name = (api_item.get("category_name") or "").strip()
    mapped_cat, _ = map_kokodalin(category_name) if category_name else (None, "INVALID_INPUT")
    category_path_internal: Optional[str] = None
    if mapped_cat:
        category_path_internal = "/".join(mapped_cat.internal_path)
    else:
        reasons.append("CATEGORY_UNMAPPED")

    parsed = parse_product_name(item_name)
    brand = parsed.brand
    final_qty = parsed.pack_quantity
    final_unit = parsed.pack_unit
    if final_unit == UnitKind.UNKNOWN:
        final_qty = 1.0
        final_unit = UnitKind.EACH

    detail_url = f"https://www.cocodalin.com/product.html?id={item_id}" if item_id else None

    return _build_result(
        mart=MartKind.KOKODALIN,
        mart_item_id=item_id,
        mart_item_name_raw=item_name,
        brand=brand,
        name_core=parsed.name_core,
        pack_quantity=final_qty,
        pack_unit=final_unit,
        sale_price=sale_price,
        regular_price=regular_price,
        on_sale=on_sale,
        discount_rate=discount_pct,
        event_labels=[],
        observed_at=observed_at,
        raw=api_item,
        reasons=reasons,
        source_url=detail_url,
        category_path_internal=category_path_internal,
    )
