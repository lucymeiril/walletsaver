"""
정부 농축산물 도매가 앵커 — 회귀 테스트 (Task 2)

출처: 서울시 공공데이터포털 농수산물 도매시장 시세 (KAMIS 생산경로 금지)
검증 항목:
  1. GovWholesalePrice 스키마 — 테이블 생성 + 필드 무결성
  2. 앵커 계산 — avg_price 기반 상한/하한/핫딜 임계값
  3. 출처 guard — KAMIS 관련 source 값 거부 (GovWholesaleSource Enum에 없음)
  4. DB 저장 회귀 — 저장·조회·가격밴드 산출 일치
  5. 복수 품목·복수 시장 적재 후 품목별 최신 앵커 조회
"""

from __future__ import annotations

import pytest
import sys
from pathlib import Path
from datetime import datetime, timedelta

ROOT = Path(__file__).resolve().parent.parent.parent
for p in [
    str(ROOT),
    str(ROOT / "packages" / "db-admin" / "backend"),
    str(ROOT / "packages" / "shared"),
]:
    if p not in sys.path:
        sys.path.insert(0, p)

from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker

from storage.models import (
    Base, GovWholesalePrice, GovWholesaleSource,
    Category, Product,
)


# ─── 공용 fixture ────────────────────────────────────────────────────────────

