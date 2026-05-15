"""
핫딜 크롤러 테스트 — 뽐뿌, FM코리아, 클리앙.

각 크롤러의 인스턴스 생성, parse 메서드, 가격 파싱,
URL 정규화, validate(필수 필드 누락 거부)를 테스트한다.
"""

import asyncio

import pytest

from crawlers.hotdeals.ppomppu.crawler import PpomppuCrawler
from crawlers.hotdeals.fmkorea.crawler import FmkoreaCrawler
from crawlers.hotdeals.clien.crawler import ClienCrawler
from core.models import CrawlerGroup, HotdealPost


# ──────────────────────────────────────────────
# 샘플 HTML 픽스처
# ──────────────────────────────────────────────

PPOMPPU_SAMPLE_HTML = """
<html><body>
<table>
  <tr class="baseList bbs_new1">
    <td>1234</td>
    <td>
      <a class="baseList-title" href="view.php?id=ppomppu&no=1234">
        <font class="list_title">[식품] 맛있는 라면 세트 12,500원 무료배송</font>
      </a>
    </td>
    <td class="baseList-price">12,500원</td>
    <td>15 - 2</td>
  </tr>
  <tr class="baseList bbs_new1">
    <td>1235</td>
    <td>
      <a class="baseList-title" href="view.php?id=ppomppu&no=1235">
        <font class="list_title">[가전] 무선 이어폰 29,900원</font>
      </a>
    </td>
    <td class="baseList-price">29,900원</td>
    <td>8 - 0</td>
  </tr>
  <tr class="baseList bbs_new1">
    <td>1236</td>
    <td>
      <a class="baseList-title" href="view.php?id=ppomppu&no=1236">
        <font class="list_title">무료 나눔 이벤트</font>
      </a>
    </td>
    <td class="baseList-price">무료</td>
    <td>20 - 1</td>
  </tr>
  <tr class="baseList notice">
    <td>공지</td>
    <td>
      <a class="baseList-title" href="view.php?id=ppomppu&no=9999">
        <font class="list_title">[공지] 게시판 이용 안내</font>
      </a>
    </td>
    <td class="baseList-price"></td>
    <td></td>
  </tr>
  <tr class="baseList bbs_new1">
    <td>1237</td>
    <td>
      <a class="baseList-title" href="https://www.ppomppu.co.kr/zboard/view.php?id=ppomppu&no=1237">
        <font class="list_title">[디지털] SSD 500GB 특가 45,000원</font>
      </a>
    </td>
    <td class="baseList-price">45,000원</td>
    <td>5 - 0</td>
  </tr>
</table>
</body></html>
"""

FMKOREA_SAMPLE_HTML = """
<html><body>
<div class="fm_best_widget">
  <ul>
    <li class="li li_best2_pop0">
      <div class="li_inner">
        <h3 class="title">
          <a href="/hotdeal/7001">삼성 갤럭시 버즈3 79,000원 역대최저가</a>
        </h3>
        <span class="hotdeal_info">11번가 | 79,000원 | 무료배송</span>
        <span class="comment_count">[32]</span>
        <span class="vote_count">45</span>
      </div>
    </li>
    <li class="li li_best2_pop1">
      <div class="li_inner">
        <h3 class="title">
          <a href="/hotdeal/7002">애플 에어팟 프로2 259,000원</a>
        </h3>
        <span class="hotdeal_info">쿠팡 | 259,000원 | 로켓배송</span>
        <span class="comment_count">[15]</span>
        <span class="vote_count">28</span>
      </div>
    </li>
    <li class="li li_best2_pop0">
      <div class="li_inner">
        <h3 class="title">
          <a href="https://www.fmkorea.com/hotdeal/7003">무료 앱 나눔</a>
        </h3>
        <span class="hotdeal_info">구글플레이 | 무료</span>
      </div>
    </li>
  </ul>
</div>
</body></html>
"""

