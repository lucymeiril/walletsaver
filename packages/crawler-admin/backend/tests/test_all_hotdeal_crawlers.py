"""
전체 핫딜 크롤러 통합 TDD 테스트.

7개 핫딜 커뮤니티 크롤러를 대상으로:
  1. 인스턴스 생성 및 메타 정보 검증
  2. 가격 파싱 로직 검증
  3. 샘플 HTML parse 검증 (오프라인)
  4. 실제 네트워크 크롤링 검증 (온라인, max_items=10)
  5. 스키마 유효성 (title, url, price>=0)
  6. 중복 검사
  7. 결과 로그 저장

실행: cd packages/crawler-admin/backend && py -m pytest tests/test_all_hotdeal_crawlers.py -v
"""

import asyncio
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import pytest

from crawlers.hotdeals.ppomppu.crawler import PpomppuCrawler
from crawlers.hotdeals.fmkorea.crawler import FmkoreaCrawler
from crawlers.hotdeals.clien.crawler import ClienCrawler
from crawlers.hotdeals.arca.crawler import ArcaCrawler
from crawlers.hotdeals.cocodal.crawler import CocodalCrawler
from crawlers.hotdeals.quasarzone.crawler import QuasarzoneCrawler
from crawlers.hotdeals.algumon.crawler import AlgumonCrawler
from core.models import CrawlerGroup, CrawlStatus, HotdealPost

logger = logging.getLogger(__name__)

# 결과 로그 저장 경로
RESULTS_DIR = Path(__file__).parent / "crawl_results"


# ──────────────────────────────────────────────
# 헬퍼 함수
# ──────────────────────────────────────────────

def save_crawl_results(name: str, items: list[dict], status: str, error: str = ""):
    """크롤 결과를 JSON 파일로 저장한다."""
    RESULTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = RESULTS_DIR / f"{name}_{timestamp}.json"
    report = {
        "crawler": name,
        "status": status,
        "items_count": len(items),
        "error": error,
        "timestamp": timestamp,
        "items": items[:10],  # 최대 10개만 저장
    }
    filepath.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"[결과 저장] {filepath}")


def validate_hotdeal_schema(item: dict) -> list[str]:
    """HotdealPost 스키마 유효성 검사. 위반 사항 리스트 반환."""
    errors = []

    # 필수 필드 존재
    if not item.get("title") or not isinstance(item["title"], str):
        errors.append("title이 없거나 문자열이 아님")
    elif len(item["title"]) < 3:
        errors.append(f"title이 너무 짧음: '{item['title']}'")

    if not item.get("url") or not isinstance(item["url"], str):
        errors.append("url이 없거나 문자열이 아님")
    elif not item["url"].startswith("http"):
        errors.append(f"url이 절대 경로가 아님: {item['url']}")

    # 가격은 None 또는 0 이상
    price = item.get("price")
    if price is not None and (not isinstance(price, (int, float)) or price < 0):
        errors.append(f"price가 음수이거나 유효하지 않음: {price}")

    return errors


# ──────────────────────────────────────────────
# 샘플 HTML 데이터 (오프라인 테스트용)
# ──────────────────────────────────────────────

ARCA_SAMPLE_HTML = """
<html><body>
<div class="article-list">
  <div class="list-table hybrid">
    <div class="vrow hybrid">
      <div class="vrow-inner">
        <div class="vrow-top deal">
          <span class="vcol col-title">
            <span class="badges">
              <span class="deal-store">G마켓</span>
              <a class="badge" href="/b/hotdeal?category=elec">전자제품</a>
            </span>
            <a class="title hybrid-title" href="/b/hotdeal/12345?p=1">
              삼성 SSD 870 EVO 500GB
              <span class="info"><span class="comment-count">[5]</span></span>
            </a>
          </span>
        </div>
        <a class="title hybrid-bottom" href="/b/hotdeal/12345?p=1">
          <div class="vrow-bottom deal">
            <span class="deal-price">49,900원</span>
            <span class="deal-delivery">무료</span>
          </div>
        </a>
      </div>
    </div>
    <div class="vrow hybrid">
      <div class="vrow-inner">
        <div class="vrow-top deal">
          <span class="vcol col-title">
            <span class="badges">
              <span class="deal-store">쿠팡</span>
              <a class="badge" href="/b/hotdeal?category=food">식품</a>
            </span>
            <a class="title hybrid-title" href="/b/hotdeal/12346?p=1">
              대추방울토마토 2kg 특가
              <span class="info"><span class="comment-count">[3]</span></span>
            </a>
          </span>
        </div>
        <a class="title hybrid-bottom" href="/b/hotdeal/12346?p=1">
          <div class="vrow-bottom deal">
            <span class="deal-price">10,970원</span>
            <span class="deal-delivery">3,000원</span>
          </div>
        </a>
      </div>
    </div>
  </div>
</div>
</body></html>
"""