@pytest.fixture
def wdb():
    """인메모리 DB — gov_wholesale_prices 테이블 포함."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    sess = Session()
    yield sess
    sess.rollback()
    sess.close()
    engine.dispose()


def _sample_wholesale(
    product_name: str = "삼겹살",
    avg_price: float = 14_500.0,
    source: GovWholesaleSource = GovWholesaleSource.GARAK_WHOLESALE,
    recorded_date: datetime | None = None,
) -> GovWholesalePrice:
    return GovWholesalePrice(
        product_name=product_name,
        category_code="122",          # 돼지고기
        wholesale_market="가락시장",
        source=source,
        api_dataset_code="OA-1170",
        unit="100g",
        avg_price=avg_price,
        min_price=avg_price * 0.85,
        max_price=avg_price * 1.20,
        recorded_date=recorded_date or datetime.utcnow(),
    )


# ─── 1. 스키마 무결성 ────────────────────────────────────────────────────────

class TestGovWholesalePriceSchema:
    """GovWholesalePrice 테이블 스키마 검증."""

    def test_table_created(self, wdb):
        """gov_wholesale_prices 테이블이 생성된다."""
        row = _sample_wholesale()
        wdb.add(row)
        wdb.commit()
        saved = wdb.execute(select(GovWholesalePrice)).scalars().first()
        assert saved is not None
        assert saved.id is not None

    def test_required_fields_persist(self, wdb):
        """필수 필드가 모두 저장된다."""
        row = _sample_wholesale(product_name="양파", avg_price=3_200.0)
        wdb.add(row)
        wdb.commit()
        wdb.expire_all()
        saved = wdb.execute(select(GovWholesalePrice)).scalars().first()
        assert saved.product_name == "양파"
        assert saved.avg_price == 3_200.0
        assert saved.source == GovWholesaleSource.GARAK_WHOLESALE
        assert saved.wholesale_market == "가락시장"

    def test_min_max_price_nullable(self, wdb):
        """min_price / max_price는 NULL 허용."""
        row = GovWholesalePrice(
            product_name="감자",
            wholesale_market="강서시장",
            source=GovWholesaleSource.GANGSEO_WHOLESALE,
            unit="1kg",
            avg_price=2_100.0,
            recorded_date=datetime.utcnow(),
        )
        wdb.add(row)
        wdb.commit()
        wdb.expire_all()
        saved = wdb.execute(select(GovWholesalePrice)).scalars().first()
        assert saved.min_price is None
        assert saved.max_price is None


# ─── 2. 가격 앵커 계산 ───────────────────────────────────────────────────────

class TestGovWholesaleAnchorCalculation:
    """avg_price 기반 상한/하한/핫딜 임계값 계산."""

    def test_upper_bound_is_130pct(self, wdb):
        row = _sample_wholesale(avg_price=10_000.0)
        wdb.add(row)
        wdb.commit()
        assert row.upper_bound == 13_000.0

    def test_lower_bound_is_70pct(self, wdb):
        row = _sample_wholesale(avg_price=10_000.0)
        wdb.add(row)
        wdb.commit()
        assert row.lower_bound == 7_000.0

    def test_hotdeal_threshold_is_85pct(self, wdb):
        row = _sample_wholesale(avg_price=10_000.0)
        wdb.add(row)
        wdb.commit()
        assert row.hotdeal_threshold == 8_500.0

    def test_custom_rate_overrides(self, wdb):
        """사용자 지정 비율로 상한/하한 재계산."""
        row = _sample_wholesale(avg_price=20_000.0)
        row.upper_bound_rate = 1.50   # 150%
        row.lower_bound_rate = 0.60   # 60%
        row.hotdeal_rate = 0.75       # 75%
        wdb.add(row)
        wdb.commit()
        assert row.upper_bound == 30_000.0
        assert row.lower_bound == 12_000.0
        assert row.hotdeal_threshold == 15_000.0

    def test_retail_price_above_upper_is_expensive(self, wdb):
        """소매가 > 상한 → '비쌈' 판정."""
        row = _sample_wholesale(avg_price=10_000.0)
        wdb.add(row)
        wdb.commit()
        retail_price = 14_000.0   # 140% of wholesale — 상한 130% 초과
        assert retail_price > row.upper_bound

    def test_retail_price_below_hotdeal_is_hot(self, wdb):
        """소매가 < 핫딜 임계 → '핫딜' 판정."""
        row = _sample_wholesale(avg_price=10_000.0)
        wdb.add(row)
        wdb.commit()
        retail_price = 8_000.0   # 80% of wholesale — 핫딜 기준(85%) 이하
        assert retail_price < row.hotdeal_threshold


# ─── 3. 출처 GUARD — KAMIS 재도입 금지 ──────────────────────────────────────

class TestGovWholesaleSourceGuard:
    """KAMIS 출처가 GovWholesaleSource에 포함되지 않음을 강제 검증."""

    def test_kamis_not_in_allowed_sources(self):
        """KAMIS는 GovWholesaleSource Enum에 없어야 한다 (생산경로 금지)."""
        allowed = {s.value for s in GovWholesaleSource}
        assert "KAMIS" not in allowed, (
            "KAMIS가 GovWholesaleSource에 포함됨 — 생산경로 재도입 금지 위반"
        )

    def test_valid_sources_include_garak(self):
        """가락시장(GARAK_WHOLESALE)은 유효한 출처다."""
        assert GovWholesaleSource.GARAK_WHOLESALE in GovWholesaleSource

    def test_valid_sources_include_mafra(self):
        """농림축산식품부(MAFRA_WHOLESALE) 출처도 유효하다."""
        assert GovWholesaleSource.MAFRA_WHOLESALE in GovWholesaleSource

    def test_invalid_source_raises(self, wdb):
        """허용되지 않는 source 값('KAMIS')은 Python Enum에 없으므로 저장 전 TypeError 발생."""
        with pytest.raises((ValueError, KeyError, LookupError)):
            # GovWholesaleSource("KAMIS") 호출 자체가 ValueError
            _ = GovWholesaleSource("KAMIS")


# ─── 4. DB 저장 회귀 ────────────────────────────────────────────────────────

class TestGovWholesalePriceRegression:
    """복수 품목·복수 날짜 적재 후 조회 회귀."""

    def test_multiple_products_multiple_dates(self, wdb):
        """5개 품목 × 3일치 = 15행 저장 후 전체 조회."""
        products = ["삼겹살", "양파", "감자", "사과", "배추"]
        prices = [14_500, 3_200, 2_100, 5_800, 4_500]
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        rows = []
        for i, (name, price) in enumerate(zip(products, prices)):
            for d in range(3):
                rows.append(GovWholesalePrice(
                    product_name=name,
                    wholesale_market="가락시장",
                    source=GovWholesaleSource.GARAK_WHOLESALE,
                    unit="100g",
                    avg_price=price * (1 + d * 0.02),
                    recorded_date=today - timedelta(days=d),
                ))
        wdb.add_all(rows)
        wdb.commit()

        count = wdb.execute(select(func.count()).select_from(GovWholesalePrice)).scalar()
        assert count == 15

    def test_latest_anchor_per_product(self, wdb):
        """품목별 최신 날짜 앵커 조회."""
        today = datetime.utcnow()
        yesterday = today - timedelta(days=1)
        old = _sample_wholesale("삼겹살", avg_price=13_000, recorded_date=yesterday)
        new = _sample_wholesale("삼겹살", avg_price=14_500, recorded_date=today)
        wdb.add_all([old, new])
        wdb.commit()

        latest = (
            wdb.execute(
                select(GovWholesalePrice)
                .where(GovWholesalePrice.product_name == "삼겹살")
                .order_by(GovWholesalePrice.recorded_date.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )
        assert latest.avg_price == 14_500.0

    def test_price_band_regression_pork_belly(self, wdb):
        """삼겹살 도매가 기준 가격밴드 회귀 — 기준값 변경 시 바로 감지."""
        row = _sample_wholesale("삼겹살", avg_price=14_500.0)
        wdb.add(row)
        wdb.commit()
        # 기준 도매가 14,500원/100g 기준 앵커 고정값
        assert row.upper_bound == 18_850.0    # 14500 × 1.30
        assert row.lower_bound == 10_150.0    # 14500 × 0.70
        assert row.hotdeal_threshold == 12_325.0  # 14500 × 0.85

    def test_multiple_markets_same_product(self, wdb):
        """동일 품목이 여러 시장에 적재될 수 있다."""
        rows = [
            GovWholesalePrice(
                product_name="양파",
                wholesale_market=market,
                source=src,
                unit="1kg",
                avg_price=3_200.0,
                recorded_date=datetime.utcnow(),
            )
            for market, src in [
                ("가락시장", GovWholesaleSource.GARAK_WHOLESALE),
                ("강서시장", GovWholesaleSource.GANGSEO_WHOLESALE),
            ]
        ]
        wdb.add_all(rows)
        wdb.commit()
        count = wdb.execute(
            select(func.count()).select_from(GovWholesalePrice)
            .where(GovWholesalePrice.product_name == "양파")
        ).scalar()
        assert count == 2
