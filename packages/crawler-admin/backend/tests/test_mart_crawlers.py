"""
마트 크롤러 통합 테스트.

각 크롤러를 인스턴스화하고, 속성·메서드가 CrawlerContract를 따르는지,
파싱·검증 로직이 올바른지 검증한다.
실제 HTTP 호출 없이 목 데이터로 테스트한다.
"""

import pytest
from unittest.mock import patch, MagicMock

from crawlers.marts.emart.crawler import EmartCrawler
from crawlers.marts.homeplus.crawler import HomeplusCrawler
from crawlers.marts.lottemart.crawler import LottemartCrawler
from crawlers.marts.cocodalin.crawler import CocodalinCrawler
from core.models import CrawlerGroup, CrawlStatus, DiscountItem


# --- 목 HTML/JSON 데이터 ---

MOCK_EMART_HTML = """
<html><body>
<div class="cunit_prod">
  <div class="cunit_info"><span class="cunit_md">신선 양파 1.5kg</span></div>
  <div class="new_price"><span class="ssg_price">3,980</span></div>
  <div class="old_price"><span class="ssg_price">5,980</span></div>
  <a href="/item/detail.ssg?itemId=123">상세</a>
  <img src="https://img.emart.com/yangpa.jpg" />
</div>
<div class="cunit_prod">
  <div class="cunit_info"><span class="cunit_md">삼겹살 600g</span></div>
  <div class="new_price"><span class="ssg_price">12,900</span></div>
  <a href="/item/detail.ssg?itemId=456">상세</a>
  <img src="https://img.emart.com/samgyupsal.jpg" />
</div>
<div class="cunit_prod">
  <div class="cunit_info"><span class="cunit_md">X</span></div>
  <div class="new_price"><span class="ssg_price">0</span></div>
</div>
</body></html>
"""

MOCK_HOMEPLUS_HTML = """
<html><body>
<div class="product-item">
  <span class="product-name">국내산 감자 2kg</span>
  <span class="sale_price">4,500원</span>
  <span class="origin_price">6,000원</span>
  <a href="/goods/detail?goodsNo=789">상세</a>
  <img src="https://img.homeplus.co.kr/potato.jpg" />
</div>
<div class="product-item">
  <span class="product-name">우유 1L</span>
  <span class="sale_price">2,680원</span>
  <a href="/goods/detail?goodsNo=101">상세</a>
</div>
</body></html>
"""

MOCK_HOMEPLUS_MFRONT_HTML = """
<html><body>
<div class="unitItemInner">
  <a href="/item?itemNo=milk-1"><img alt="서울우유 1L" src="https://image.homeplus.test/milk.jpg" /></a>
  <strong class="itemName">서울우유 1L</strong>
  <span class="priceValue">2,480원</span>
  <span class="priceValue">3,100원</span>
  <span class="badge">20%</span>
</div>
</body></html>
"""

MOCK_LOTTEMART_HTML = """
<html><body>
<div class="product-item">
  <span class="product-name">제주 감귤 3kg</span>
  <span class="sale_price">9,900원</span>
  <span class="origin_price">14,900원</span>
  <a href="/goods/view?goodsNo=202">상세</a>
  <img src="https://img.lottemart.com/gamgyul.jpg" />
</div>
<div class="product-item">
  <span class="product-name">대파 한단</span>
  <span class="sale_price">1,500원</span>
  <a href="/goods/view?goodsNo=303">상세</a>
</div>
</body></html>
"""

MOCK_JSON_PAGE = """
<html><head><script>
var itemList = [
  {"itemNm": "바나나 1송이", "sellprc": 2990, "norprc": 4500, "ctgNm": "과일", "imgUrl": "https://img.test/banana.jpg", "itemUrl": "/item/111"},
  {"itemNm": "사과 5개입", "sellprc": 8900, "norprc": 12000, "ctgNm": "과일", "imgUrl": "https://img.test/apple.jpg", "itemUrl": "/item/222"},
  {"itemNm": "", "sellprc": 100},
  {"itemNm": "무료상품", "sellprc": 0}
];
</script></head><body></body></html>
"""


# --- 크롤러 인스턴스화 테스트 ---

class TestCrawlerInstantiation:
    """각 크롤러가 올바르게 인스턴스화되는지 검증."""

    @pytest.mark.parametrize("crawler_class,expected_name", [
        (EmartCrawler, "이마트"),
        (HomeplusCrawler, "홈플러스"),
        (LottemartCrawler, "롯데마트"),
        (CocodalinCrawler, "코코달인"),
    ])
    def test_crawler_has_info(self, crawler_class, expected_name):
        """크롤러가 info 속성을 가진다."""
        crawler = crawler_class()
        info = crawler.info
        assert info.name == expected_name

    @pytest.mark.parametrize("crawler_class", [
        EmartCrawler, HomeplusCrawler, LottemartCrawler,
    ])
    def test_crawler_group_is_mart(self, crawler_class):
        """마트 크롤러의 그룹이 MART이다."""
        crawler = crawler_class()
        assert crawler.info.group == CrawlerGroup.MART

    @pytest.mark.parametrize("crawler_class", [
        EmartCrawler, HomeplusCrawler, LottemartCrawler,
    ])
    def test_crawler_has_strategies(self, crawler_class):
        """마트 크롤러가 사용 전략 목록을 가진다."""
        crawler = crawler_class()
        assert len(crawler.info.strategies) >= 1

    @pytest.mark.parametrize("crawler_class", [
        EmartCrawler, HomeplusCrawler, LottemartCrawler, CocodalinCrawler,
    ])
    def test_crawler_has_required_methods(self, crawler_class):
        """CrawlerContract 필수 메서드를 구현한다."""
        crawler = crawler_class()
        assert hasattr(crawler, "crawl")
        assert hasattr(crawler, "parse")
        assert hasattr(crawler, "validate")
        assert callable(crawler.crawl)
        assert callable(crawler.parse)
        assert callable(crawler.validate)


