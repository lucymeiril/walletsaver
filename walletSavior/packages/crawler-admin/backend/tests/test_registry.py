"""
크롤러 레지스트리 테스트.

레지스트리가 plugin.yaml 파일을 자동 발견하고
크롤러를 인스턴스화할 수 있는지 검증한다.
"""

import pytest
from pathlib import Path

from crawlers.registry.registry import CrawlerRegistry


@pytest.fixture
def registry():
    """crawlers/ 디렉토리를 스캔하는 레지스트리."""
    crawlers_dir = Path(__file__).resolve().parent.parent / "crawlers"
    reg = CrawlerRegistry(crawlers_dir=crawlers_dir)
    reg.discover()
    return reg


class TestRegistryDiscover:
    """plugin.yaml 자동 발견 테스트."""

    def test_discovers_plugin_yaml_files(self, registry):
        """plugin.yaml이 있는 크롤러를 발견한다."""
        crawler_list = registry.list_crawlers()
        assert len(crawler_list) >= 2, f"최소 2개 이상의 크롤러가 발견되어야 한다: {crawler_list}"

    def test_discovers_cocodalin(self, registry):
        """코코달인 크롤러를 발견한다."""
        names = [c["name"] for c in registry.list_crawlers()]
        assert "cocodalin" in names

    def test_discovers_algumon(self, registry):
        """알구몬 크롤러를 발견한다."""
        names = [c["name"] for c in registry.list_crawlers()]
        assert "algumon" in names

    def test_discovers_new_mart_crawlers(self, registry):
        """새로 추가된 마트 크롤러를 발견한다."""
        names = [c["name"] for c in registry.list_crawlers()]
        for name in ["emart", "homeplus", "lottemart"]:
            assert name in names, f"'{name}' 크롤러가 발견되어야 한다"


class TestRegistryListCrawlers:
    """크롤러 목록 조회 테스트."""

    def test_list_returns_required_fields(self, registry):
        """목록 조회 시 필수 필드가 포함된다."""
        for crawler in registry.list_crawlers():
            assert "name" in crawler
            assert "display_name" in crawler
            assert "category" in crawler
            assert "difficulty" in crawler
            assert "schedule" in crawler

    def test_mart_crawlers_have_correct_category(self, registry):
        """마트 크롤러의 카테고리가 'mart'이다."""
        for crawler in registry.list_crawlers():
            if crawler["name"] in ["emart", "homeplus", "lottemart", "cocodalin"]:
                assert crawler["category"] == "mart"

    def test_hotdeal_crawlers_have_correct_category(self, registry):
        """핫딜 크롤러의 카테고리가 'hotdeal'이다."""
        for crawler in registry.list_crawlers():
            if crawler["name"] == "algumon":
                assert crawler["category"] == "hotdeal"


class TestRegistryGetCrawler:
    """크롤러 인스턴스 생성 테스트."""

    def test_get_cocodalin_crawler(self, registry):
        """코코달인 크롤러를 인스턴스화한다."""
        crawler = registry.get_crawler("cocodalin")
        assert crawler is not None
        assert hasattr(crawler, "info")
        assert hasattr(crawler, "crawl")

    def test_get_algumon_crawler(self, registry):
        """알구몬 크롤러를 인스턴스화한다."""
        crawler = registry.get_crawler("algumon")
        assert crawler is not None
        assert hasattr(crawler, "info")

    def test_get_emart_crawler(self, registry):
        """이마트 크롤러를 인스턴스화한다."""
        crawler = registry.get_crawler("emart")
        assert crawler is not None
        assert hasattr(crawler, "crawl")

    def test_get_homeplus_crawler(self, registry):
        """홈플러스 크롤러를 인스턴스화한다."""
        crawler = registry.get_crawler("homeplus")
        assert crawler is not None

    def test_get_lottemart_crawler(self, registry):
        """롯데마트 크롤러를 인스턴스화한다."""
        crawler = registry.get_crawler("lottemart")
        assert crawler is not None

    def test_get_nonexistent_raises_error(self, registry):
        """존재하지 않는 크롤러 요청 시 KeyError 발생."""
        with pytest.raises(KeyError):
            registry.get_crawler("nonexistent_crawler")