CLIEN_SAMPLE_HTML = """
<html><body>
<div class="board_list">
  <div class="list_item symph_row" data-board-sn="100001">
    <div class="list_title">
      <a class="list_subject" href="/service/board/jirum/100001">
        <span class="subject_fixed">[노트북] LG 그램 15인치 1,299,000원</span>
      </a>
      <span class="reply_symph">[24]</span>
    </div>
    <span class="hit">3421</span>
  </div>
  <div class="list_item symph_row" data-board-sn="100002">
    <div class="list_title">
      <a class="list_subject" href="/service/board/jirum/100002">
        <span class="subject_fixed">[생활] 대용량 세제 9,900원 특가</span>
      </a>
      <span class="reply_symph">[8]</span>
    </div>
    <span class="hit">1523</span>
  </div>
  <div class="list_item symph_row notice" data-board-sn="99999">
    <div class="list_title">
      <a class="list_subject" href="/service/board/jirum/99999">
        <span class="subject_fixed">[공지] 알뜰구매 게시판 규칙 안내</span>
      </a>
    </div>
  </div>
  <div class="list_item symph_row" data-board-sn="100003">
    <div class="list_title">
      <a class="list_subject" href="https://www.clien.net/service/board/jirum/100003">
        <span class="subject_fixed">무료 전자책 이벤트</span>
      </a>
      <span class="reply_symph">[5]</span>
    </div>
    <span class="hit">892</span>
  </div>
</div>
</body></html>
"""


# ──────────────────────────────────────────────
# 크롤러 인스턴스 생성 테스트
# ──────────────────────────────────────────────

class TestCrawlerInstantiation:
    """각 크롤러의 인스턴스 생성 및 메타 정보를 확인한다."""

    def test_ppomppu_instantiation(self):
        crawler = PpomppuCrawler()
        assert crawler.info.name == "뽐뿌"
        assert crawler.info.group == CrawlerGroup.HOTDEAL
        assert "requests" in crawler.info.strategies
        assert "ppomppu" in crawler.info.target_url

    def test_fmkorea_instantiation(self):
        crawler = FmkoreaCrawler()
        assert crawler.info.name == "FM코리아"
        assert crawler.info.group == CrawlerGroup.HOTDEAL
        assert "requests" in crawler.info.strategies
        assert "fmkorea" in crawler.info.target_url

    def test_clien_instantiation(self):
        crawler = ClienCrawler()
        assert crawler.info.name == "클리앙"
        assert crawler.info.group == CrawlerGroup.HOTDEAL
        assert "requests" in crawler.info.strategies
        assert "clien" in crawler.info.target_url


# ──────────────────────────────────────────────
# 가격 파싱 테스트
# ──────────────────────────────────────────────

class TestPriceParsing:
    """한국 원화 가격 포맷 파싱을 테스트한다."""

    @pytest.fixture
    def ppomppu(self):
        return PpomppuCrawler()

    @pytest.fixture
    def fmkorea(self):
        return FmkoreaCrawler()

    @pytest.fixture
    def clien(self):
        return ClienCrawler()

    def test_comma_separated_price(self, ppomppu):
        """콤마 포함 가격: '12,500원' → 12500"""
        assert ppomppu._extract_price("12,500원") == 12500

    def test_large_comma_price(self, ppomppu):
        """큰 가격: '1,299,000원' → 1299000"""
        assert ppomppu._extract_price("1,299,000원") == 1299000

    def test_no_comma_price(self, ppomppu):
        """콤마 없는 가격: '500원' → 500"""
        assert ppomppu._extract_price("500원") == 500

    def test_free_price(self, ppomppu):
        """무료: '무료' → 0"""
        assert ppomppu._extract_price("무료") == 0

    def test_free_shipping_not_free(self, ppomppu):
        """무료배송은 무료가 아님"""
        assert ppomppu._extract_price("무료배송") is None

    def test_price_in_sentence(self, fmkorea):
        """문장 내 가격: '특가 29,900원 한정수량' → 29900"""
        assert fmkorea._extract_price("특가 29,900원 한정수량") == 29900

    def test_no_price(self, clien):
        """가격 없는 텍스트"""
        assert clien._extract_price("가격 정보 없음") is None

    def test_empty_string(self, clien):
        """빈 문자열"""
        assert clien._extract_price("") is None

    def test_none_input(self, ppomppu):
        """None 입력"""
        assert ppomppu._extract_price(None) is None

    def test_price_with_won_sign(self, fmkorea):
        """'79,000원' → 79000"""
        assert fmkorea._extract_price("79,000원") == 79000