# --- 파싱 테스트 (HTML) ---

class TestEmartParse:
    """이마트 크롤러 파싱 테스트."""

    @pytest.mark.asyncio
    async def test_parse_html_items(self):
        """HTML에서 상품을 파싱한다."""
        crawler = EmartCrawler()
        items = await crawler.parse(MOCK_EMART_HTML)
        # 유효한 상품 2개 (이름 1자 + 가격 0인 것 제외)
        valid = [i for i in items if i.sale_price > 0 and len(i.name) >= 2]
        assert len(valid) >= 1

    @pytest.mark.asyncio
    async def test_parse_item_fields(self):
        """파싱된 상품의 필수 필드가 채워진다."""
        crawler = EmartCrawler()
        items = await crawler.parse(MOCK_EMART_HTML)
        valid = [i for i in items if i.sale_price > 0 and len(i.name) >= 2]
        if valid:
            item = valid[0]
            assert item.store == "이마트"
            assert item.sale_price > 0
            assert len(item.name) >= 2

    def test_emart_keeps_pack_price_separate_from_100g_reference_unit(self):
        crawler = EmartCrawler()
        item = crawler._next_data_to_discount_item({
            "itemName": "[냉장] 한우 불고기1+등급300g",
            "finalPrice": "14,850",
            "strikeOutPrice": "19,800",
            "sellUnitCapacity": "100g",
            "siteName": "이마트",
        })

        assert item is not None
        assert item.sale_price == 14850
        assert item.original_price == 19800
        assert item.unit == "300g"
        assert item.display_unit == "300g"
        assert item.package_quantity == 300
        assert item.package_unit == "g"
        assert item.price_per_100g == 4950
        assert item.attributes["storage_type"] == "chilled"
        assert item.attributes["quality_grade"] == "1+"
        assert item.attributes["cut"] == "bulgogi"

    def test_emart_parses_parenthesized_frozen_shrimp_package(self):
        crawler = EmartCrawler()
        item = crawler._next_data_to_discount_item({
            "itemName": "[냉동][베트남] 흰다리 새우살 (200g)",
            "finalPrice": "4,488",
            "sellUnitCapacity": "100g",
            "siteName": "이마트",
        })

        assert item is not None
        assert item.sale_price == 4488
        assert item.unit == "200g"
        assert item.package_quantity == 200
        assert item.price_per_100g == 2244
        assert item.attributes["storage_type"] == "frozen"
        assert item.attributes["origin"] == "vietnam"
        assert item.attributes["cut"] == "shrimp_meat"

    def test_emart_preserves_peacock_as_collection_not_category(self):
        crawler = EmartCrawler()
        item = crawler._next_data_to_discount_item({
            "itemName": "한돈으로 만든 햄꼬마김밥키트157g",
            "finalPrice": "6,980",
            "sellUnitCapacity": "157g",
            "brandName": "피코크",
            "siteName": "이마트",
        })

        assert item is not None
        assert item.category == ""
        assert item.attributes["collection"] == "피코크"
        assert item.package_quantity == 157
        assert item.price_per_100g == 4445.86

    def test_emart_next_data_preserves_source_urls_prices_and_collection(self):
        crawler = EmartCrawler()
        item = crawler._next_data_to_discount_item({
            "itemId": "100",
            "itemName": "피코크 왕교자 700g",
            "finalPrice": "6,980",
            "originalPrice": "8,980",
            "brandName": "피코크",
            "itemImgUrl": "//img.ssgcdn.com/transient/mandu.jpg",
            "itemUrl": "/item/itemView.ssg?itemId=100",
            "siteName": "이마트",
            "categoryName": "냉동/간편식",
        })

        assert item is not None
        assert item.sale_price == 6980
        assert item.original_price == 8980
        assert item.discount_percent == pytest.approx(22.3)
        assert item.image_url == "https://img.ssgcdn.com/transient/mandu.jpg"
        assert item.detail_url == "https://emart.ssg.com/item/itemView.ssg?itemId=100"
        assert item.category == "냉동/간편식"
        assert item.attributes["collection"] == "피코크"
        assert item.attributes["source_record_key"] == "100"
        assert item.attributes["source_url"] == item.detail_url
        assert item.attributes["image_url"] == item.image_url
        assert item.attributes["category_hint"] == "냉동/간편식"
        assert item.unit == "700g"

    @pytest.mark.asyncio
    async def test_emart_next_data_collects_multiple_categories_with_period_and_source_keys(self):
        crawler = EmartCrawler()
        html = """
        <script id="__NEXT_DATA__" type="application/json">{
          "props":{"pageProps":{"dehydratedState":{"queries":[{"state":{"data":{"areaList":[
            {"title":"채소","dataList":[
              {"itemId":"veg-1","itemName":"양파 1kg","finalPrice":"3,980","itemUrl":"/item/veg-1","itemImgUrl":"/img/veg.jpg","sellUnitCapacity":"1kg","eventStartDate":"2026-03-18","eventEndDate":"2026-03-24"}
            ]},
            {"title":"정육","dataList":[
              {"itemId":"meat-1","itemName":"삼겹살 600g","finalPrice":"12,900","itemUrl":"/item/meat-1","itemImgUrl":"/img/meat.jpg","sellUnitCapacity":"600g"},
              {"itemId":"veg-1","itemName":"양파 1kg","finalPrice":"3,980","itemUrl":"/item/veg-1","itemImgUrl":"/img/veg.jpg","sellUnitCapacity":"1kg"}
            ]}
          ]}}}]}}}
        }</script>
        """

        items = await crawler.parse(html)

        assert [item.attributes["source_record_key"] for item in items] == ["veg-1", "meat-1"]
        assert {item.category for item in items} == {"채소", "정육"}
        assert items[0].valid_from is not None
        assert items[0].valid_until is not None
        assert items[0].attributes["period"] == "2026-03-18~2026-03-24"

    def test_emart_source_requests_cover_categories_and_pagination(self):
        crawler = EmartCrawler()
        crawler.SEARCH_QUERIES = ["행사"]
        crawler.CATEGORY_QUERIES = ["채소", "정육"]
        crawler.MAX_PAGES = 2

        requests = crawler._build_source_requests()

        assert [req["page"] for req in requests if req["query"] == "채소"] == [1, 2]
        assert any("query=%EC%A0%95%EC%9C%A1" in req["url"] for req in requests)

    @pytest.mark.asyncio
    async def test_emart_crawl_dedupes_overlapping_pages_before_counts(self):
        crawler = EmartCrawler()
        crawler.SEARCH_QUERIES = ["행사"]
        crawler.CATEGORY_QUERIES = ["채소"]
        crawler.MAX_PAGES = 1
        crawler._anti_detect = MagicMock()
        crawler._anti_detect.get_random_headers.return_value = {}
        crawler._anti_detect.get_random_delay.return_value = 0
        response = MagicMock(status_code=200, text=MOCK_EMART_HTML)

        with patch.object(crawler, "_retry_request", return_value=response):
            result = await crawler.crawl()

        assert result.status == CrawlStatus.SUCCESS
        assert result.items_count == 2
        assert result.quality_details["item_counts"]["raw"] == 2
        assert result.quality_details["item_counts"]["duplicates_after_validation"] == 0


