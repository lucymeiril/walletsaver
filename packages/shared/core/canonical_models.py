"""
WalletSavior Phase B — 표준 도메인 모델 (Pydantic v2).

왜 이 파일인가:
    4개 마트(이마트·홈플러스·롯데마트·코스트코)와 쿠팡이 완전히 다른 raw 형식을 사용한다.
    이 파일은 "공통 언어"를 정의한다. 크롤러는 raw 데이터를 이 모델로 변환하고,
    DB·API·검색·시각화는 이 모델만 다룬다.

raw → 이 모델 변환은 B4(product-canonicalize)에서 수행한다.
B2에서 UnitKind enum이 확정되면 pack_unit 필드의 타입을 UnitKind로 교체한다.
B3에서 내부 카테고리 매핑이 완성되면 category_path_internal에 실제 CategoryNode.id가 채워진다.

레거시 DiscountItem (core/models.py) 은 이 파일에서 참조하지 않는다.
점진적 마이그레이션 대상이며, 두 모델은 독립적으로 공존한다.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ══════════════════════════════════════════════════════
# Enums
# ══════════════════════════════════════════════════════

class MartKind(str, Enum):
    """
    마트 식별 enum.

    왜 string이 아닌 enum인가:
        타이포 방지 + 쿼리 필터링의 타입 안전성이 목적이다.
        string "EMART"는 "Emart"·"emart"와 구별이 안 되어
        통계 집계·JOIN 시 데이터 오염이 발생한다.
        enum은 직렬화 시에도 동일 string으로 내려가므로 하위 호환이 깨지지 않는다.
    """
    EMART = "EMART"
    HOMEPLUS = "HOMEPLUS"
    LOTTEMART = "LOTTEMART"
    COSTCO = "COSTCO"
    COUPANG = "COUPANG"
    ALGUMON = "ALGUMON"
    ARCALIVE = "ARCALIVE"
    KOKODALIN = "KOKODALIN"


class UnitPriceBasis(str, Enum):
    """
    단위가 기준 — "100g당 ₩xxx" 같은 단위가를 정규화할 기준값.

    왜 필요한가:
        마트마다 단위가 표기가 다르다.
        이마트: sellUnitCapacity("100g") / 홈플러스: unitMeasure("G")+unitQty
        롯데마트: price.unit.label("fop.price.per.100gram"|"fop.price.per.each")
        코스트코: "100㎖당 3,099원" 한글 텍스트
        이를 per_100g·per_1kg·per_each 등으로 통일해야 마트 간 가격 비교가 가능하다.
    """
    PER_100G = "per_100g"
    PER_1KG = "per_1kg"
    PER_100ML = "per_100ml"
    PER_1L = "per_1l"
    PER_EACH = "per_each"
    UNKNOWN = "unknown"


class ReviewReason(str, Enum):
    """
    검토 대기열 등록 사유 — B4 product-canonicalize 단계에서 자동 판별.

    왜 enum인가:
        사유별로 운영자 대응 방식이 다르다.
        CATEGORY_UNKNOWN → 카테고리 매핑 추가 필요
        PRODUCT_AMBIGUOUS → 상품명 클렌징 규칙 보완 필요
        UNIT_UNPARSABLE → B2 단위 파서 예외 케이스 추가 필요
        PRICE_INVALID → 수집된 raw 가격 값 자체 문제
    """
    CATEGORY_UNKNOWN = "CATEGORY_UNKNOWN"
    PRODUCT_AMBIGUOUS = "PRODUCT_AMBIGUOUS"
    UNIT_UNPARSABLE = "UNIT_UNPARSABLE"
    PRICE_INVALID = "PRICE_INVALID"


# ══════════════════════════════════════════════════════
# CategoryNode
# ══════════════════════════════════════════════════════

class CategoryNodeSchema(BaseModel):
    """
    내부 카테고리 트리 노드 — 마트별 카테고리 명칭 차이를 흡수하는 표준 계층.

    왜 별도 모델인가:
        홈플러스는 rcate>lcate>mcate>scate>dcate 5단계,
        롯데마트는 categoryPath 리스트(3단계 이하),
        이마트는 카테고리 정보 자체가 raw payload에 없다(별도 API 필요).
        이 차이를 흡수하고 B3 카테고리매핑이 표준 트리를 채워 넣는다.

    level: 1=대분류, 2=중분류, 3=소분류, 4=세분류.
    path: "/대/중/소/세" 형식 — URL slug 조합이 아닌 한글명 경로.
           CategoryNode.id가 변경돼도 path는 변하지 않아야 한다.
    name_slug: 검색/URL에 쓰이는 ASCII-compatible 식별자.
    display_order: 같은 level·parent 내에서 UI 표시 순서.
    """
    id: str
    parent_id: Optional[str] = None  # 루트 노드는 null — 최상위 대분류
    name_kr: str
    name_slug: str
    level: int  # 1~4
    path: str   # "/정육ㆍ계란/계란ㆍ메추리알/일반란"
    display_order: int = 0


# ══════════════════════════════════════════════════════
# CanonicalProduct
# ══════════════════════════════════════════════════════

class CanonicalProduct(BaseModel):
    """
    마트 간 비교의 기본 단위 — "같은 상품"이라고 판단된 SKU 묶음의 대표 정보.

    id:
        SHA1(brand|name_core|pack_qty|pack_unit) — 결정적(deterministic) 해시.
        왜 UUID가 아닌가: 같은 상품은 어떤 마트에서 수집해도 항상 같은 id를 가져야
        중복 생성 없이 멱등 upsert가 가능하다.
        브랜드+핵심명+용량+단위가 모두 같으면 같은 상품으로 본다.

    brand:
        nullable — 이마트는 brandName 필드 없거나 ""인 경우 많고,
        홈플러스는 brandNm=null이 대부분이다.
        PB상품이나 신선식품은 브랜드 개념이 없으므로 null 허용.

    name_core:
        브랜드명·용량·카테고리어·광고 문구를 제거한 핵심 상품명.
        예: "[농할 20%쿠폰] 한끼 양배추 800g 통" → "양배추"
        B4 product-canonicalize 단계에서 NLP/규칙 기반으로 추출.

    pack_quantity + pack_unit:
        포장 용량/수량 — 단위가 계산의 분모.
        B2 단위 파서가 파싱 결과를 채운다.
        pack_unit은 현재 string placeholder; B2 완료 후 UnitKind enum으로 교체.
        둘 다 없으면 pack_quantity=1.0, pack_unit="개"로 폴백.

    category_path_internal:
        CategoryNode.id FK — 마트별 카테고리를 내부 표준 트리로 매핑한 결과.
        B3 카테고리매핑 전까지는 null 허용.
        null이면 ProductReviewQueue에 CATEGORY_UNKNOWN 사유로 등록된다.

    representative_image_url:
        nullable — 이미지가 없거나 여러 마트 중 하나만 제공할 수 있다.
        여러 SKU alias 중 가장 해상도 좋은 이미지를 B4에서 선택한다.
    """
    id: str
    brand: Optional[str] = None
    name_core: str
    pack_quantity: float = 1.0
    pack_unit: str = "개"  # B2 완료 후 UnitKind enum으로 교체 예정
    category_path_internal: Optional[str] = None  # CategoryNode.id FK; B3 전까지 null 가능
    representative_image_url: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    @staticmethod
    def make_id(
        brand: Optional[str],
        name_core: str,
        pack_quantity: float,
        pack_unit: str,
    ) -> str:
        """
        결정적 canonical id 생성.

        SHA1(brand|name_core|pack_qty|pack_unit) — 같은 입력은 항상 같은 id.
        brand가 None이면 빈 문자열로 처리 (null vs "" 혼동 방지).
        pack_quantity는 소수점 6자리로 정규화 (0.1 vs .10 혼동 방지).
        """
        raw = f"{brand or ''}|{name_core}|{pack_quantity:.6f}|{pack_unit}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    @classmethod
    def build(
        cls,
        brand: Optional[str],
        name_core: str,
        pack_quantity: float,
        pack_unit: str,
        **kwargs: Any,
    ) -> "CanonicalProduct":
        """brand+name_core+pack_qty+pack_unit으로 id를 자동 계산해서 생성하는 팩토리."""
        return cls(
            id=cls.make_id(brand, name_core, pack_quantity, pack_unit),
            brand=brand,
            name_core=name_core,
            pack_quantity=pack_quantity,
            pack_unit=pack_unit,
            **kwargs,
        )


# ══════════════════════════════════════════════════════
# MartSkuAlias
# ══════════════════════════════════════════════════════

class MartSkuAlias(BaseModel):
    """
    마트별 SKU 식별자 ↔ CanonicalProduct 매핑 테이블.

    왜 별도 테이블인가:
        같은 상품이 이마트에서는 itemId="1000641687348",
        홈플러스에서는 itemNo="069483347"로 다른 id를 가진다.
        CanonicalProduct에 마트별 id를 직접 넣으면 마트 추가 시 스키마를 변경해야 한다.
        alias 테이블로 분리하면 CanonicalProduct는 건드리지 않고 마트를 추가할 수 있다.

    mart_item_id:
        마트 원본 상품 id — 이마트: itemId, 홈플러스: itemNo,
        롯데마트: retailerProductId("OS8809214203632"), 코스트코: URL의 p/{id}.

    mart_item_name_raw:
        마트에서 수집한 원본 상품명 전문 — 정규화 전 텍스트.
        name_core와 비교해서 B4 정규화 품질을 검증하는 데 사용.

    first_seen_at / last_seen_at:
        상품의 판매 기간을 추적한다. 단종 감지에 활용.
        last_seen_at이 오래되면 "더 이상 판매 안 함" 알림 후보.
    """
    id: str
    canonical_id: str
    mart: MartKind
    mart_item_id: str
    mart_item_name_raw: str
    source_url: Optional[str] = None
    first_seen_at: datetime = Field(default_factory=datetime.now)
    last_seen_at: datetime = Field(default_factory=datetime.now)


# ══════════════════════════════════════════════════════
# PriceObservation
# ══════════════════════════════════════════════════════

class PriceObservation(BaseModel):
    """
    특정 마트·특정 시점의 가격 스냅샷 — 가격 이력의 원자적 단위.

    왜 DiscountHistory와 별도인가:
        DiscountHistory는 "행사 기간" 단위의 레코드지만,
        PriceObservation은 "크롤러가 수집한 시점" 단위다.
        가격 변동 추이 분석, 할인 시작/종료 감지, 이상가 탐지를 위해
        더 세밀한 시계열이 필요하다.

    regular_price:
        nullable — 할인 중이 아닌 경우 정가가 표시되지 않는 마트가 있다.
        이마트: strikeOutPrice(없으면 null), 홈플러스: salePrice(항상 존재),
        롯데마트: price.original.amount(null이면 미할인), 코스트코: original-price.

    on_sale:
        sale_price < regular_price이면 True.
        regular_price가 null인 경우 마트가 제공하는 dcRate > 0으로 판단.

    discount_rate:
        nullable — 마트가 제공하는 값을 그대로 사용. 정수 퍼센트.
        이마트: discountRate("20" → 20), 홈플러스: dcRate(int),
        롯데마트: original/current 비율로 역산, 코스트코: 미제공(null).

    unit_price_normalized:
        nullable — 단위가 기준으로 정규화된 가격.
        단위가 파싱 실패 시 null. B2 단위 파서가 채운다.

    unit_price_basis:
        per_100g·per_each 등 단위가 기준 — unit_price_normalized와 쌍으로 해석.

    raw_payload_hash:
        SHA1(원본 payload JSON 문자열) — raw 데이터 무결성 추적.
        raw blob 자체는 raw_payloads 테이블(별도 옵션)에 저장.
        hash만으로도 어떤 raw에서 이 관측값이 나왔는지 추적 가능.

    event_labels:
        마트가 상품에 붙인 이벤트 태그 목록.
        홈플러스 eventFlagList[label], 롯데마트 offers[description].
        마케팅 분석·"1+1 상품만 필터" 등 기능에 사용.
    """
    id: str
    canonical_id: str
    mart: MartKind
    regular_price: Optional[int] = None   # 정가; 할인 미표시 또는 미할인 상품은 null
    sale_price: int                        # 실제 구매가 (할인 적용 후)
    on_sale: bool
    discount_rate: Optional[int] = None   # 정수 퍼센트; 마트 미제공 시 null
    unit_price_normalized: Optional[float] = None
    unit_price_basis: UnitPriceBasis = UnitPriceBasis.UNKNOWN
    observed_at: datetime = Field(default_factory=datetime.now)
    source_url: Optional[str] = None
    raw_payload_hash: str                  # SHA1(raw payload JSON)
    event_labels: list[str] = Field(default_factory=list)


# ══════════════════════════════════════════════════════
# ProductReviewQueue
# ══════════════════════════════════════════════════════

class ProductReviewQueue(BaseModel):
    """
    자동 처리 불가 상품의 운영자 검토 대기열.

    왜 필요한가:
        B4 product-canonicalize는 규칙+AI로 자동화하지만,
        애매한 상품(브랜드 없는 신선식품, 이름이 광고 문구만인 상품 등)은
        자동 결정을 내리지 않고 이 큐에 쌓아 운영자가 검토한다.
        잘못된 canonical 매핑이 통계를 오염시키는 것보다
        미처리 상태로 두는 게 낫다.

    raw_payload:
        크롤러가 수집한 원본 데이터 전체 — 정보 손실 없이 재처리 가능하게 보존.
        이 데이터로 언제든 canonicalize를 재시도할 수 있어야 한다.

    suggested_canonical_id:
        nullable — AI가 가장 가능성 높은 canonical_id를 추천했을 때 채워진다.
        운영자가 확인 후 승인(resolved_at 기록)하면 MartSkuAlias에 반영.

    resolver_user_id:
        nullable — 자동 처리된 경우(AI 재시도 성공) null.
        운영자가 수동 해결한 경우 user id를 기록해 감사 로그 역할.
    """
    id: str
    raw_payload: dict[str, Any]
    source_mart: MartKind
    reason: ReviewReason
    suggested_canonical_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    resolved_at: Optional[datetime] = None  # null이면 미해결
    resolver_user_id: Optional[str] = None  # null이면 미처리 또는 자동처리
