"""
SQLAlchemy ORM 모델 — 모든 테이블 정의를 한 곳에 모은다.

왜 존재하는가:
    core/models.py의 Pydantic 모델은 "전송·검증용 DTO"이고,
    이 파일의 SQLAlchemy 모델은 "실제 DB 스키마"다.
    두 계층을 분리해야 DB 스키마 변경이 API 응답 형태에 영향을 주지 않는다.
어디서 쓰이는가:
    storage/db.py (DBStorage)가 이 모델들로 CRUD를 수행한다.
    alembic 마이그레이션도 이 Base.metadata를 참조한다.
지원 DB:
    SQLite (개발) — auto-create, JSON은 TEXT로 저장
    PostgreSQL (운영) — 네이티브 JSON, 인덱스 최적화
"""

from datetime import datetime

from sqlalchemy import (
    String, Integer, Float, DateTime, Text, JSON,
    ForeignKey, Index, Boolean,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """모든 ORM 모델의 공통 베이스 — metadata 공유로 일괄 테이블 생성 지원."""
    pass


# ──────────────────────────────────────────────
# 1. 품목 마스터
# ──────────────────────────────────────────────

class Product(Base):
    """
    품목 마스터 — 모든 가격 비교의 기준 단위.

    왜 필요한가:
        "양파 1kg"처럼 표준화된 품목 단위가 없으면
        마트마다 다른 상품명·용량을 비교할 수 없다.
    어디서 쓰이는가:
        baseline_prices, discount_history, hotdeal_posts 등
        모든 가격 테이블이 이 테이블을 FK로 참조한다.
        프론트엔드 PRODUCTS 배열의 원천.
    """
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)  # "양파", "삼겹살"
    category: Mapped[str] = mapped_column(String(200), default="")  # "채소류 > 근채류"
    unit: Mapped[str] = mapped_column(String(50), default="")  # "1kg", "100g"
    icon: Mapped[str] = mapped_column(String(10), default="")  # emoji
    # 부가 속성 — 산지, 등급, 보관법 등 품목마다 다른 메타데이터
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    # relationships
    baseline_prices = relationship("BaselinePrice", back_populates="product", lazy="selectin")
    discount_items = relationship("DiscountHistory", back_populates="product", lazy="selectin")


# ──────────────────────────────────────────────
# 2. 기준 가격 (평균 산출의 유일한 원천)
# ──────────────────────────────────────────────

class BaselinePrice(Base):
    """
    기준 가격 — 정부 공식(KAMIS) + 마트 정가만 기록.

    왜 별도 테이블인가:
        할인가·핫딜가를 평균에 섞으면 baseline이 왜곡된다.
        이 테이블에는 "정상 시장가"만 넣어서 신뢰할 수 있는 평균을 산출한다.
    어디서 쓰이는가:
        statistics.compute_stats()가 이 테이블에서 avg/min/max를 계산하고,
        프론트엔드 product.avg, product.low, product.high의 원천이 된다.
    """
    __tablename__ = "baseline_prices"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    source: Mapped[str] = mapped_column(String(50))  # "KAMIS", "이마트", "코스트코"
    source_type: Mapped[str] = mapped_column(String(30))  # "government", "mart_regular"
    price: Mapped[int] = mapped_column(Integer)
    unit: Mapped[str] = mapped_column(String(50), default="")
    recorded_date: Mapped[datetime] = mapped_column(DateTime, index=True)
    crawled_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    product = relationship("Product", back_populates="baseline_prices")

    # 복합 인덱스 — product_id + recorded_date 조합 조회가 빈번 (일별 평균 등)
    __table_args__ = (
        Index("ix_baseline_product_date", "product_id", "recorded_date"),
    )


# ──────────────────────────────────────────────
# 3. 할인 이력 (baseline과 분리하여 가격 오염 방지)
# ──────────────────────────────────────────────

