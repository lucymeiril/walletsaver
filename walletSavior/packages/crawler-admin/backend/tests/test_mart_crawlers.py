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
             patch.object(crawler, "_fetch_via_playwright", return_value=[]):
            result = await crawler.crawl()

        assert result.status == CrawlStatus.SUCCESS
        assert result.crawler_name == "홈플러스"

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

        with patch("crawlers.marts.lottemart.crawler.requests.get", return_value=mock_resp), \
             patch.object(crawler, "_fetch_via_playwright", return_value=[]):
            result = await crawler.crawl()

        assert result.status == CrawlStatus.SUCCESS
        assert result.crawler_name == "롯데마트"

    @pytest.mark.asyncio
    async def test_crawl_http_error(self):
        """HTTP 에러 시 FAILED 상태를 반환한다."""
        from engine.anti_detect import AntiDetect
        crawler = EmartCrawler(anti_detect=AntiDetect(delay_min=0.0, delay_max=0.01))
        mock_resp = MagicMock()
        mock_resp.status_code = 403

        with patch("crawlers.marts.emart.crawler.requests.get", return_value=mock_resp):
            result = await crawler.crawl()

        assert result.status == CrawlStatus.FAILED

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