QUASARZONE_SAMPLE_HTML = """
<html><body>
<div class="market-info-list">
  <div class="market-info-list-cont">
    <div class="market-info-sub">
      <p class="tit">
        <a href="/bbs/qb_saleinfo/views/1001">
          <span class="ellipsis-with-reply-cnt">
            <span class="deal-condition"><span>진행중</span></span>
            <span class="text">LG 모니터 27인치 IPS 특가</span>
          </span>
        </a>
      </p>
      <p class="market-info-sub-txt">
        PC/하드웨어 가격 ￦ 259,000 (KRW) 배송비 무료
      </p>
    </div>
  </div>
  <div class="market-info-list-cont">
    <div class="market-info-sub">
      <p class="tit">
        <a href="/bbs/qb_saleinfo/views/1002">
          <span class="ellipsis-with-reply-cnt">
            <span class="deal-condition"><span>종료</span></span>
            <span class="text">AMD 라이젠 7 5800X 할인</span>
          </span>
        </a>
      </p>
      <p class="market-info-sub-txt">
        CPU 가격 ￦ 199,000 (KRW) 배송비 3,000원
      </p>
    </div>
  </div>
</div>
</body></html>
"""

ALGUMON_SAMPLE_HTML = """
<html><body>
<script type="application/ld+json">
{
  "@type": "CollectionPage",
  "mainEntity": {
    "itemListElement": [
      {
        "item": {
          "name": "[뽐뿌] 삼성 갤럭시 S25 울트라 1,199,000원 역대최저가",
          "url": "https://www.algumon.com/l/d/abc123"
        }
      },
      {
        "item": {
          "name": "[클리앙] 애플 맥북 에어 M3 무료 업그레이드 이벤트",
          "url": "https://www.algumon.com/l/d/def456"
        }
      }
    ]
  }
}
</script>
<div class="deal-card-content">
  <h3><a href="/l/d/ghi789">로지텍 MX 마스터 3S 79,000원</a></h3>
  <p class="deal-price-text">79,000원</p>
</div>
</body></html>
"""


# ──────────────────────────────────────────────
# 1. 인스턴스 생성 테스트 — 모든 7개 크롤러
# ──────────────────────────────────────────────

class TestAllCrawlerInstantiation:
    """7개 크롤러의 인스턴스 생성 및 메타 정보를 검증한다."""

    @pytest.mark.parametrize("CrawlerClass,expected_name,expected_url_part", [
        (PpomppuCrawler, "뽐뿌", "ppomppu"),
        (FmkoreaCrawler, "FM코리아", "fmkorea"),
        (ClienCrawler, "클리앙", "clien"),
        (ArcaCrawler, "아카라이브", "arca"),
        (CocodalCrawler, "코코달", "cocodal"),
        (QuasarzoneCrawler, "퀘이사존", "quasarzone"),
        (AlgumonCrawler, "알구몬", "algumon"),
    ])
    def test_crawler_instantiation(self, CrawlerClass, expected_name, expected_url_part):
        """각 크롤러 인스턴스 생성 및 info 속성 검증."""
        crawler = CrawlerClass()
        assert crawler.info.name == expected_name
        assert crawler.info.group == CrawlerGroup.HOTDEAL
        assert expected_url_part in crawler.info.target_url
        assert len(crawler.info.strategies) >= 1
        assert crawler.info.version


# ──────────────────────────────────────────────
# 2. 가격 파싱 테스트 — 전체 크롤러의 _extract_price
# ──────────────────────────────────────────────