# ──────────────────────────────────────────────
# parse 메서드 테스트
# ──────────────────────────────────────────────

class TestPpomppuParse:
    """뽐뿌 크롤러의 parse 결과를 검증한다."""

    @pytest.fixture
    def crawler(self):
        return PpomppuCrawler()

    def test_parse_returns_items(self, crawler):
        items = asyncio.run(
            crawler.parse(PPOMPPU_SAMPLE_HTML)
        )
        # 공지 제외하고 최소 3개 이상
        assert len(items) >= 3

    def test_parse_item_fields(self, crawler):
        items = asyncio.run(
            crawler.parse(PPOMPPU_SAMPLE_HTML)
        )
        first = items[0]
        assert isinstance(first, HotdealPost)
        assert len(first.title) >= 3
        assert first.url
        assert first.price_evidence
        assert first.category_hints
        assert first.source_community == "뽐뿌"

    def test_parse_extracts_price(self, crawler):
        items = asyncio.run(
            crawler.parse(PPOMPPU_SAMPLE_HTML)
        )
        prices = [item.price for item in items if item.price is not None]
        assert 12500 in prices

    def test_parse_extracts_category(self, crawler):
        items = asyncio.run(
            crawler.parse(PPOMPPU_SAMPLE_HTML)
        )
        categories = [item.category for item in items if item.category]
        assert any("식품" in c for c in categories)

    def test_parse_skips_notices(self, crawler):
        items = asyncio.run(
            crawler.parse(PPOMPPU_SAMPLE_HTML)
        )
        titles = [item.title for item in items]
        assert not any("[공지]" in t for t in titles)

    def test_parse_free_item(self, crawler):
        items = asyncio.run(
            crawler.parse(PPOMPPU_SAMPLE_HTML)
        )
        free_items = [item for item in items if item.price == 0]
        assert len(free_items) >= 1


class TestFmkoreaParse:
    """FM코리아 크롤러의 parse 결과를 검증한다."""

    @pytest.fixture
    def crawler(self):
        return FmkoreaCrawler()

    def test_parse_returns_items(self, crawler):
        items = asyncio.run(
            crawler.parse(FMKOREA_SAMPLE_HTML)
        )
        assert len(items) >= 2

    def test_parse_item_fields(self, crawler):
        items = asyncio.run(
            crawler.parse(FMKOREA_SAMPLE_HTML)
        )
        first = items[0]
        assert isinstance(first, HotdealPost)
        assert len(first.title) >= 3
        assert first.url
        assert first.price_evidence
        assert first.category_hints
        assert first.source_community == "FM코리아"

    def test_parse_extracts_price(self, crawler):
        items = asyncio.run(
            crawler.parse(FMKOREA_SAMPLE_HTML)
        )
        prices = [item.price for item in items if item.price is not None]
        assert 79000 in prices

    def test_parse_free_item(self, crawler):
        items = asyncio.run(
            crawler.parse(FMKOREA_SAMPLE_HTML)
        )
        free_items = [item for item in items if item.price == 0]
        assert len(free_items) >= 1


class TestClienParse:
    """클리앙 크롤러의 parse 결과를 검증한다."""

    @pytest.fixture
    def crawler(self):
        return ClienCrawler()

    def test_parse_returns_items(self, crawler):
        items = asyncio.run(
            crawler.parse(CLIEN_SAMPLE_HTML)
        )
        # 공지 제외하고 최소 2개
        assert len(items) >= 2

    def test_parse_item_fields(self, crawler):
        items = asyncio.run(
            crawler.parse(CLIEN_SAMPLE_HTML)
        )
        first = items[0]
        assert isinstance(first, HotdealPost)
        assert len(first.title) >= 3
        assert first.url
        assert first.price_evidence
        assert first.category_hints
        assert first.source_community == "클리앙"

    def test_parse_extracts_price(self, crawler):
        items = asyncio.run(
            crawler.parse(CLIEN_SAMPLE_HTML)
        )
        prices = [item.price for item in items if item.price is not None]
        assert 1299000 in prices

    def test_parse_skips_notices(self, crawler):
        items = asyncio.run(
            crawler.parse(CLIEN_SAMPLE_HTML)
        )
        titles = [item.title for item in items]
        assert not any("[공지]" in t for t in titles)

    def test_parse_extracts_category(self, crawler):
        items = asyncio.run(
            crawler.parse(CLIEN_SAMPLE_HTML)
        )
        categories = [item.category for item in items if item.category]
        assert any("노트북" in c for c in categories)