class TestHomeplusParse:
    """홈플러스 크롤러 파싱 테스트."""

    @pytest.mark.asyncio
    async def test_parse_html_items(self):
        """HTML에서 상품을 파싱한다."""
        crawler = HomeplusCrawler()
        items = await crawler.parse(MOCK_HOMEPLUS_HTML)
        assert len(items) >= 1

    @pytest.mark.asyncio
    async def test_parse_discount_calculation(self):
        """할인율이 올바르게 계산된다."""
        crawler = HomeplusCrawler()
        items = await crawler.parse(MOCK_HOMEPLUS_HTML)
        discounted = [i for i in items if i.discount_percent is not None]
        if discounted:
            item = discounted[0]
            assert 0 < item.discount_percent < 100
            assert item.original_price > item.sale_price

    @pytest.mark.asyncio
    async def test_mfront_preserves_real_source_shaped_fields(self):
        """mfront 상품 카드에서 가격·단위·이미지·상세 URL을 보존한다."""
        crawler = HomeplusCrawler()
        items = await crawler.parse(MOCK_HOMEPLUS_MFRONT_HTML)

        assert len(items) == 1
        item = items[0]
        assert item.name == "서울우유 1L"
        assert item.sale_price == 2480
        assert item.original_price == 3100
        assert item.discount_percent == 20.0
        assert item.unit == "1L"
        assert item.package_quantity == 1
        assert item.package_unit == "L"
        assert item.image_url == "https://image.homeplus.test/milk.jpg"
        assert item.detail_url == "https://mfront.homeplus.co.kr/item?itemNo=milk-1"

    def test_homeplus_json_preserves_unit_and_source_fields(self):
        crawler = HomeplusCrawler()
        item = crawler._json_to_discount_item({
            "goodsNo": "beef-1",
            "goodsNm": "호주산 척아이롤 500g",
            "salePrice": "12900",
            "originPrice": "15900",
            "unit": "500g",
            "imgUrl": "https://image.homeplus.test/beef.jpg",
            "goodsUrl": "/goods/detail?goodsNo=beef-1",
            "categoryNm": "정육",
        })

        assert item is not None
        assert item.sale_price == 12900
        assert item.original_price == 15900
        assert item.discount_percent == pytest.approx(18.9)
        assert item.unit == "500g"
        assert item.category == "정육"
        assert item.image_url == "https://image.homeplus.test/beef.jpg"
        assert item.detail_url == "https://www.homeplus.co.kr/goods/detail?goodsNo=beef-1"
        assert item.attributes["source_record_key"] == "beef-1"
        assert item.attributes["source_url"] == item.detail_url

    def test_homeplus_source_requests_are_bounded_by_query_category_and_page(self):
        crawler = HomeplusCrawler()
        crawler.SEARCH_QUERIES = ["행사"]
        crawler.CATEGORY_QUERIES = ["유제품"]
        crawler.MAX_PAGES = 2
        crawler.MAX_REQUESTS = None

        requests = crawler._build_source_requests()

        assert len(requests) == 4
        assert requests[2]["category_hint"] == "유제품"
        assert requests[3]["url"].endswith("&page=2")

    @pytest.mark.asyncio
    async def test_homeplus_validate_dedupes_by_source_record_key_for_incremental_update(self):
        crawler = HomeplusCrawler()
        first = crawler._json_to_discount_item({
            "goodsNo": "hp-1",
            "goodsNm": "두부 300g",
            "salePrice": "1980",
            "goodsUrl": "/goods/detail?goodsNo=hp-1",
        })
        updated = crawler._json_to_discount_item({
            "goodsNo": "hp-1",
            "goodsNm": "두부 300g",
            "salePrice": "1780",
            "goodsUrl": "/goods/detail?goodsNo=hp-1",
        })

        valid = await crawler.validate([first, updated])

        assert len(valid) == 1
        assert valid[0].attributes["source_record_key"] == "hp-1"

    def test_homeplus_dedupes_before_collection_counts(self):
        crawler = HomeplusCrawler()
        first = crawler._json_to_discount_item({
            "goodsNo": "hp-1",
            "goodsNm": "두부 300g",
            "salePrice": "1980",
            "goodsUrl": "/goods/detail?goodsNo=hp-1",
        })
        duplicate = crawler._json_to_discount_item({
            "goodsNo": "hp-1",
            "goodsNm": "두부 300g",
            "salePrice": "1980",
            "goodsUrl": "/goods/detail?goodsNo=hp-1",
        })

        assert first is not None
        assert duplicate is not None
        assert crawler._dedupe_items([first, duplicate]) == [first]