class DiscountHistory(Base):
    """
    할인 이력 — 마트 전단 할인가를 별도 기록.

    왜 baseline과 분리하는가:
        "1+1", "반값 행사" 같은 특가는 일시적이라
        평균에 포함하면 "지금 비싼가?"를 정확히 판단할 수 없다.
        분리 저장하면 "이 품목은 할인 주기가 2.3주" 같은 패턴 분석이 가능하다.
    어디서 쓰이는가:
        프론트엔드 MART_DATA.items의 원천 — 마트별 현재 할인 목록.
    """
    __tablename__ = "discount_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    store: Mapped[str] = mapped_column(String(50))  # "이마트", "홈플러스"
    original_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sale_price: Mapped[int] = mapped_column(Integer)
    discount_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    event_name: Mapped[str] = mapped_column(String(200), default="")  # "주간특가", "1+1"
    valid_from: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    image_url: Mapped[str] = mapped_column(Text, default="")
    crawled_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    product = relationship("Product", back_populates="discount_items")


# ──────────────────────────────────────────────
# 4. 핫딜 게시글 (참고용만 — 절대 평균에 불포함)
# ──────────────────────────────────────────────

class HotdealPost(Base):
    """
    핫딜 게시글 — 뽐뿌·어미새·루리웹 등 커뮤니티 핫딜.

    왜 평균에 넣지 않는가:
        "1원 이벤트", "한정 10개" 같은 비정상 가격이 섞이면
        baseline이 오염되어 "지금 사도 되는가?" 판정이 무의미해진다.
    어디서 쓰이는가:
        프론트엔드 HOTDEALS 배열의 원천.
        price_vs_avg로 baseline 대비 얼마나 저렴한지 참고만 제공.
    """
    __tablename__ = "hotdeal_posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text, unique=True)
    source_community: Mapped[str] = mapped_column(String(50), default="")  # "뽐뿌", "어미새"
    price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    original_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    category: Mapped[str] = mapped_column(String(50), default="")  # "food", "electronics"
    matched_product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id"), nullable=True
    )
    price_vs_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    views: Mapped[int] = mapped_column(Integer, default=0)
    comments_count: Mapped[int] = mapped_column(Integer, default=0)
    thumbnail_url: Mapped[str] = mapped_column(Text, default="")
    crawled_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


# ──────────────────────────────────────────────
# 5. 주유소 정보
# ──────────────────────────────────────────────

class GasStation(Base):
    """
    주유소 정보 — OPINET API로 수집한 유가 데이터.

    어디서 쓰이는가:
        프론트엔드 GAS_STATIONS 배열의 원천.
        연료 종류별(gasoline/diesel/lpg) 최저가 정렬에 사용.
    """
    __tablename__ = "gas_stations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    brand: Mapped[str] = mapped_column(String(50), default="")
    address: Mapped[str] = mapped_column(Text, default="")
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    gasoline_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    diesel_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lpg_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


# ──────────────────────────────────────────────
# 6. 크롤링 실행 로그
# ──────────────────────────────────────────────

class CrawlLog(Base):
    """
    크롤링 실행 로그 — 각 크롤러 실행 결과를 기록.

    왜 필요한가:
        "마지막 성공은 언제?", "어떤 전략이 실패했나?" 를 추적해야
        DiagnosticsEngine이 자동 진단·복구를 할 수 있다.
    어디서 쓰이는가:
        프론트엔드 크롤러 관리 대시보드 + 자동 복구 트리거.
    """
    __tablename__ = "crawl_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    crawler_name: Mapped[str] = mapped_column(String(50), index=True)
    status: Mapped[str] = mapped_column(String(20))  # "success", "failed", "partial"
    strategy_used: Mapped[str | None] = mapped_column(String(50), nullable=True)
    items_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    diagnosis: Mapped[dict | None] = mapped_column(JSON, nullable=True)


# ──────────────────────────────────────────────
# 7. 사용자 관심 품목 (서버사이드 백업)
# ──────────────────────────────────────────────

class UserFavorite(Base):
    """
    사용자 관심 품목 — 로그인 없이도 세션 기반으로 저장.

    왜 서버에 저장하는가:
        localStorage만 쓰면 디바이스 변경 시 목록이 사라진다.
        서버 백업 + localStorage 캐시 이중화로 사용자 경험을 보장.
    """
    __tablename__ = "user_favorites"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(100), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


# ──────────────────────────────────────────────
# 8. 가격 알림 설정
# ──────────────────────────────────────────────

class PriceAlert(Base):
    """
    가격 알림 — 목표 가격 이하로 떨어지면 알림 발송.

    어디서 쓰이는가:
        크롤링 완료 이벤트 → alert 체크 → 조건 충족 시 알림 큐 발행.
    """
    __tablename__ = "price_alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(100), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    target_price: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    triggered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
