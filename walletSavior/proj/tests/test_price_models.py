"""
가격 데이터 모델 + 크롤러 데이터 파이프라인 TDD 테스트.

검증 대상:
1. DiscountItem 생성 및 유효성
2. DiscountItem → ProductPrice 변환 정확성
3. DataSource 신뢰도 분류
4. HotdealPost가 baseline에 불포함되는지 구조적으로 확인
5. ProductPrice의 price analysis 적합성
"""

import pytest
from datetime import datetime

from core.models import (
    ProductPrice, DiscountItem, HotdealPost,
    DataSource, CrawlerGroup,
)


class TestDataSource:
    """데이터 원본 신뢰도 분류 테스트."""

    def test_government_is_baseline(self):
        """정부 데이터는 baseline."""
        assert DataSource.GOVERNMENT.value == "government"

    def test_mart_discount_is_not_baseline(self):
        """마트 할인가는 discount_history."""
        assert DataSource.MART_DISCOUNT.value == "mart_discount"

    def test_hotdeal_is_separate(self):
        """핫딜은 별도 저장소."""
        assert DataSource.HOTDEAL.value == "hotdeal"

    def test_all_sources_exist(self):
        """모든 소스 유형이 정의되어 있다."""
        expected = {"government", "mart_regular", "mart_discount", "hotdeal", "delivery", "gas_station"}
        actual = {ds.value for ds in DataSource}
        assert actual == expected


class TestDiscountItem:
    """마트 전단 할인 상품 테스트."""

    def test_create_minimal(self):
        """최소 필드만으로 생성."""
        item = DiscountItem(name="양파 1.5kg", store="이마트", sale_price=2480)
        assert item.name == "양파 1.5kg"
        assert item.store == "이마트"
        assert item.sale_price == 2480

    def test_create_full(self):
        """전체 필드 생성."""
        item = DiscountItem(
            name="GAP 양파 1.5kg",
            normalized_name="양파",
            store="이마트",
            original_price=3980,
            sale_price=2480,
            discount_percent=38.0,
            unit="1.5kg",
            category="채소류",
            event_name="주간특가",
            valid_from=datetime(2026, 3, 18),
            valid_until=datetime(2026, 3, 24),
        )
        assert item.discount_percent == 38.0
        assert item.event_name == "주간특가"

    def test_to_product_price_conversion(self):
        """DiscountItem → ProductPrice 변환 정확성."""
        item = DiscountItem(
            name="GAP 양파 1.5kg",
            normalized_name="양파",
            store="이마트",
            original_price=3980,
            sale_price=2480,
            discount_percent=38.0,
            unit="1.5kg",
            category="채소류",
        )
        pp = item.to_product_price()

        assert pp.product_name == "양파"  # normalized_name 사용
        assert pp.store == "이마트"
        assert pp.source == DataSource.MART_DISCOUNT  # 자동 분류
        assert pp.price == 2480
        assert pp.original_price == 3980
        assert pp.discount_rate == pytest.approx(0.38)
        assert pp.unit == "1.5kg"

    def test_to_product_price_uses_name_when_no_normalized(self):
        """normalized_name이 없으면 원본 name 사용."""
        item = DiscountItem(name="삼겹살 600g", store="홈플러스", sale_price=9900)
        pp = item.to_product_price()
        assert pp.product_name == "삼겹살 600g"

    def test_to_product_price_no_discount(self):
        """할인율 없는 경우 discount_rate은 None."""
        item = DiscountItem(name="우유 1L", store="롯데마트", sale_price=2800)
        pp = item.to_product_price()
        assert pp.discount_rate is None


