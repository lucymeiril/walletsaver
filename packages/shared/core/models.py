"""
프로젝트 전체의 "언어"를 정의하는 중앙 데이터 모델.

왜 존재하는가:
    크롤러, 엔진, 저장소, API 등 모든 모듈이 같은 데이터 형태로 대화해야 한다.
    Pydantic을 쓰는 이유는 (1) 타입 검증으로 잘못된 데이터가 파이프라인에 흘러들어가는 것을
    막고 (2) JSON 직렬화가 API 응답·이벤트 발행에 바로 쓸 수 있기 때문이다.
어디서 쓰이는가:
    모든 모듈이 import한다. contracts/ 인터페이스의 파라미터·리턴 타입이며,
    이벤트 버스(Event), 진단 리포트(DiagnosisReport), DB 저장(ProductPrice) 등 전 계층에 걸쳐 사용.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# --- 열거형 (Enum) ---

class CrawlStatus(str, Enum):
    """크롤링 작업의 생명주기 상태 — executor가 이벤트 발행·결과 판정에 사용."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"      # 일부 성공
    CANCELLED = "cancelled"


class ErrorType(str, Enum):
    """
    크롤링 실패의 원인 분류 — DiagnosticsEngine이 자동 진단·추천 대응을 결정하는 핵심 키.

    왜 세분화하는가: "실패했다"만으로는 대응이 불가능하다.
    IP_BANNED이면 프록시를 교체하고, DOM_CHANGED이면 셀렉터를 업데이트해야 한다.
    이 enum 값 하나로 진단 엔진이 원인 파악 → 심각도 산정 → 대응 추천까지 자동화한다.
    """
    HTTP_ERROR = "http_error"
    CAPTCHA_DETECTED = "captcha_detected"
    IP_BANNED = "ip_banned"
    JS_CHALLENGE = "js_challenge"
    DOM_CHANGED = "dom_changed"
    TIMEOUT = "timeout"
    LOGIN_REQUIRED = "login_required"
    EMPTY_RESPONSE = "empty_response"
    PARSE_ERROR = "parse_error"
    NETWORK_ERROR = "network_error"
    UNKNOWN = "unknown"


class CrawlerGroup(str, Enum):
    """크롤러를 데이터 성격별로 묶는 그룹 — 스케줄링 주기·신뢰도 정책이 그룹별로 다르다."""
    PUBLIC_API = "public"       # 공공 API
    MART = "marts"              # 대형마트
    HOTDEAL = "hotdeals"        # 핫딜 게시판
    FOOD = "food"               # 배달/식당
    SHOPPING = "shopping"       # 패션/쇼핑
    LOCAL = "local"             # 위치 기반 (네이버 플레이스, 주유소 등)


# --- 크롤러 정보 ---

class CrawlerInfo(BaseModel):
    """크롤러 플러그인의 자기소개서 — registry가 플러그인을 자동 발견·분류할 때 읽는 메타 정보."""
    name: str                                   # "이마트"
    version: str = "1.0.0"
    group: CrawlerGroup
    description: str = ""
    target_url: str = ""                        # 메인 대상 URL
    strategies: list[str] = Field(default_factory=list)  # ["requests", "selenium"]
    schedule: Optional[str] = None              # cron 표현식


# --- 크롤링 요청/결과 ---

class CrawlRequest(BaseModel):
    """API 또는 스케줄러가 엔진에 보내는 크롤링 실행 요청 — executor.execute()의 입력."""
    crawler_name: str
    url: Optional[str] = None                   # None이면 크롤러 기본 URL 사용
    options: dict[str, Any] = Field(default_factory=dict)
    force_strategy: Optional[str] = None        # 강제로 특정 전략 사용


class CrawlResult(BaseModel):
    """
    모든 크롤링 작업의 통일된 출력 — 성공·실패 관계없이 동일 구조.

    왜 통일하는가: 후속 파이프라인(저장소 저장, 진단, 이벤트 발행)이 성공/실패를
    분기 없이 처리할 수 있어야 한다. 실패 시에도 errors 필드에 각 전략의 실패 상세가 담겨
    DiagnosticsEngine이 자동 분석할 수 있다.
    어디서 쓰이나: executor → 이 모델 → storage / diagnostics / event_bus
    """
    status: CrawlStatus
    crawler_name: str
    strategy_used: Optional[str] = None         # 성공한 전략
    items_count: int = 0
    items: list[dict[str, Any]] = Field(default_factory=list)
    raw_data: Optional[str] = None
    started_at: datetime = Field(default_factory=datetime.now)
    finished_at: Optional[datetime] = None
    duration_seconds: float = 0.0
    errors: list[StrategyFailure] = Field(default_factory=list)
    error_msg: Optional[str] = None
    quality_score: Optional[float] = None
    quality_details: dict[str, Any] = Field(default_factory=dict)


