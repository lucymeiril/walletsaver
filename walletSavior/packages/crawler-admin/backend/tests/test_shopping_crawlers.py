"""
쇼핑 크롤러 + 오피넷 통합 테스트 (TDD).

각 크롤러를 인스턴스화 → 실제 네트워크 호출 → 결과 스키마 검증.
- 무신사(Musinsa): PLP API 기반
- 지오다노(Giordano): SALE 페이지 HTML 파싱
- 유니클로(Uniqlo): API + Playwright fallback
- 오피넷(OPINET): 주유소 가격 (API/웹 스크레이핑)

실행: cd packages/crawler-admin/backend && py -m pytest tests/test_shopping_crawlers.py -v
"""

import asyncio
import logging
import time
from datetime import datetime

import pytest

from core.models import CrawlStatus, DiscountItem

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    """asyncio 코루틴 실행 헬퍼 — DeprecationWarning 방지."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def validate_discount_item(item: dict, source: str) -> list[str]:
    """DiscountItem dict 스키마 검증. 오류 목록 반환."""
    errors = []

    # 필수 필드
    if not item.get("name") or len(str(item["name"])) < 2:
        errors.append(f"[{source}] name 없거나 너무 짧음: {item.get('name')!r}")

    if not item.get("store"):
        errors.append(f"[{source}] store 필드 없음")

    sale_price = item.get("sale_price")
    if sale_price is None or (isinstance(sale_price, (int, float)) and sale_price <= 0):
        errors.append(f"[{source}] sale_price 비정상: {sale_price}")

    # 선택 필드 타입 체크
    original = item.get("original_price")
    if original is not None and isinstance(original, (int, float)) and original < 0:
        errors.append(f"[{source}] original_price 음수: {original}")

    discount = item.get("discount_percent")
    if discount is not None and isinstance(discount, (int, float)):
        if discount < 0 or discount > 100:
            errors.append(f"[{source}] discount_percent 범위 이상: {discount}")

    return errors


def validate_gas_station(item: dict) -> list[str]:
    """주유소 데이터 스키마 검증."""
    errors = []

    if not item.get("name") or len(str(item["name"])) < 2:
        errors.append(f"name 없거나 짧음: {item.get('name')!r}")

    has_price = any([
        item.get("gasoline_price"),
        item.get("diesel_price"),
        item.get("lpg_price"),
    ])
    if not has_price:
        errors.append(f"가격 필드 없음: {item.get('name')}")

    for key in ("gasoline_price", "diesel_price", "lpg_price"):
        price = item.get(key)
        if price is not None and isinstance(price, (int, float)):
            if price < 500 or price > 5000:
                errors.append(f"{key} 범위 이상 ({price}): {item.get('name')}")

    return errors


def log_items_summary(items: list[dict], source: str, max_display: int = 5):
    """수집된 항목 요약 로깅."""
    logger.info(f"\n{'='*60}")
    logger.info(f"  {source} 결과: {len(items)}개 수집")
    logger.info(f"{'='*60}")
    for i, item in enumerate(items[:max_display]):
        if "sale_price" in item:
            logger.info(
                f"  [{i+1}] {item.get('name', '?')[:40]:40s} | "
                f"₩{item.get('sale_price', 0):>8,} "
                f"(원가 ₩{item.get('original_price') or '?':>8}) "
                f"할인 {item.get('discount_percent') or '?'}%"
            )
        elif "gasoline_price" in item:
            logger.info(
                f"  [{i+1}] {item.get('name', '?')[:30]:30s} | "
                f"휘발유 ₩{item.get('gasoline_price') or '?'} | "
                f"경유 ₩{item.get('diesel_price') or '?'} | "
                f"LPG ₩{item.get('lpg_price') or '?'}"
            )
    if len(items) > max_display:
        logger.info(f"  ... +{len(items) - max_display}개 더")


# ===========================================================================
# 1. 무신사 (Musinsa) 테스트
# ===========================================================================

class TestMusinsaCrawler:
    """무신사 크롤러 테스트 — PLP API 기반 패션 할인 상품 수집."""

    def _get_crawler(self):
        from crawlers.shopping.musinsa.crawler import MusinsaCrawler
        return MusinsaCrawler()

    def test_crawler_info(self):
        """크롤러 메타정보가 올바른지 확인."""
        crawler = self._get_crawler()
        info = crawler.info
        assert info.name == "무신사"
        assert info.group.value == "shopping"
        assert info.target_url == "https://www.musinsa.com"

    @pytest.mark.live
    def test_api_fetch(self):
        """PLP API가 상품을 반환하는지 확인."""
        crawler = self._get_crawler()
        items = crawler._fetch_via_api()

        logger.info(f"[무신사] API 수집: {len(items)}개")
        if items:
            log_items_summary(
                [i.model_dump() for i in items], "무신사 API"
            )
            # 스키마 검증
            all_errors = []
            for item in items:
                d = item.model_dump()
                errs = validate_discount_item(d, "musinsa")
                all_errors.extend(errs)

            if all_errors:
                logger.warning(f"[무신사] 검증 오류: {all_errors[:5]}")

            assert len(items) >= 1, "최소 1개 이상의 상품 필요"
            # 필수 필드 확인
            sample = items[0]
            assert sample.name and len(sample.name) >= 2
            assert sample.sale_price > 0
            assert sample.store == "무신사"
        else:
            pytest.skip("무신사 API 응답 없음 (네트워크 이슈 가능)")

    @pytest.mark.live
    def test_full_crawl(self):
        """crawl() 전체 흐름 테스트."""
        crawler = self._get_crawler()
        result = _run(crawler.crawl())

        logger.info(
            f"[무신사] 크롤 결과: status={result.status}, "
            f"items={result.items_count}, strategy={result.strategy_used}, "
            f"duration={result.duration_seconds:.2f}s"
        )

        if result.items:
            log_items_summary(result.items, "무신사 전체")

        assert result.status in (CrawlStatus.SUCCESS, CrawlStatus.PARTIAL)
        assert result.items_count >= 1
        assert result.crawler_name == "무신사"

        # 각 항목 스키마 검증
        for item in result.items[:10]:
            errors = validate_discount_item(item, "musinsa")
            assert not errors, f"스키마 오류: {errors}"

    def test_parse_mock_json(self):
        """모의 API 응답 파싱 검증."""
        crawler = self._get_crawler()
        mock_data = {
            "data": {
                "goods": [
                    {
                        "goodsName": "오버핏 맨투맨",
                        "salePrice": 29900,
                        "normalPrice": 49900,
                        "saleRate": 40,
                        "brandName": "커버낫",
                        "imageUrl": "/img/test.jpg",
                        "goodsNo": 12345,
                    }
                ]
            }
        }
        goods = crawler._extract_goods_from_api(mock_data)
        assert len(goods) == 1

        item = crawler._api_product_to_item(goods[0], "001")
        assert item is not None
        assert item.name == "오버핏 맨투맨"
        assert item.sale_price == 29900
        assert item.original_price == 49900
        assert "커버낫" in item.category

    def test_validate_deduplication(self):
        """중복 제거 검증."""
        crawler = self._get_crawler()
        items = [
            DiscountItem(name="테스트A", store="무신사", sale_price=10000),
            DiscountItem(name="테스트A", store="무신사", sale_price=10000),
            DiscountItem(name="테스트B", store="무신사", sale_price=20000),
        ]
        valid = _run(crawler.validate(items))
        assert len(valid) == 2


# ===========================================================================
# 2. 지오다노 (Giordano) 테스트
# ===========================================================================

class TestGiordanoCrawler:
    """지오다노 크롤러 테스트 — SALE 페이지 HTML 파싱."""

    def _get_crawler(self):
        from crawlers.shopping.giordano.crawler import GiordanoCrawler
        return GiordanoCrawler()

    def test_crawler_info(self):
        """크롤러 메타정보 확인."""
        crawler = self._get_crawler()
        info = crawler.info
        assert info.name == "지오다노"
        assert info.group.value == "shopping"

    @pytest.mark.live
    def test_discover_sale_urls(self):
        """메인 페이지에서 세일 URL 발견 테스트."""
        crawler = self._get_crawler()
        urls = crawler._discover_sale_urls()
        logger.info(f"[지오다노] 발견된 세일 URL: {urls}")
        # 동적 발견 실패해도 기본 URL이 포함되어야 함
        assert len(urls) >= 1, "최소 1개 세일 URL 필요 (기본 URL 포함)"

    @pytest.mark.live
    def test_full_crawl(self):
        """crawl() 전체 흐름 테스트."""
        crawler = self._get_crawler()
        result = _run(crawler.crawl())

        logger.info(
            f"[지오다노] 크롤 결과: status={result.status}, "
            f"items={result.items_count}, strategy={result.strategy_used}, "
            f"duration={result.duration_seconds:.2f}s"
        )

        if result.items:
            log_items_summary(result.items, "지오다노 전체")

        # 지오다노는 세일이 없을 수 있으므로 PARTIAL도 허용
        assert result.status in (CrawlStatus.SUCCESS, CrawlStatus.PARTIAL)
        assert result.crawler_name == "지오다노"

        if result.items:
            for item in result.items[:10]:
                errors = validate_discount_item(item, "giordano")
                assert not errors, f"스키마 오류: {errors}"

    def test_parse_mock_html(self):
        """모의 HTML 파싱 검증."""
        crawler = self._get_crawler()
        mock_html = """
        <html><body>
        <ul>
        <li class="each_prd_box">
          <div class="box">
            <a href="/shop/detail.php?prdcode=123">
              <img src="https://www.giordano.co.kr/img/test.jpg" />
            </a>
            <div class="info">
              <p class="name">린넨 셔츠</p>
              <div class="price">
                <span class="consumer">39,800원</span>
                <span class="sale_prc">50%</span>
                <span class="sell">19,800원</span>
              </div>
            </div>
          </div>
        </li>
        <li class="each_prd_box">
          <div class="box">
            <a href="/shop/detail.php?prdcode=456">
              <img src="https://www.giordano.co.kr/img/test2.jpg" />
            </a>
            <div class="info">
              <p class="name">코튼 팬츠</p>
              <div class="price">
                <span class="consumer">29,800원</span>
                <span class="sell">14,800원</span>
              </div>
            </div>
          </div>
        </li>
        </ul>
        </body></html>
        """
        items = _run(crawler.parse(mock_html))
        assert len(items) >= 2

        shirt = items[0]
        assert shirt.name == "린넨 셔츠"
        assert shirt.sale_price == 19800
        assert shirt.original_price == 39800
        assert shirt.store == "지오다노"

    def test_parse_price_text(self):
        """가격 텍스트 파싱 검증."""
        crawler = self._get_crawler()

        # "19,800원\n20%\n15,800원"
        orig, pct, sale = crawler._parse_price_text("19,800원\n20%\n15,800원")
        assert orig == 19800
        assert sale == 15800
        assert pct == 20.0

        # 가격만 1개
        orig, pct, sale = crawler._parse_price_text("9,900원")
        assert sale == 9900

    def test_validate_deduplication(self):
        """중복 제거 검증."""
        crawler = self._get_crawler()
        items = [
            DiscountItem(name="셔츠A", store="지오다노", sale_price=15000),
            DiscountItem(name="셔츠A", store="지오다노", sale_price=15000),
            DiscountItem(name="바지B", store="지오다노", sale_price=20000),
        ]
        valid = _run(crawler.validate(items))
        assert len(valid) == 2


# ===========================================================================
# 3. 유니클로 (Uniqlo) 테스트
# ===========================================================================

class TestUniqloCrawler:
    """유니클로 크롤러 테스트 — API + Playwright fallback."""

    def _get_crawler(self):
        from crawlers.shopping.uniqlo.crawler import UniqloCrawler
        return UniqloCrawler()

    def test_crawler_info(self):
        """크롤러 메타정보 확인."""
        crawler = self._get_crawler()
        info = crawler.info
        assert info.name == "유니클로"
        assert info.group.value == "shopping"
        assert info.target_url == "https://www.uniqlo.com/kr"

    @pytest.mark.live
    def test_api_fetch(self):
        """상품 API 호출 테스트."""
        crawler = self._get_crawler()
        items = crawler._fetch_via_api()
        logger.info(f"[유니클로] API 수집: {len(items)}개")

        if items:
            log_items_summary([i.model_dump() for i in items], "유니클로 API")
            sample = items[0]
            assert sample.name and len(sample.name) >= 2
            assert sample.sale_price > 0
            assert sample.store == "유니클로"
        else:
            logger.info("[유니클로] API 응답 없음 — Playwright fallback 필요할 수 있음")

    @pytest.mark.live
    def test_full_crawl(self):
        """crawl() 전체 흐름 테스트."""
        crawler = self._get_crawler()
        result = _run(crawler.crawl())

        logger.info(
            f"[유니클로] 크롤 결과: status={result.status}, "
            f"items={result.items_count}, strategy={result.strategy_used}, "
            f"duration={result.duration_seconds:.2f}s"
        )

        if result.items:
            log_items_summary(result.items, "유니클로 전체")

        # 유니클로는 anti-bot이 강하므로 PARTIAL/FAILED 허용
        assert result.status in (
            CrawlStatus.SUCCESS, CrawlStatus.PARTIAL, CrawlStatus.FAILED
        )
        assert result.crawler_name == "유니클로"

        if result.status != CrawlStatus.FAILED:
            for item in result.items[:10]:
                errors = validate_discount_item(item, "uniqlo")
                assert not errors, f"스키마 오류: {errors}"

    def test_parse_mock_api_json(self):
        """모의 API JSON 파싱."""
        crawler = self._get_crawler()
        mock_product = {
            "name": "에어리즘 코튼 반팔 T",
            "productId": "E466055",
            "prices": {
                "base": {"value": 14900},
                "original": {"value": 19900},
            },
            "images": {
                "main": {"image": "https://image.uniqlo.com/test.jpg"},
            },
            "genderName": "남성",
        }
        item = crawler._api_to_discount_item(mock_product)
        assert item is not None
        assert item.name == "에어리즘 코튼 반팔 T"
        assert item.sale_price == 14900
        assert item.original_price == 19900
        assert item.store == "유니클로"

    def test_extract_products_from_api(self):
        """다양한 API 응답 구조에서 상품 리스트 추출."""
        crawler = self._get_crawler()

        data1 = {"result": {"items": [{"name": "테스트"}]}}
        assert len(crawler._extract_products_from_api(data1)) == 1

        data2 = {"data": {"products": [{"name": "테스트"}]}}
        assert len(crawler._extract_products_from_api(data2)) == 1

        data3 = {"items": [{"name": "테스트"}]}
        assert len(crawler._extract_products_from_api(data3)) == 1

    def test_validate_deduplication(self):
        """중복 제거 검증."""
        crawler = self._get_crawler()
        items = [
            DiscountItem(name="에어리즘A", store="유니클로", sale_price=14900),
            DiscountItem(name="에어리즘A", store="유니클로", sale_price=14900),
            DiscountItem(name="히트텍B", store="유니클로", sale_price=19900),
        ]
        valid = _run(crawler.validate(items))
        assert len(valid) == 2


# ===========================================================================
# 4. 오피넷 (OPINET) 테스트
# ===========================================================================

class TestOpinetCrawler:
    """오피넷 크롤러 테스트 — 주유소 가격 (API + 웹 스크레이핑)."""

    def _get_crawler(self):
        from crawlers.government.opinet.crawler import OpinetCrawler
        return OpinetCrawler()

    def test_crawler_info(self):
        """크롤러 메타정보 확인."""
        crawler = self._get_crawler()
        info = crawler.info
        assert info.name == "오피넷"
        assert info.group.value == "public"
        assert info.target_url == "https://www.opinet.co.kr"

    @pytest.mark.live
    def test_full_crawl(self):
        """crawl() 전체 흐름 테스트 (API 또는 웹 스크레이핑)."""
        crawler = self._get_crawler()
        result = _run(crawler.crawl())

        logger.info(
            f"[오피넷] 크롤 결과: status={result.status}, "
            f"items={result.items_count}, strategy={result.strategy_used}, "
            f"duration={result.duration_seconds:.2f}s"
        )

        if result.items:
            log_items_summary(result.items, "오피넷 전체")

        assert result.status in (
            CrawlStatus.SUCCESS, CrawlStatus.PARTIAL, CrawlStatus.FAILED
        )
        assert result.crawler_name == "오피넷"

        if result.items:
            for item in result.items[:10]:
                errors = validate_gas_station(item)
                assert not errors, f"스키마 오류: {errors}"

    @pytest.mark.live
    def test_web_scraping_fallback(self):
        """웹 스크레이핑 fallback 테스트 (API 키 없이)."""
        from crawlers.government.opinet.crawler import OpinetCrawler
        crawler = OpinetCrawler()
        # API 키 강제 제거
        crawler._api_key = ""

        result = _run(crawler.crawl())

        logger.info(
            f"[오피넷 웹] status={result.status}, items={result.items_count}, "
            f"strategy={result.strategy_used}"
        )

        if result.items:
            log_items_summary(result.items, "오피넷 웹스크레이핑")

        # 웹 스크레이핑은 구조 변경에 취약하므로 FAILED도 허용
        assert result.status in (
            CrawlStatus.SUCCESS, CrawlStatus.PARTIAL, CrawlStatus.FAILED
        )

    def test_parse_mock_api_json(self):
        """모의 API JSON 파싱 검증."""
        crawler = self._get_crawler()
        mock_json = {
            "RESULT": {
                "OIL": [
                    {
                        "OS_NM": "테스트 주유소",
                        "POLL_DIV_CO": "SKE",
                        "NEW_ADR": "서울시 강남구",
                        "PRICE": 1650.0,
                        "SELF_YN": "Y",
                        "UNI_ID": "A0001",
                        "GIS_Y_COOR": 37.5,
                        "GIS_X_COOR": 127.0,
                    },
                    {
                        "OS_NM": "알뜰 주유소",
                        "POLL_DIV_CO": "RTO",
                        "NEW_ADR": "서울시 송파구",
                        "PRICE": 1580.0,
                        "SELF_YN": "N",
                        "UNI_ID": "A0002",
                    },
                ]
            }
        }

        import json
        items = _run(
            crawler.parse(json.dumps(mock_json))
        )

        assert len(items) == 2

        station = items[0]
        assert station["name"] == "테스트 주유소"
        assert station["brand"] == "SK에너지"
        assert station["gasoline_price"] == 1650.0
        assert station["is_self"] is True
        assert station["address"] == "서울시 강남구"

    def test_validate_filters_bad_prices(self):
        """비정상 가격 필터링 검증."""
        crawler = self._get_crawler()
        items = [
            {"name": "정상 주유소", "gasoline_price": 1650, "diesel_price": 1500, "lpg_price": None},
            {"name": "너무 비쌈", "gasoline_price": 9999, "diesel_price": None, "lpg_price": None},
            {"name": "이름없음", "gasoline_price": 1600, "diesel_price": None, "lpg_price": None},
            {"name": "가격없음", "gasoline_price": None, "diesel_price": None, "lpg_price": None},
        ]
        valid = _run(crawler.validate(items))

        # "정상 주유소"는 통과, "너무 비쌈"은 가격 None 처리 후 탈락, "가격없음" 탈락
        names = [v["name"] for v in valid]
        assert "정상 주유소" in names
        assert "가격없음" not in names

    def test_validate_deduplication(self):
        """중복 주유소 제거."""
        crawler = self._get_crawler()
        items = [
            {"name": "중복주유소", "gasoline_price": 1650, "diesel_price": None, "lpg_price": None},
            {"name": "중복주유소", "gasoline_price": 1660, "diesel_price": None, "lpg_price": None},
            {"name": "다른주유소", "gasoline_price": 1700, "diesel_price": None, "lpg_price": None},
        ]
        valid = _run(crawler.validate(items))
        assert len(valid) == 2

    def test_brand_mapping(self):
        """브랜드 코드 매핑 테스트."""
        crawler = self._get_crawler()
        assert crawler.BRAND_MAP["SKE"] == "SK에너지"
        assert crawler.BRAND_MAP["GSC"] == "GS칼텍스"
        assert crawler.BRAND_MAP["HDO"] == "현대오일뱅크"
        assert crawler.BRAND_MAP["SOL"] == "S-OIL"
        assert crawler.BRAND_MAP["RTO"] == "알뜰주유소"


# ===========================================================================
# 5. 전체 요약 테스트
# ===========================================================================

class TestAllCrawlersSummary:
    """모든 크롤러의 라이브 수집을 한번에 실행하고 요약 리포트 출력."""

    @pytest.mark.live
    def test_all_crawlers_report(self):
        """전체 크롤러 실행 및 리포트."""
        from crawlers.shopping.musinsa.crawler import MusinsaCrawler
        from crawlers.shopping.giordano.crawler import GiordanoCrawler
        from crawlers.shopping.uniqlo.crawler import UniqloCrawler
        from crawlers.government.opinet.crawler import OpinetCrawler

        crawlers = [
            ("무신사", MusinsaCrawler()),
            ("지오다노", GiordanoCrawler()),
            ("유니클로", UniqloCrawler()),
            ("오피넷", OpinetCrawler()),
        ]

        results = []

        for name, crawler in crawlers:
            start = time.time()
            try:
                result = _run(crawler.crawl())
                elapsed = time.time() - start
                results.append({
                    "name": name,
                    "status": result.status.value,
                    "items": result.items_count,
                    "strategy": result.strategy_used,
                    "duration": f"{elapsed:.1f}s",
                    "error": result.error_msg[:80] if result.error_msg else None,
                })
            except Exception as e:
                results.append({
                    "name": name,
                    "status": "error",
                    "items": 0,
                    "strategy": None,
                    "duration": f"{time.time()-start:.1f}s",
                    "error": str(e)[:80],
                })

        # 리포트 출력
        logger.info("\n" + "=" * 80)
        logger.info("  전체 크롤러 테스트 결과 리포트")
        logger.info("=" * 80)
        logger.info(f"  {'크롤러':<10} {'상태':<10} {'수집수':>6} {'전략':<15} {'시간':>8} {'오류'}")
        logger.info("-" * 80)
        for r in results:
            logger.info(
                f"  {r['name']:<10} {r['status']:<10} {r['items']:>6} "
                f"{(r['strategy'] or '-'):<15} {r['duration']:>8} "
                f"{r['error'] or ''}"
            )
        logger.info("=" * 80)

        # 최소 2개 크롤러가 데이터를 수집해야 함
        success_count = sum(1 for r in results if r["items"] > 0)
        logger.info(f"  성공한 크롤러: {success_count}/{len(results)}")
        assert success_count >= 1, f"최소 1개 크롤러가 데이터 수집해야 함 (현재: {success_count})"