class TestAllPriceParsing:
    """모든 크롤러의 가격 파싱 로직을 검증한다."""

    @pytest.fixture(params=[
        PpomppuCrawler,
        FmkoreaCrawler,
        ClienCrawler,
        ArcaCrawler,
        QuasarzoneCrawler,
        AlgumonCrawler,
    ])
    def crawler(self, request):
        return request.param()

    def test_comma_price(self, crawler):
        """콤마 가격: '12,500원' → 12500"""
        assert crawler._extract_price("12,500원") == 12500

    def test_large_price(self, crawler):
        """큰 금액: '1,299,000원' → 1299000"""
        assert crawler._extract_price("1,299,000원") == 1299000

    def test_no_comma_price(self, crawler):
        """콤마 없는 가격: '500원' → 500"""
        assert crawler._extract_price("500원") == 500

    def test_none_input(self, crawler):
        """None 입력 → None"""
        assert crawler._extract_price(None) is None

    def test_empty_string(self, crawler):
        """빈 문자열 → None"""
        assert crawler._extract_price("") is None

    def test_no_price_text(self, crawler):
        """가격 없는 텍스트 → None"""
        assert crawler._extract_price("가격 정보 없음") is None

    def test_quasarzone_won_sign(self):
        """퀘이사존 '￦ 59,000' 패턴"""
        qz = QuasarzoneCrawler()
        assert qz._extract_price("가격 ￦ 59,000 (KRW)") == 59000


# ──────────────────────────────────────────────
# 3. 오프라인 parse 테스트 — 샘플 HTML 기반
# ──────────────────────────────────────────────

class TestArcaParse:
    """아카라이브 크롤러의 parse 결과를 검증한다."""

    @pytest.fixture
    def crawler(self):
        return ArcaCrawler()

    def test_parse_returns_items(self, crawler):
        items = asyncio.get_event_loop().run_until_complete(
            crawler.parse(ARCA_SAMPLE_HTML)
        )
        assert len(items) >= 2

    def test_parse_item_fields(self, crawler):
        items = asyncio.get_event_loop().run_until_complete(
            crawler.parse(ARCA_SAMPLE_HTML)
        )
        first = items[0]
        assert isinstance(first, HotdealPost)
        assert len(first.title) >= 3
        assert first.url.startswith("http")
        assert first.source_community == "아카라이브"

    def test_parse_extracts_price(self, crawler):
        items = asyncio.get_event_loop().run_until_complete(
            crawler.parse(ARCA_SAMPLE_HTML)
        )
        prices = [item.price for item in items if item.price is not None]
        assert 49900 in prices

    def test_parse_extracts_category(self, crawler):
        items = asyncio.get_event_loop().run_until_complete(
            crawler.parse(ARCA_SAMPLE_HTML)
        )
        categories = [item.category for item in items if item.category]
        assert any("G마켓" in c for c in categories)


class TestQuasarzoneParse:
    """퀘이사존 크롤러의 parse 결과를 검증한다."""

    @pytest.fixture
    def crawler(self):
        return QuasarzoneCrawler()

    def test_parse_returns_items(self, crawler):
        items = asyncio.get_event_loop().run_until_complete(
            crawler.parse(QUASARZONE_SAMPLE_HTML)
        )
        assert len(items) >= 2

    def test_parse_item_fields(self, crawler):
        items = asyncio.get_event_loop().run_until_complete(
            crawler.parse(QUASARZONE_SAMPLE_HTML)
        )
        first = items[0]
        assert isinstance(first, HotdealPost)
        assert len(first.title) >= 3
        assert first.url.startswith("http")
        assert first.source_community == "퀘이사존"

    def test_parse_extracts_price(self, crawler):
        items = asyncio.get_event_loop().run_until_complete(
            crawler.parse(QUASARZONE_SAMPLE_HTML)
        )
        prices = [item.price for item in items if item.price is not None]
        assert 259000 in prices

    def test_parse_removes_status_from_title(self, crawler):
        """종료/진행중 상태 텍스트가 제목에서 제거되어야 한다."""
        items = asyncio.get_event_loop().run_until_complete(
            crawler.parse(QUASARZONE_SAMPLE_HTML)
        )
        for item in items:
            assert "진행중" not in item.title
            assert "종료" not in item.title


class TestAlgumonParse:
    """알구몬 크롤러의 parse 결과를 검증한다."""

    @pytest.fixture
    def crawler(self):
        return AlgumonCrawler()

    def test_parse_json_ld(self, crawler):
        """JSON-LD 기반 파싱 검증."""
        items = asyncio.get_event_loop().run_until_complete(
            crawler.parse(ALGUMON_SAMPLE_HTML)
        )
        # JSON-LD에서 2개 추출
        assert len(items) >= 2

    def test_parse_item_fields(self, crawler):
        items = asyncio.get_event_loop().run_until_complete(
            crawler.parse(ALGUMON_SAMPLE_HTML)
        )
        first = items[0]
        assert isinstance(first, HotdealPost)
        assert len(first.title) >= 3
        assert first.url.startswith("http")

    def test_parse_extracts_price(self, crawler):
        items = asyncio.get_event_loop().run_until_complete(
            crawler.parse(ALGUMON_SAMPLE_HTML)
        )
        prices = [item.price for item in items if item.price is not None]
        assert 1199000 in prices
        assert 79000 in prices