class TestLottemartParse:
    """롯데마트 크롤러 파싱 테스트."""

    @pytest.mark.asyncio
    async def test_parse_html_items(self):
        """HTML에서 상품을 파싱한다."""
        crawler = LottemartCrawler()
        items = await crawler.parse(MOCK_LOTTEMART_HTML)
        assert len(items) >= 1

    @pytest.mark.asyncio
    async def test_parsed_store_name(self):
        """파싱된 상품의 매장명이 '롯데마트'이다."""
        crawler = LottemartCrawler()
        items = await crawler.parse(MOCK_LOTTEMART_HTML)
        for item in items:
            assert item.store == "롯데마트"

    def test_initial_state_preserves_count_and_source_owned_fields(self):
        crawler = LottemartCrawler()
        html = """
        <html><script>window.__INITIAL_STATE__={
          "data":{"products":{"productEntities":{
            "sku-1":{
              "name":"[행사] 오늘좋은 생수 2L*6입",
              "price":{"current":{"amount":"2,990"},"original":{"amount":"3,990"}},
              "image":{"src":"https://image.lottemart.test/water.jpg"},
              "categoryPath":["생수/음료","생수"],
              "size":{"value":"2L*6입"},
              "offer":{"description":"주간특가"},
              "url":"/products/sku-1",
              "brand":"오늘좋은"
            }
          }}}
        };</script></html>
        """

        assert crawler.count_raw_candidates(html) == 1
        items = crawler._extract_from_initial_state(html)
        assert len(items) == 1
        item = items[0]
        assert item.name == "오늘좋은 생수 2L*6입"
        assert item.sale_price == 2990
        assert item.original_price == 3990
        assert item.category == "생수/음료"
        assert item.event_name == "주간특가"
        assert item.image_url == "https://image.lottemart.test/water.jpg"
        assert item.detail_url == "https://lottemartzetta.com/products/sku-1"
        assert item.attributes["source_record_key"] == "sku-1"
        assert item.attributes["category_path"] == ["생수/음료", "생수"]
        assert item.attributes["source_url"] == item.detail_url

    def test_lottemart_source_requests_include_category_pagination(self):
        crawler = LottemartCrawler()
        crawler.SEARCH_QUERIES = ["특가"]
        crawler.CATEGORY_QUERIES = ["생수"]
        crawler.MAX_PAGES = 2

        requests = crawler._build_source_requests()

        assert [req["page"] for req in requests] == [1, 2, 1, 2]
        assert requests[2]["category_hint"] == "생수"
        assert "page=2" in requests[3]["url"]

    @pytest.mark.asyncio
    async def test_lottemart_validate_uses_source_key_not_price_for_incremental_update(self):
        crawler = LottemartCrawler()
        first = crawler._entity_to_discount_item({
            "name": "오늘좋은 생수 2L*6입",
            "price": {"current": {"amount": "2,990"}},
            "url": "/products/water-1",
        }, "water-1")
        updated = crawler._entity_to_discount_item({
            "name": "오늘좋은 생수 2L*6입",
            "price": {"current": {"amount": "2,690"}},
            "url": "/products/water-1",
        }, "water-1")

        valid = await crawler.validate([first, updated])

        assert len(valid) == 1
        assert valid[0].attributes["source_record_key"] == "water-1"


# --- JSON 파싱 테스트 ---