# ──────────────────────────────────────────────
# URL 정규화 테스트
# ──────────────────────────────────────────────

class TestUrlNormalization:
    """상대 URL이 절대 URL로 올바르게 변환되는지 확인한다."""

    def test_ppomppu_relative_url(self):
        crawler = PpomppuCrawler()
        items = asyncio.run(
            crawler.parse(PPOMPPU_SAMPLE_HTML)
        )
        for item in items:
            assert item.url.startswith("http"), f"URL이 절대 경로가 아님: {item.url}"

    def test_ppomppu_absolute_url_preserved(self):
        crawler = PpomppuCrawler()
        items = asyncio.run(
            crawler.parse(PPOMPPU_SAMPLE_HTML)
        )
        abs_items = [i for i in items if "1237" in i.url]
        if abs_items:
            assert abs_items[0].url.startswith("https://www.ppomppu.co.kr")

    def test_fmkorea_relative_url(self):
        crawler = FmkoreaCrawler()
        items = asyncio.run(
            crawler.parse(FMKOREA_SAMPLE_HTML)
        )
        for item in items:
            assert item.url.startswith("http"), f"URL이 절대 경로가 아님: {item.url}"

    def test_clien_relative_url(self):
        crawler = ClienCrawler()
        items = asyncio.run(
            crawler.parse(CLIEN_SAMPLE_HTML)
        )
        for item in items:
            assert item.url.startswith("http"), f"URL이 절대 경로가 아님: {item.url}"


# ──────────────────────────────────────────────
# validate 테스트
# ──────────────────────────────────────────────

class TestValidation:
    """validate가 필수 필드 누락·중복을 올바르게 거부하는지 확인한다."""

    def test_ppomppu_rejects_short_title(self):
        crawler = PpomppuCrawler()
        items = [
            HotdealPost(title="AB", url="https://example.com/1", source_community="뽐뿌"),
            HotdealPost(title="정상 제목 테스트", url="https://example.com/2", source_community="뽐뿌"),
        ]
        valid = asyncio.run(crawler.validate(items))
        assert len(valid) == 1
        assert valid[0].title == "정상 제목 테스트"

    def test_fmkorea_deduplicates_urls(self):
        crawler = FmkoreaCrawler()
        items = [
            HotdealPost(title="상품 A", url="https://example.com/dup", source_community="FM코리아"),
            HotdealPost(title="상품 B", url="https://example.com/dup", source_community="FM코리아"),
            HotdealPost(title="상품 C", url="https://example.com/unique", source_community="FM코리아"),
        ]
        valid = asyncio.run(crawler.validate(items))
        assert len(valid) == 2

    def test_clien_rejects_short_title(self):
        crawler = ClienCrawler()
        items = [
            HotdealPost(title="X", url="https://example.com/1", source_community="클리앙"),
            HotdealPost(title="OK", url="https://example.com/2", source_community="클리앙"),
            HotdealPost(title="정상적인 핫딜 게시글", url="https://example.com/3", source_community="클리앙"),
        ]
        valid = asyncio.run(crawler.validate(items))
        assert len(valid) == 1
        assert valid[0].title == "정상적인 핫딜 게시글"

    def test_validate_preserves_valid_items(self):
        crawler = PpomppuCrawler()
        items = [
            HotdealPost(title="좋은 상품 핫딜", url="https://example.com/a", source_community="뽐뿌", price=15000),
            HotdealPost(title="또 다른 핫딜", url="https://example.com/b", source_community="뽐뿌", price=29000),
        ]
        valid = asyncio.run(crawler.validate(items))
        assert len(valid) == 2


# ──────────────────────────────────────────────
# source collection loop / source-owned facts
# ──────────────────────────────────────────────