# ──────────────────────────────────────────────
# 4. 코코달 비활성 테스트
# ──────────────────────────────────────────────

class TestCocodalInactive:
    """코코달 크롤러의 비활성 상태를 검증한다."""

    def test_crawl_returns_failed(self):
        """사이트 접속 불가로 FAILED 반환해야 한다."""
        crawler = CocodalCrawler()
        result = asyncio.get_event_loop().run_until_complete(crawler.crawl())
        assert result.status == CrawlStatus.FAILED
        assert "접속 불가" in result.error_msg

    def test_parse_returns_empty(self):
        crawler = CocodalCrawler()
        items = asyncio.get_event_loop().run_until_complete(crawler.parse(""))
        assert items == []


# ──────────────────────────────────────────────
# 5. validate 테스트 — 전체 크롤러
# ──────────────────────────────────────────────

class TestAllValidation:
    """모든 크롤러의 validate가 짧은 제목·중복 URL을 올바르게 거부하는지 확인한다."""

    @pytest.fixture(params=[
        (PpomppuCrawler, "뽐뿌"),
        (FmkoreaCrawler, "FM코리아"),
        (ClienCrawler, "클리앙"),
        (ArcaCrawler, "아카라이브"),
        (QuasarzoneCrawler, "퀘이사존"),
        (AlgumonCrawler, "알구몬"),
    ])
    def crawler_and_source(self, request):
        CrawlerClass, source = request.param
        return CrawlerClass(), source

    def test_rejects_short_title(self, crawler_and_source):
        """3글자 미만 제목은 거부한다."""
        crawler, source = crawler_and_source
        items = [
            HotdealPost(title="AB", url="https://example.com/1", source_community=source),
            HotdealPost(title="정상 제목 테스트 게시글", url="https://example.com/2", source_community=source),
        ]
        valid = asyncio.get_event_loop().run_until_complete(crawler.validate(items))
        assert len(valid) == 1
        assert valid[0].title == "정상 제목 테스트 게시글"

    def test_deduplicates_urls(self, crawler_and_source):
        """중복 URL을 제거한다."""
        crawler, source = crawler_and_source
        items = [
            HotdealPost(title="상품 A 핫딜", url="https://example.com/dup", source_community=source),
            HotdealPost(title="상품 B 핫딜", url="https://example.com/dup", source_community=source),
            HotdealPost(title="상품 C 핫딜", url="https://example.com/unique", source_community=source),
        ]
        valid = asyncio.get_event_loop().run_until_complete(crawler.validate(items))
        assert len(valid) == 2

    def test_preserves_valid_items(self, crawler_and_source):
        """유효한 항목은 보존한다."""
        crawler, source = crawler_and_source
        items = [
            HotdealPost(title="좋은 상품 핫딜 특가", url="https://example.com/a", source_community=source, price=15000),
            HotdealPost(title="또 다른 핫딜 할인", url="https://example.com/b", source_community=source, price=29000),
        ]
        valid = asyncio.get_event_loop().run_until_complete(crawler.validate(items))
        assert len(valid) == 2


# ──────────────────────────────────────────────
# 6. 실제 네트워크 크롤링 테스트 (라이브)
# ──────────────────────────────────────────────