class TestJsonParsing:
    """페이지 내 임베디드 JSON 파싱 테스트."""

    @pytest.mark.asyncio
    async def test_emart_json_parsing(self):
        """이마트 크롤러가 임베디드 JSON을 파싱한다."""
        crawler = EmartCrawler()
        items = await crawler.parse(MOCK_JSON_PAGE)
        # 빈 이름과 가격 0 제외 → 2개
        valid = [i for i in items if i.sale_price > 0 and len(i.name) >= 2]
        assert len(valid) == 2

    @pytest.mark.asyncio
    async def test_json_discount_calculation(self):
        """JSON 파싱 시 할인율이 계산된다."""
        crawler = EmartCrawler()
        items = await crawler.parse(MOCK_JSON_PAGE)
        valid = [i for i in items if i.discount_percent is not None]
        assert len(valid) >= 1
        for item in valid:
            assert 0 < item.discount_percent < 100


# --- 검증(validate) 테스트 ---

class TestValidation:
    """크롤러 validate 메서드 테스트."""

    @pytest.mark.asyncio
    async def test_removes_duplicates(self):
        """중복 상품을 제거한다."""
        crawler = EmartCrawler()
        items = [
            DiscountItem(name="양파 1kg", store="이마트", sale_price=3000),
            DiscountItem(name="양파 1kg", store="이마트", sale_price=3000),
            DiscountItem(name="감자 2kg", store="이마트", sale_price=4000),
        ]
        valid = await crawler.validate(items)
        assert len(valid) == 2

    @pytest.mark.asyncio
    async def test_removes_invalid_price(self):
        """가격이 0 이하인 상품을 제거한다."""
        crawler = HomeplusCrawler()
        items = [
            DiscountItem(name="양파 1kg", store="홈플러스", sale_price=3000),
            DiscountItem(name="감자 2kg", store="홈플러스", sale_price=0),
            DiscountItem(name="대파", store="홈플러스", sale_price=-100),
        ]
        valid = await crawler.validate(items)
        assert len(valid) == 1

    @pytest.mark.asyncio
    async def test_removes_short_name(self):
        """이름이 너무 짧은 상품을 제거한다."""
        crawler = LottemartCrawler()
        items = [
            DiscountItem(name="X", store="롯데마트", sale_price=1000),
            DiscountItem(name="감귤 3kg", store="롯데마트", sale_price=9900),
        ]
        valid = await crawler.validate(items)
        assert len(valid) == 1
        assert valid[0].name == "감귤 3kg"


# --- DiscountItem → ProductPrice 변환 테스트 ---

class TestDiscountItemConversion:
    """DiscountItem.to_product_price() 변환 테스트."""

    def test_to_product_price(self):
        """DiscountItem이 ProductPrice로 변환된다."""
        item = DiscountItem(
            name="양파 1kg",
            store="이마트",
            original_price=5000,
            sale_price=3000,
            discount_percent=40.0,
            category="채소류",
        )
        pp = item.to_product_price()
        assert pp.product_name == "양파 1kg"
        assert pp.store == "이마트"
        assert pp.price == 3000
        assert pp.original_price == 5000
        assert pp.discount_rate == pytest.approx(0.4)


# --- 크롤링 (mock HTTP) 테스트 ---