# --- 에러 & 진단 ---

class StrategyFailure(BaseModel):
    """개별 전략의 실패 기록 — cascade 중 어떤 전략이 왜 실패했는지 DiagnosticsEngine에 전달."""
    strategy_name: str
    error_type: ErrorType
    error_msg: str
    status_code: Optional[int] = None
    timestamp: datetime = Field(default_factory=datetime.now)


class DiagnosisReport(BaseModel):
    """
    실패 원인 자동 진단 리포트 — AI가 크롤러를 자가 치유하기 위한 근거 자료.

    DiagnosticsEngine.analyze() → 이 모델 → 대시보드 표시 / 자동 복구 트리거.
    """
    crawler_name: str
    overall_error_type: ErrorType
    summary: str                                # 사람이 읽을 수 있는 요약
    failures: list[StrategyFailure]             # 각 전략의 실패 상세
    recommendation: str                         # 추천 대응
    timestamp: datetime = Field(default_factory=datetime.now)


# --- 이벤트 ---

class Event(BaseModel):
    """이벤트 버스를 통해 모듈 간 전달되는 메시지 봉투 — 발행자와 구독자가 서로를 몰라도 소통할 수 있게 한다."""
    event_type: str
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.now)
    source: str = ""                            # 이벤트 발행 모듈


# --- 가격 데이터 (순수 DB용) ---

class DataSource(str, Enum):
    """
    데이터 원본의 신뢰도 계층 — "이 가격을 평균 산출에 넣어도 되는가?"를 결정한다.

    GOVERNMENT/MART_REGULAR → baseline(평균 산출 대상),
    MART_DISCOUNT → 할인 이력 기록용,
    HOTDEAL → 참고만(1원 이벤트 같은 이상치가 평균을 오염시키므로 평균에 불포함).
    statistics.compute_stats()와 verification이 이 분류에 의존한다.
    """
    GOVERNMENT = "government"       # 정부 공식 (KAMIS, KOSIS) — baseline
    MART_REGULAR = "mart_regular"   # 마트 정가 — baseline
    MART_DISCOUNT = "mart_discount" # 마트 전단 할인가 — discount_history
    HOTDEAL = "hotdeal"             # 핫딜 게시판 — 참고만, 평균에 불포함
    DELIVERY = "delivery"           # 배달앱 — 외식 참고
    GAS_STATION = "gas_station"     # 주유소 — 연료 baseline


class ProductPrice(BaseModel):
    """
    DB에 저장되는 정규화된 가격 레코드 — 모든 가격 비교의 기본 단위.

    왜 필요한가:
        크롤러마다 다른 형식(DiscountItem, HotdealPost 등)의 데이터를 생산하지만,
        통계·비교·등급 판정은 하나의 통일된 형태가 필요하다.
    어디서 쓰이나:
        크롤러 → DiscountItem.to_product_price() → 이 모델 → DB(baseline_prices, discount_history)
        → statistics.compute_stats() → 평균·중간·최저가 산출
    """
    product_name: str                           # "양파", "삼겹살" (표준화된 명칭)
    category: str = ""                          # "채소류 > 근채류"
    store: str = ""                             # "이마트", "코스트코" 또는 "KAMIS"
    source: DataSource                          # 데이터 원본 신뢰도 분류
    price: int                                  # 가격 (원)
    unit: str = ""                              # "1kg", "100g", "1L"
    original_price: Optional[int] = None        # 할인 전 정가 (할인 아닐 때 None)
    discount_rate: Optional[float] = None       # 할인율 (0.0 ~ 1.0)
    recorded_date: datetime = Field(default_factory=datetime.now)
    valid_from: Optional[datetime] = None       # 할인 시작일
    valid_until: Optional[datetime] = None      # 할인 종료일
    source_url: str = ""                        # 수집 원본 URL
    crawled_at: datetime = Field(default_factory=datetime.now)
    raw_text: str = ""                          # 원본 텍스트 (디버깅/검증용)