@pytest.mark.timeout(60)
class TestLiveCrawling:
    """실제 사이트에서 크롤링하여 데이터를 검증한다.

    네트워크 환경에 따라 실패할 수 있으며, 이 경우 결과를 로그로 남긴다.
    -m "not live" 로 건너뛸 수 있다.
    """

    @pytest.mark.live
    def test_ppomppu_live(self):
        """뽐뿌 라이브 크롤링 — 실제 핫딜 게시글 수집."""
        crawler = PpomppuCrawler()
        result = asyncio.get_event_loop().run_until_complete(crawler.crawl())

        if result.status == CrawlStatus.FAILED:
            save_crawl_results("ppomppu", [], "FAILED", result.error_msg or "")
            pytest.skip(f"뽐뿌 네트워크 접근 실패: {result.error_msg}")

        assert result.status == CrawlStatus.SUCCESS
        assert result.items_count > 0
        assert len(result.items) > 0

        # 스키마 유효성 검증
        for item in result.items[:10]:
            errors = validate_hotdeal_schema(item)
            assert not errors, f"스키마 위반: {errors}, 항목: {item.get('title', '?')}"

        # 중복 URL 검사
        urls = [item["url"] for item in result.items]
        assert len(urls) == len(set(urls)), "중복 URL이 존재한다"

        save_crawl_results("ppomppu", result.items, "SUCCESS")
        logger.info(f"[뽐뿌] 라이브 크롤링 성공: {result.items_count}개")

    @pytest.mark.live
    def test_fmkorea_live(self):
        """FM코리아 라이브 크롤링."""
        crawler = FmkoreaCrawler()
        result = asyncio.get_event_loop().run_until_complete(crawler.crawl())

        if result.status == CrawlStatus.FAILED:
            save_crawl_results("fmkorea", [], "FAILED", result.error_msg or "")
            pytest.skip(f"FM코리아 네트워크 접근 실패: {result.error_msg}")

        assert result.status == CrawlStatus.SUCCESS
        assert result.items_count > 0

        for item in result.items[:10]:
            errors = validate_hotdeal_schema(item)
            assert not errors, f"스키마 위반: {errors}"

        urls = [item["url"] for item in result.items]
        assert len(urls) == len(set(urls))

        save_crawl_results("fmkorea", result.items, "SUCCESS")
        logger.info(f"[FM코리아] 라이브 크롤링 성공: {result.items_count}개")

    @pytest.mark.live
    def test_clien_live(self):
        """클리앙 라이브 크롤링."""
        crawler = ClienCrawler()
        result = asyncio.get_event_loop().run_until_complete(crawler.crawl())

        if result.status == CrawlStatus.FAILED:
            save_crawl_results("clien", [], "FAILED", result.error_msg or "")
            pytest.skip(f"클리앙 네트워크 접근 실패: {result.error_msg}")

        assert result.status == CrawlStatus.SUCCESS
        assert result.items_count > 0

        for item in result.items[:10]:
            errors = validate_hotdeal_schema(item)
            assert not errors, f"스키마 위반: {errors}"

        urls = [item["url"] for item in result.items]
        assert len(urls) == len(set(urls))

        save_crawl_results("clien", result.items, "SUCCESS")
        logger.info(f"[클리앙] 라이브 크롤링 성공: {result.items_count}개")

    @pytest.mark.live
    def test_arca_live(self):
        """아카라이브 라이브 크롤링 — Cloudflare 보호 사이트."""
        crawler = ArcaCrawler()
        result = asyncio.get_event_loop().run_until_complete(crawler.crawl())

        if result.status == CrawlStatus.FAILED:
            save_crawl_results("arca", [], "FAILED", result.error_msg or "")
            pytest.skip(f"아카라이브 네트워크 접근 실패 (Cloudflare 차단 가능): {result.error_msg}")

        # Cloudflare 사이트이므로 0개 수집도 SUCCESS일 수 있음 (부분 차단)
        if result.items_count == 0:
            save_crawl_results("arca", [], "PARTIAL", "Cloudflare 부분 차단 — 게시글 0개")
            pytest.skip("아카라이브 Cloudflare 부분 차단 — 게시글 0개 수집")

        for item in result.items[:10]:
            errors = validate_hotdeal_schema(item)
            assert not errors, f"스키마 위반: {errors}"

        urls = [item["url"] for item in result.items]
        assert len(urls) == len(set(urls))

        save_crawl_results("arca", result.items, "SUCCESS")
        logger.info(f"[아카라이브] 라이브 크롤링 성공: {result.items_count}개")

    @pytest.mark.live
    def test_cocodal_live(self):
        """코코달 라이브 크롤링 — 사이트 비활성 상태이므로 FAILED 예상."""
        crawler = CocodalCrawler()
        result = asyncio.get_event_loop().run_until_complete(crawler.crawl())

        # 사이트 비활성 → FAILED가 정상
        assert result.status == CrawlStatus.FAILED
        assert "접속 불가" in (result.error_msg or "")
        save_crawl_results("cocodal", [], "FAILED_EXPECTED", result.error_msg or "")
        logger.info("[코코달] 예상대로 FAILED — 사이트 비활성")

    @pytest.mark.live
    def test_quasarzone_live(self):
        """퀘이사존 라이브 크롤링."""
        crawler = QuasarzoneCrawler()
        result = asyncio.get_event_loop().run_until_complete(crawler.crawl())

        if result.status == CrawlStatus.FAILED:
            save_crawl_results("quasarzone", [], "FAILED", result.error_msg or "")
            pytest.skip(f"퀘이사존 네트워크 접근 실패: {result.error_msg}")

        assert result.status == CrawlStatus.SUCCESS
        assert result.items_count > 0

        for item in result.items[:10]:
            errors = validate_hotdeal_schema(item)
            assert not errors, f"스키마 위반: {errors}"

        urls = [item["url"] for item in result.items]
        assert len(urls) == len(set(urls))

        save_crawl_results("quasarzone", result.items, "SUCCESS")
        logger.info(f"[퀘이사존] 라이브 크롤링 성공: {result.items_count}개")

    @pytest.mark.live
    def test_algumon_live(self):
        """알구몬 라이브 크롤링."""
        crawler = AlgumonCrawler()
        result = asyncio.get_event_loop().run_until_complete(crawler.crawl())

        if result.status == CrawlStatus.FAILED:
            save_crawl_results("algumon", [], "FAILED", result.error_msg or "")
            pytest.skip(f"알구몬 네트워크 접근 실패: {result.error_msg}")

        assert result.status == CrawlStatus.SUCCESS
        assert result.items_count > 0

        for item in result.items[:10]:
            errors = validate_hotdeal_schema(item)
            assert not errors, f"스키마 위반: {errors}"

        urls = [item["url"] for item in result.items]
        assert len(urls) == len(set(urls))

        save_crawl_results("algumon", result.items, "SUCCESS")
        logger.info(f"[알구몬] 라이브 크롤링 성공: {result.items_count}개")