class TestCrawlWithMock:
    """모의 HTTP 응답으로 크롤링 전체 흐름 테스트."""

    @pytest.mark.asyncio
    async def test_emart_crawl_success(self):
        """이마트 크롤링 성공 시 CrawlResult를 반환한다."""
        from engine.anti_detect import AntiDetect
        crawler = EmartCrawler(anti_detect=AntiDetect(delay_min=0.0, delay_max=0.01))
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = MOCK_EMART_HTML
        mock_resp.encoding = "utf-8"

        with patch("crawlers.marts.emart.crawler.requests.get", return_value=mock_resp):
            result = await crawler.crawl()

        assert result.status == CrawlStatus.SUCCESS
        assert result.crawler_name == "이마트"
        assert result.items_count >= 0
        assert result.quality_score is not None
        assert result.quality_details["coverage"]["sale_price"] == 1.0
        assert "zero_valid_items" not in result.quality_details["alerts"]

    @pytest.mark.asyncio
    async def test_homeplus_crawl_success(self):
        """홈플러스 크롤링 성공 시 CrawlResult를 반환한다."""
        crawler = HomeplusCrawler()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = MOCK_HOMEPLUS_HTML
        mock_resp.encoding = "utf-8"
        mock_resp.url = "https://front.homeplus.co.kr/event/eventMain.do"

        # 홈플러스는 SPA이므로 Playwright를 먼저 시도함 → mock으로 빈 결과 반환
        # HTTP fallback에서 mock_resp로 상품 수집
        with patch("crawlers.marts.homeplus.crawler.requests.get", return_value=mock_resp), \
             patch.object(crawler, "_fetch_via_playwright", return_value=([], 0)):
            result = await crawler.crawl()

        assert result.status == CrawlStatus.SUCCESS
        assert result.crawler_name == "홈플러스"
        assert result.strategy_used == "requests"
        assert "fallback_used" in result.quality_details["alerts"]

    @pytest.mark.asyncio
    async def test_homeplus_bounded_request_limit_skips_http_fallback(self):
        """Bounded Homeplus diagnostics do not exceed the approved one-request cap."""
        crawler = HomeplusCrawler()
        crawler.MAX_ITEMS = 2
        crawler.MAX_PAGES = 1
        crawler.MAX_REQUESTS = 1

        with patch("crawlers.marts.homeplus.crawler.requests.get") as mock_get, \
             patch.object(crawler, "_fetch_via_playwright", return_value=([], 1)):
            result = await crawler.crawl()

        mock_get.assert_not_called()
        assert result.status == CrawlStatus.FAILED
        assert result.strategy_used == "playwright"
        assert "fallback_used" not in result.quality_details["alerts"]

    @pytest.mark.asyncio
    async def test_lottemart_crawl_success(self):
        """롯데마트 크롤링 성공 시 CrawlResult를 반환한다."""
        from engine.anti_detect import AntiDetect
        crawler = LottemartCrawler(anti_detect=AntiDetect(delay_min=0.0, delay_max=0.01))
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = MOCK_LOTTEMART_HTML
        mock_resp.encoding = "utf-8"
        mock_resp.url = "https://lottemartzetta.com/search?query=test"

        with patch("crawlers.marts.lottemart.crawler.requests.Session.get", return_value=mock_resp), \
             patch.object(crawler, "_fetch_via_playwright", return_value=[]):
            result = await crawler.crawl()

        assert result.status == CrawlStatus.SUCCESS
        assert result.crawler_name == "롯데마트"
        assert result.quality_details["fetch"]["fallback_used"] is True

    @pytest.mark.asyncio
    async def test_lottemart_crawl_zero_valid_items_fails_without_silent_success(self):
        """HTTP 200이어도 유효 상품이 없으면 성공으로 처리하지 않는다."""
        from engine.anti_detect import AntiDetect
        crawler = LottemartCrawler(anti_detect=AntiDetect(delay_min=0.0, delay_max=0.01))
        crawler.SEARCH_QUERIES = ["테스트"]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body>no products</body></html>"
        mock_resp.encoding = "utf-8"
        mock_resp.url = "https://lottemartzetta.com/search?query=test"

        with patch("crawlers.marts.lottemart.crawler.requests.Session.get", return_value=mock_resp), \
             patch.object(crawler, "_fetch_via_playwright", return_value=[]):
            result = await crawler.crawl()

        assert result.status == CrawlStatus.FAILED
        assert result.items_count == 0
        assert result.quality_details["alerts"]

    @pytest.mark.asyncio
    async def test_crawl_http_error(self):
        """HTTP 에러 시 FAILED 상태를 반환한다."""
        from engine.anti_detect import AntiDetect
        crawler = EmartCrawler(anti_detect=AntiDetect(delay_min=0.0, delay_max=0.01))
        crawler.SEARCH_QUERIES = ["테스트"]
        crawler.MAX_PAGES = 1
        mock_resp = MagicMock()
        mock_resp.status_code = 403

        with patch("crawlers.marts.emart.crawler.requests.get", return_value=mock_resp):
            result = await crawler.crawl()

        assert result.status == CrawlStatus.FAILED
        assert result.error_msg
        assert result.errors
        assert result.quality_details["alerts"]

    @pytest.mark.asyncio
    async def test_emart_zero_source_rows_has_actionable_diagnostics(self):
        """HTTP 200 + 원천 후보 0건은 source-zero 원인으로 진단한다."""
        from engine.anti_detect import AntiDetect
        crawler = EmartCrawler(anti_detect=AntiDetect(delay_min=0.0, delay_max=0.01))
        crawler.SEARCH_QUERIES = ["테스트"]
        crawler.MAX_PAGES = 1
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body>no products</body></html>"
        mock_resp.encoding = "utf-8"

        with patch("crawlers.marts.emart.crawler.requests.get", return_value=mock_resp):
            result = await crawler.crawl()

        diagnostic = result.quality_details["zero_result_diagnostic"]
        assert result.status == CrawlStatus.FAILED
        assert diagnostic["stage"] == "source_zero_raw_rows"
        assert "network" in diagnostic["message"].lower() or "source" in diagnostic["message"].lower()
        assert "zero_source_raw_rows" in result.quality_details["alerts"]
        assert result.error_msg
        assert result.errors[0].error_type.value == "empty_response"

    @pytest.mark.asyncio
    async def test_emart_raw_rows_not_parsed_has_selector_diagnostics(self):
        """원천 후보는 있으나 파싱 결과 0건이면 셀렉터/파싱 문제로 진단한다."""
        from engine.anti_detect import AntiDetect
        crawler = EmartCrawler(anti_detect=AntiDetect(delay_min=0.0, delay_max=0.01))
        crawler.SEARCH_QUERIES = ["테스트"]
        crawler.MAX_PAGES = 1
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = """
        <html><body>
          <div class="cunit_prod"><span class="cunit_md">양파 1kg</span></div>
        </body></html>
        """
        mock_resp.encoding = "utf-8"

        with patch("crawlers.marts.emart.crawler.requests.get", return_value=mock_resp):
            result = await crawler.crawl()

        diagnostic = result.quality_details["zero_result_diagnostic"]
        assert result.status == CrawlStatus.FAILED
        assert diagnostic["stage"] == "parse_filtered_all_raw_rows"
        assert "selector" in diagnostic["message"].lower() or "parser" in diagnostic["message"].lower()
        assert "raw_rows_not_parsed" in result.quality_details["alerts"]
        assert result.errors[0].error_type.value == "parse_error"

    @pytest.mark.asyncio
    async def test_emart_validation_rejected_all_rows_has_validation_diagnostics(self):
        """파싱 row가 모두 validate에서 탈락하면 validation 원인으로 진단한다."""
        from engine.anti_detect import AntiDetect
        crawler = EmartCrawler(anti_detect=AntiDetect(delay_min=0.0, delay_max=0.01))
        crawler.SEARCH_QUERIES = ["테스트"]
        crawler.MAX_PAGES = 1
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body>patched parse</body></html>"
        mock_resp.encoding = "utf-8"
        parsed_item = DiscountItem(name="양파 1kg", store="이마트", sale_price=0)

        with patch("crawlers.marts.emart.crawler.requests.get", return_value=mock_resp), \
             patch.object(crawler, "_count_raw_candidates", return_value=1), \
             patch.object(crawler, "parse", return_value=[parsed_item]):
            result = await crawler.crawl()

        diagnostic = result.quality_details["zero_result_diagnostic"]
        assert result.status == CrawlStatus.FAILED
        assert diagnostic["stage"] == "validation_rejected_all_rows"
        assert "validation" in diagnostic["message"].lower()
        assert "validation_rejected_all_rows" in result.quality_details["alerts"]

    @pytest.mark.asyncio
    async def test_crawl_json_page(self):
        """JSON 임베디드 페이지에서 크롤링 성공."""
        from engine.anti_detect import AntiDetect
        crawler = EmartCrawler(anti_detect=AntiDetect(delay_min=0.0, delay_max=0.01))
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = MOCK_JSON_PAGE
        mock_resp.encoding = "utf-8"

        with patch("crawlers.marts.emart.crawler.requests.get", return_value=mock_resp):
            result = await crawler.crawl()

        assert result.status == CrawlStatus.SUCCESS
        assert result.items_count == 2