class DiscountItem(BaseModel):
    """
    마트 크롤러가 생산하는 할인 상품 원시 데이터 — ProductPrice로 정규화되기 전 단계.

    왜 별도 모델인가:
        크롤러가 수집한 원본 정보(행사명, 이미지 URL 등)를 보존해야 대시보드 표시와
        디버깅이 가능하다. to_product_price()로 정규화하면 이런 부가 정보가 소실된다.
    흐름: 마트 크롤러 → DiscountItem → to_product_price() → ProductPrice → DB
    """
    name: str                                   # 상품명 (원본)
    normalized_name: str = ""                   # 표준화된 품목명 (양파, 삼겹살 등)
    store: str                                  # 매장명
    original_price: Optional[int] = None        # 정가 (원)
    sale_price: int                             # 할인가 (원)
    discount_percent: Optional[float] = None    # 할인율 (%)
    unit: str = ""                              # 단위
    display_unit: str = ""                      # 고객 표시용 판매 단위(예: 300g)
    package_quantity: Optional[float] = None    # 포장 수량(예: 300)
    package_unit: str = ""                      # 포장 단위(예: g)
    price_per_100g: Optional[float] = None      # 중량 상품의 100g당 가격
    attributes: dict[str, Any] = Field(default_factory=dict)  # 냉장/원산지/등급 등
    category: str = ""                          # 카테고리
    event_name: str = ""                        # 행사명 ("1+1", "반값", "주간특가")
    valid_from: Optional[datetime] = None       # 행사 시작일
    valid_until: Optional[datetime] = None      # 행사 종료일
    image_url: str = ""                         # 상품 이미지 URL
    detail_url: str = ""                        # 상세 페이지 URL
    crawled_at: datetime = Field(default_factory=datetime.now)

    def to_product_price(self) -> ProductPrice:
        """DiscountItem → ProductPrice 변환."""
        return ProductPrice(
            product_name=self.normalized_name or self.name,
            store=self.store,
            source=DataSource.MART_DISCOUNT,
            price=self.sale_price,
            unit=self.unit,
            category=self.category,
            original_price=self.original_price,
            discount_rate=self.discount_percent / 100 if self.discount_percent else None,
            valid_from=self.valid_from,
            valid_until=self.valid_until,
            source_url=self.detail_url,
            crawled_at=self.crawled_at,
            raw_text=self.name,
        )


class HotdealPost(BaseModel):
    """
    핫딜 커뮤니티(뽐뿌·어미새 등) 게시글 — 평균 산출에 절대 포함하지 않는다.

    왜 ProductPrice와 분리하는가:
        핫딜은 "1원 이벤트", "한정 수량 특가" 등 정상 시장가와 동떨어진 가격이 많다.
        이걸 평균에 넣으면 baseline이 왜곡되어 "지금 사도 괜찮아요" 판정이 엉망이 된다.
        별도 모델로 격리하고 price_vs_avg 필드로 참고 비교만 제공한다.
    """
    title: str
    url: str
    source_community: str = ""                  # "뽐뿌", "어미새", "루리웹"
    price: Optional[int] = None
    original_price: Optional[int] = None
    price_evidence: str = ""                   # 원문 가격 텍스트/증거
    category: str = ""
    category_hints: list[str] = Field(default_factory=list)
    image_url: str = ""
    post_date: Optional[datetime] = None
    period: str = ""
    crawled_at: datetime = Field(default_factory=datetime.now)
    matched_product: str = ""                   # DB 매칭된 품목명
    price_vs_avg: Optional[float] = None        # 평균 대비 비율 (0.7 = 30% 저렴)


# --- 대기열 (Pending Ingestion) ---

class IngestionStatus(str, Enum):
    """크롤 결과 대기열 상태"""
    PENDING = "pending"
    CRAWLER_APPROVED = "crawler_approved"
    APPROVED = "approved"
    REJECTED = "rejected"
    PARTIAL = "partial"


class PendingIngestionSummary(BaseModel):
    """대기열 항목 요약 — 목록 표시용"""
    id: int
    crawler_name: str
    crawl_status: str
    items_count: int
    schema_type: str
    quality_score: Optional[float] = None
    status: IngestionStatus = IngestionStatus.PENDING
    crawled_at: datetime = Field(default_factory=datetime.now)
    duration_seconds: Optional[float] = None


class PendingIngestionDetail(PendingIngestionSummary):
    """대기열 항목 상세 — 미리보기, 검토용"""
    items: list[dict[str, Any]] = Field(default_factory=list)
    quality_details: Optional[dict[str, Any]] = None
    errors: list[dict[str, Any]] = Field(default_factory=list)
    crawler_reviewer_notes: Optional[str] = None
    db_reviewer_notes: Optional[str] = None
    rejected_reason: Optional[str] = None
    approved_items: Optional[list[dict[str, Any]]] = None
    strategy_used: Optional[str] = None
    source_url: Optional[str] = None


class IngestionReviewRequest(BaseModel):
    """크롤러/DB 관리자의 검토 요청"""
    action: str                                         # "approve", "reject", "partial"
    notes: Optional[str] = None
    approved_item_indices: Optional[list[int]] = None   # partial 승인 시 항목 인덱스
    rejected_reason: Optional[str] = None