PPOMPPU_PAGE1_WITH_NEXT = """
<html><body><table>
  <tr class="baseList bbs_new1">
    <td>2001</td><td><a class="baseList-title" href="view.php?id=ppomppu&no=2001"><font class="list_title">[마트] 쌀 10kg 29,900원</font></a></td>
    <td class="baseList-price">29,900원</td><td><time datetime="2025-01-03T10:00:00">2025-01-03 10:00</time></td>
  </tr>
</table><a class="next" href="zboard.php?id=ppomppu&page=2">다음</a></body></html>
"""

PPOMPPU_PAGE2_WITH_CUTOFF = """
<html><body><table>
  <tr class="baseList bbs_new1">
    <td>2002</td><td><a class="baseList-title" href="view.php?id=ppomppu&no=2002"><font class="list_title">[생활] 키친타월 8,900원</font></a></td>
    <td class="baseList-price">8,900원</td><td><time datetime="2025-01-02T10:00:00">2025-01-02 10:00</time></td>
  </tr>
</table></body></html>
"""

CLIEN_FACT_HTML = """
<html><body><div class="board_list">
  <div class="list_item symph_row" data-board-sn="3001">
    <div class="list_title"><a class="list_subject" href="/service/board/jirum/3001"><span class="subject_fixed">[PC] USB 허브 12,900원</span></a></div>
    <img data-src="/images/hub.jpg" />
    <time datetime="2025-01-04T09:30:00">2025-01-04 09:30</time>
  </div>
</div></body></html>
"""

FMKOREA_DUP_KEY_HTML = """
<html><body><div class="fm_best_widget"><ul>
  <li class="li li_best2_pop0"><h3 class="title"><a href="/hotdeal/9001?utm=one">마우스 특가 19,900원</a></h3><span class="hotdeal_info">11번가 | 19,900원</span></li>
  <li class="li li_best2_pop1"><h3 class="title"><a href="https://www.fmkorea.com/hotdeal/9001?utm=two">마우스 특가 19,900원 재등록</a></h3><span class="hotdeal_info">11번가 | 19,900원</span></li>
</ul></div></body></html>
"""


def test_ppomppu_collect_pages_uses_next_page_and_since_date_cutoff(monkeypatch):
    crawler = PpomppuCrawler()
    pages = {
        crawler.DEAL_URL: PPOMPPU_PAGE1_WITH_NEXT,
        "https://www.ppomppu.co.kr/zboard/zboard.php?id=ppomppu&page=2": PPOMPPU_PAGE2_WITH_CUTOFF,
    }
    seen_urls = []

    def fake_fetch(url):
        seen_urls.append(url)
        return pages[url]

    monkeypatch.setattr(crawler, "_fetch_collection_page", fake_fetch)
    items = asyncio.run(crawler.collect_pages(max_pages=3, since_source_keys=set(), since_post_date=None))

    assert seen_urls == list(pages.keys())
    assert [item.source_record_key for item in items] == ["ppomppu:no:2001", "ppomppu:no:2002"]
    assert all(item.source_url.startswith("https://www.ppomppu.co.kr") for item in items)

    cutoff_items = asyncio.run(crawler.collect_pages(max_pages=3, since_post_date=items[0].post_date))
    assert cutoff_items == []


def test_clien_preserves_source_owned_facts_image_category_and_post_date():
    crawler = ClienCrawler()
    items = asyncio.run(crawler.parse(CLIEN_FACT_HTML))
    valid = asyncio.run(crawler.validate(items))

    assert len(valid) == 1
    item = valid[0]
    assert item.source_record_key == "clien:post:3001"
    assert item.source_url == "https://www.clien.net/service/board/jirum/3001"
    assert item.image_url == "https://www.clien.net/images/hub.jpg"
    assert item.category_hints == ["PC"]
    assert item.post_date.isoformat() == "2025-01-04T09:30:00"


def test_fmkorea_deduplicates_by_source_record_key_not_tracking_query():
    crawler = FmkoreaCrawler()
    items = asyncio.run(crawler.parse(FMKOREA_DUP_KEY_HTML))
    valid = asyncio.run(crawler.validate(items))

    assert len(valid) == 1
    assert valid[0].source_record_key == "fmkorea:post:9001"
    assert valid[0].category_hints == ["11번가"]