# --- __INITIAL_STATE__ 파싱 테스트 (롯데마트 Zetta) ---

MOCK_INITIAL_STATE_HTML = """
<html><head><script>
window.__INITIAL_STATE__={"data":{"products":{"productEntities":{
"uuid-001":{"name":"[할인] 신선 양파 1.5kg","price":{"original":{"amount":"5980","currency":"KRW"},"current":{"amount":"3980","currency":"KRW"}},"image":{"src":"https://img.test/yangpa.jpg"},"categoryPath":["채소"],"size":{"value":"1.5kg"},"offer":{"description":"주간특가"},"brand":"","productId":"uuid-001"},
"uuid-002":{"name":"국내산 삼겹살 600g","price":{"original":{"amount":"18900","currency":"KRW"},"current":{"amount":"12900","currency":"KRW"}},"image":{"src":"https://img.test/samgyup.jpg"},"categoryPath":["정육"],"size":{"value":"600g"},"offer":{"description":"롯데마트 할인"},"brand":"롯데축산","productId":"uuid-002"},
"uuid-003":{"name":"X","price":{"original":{"amount":"100","currency":"KRW"},"current":{"amount":"0","currency":"KRW"}},"image":{},"categoryPath":[],"size":{},"offer":{},"brand":"","productId":"uuid-003"}
}},"search":{}}}</script></head><body></body></html>
"""


class TestLottemartInitialState:
    """롯데마트 __INITIAL_STATE__ 파싱 테스트."""

    @pytest.mark.asyncio
    async def test_parse_initial_state(self):
        """__INITIAL_STATE__에서 상품을 파싱한다."""
        crawler = LottemartCrawler()
        items = await crawler.parse(MOCK_INITIAL_STATE_HTML)
        # 이름 1자("X")와 가격 0인 상품 제외 → 2개
        valid = [i for i in items if i.sale_price > 0 and len(i.name) >= 2]
        assert len(valid) == 2

    @pytest.mark.asyncio
    async def test_initial_state_fields(self):
        """__INITIAL_STATE__ 파싱 시 필드가 올바르게 추출된다."""
        crawler = LottemartCrawler()
        items = await crawler.parse(MOCK_INITIAL_STATE_HTML)
        valid = [i for i in items if i.sale_price > 0 and len(i.name) >= 2]
        assert len(valid) >= 1
        item = valid[0]
        assert item.store == "롯데마트"
        assert item.sale_price > 0
        assert item.image_url != ""

    @pytest.mark.asyncio
    async def test_initial_state_discount_calc(self):
        """__INITIAL_STATE__ 파싱 시 할인율이 계산된다."""
        crawler = LottemartCrawler()
        items = await crawler.parse(MOCK_INITIAL_STATE_HTML)
        discounted = [i for i in items if i.discount_percent is not None and i.discount_percent > 0]
        assert len(discounted) >= 1
        for item in discounted:
            assert 0 < item.discount_percent < 100
            assert item.original_price > item.sale_price

    @pytest.mark.asyncio
    async def test_initial_state_promotion_prefix_removed(self):
        """프로모션 접두사([할인])가 상품명에서 제거된다."""
        crawler = LottemartCrawler()
        items = await crawler.parse(MOCK_INITIAL_STATE_HTML)
        yangpa = [i for i in items if "양파" in i.name]
        assert len(yangpa) == 1
        assert not yangpa[0].name.startswith("[")

    def test_initial_state_preserves_unit_url_and_keeps_brand_out_of_category(self):
        crawler = LottemartCrawler()
        item = crawler._entity_to_discount_item({
            "name": "롯데한우 등심 300g",
            "price": {
                "original": {"amount": "19800"},
                "current": {"amount": "14850"},
            },
            "image": {"src": "https://img.lottemart.test/beef.jpg"},
            "categoryPath": [],
            "size": {"value": "300g"},
            "offer": {"description": "주간특가"},
            "brand": "롯데축산",
            "url": "/products/beef-300",
        }, "beef-300")

        assert item is not None
        assert item.sale_price == 14850
        assert item.original_price == 19800
        assert item.discount_percent == 25.0
        assert item.unit == "300g"
        assert item.package_quantity == 300
        assert item.package_unit == "g"
        assert item.price_per_100g == 4950
        assert item.image_url == "https://img.lottemart.test/beef.jpg"
        assert item.detail_url == "https://lottemartzetta.com/products/beef-300"
        assert item.category == ""
        assert item.attributes["brand"] == "롯데축산"


