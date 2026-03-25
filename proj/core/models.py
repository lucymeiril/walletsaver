"""
공유 데이터 모델 (Pydantic).

모든 모듈이 공통으로 사용하는 데이터 구조체.
계약 인터페이스의 파라미터/리턴 타입으로 사용된다.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# --- 열거형 (Enum) ---

class CrawlStatus(str, Enum):
    """크롤링 작업 상태."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"      # 일부 성공
    CANCELLED = "cancelled"


class ErrorType(str, Enum):
    """크롤링 에러 분류."""
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
    """크롤러 그룹."""
    PUBLIC_API = "public"       # 공공 API
    MART = "marts"              # 대형마트
    HOTDEAL = "hotdeals"        # 핫딜 게시판
    FOOD = "food"               # 배달/식당


# --- 크롤러 정보 ---

class CrawlerInfo(BaseModel):
    """크롤러 플러그인 메타 정보."""
    name: str                                   # "이마트"
    version: str = "1.0.0"
    group: CrawlerGroup
    description: str = ""
    target_url: str = ""                        # 메인 대상 URL
    strategies: list[str] = Field(default_factory=list)  # ["requests", "selenium"]
    schedule: Optional[str] = None              # cron 표현식


# --- 크롤링 요청/결과 ---

class CrawlRequest(BaseModel):
    """크롤링 실행 요청."""
    crawler_name: str
    url: Optional[str] = None                   # None이면 크롤러 기본 URL 사용
    options: dict[str, Any] = Field(default_factory=dict)
    force_strategy: Optional[str] = None        # 강제로 특정 전략 사용


class CrawlResult(BaseModel):
    """크롤링 실행 결과."""
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


# --- 에러 & 진단 ---

class StrategyFailure(BaseModel):
    """개별 전략의 실패 기록."""
    strategy_name: str
    error_type: ErrorType
    error_msg: str
    status_code: Optional[int] = None
    timestamp: datetime = Field(default_factory=datetime.now)


class DiagnosisReport(BaseModel):
    """실패 진단 리포트."""
    crawler_name: str
    overall_error_type: ErrorType
    summary: str                                # 사람이 읽을 수 있는 요약
    failures: list[StrategyFailure]             # 각 전략의 실패 상세
    recommendation: str                         # 추천 대응
    timestamp: datetime = Field(default_factory=datetime.now)


# --- 이벤트 ---

class Event(BaseModel):
    """이벤트 버스 이벤트."""
    event_type: str
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.now)
    source: str = ""                            # 이벤트 발행 모듈


# --- 가격 데이터 (순수 DB용) ---

class DataSource(str, Enum):
    """데이터 원본 — 신뢰도 분류에 사용."""
    GOVERNMENT = "government"       # 정부 공식 (KAMIS, KOSIS) — baseline
    MART_REGULAR = "mart_regular"   # 마트 정가 — baseline
    MART_DISCOUNT = "mart_discount" # 마트 전단 할인가 — discount_history
    HOTDEAL = "hotdeal"             # 핫딜 게시판 — 참고만, 평균에 불포함
    DELIVERY = "delivery"           # 배달앱 — 외식 참고
    GAS_STATION = "gas_station"     # 주유소 — 연료 baseline


class ProductPrice(BaseModel):
    """
    품목 가격 레코드 — 순수 DB의 기본 단위.

    baseline_prices, discount_history 모두에 사용.
    이 레코드가 누적되어 평균/중간/최저가를 산출한다.
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
    마트 전단 할인 상품 — 크롤러가 생산하는 구조화된 데이터.

    크롤러 → DiscountItem → ProductPrice로 변환 → DB 저장.
    """
    name: str                                   # 상품명 (원본)
    normalized_name: str = ""                   # 표준화된 품목명 (양파, 삼겹살 등)
    store: str                                  # 매장명
    original_price: Optional[int] = None        # 정가 (원)
    sale_price: int                             # 할인가 (원)
    discount_percent: Optional[float] = None    # 할인율 (%)
    unit: str = ""                              # 단위
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
    핫딜 게시판 글 — 참고 전용, 평균 산출에 불포함.
    """
    title: str
    url: str
    source_community: str = ""                  # "뽐뿌", "어미새", "루리웹"
    price: Optional[int] = None
    original_price: Optional[int] = None
    category: str = ""
    crawled_at: datetime = Field(default_factory=datetime.now)
    matched_product: str = ""                   # DB 매칭된 품목명
    price_vs_avg: Optional[float] = None        # 평균 대비 비율 (0.7 = 30% 저렴)