# ──────────────────────────────────────────────
# 7. 전체 크롤러 요약 보고서 (라이브)
# ──────────────────────────────────────────────

@pytest.mark.live
@pytest.mark.timeout(180)
class TestCrawlerSummaryReport:
    """전체 크롤러를 순차 실행하여 요약 보고서를 생성한다."""

    def test_all_crawlers_summary(self):
        """7개 크롤러 전체 실행 및 결과 요약."""
        crawlers = [
            ("ppomppu", PpomppuCrawler()),
            ("fmkorea", FmkoreaCrawler()),
            ("clien", ClienCrawler()),
            ("arca", ArcaCrawler()),
            ("cocodal", CocodalCrawler()),
            ("quasarzone", QuasarzoneCrawler()),
            ("algumon", AlgumonCrawler()),
        ]

        summary = []
        total_items = 0

        for name, crawler in crawlers:
            try:
                result = asyncio.get_event_loop().run_until_complete(crawler.crawl())
                status = result.status.value
                count = result.items_count
                error = result.error_msg or ""

                # 스키마 위반 카운트
                schema_errors = 0
                for item in result.items[:10]:
                    if validate_hotdeal_schema(item):
                        schema_errors += 1

                summary.append({
                    "name": name,
                    "display_name": crawler.info.name,
                    "status": status,
                    "items_count": count,
                    "schema_errors": schema_errors,
                    "error": error[:100],
                })
                total_items += count

                save_crawl_results(name, result.items, status, error)

            except Exception as e:
                summary.append({
                    "name": name,
                    "display_name": crawler.info.name,
                    "status": "EXCEPTION",
                    "items_count": 0,
                    "schema_errors": 0,
                    "error": str(e)[:100],
                })

        # 요약 보고서 저장
        RESULTS_DIR.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = RESULTS_DIR / f"summary_{timestamp}.json"
        report = {
            "timestamp": timestamp,
            "total_crawlers": len(crawlers),
            "total_items": total_items,
            "crawlers": summary,
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

        # 콘솔 출력
        print("\n" + "=" * 70)
        print(f"핫딜 크롤러 요약 보고서 — {timestamp}")
        print("=" * 70)
        for s in summary:
            status_icon = "✅" if s["status"] == "success" else "⚠️" if s["status"] == "failed" else "❌"
            print(f"  {status_icon} {s['display_name']:10s} | {s['status']:10s} | {s['items_count']:3d}개 | 스키마오류: {s['schema_errors']} | {s['error'][:50]}")
        print(f"\n  총 수집: {total_items}개")
        print("=" * 70)

        # 코코달 제외하고 최소 3개 크롤러가 성공해야 한다
        success_count = sum(1 for s in summary if s["status"] == "success" and s["items_count"] > 0)
        assert success_count >= 3, f"성공한 크롤러가 3개 미만: {success_count}개"