# --- 실제 사이트 통합 테스트 (live integration) ---
# pytest -m live 로 실행 (기본 실행에서는 스킵)

@pytest.mark.live
class TestLiveEmart:
    """이마트 크롤러 실제 사이트 통합 테스트."""

    @pytest.mark.asyncio
    async def test_emart_live_crawl(self):
        """이마트 실제 크롤링: 100개 이상 수집, 스키마 검증."""
        from engine.anti_detect import AntiDetect
        crawler = EmartCrawler(anti_detect=AntiDetect(delay_min=0.5, delay_max=1.0))
        result = await crawler.crawl()

        assert result.status == CrawlStatus.SUCCESS, f"크롤링 실패: {result.error_msg}"
        assert result.items_count > 50, f"상품 수 부족: {result.items_count}개 (50개 이상 필요)"

        # 스키마 검증
        for item in result.items:
            assert isinstance(item["name"], str) and len(item["name"]) >= 2
            assert isinstance(item["sale_price"], int) and item["sale_price"] > 0
            # SSG 통합 검색이므로 이마트/트레이더스 등 다양한 매장 포함
            assert isinstance(item.get("store", ""), str) and len(item.get("store", "")) >= 1

        # 중복 검사
        keys = [f"{i['name']}_{i['sale_price']}" for i in result.items]
        assert len(keys) == len(set(keys)), "중복 상품 발견"

        # 로그 기록
        _write_live_log("emart", result)


@pytest.mark.live
class TestLiveLottemart:
    """롯데마트 크롤러 실제 사이트 통합 테스트."""

    @pytest.mark.asyncio
    async def test_lottemart_live_crawl(self):
        """롯데마트 실제 크롤링: 50개 이상 수집, 스키마 검증."""
        from engine.anti_detect import AntiDetect
        crawler = LottemartCrawler(anti_detect=AntiDetect(delay_min=0.5, delay_max=1.0))
        result = await crawler.crawl()

        assert result.status == CrawlStatus.SUCCESS, f"크롤링 실패: {result.error_msg}"
        assert result.items_count > 30, f"상품 수 부족: {result.items_count}개 (30개 이상 필요)"

        # 스키마 검증
        for item in result.items:
            assert isinstance(item["name"], str) and len(item["name"]) >= 2
            assert isinstance(item["sale_price"], int) and item["sale_price"] > 0
            assert item.get("store") == "롯데마트"

        # 중복 검사
        keys = [f"{i['name']}_{i['sale_price']}" for i in result.items]
        assert len(keys) == len(set(keys)), "중복 상품 발견"

        _write_live_log("lottemart", result)


@pytest.mark.live
class TestLiveHomeplus:
    """홈플러스 크롤러 실제 사이트 통합 테스트 (Playwright 필요)."""

    @pytest.mark.asyncio
    async def test_homeplus_live_crawl(self):
        """홈플러스 실제 크롤링: 50개 이상 수집, 스키마 검증."""
        crawler = HomeplusCrawler()
        result = await crawler.crawl()

        assert result.status == CrawlStatus.SUCCESS, f"크롤링 실패: {result.error_msg}"
        assert result.items_count > 30, f"상품 수 부족: {result.items_count}개 (30개 이상 필요)"

        # 스키마 검증
        for item in result.items:
            assert isinstance(item["name"], str) and len(item["name"]) >= 2
            assert isinstance(item["sale_price"], int) and item["sale_price"] > 0
            assert item.get("store") == "홈플러스"

        # 중복 검사
        keys = [f"{i['name']}_{i['sale_price']}" for i in result.items]
        assert len(keys) == len(set(keys)), "중복 상품 발견"

        _write_live_log("homeplus", result)


def _write_live_log(crawler_name: str, result):
    """실제 크롤링 결과를 로그 파일에 기록한다."""
    import os
    from datetime import datetime

    log_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "error-log")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"live_crawl_{crawler_name}.log")

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"\n{'='*60}\n")
        f.write(f"[{datetime.now().isoformat()}] {crawler_name} 실제 크롤링 결과\n")
        f.write(f"상태: {result.status}\n")
        f.write(f"전략: {result.strategy_used}\n")
        f.write(f"수집: {result.items_count}개\n")
        f.write(f"소요: {result.duration_seconds:.2f}초\n")
        if result.error_msg:
            f.write(f"오류: {result.error_msg}\n")
        f.write(f"--- 샘플 (최대 5개) ---\n")
        for i, item in enumerate(result.items[:5]):
            name = item.get("name", "?")
            sale = item.get("sale_price", "?")
            orig = item.get("original_price", "?")
            disc = item.get("discount_percent", "?")
            f.write(f"  [{i+1}] {name} | 할인가={sale} | 원가={orig} | 할인율={disc}%\n")
        f.write(f"{'='*60}\n")