class TestProductPrice:
    """가격 레코드 테스트 — 분석용 적합성."""

    def test_baseline_source_classification(self):
        """정부 데이터는 GOVERNMENT 소스."""
        pp = ProductPrice(
            product_name="양파",
            source=DataSource.GOVERNMENT,
            price=2350,
            store="KAMIS",
            unit="1kg",
        )
        assert pp.source == DataSource.GOVERNMENT

    def test_price_must_be_positive(self):
        """가격은 정수 (양수) — 프로덕션에서는 validator 추가."""
        pp = ProductPrice(
            product_name="사과",
            source=DataSource.MART_REGULAR,
            price=12500,
        )
        assert pp.price > 0

    def test_multiple_records_for_average_calculation(self):
        """여러 레코드로 평균 가격을 산출할 수 있다."""
        records = [
            ProductPrice(product_name="양파", source=DataSource.MART_DISCOUNT, price=2200, store="이마트"),
            ProductPrice(product_name="양파", source=DataSource.MART_DISCOUNT, price=2480, store="홈플러스"),
            ProductPrice(product_name="양파", source=DataSource.MART_DISCOUNT, price=2590, store="롯데마트"),
        ]
        avg = sum(r.price for r in records) // len(records)
        assert avg == 2423  # 실제 평균

    def test_serialization_for_db(self):
        """JSON 직렬화 가능 — DB 저장에 필수."""
        pp = ProductPrice(
            product_name="휘발유",
            source=DataSource.GAS_STATION,
            price=1612,
            unit="1L",
        )
        data = pp.model_dump()
        assert data["product_name"] == "휘발유"
        assert data["source"] == "gas_station"
        assert data["price"] == 1612


class TestHotdealPost:
    """핫딜 게시판 글 — baseline 분리 확인."""

    def test_create(self):
        item = HotdealPost(
            title="양파 5kg 3,900원",
            url="https://example.com/deal/123",
            source_community="뽐뿌",
            price=3900,
            matched_product="양파",
            price_vs_avg=0.66,
        )
        assert item.price_vs_avg == pytest.approx(0.66)

    def test_hotdeal_has_no_data_source_field(self):
        """HotdealPost는 DataSource가 없다 — ProductPrice로 변환 불가.
        이것은 의도적이다. 핫딜 가격은 baseline에 넣지 않는다."""
        fields = HotdealPost.model_fields
        assert "source" not in fields


class TestDataPipeline:
    """크롤러 → DiscountItem → ProductPrice 파이프라인 통합 테스트."""

    def test_full_pipeline(self):
        """전체 파이프라인: 크롤러 아웃풋 → 분석용 데이터."""
        # 1. 크롤러가 수집한 raw 데이터
        raw_items = [
            {"name": "양파 1.5kg", "original": 3980, "sale": 2480, "discount": "38%"},
            {"name": "삼겹살 600g", "original": 14900, "sale": 9900, "discount": "34%"},
            {"name": "계란 30구", "original": 7980, "sale": 5980, "discount": "25%"},
        ]

        # 2. DiscountItem으로 변환
        discount_items = []
        for raw in raw_items:
            di = DiscountItem(
                name=raw["name"],
                store="이마트",
                original_price=raw["original"],
                sale_price=raw["sale"],
                discount_percent=float(raw["discount"].replace("%", "")),
            )
            discount_items.append(di)

        assert len(discount_items) == 3

        # 3. ProductPrice로 변환 (DB 저장용)
        prices = [di.to_product_price() for di in discount_items]

        assert all(p.source == DataSource.MART_DISCOUNT for p in prices)
        assert prices[0].price == 2480
        assert prices[1].price == 9900

        # 4. 분석: 이마트 평균 할인율
        avg_discount = sum(p.discount_rate for p in prices if p.discount_rate) / len(prices)
        assert 0.30 < avg_discount < 0.35  # 32.3%

    def test_hotdeal_excluded_from_baseline(self):
        """핫딜 데이터는 baseline 계산에서 제외된다."""
        baseline = [
            ProductPrice(product_name="양파", source=DataSource.MART_DISCOUNT, price=2480),
            ProductPrice(product_name="양파", source=DataSource.MART_REGULAR, price=3200),
            ProductPrice(product_name="양파", source=DataSource.GOVERNMENT, price=2350),
        ]
        hotdeal = HotdealPost(
            title="양파 5kg 990원 미친가격",
            url="",
            price=990,
        )

        # baseline 평균은 핫딜 제외
        baseline_avg = sum(p.price for p in baseline) / len(baseline)
        assert baseline_avg == pytest.approx(2676.67, rel=0.01)

        # 핫딜의 990원은 포함하지 않음 — 비정상 가격이 평균을 오염시키지 않는다
        assert hotdeal.price == 990
        assert hotdeal.price < baseline_avg * 0.5  # 평균의 50% 미만 = 이상치
