"""
AntiDetect 및 전략 기본 기능 테스트 (TDD).
"""

import pytest
from engine.anti_detect import AntiDetect, USER_AGENTS
from core.exceptions import CrawlError
from engine.strategies.cloudscraper_st import CloudscraperStrategy
from engine.strategies.undetected_st import UndetectedStrategy


class TestAntiDetect:

    def test_random_user_agent(self):
        """랜덤 UA가 풀에서 선택된다."""
        ad = AntiDetect()
        ua = ad.get_random_user_agent()
        assert ua in USER_AGENTS

    def test_random_headers_structure(self):
        """헤더에 필수 키가 포함된다."""
        ad = AntiDetect()
        headers = ad.get_random_headers()

        assert "User-Agent" in headers
        assert "Accept" in headers
        assert "Accept-Language" in headers
        assert "ko" in headers["Accept-Language"]  # 한국어 포함

    def test_proxy_round_robin(self):
        """프록시가 라운드 로빈으로 순환한다."""
        ad = AntiDetect(proxies=["p1", "p2", "p3"])

        assert ad.get_next_proxy() == "p1"
        assert ad.get_next_proxy() == "p2"
        assert ad.get_next_proxy() == "p3"
        assert ad.get_next_proxy() == "p1"  # 순환

    def test_no_proxy(self):
        """프록시 미설정 시 None 반환."""
        ad = AntiDetect()
        assert ad.get_next_proxy() is None
        assert ad.get_random_proxy() is None
        assert ad.has_proxies is False

    def test_add_remove_proxy(self):
        """프록시 동적 추가/제거."""
        ad = AntiDetect()
        ad.add_proxy("p1")
        assert ad.proxy_count == 1
        assert ad.has_proxies is True

        ad.remove_proxy("p1")
        assert ad.proxy_count == 0

    def test_duplicate_proxy_not_added(self):
        """중복 프록시 추가 방지."""
        ad = AntiDetect(proxies=["p1"])
        ad.add_proxy("p1")
        assert ad.proxy_count == 1

    def test_random_delay_range(self):
        """딜레이가 지정 범위 내에 있다."""
        ad = AntiDetect(delay_min=1.0, delay_max=3.0)

        for _ in range(50):
            delay = ad.get_random_delay()
            assert 1.0 <= delay <= 3.0

    def test_user_agent_pool_size(self):
        """UA 풀에 충분한 수가 있다."""
        assert len(USER_AGENTS) >= 15


class TestSafeBrowserStrategies:
    def test_browser_strategy_sources_do_not_include_stealth_evasion(self):
        from pathlib import Path

        strategy_dir = Path(__file__).resolve().parents[1] / "strategies"
        combined = "\n".join(
            [
                (strategy_dir / "playwright_st.py").read_text(encoding="utf-8"),
                (strategy_dir / "selenium_st.py").read_text(encoding="utf-8"),
            ]
        )

        assert "playwright_stealth" not in combined
        assert "selenium_stealth" not in combined
        assert "AutomationControlled" not in combined
        assert "excludeSwitches" not in combined
        assert "useAutomationExtension" not in combined
        assert "user_agent=ua" not in combined

    @pytest.mark.asyncio
    async def test_undetected_strategy_is_disabled_for_safe_collection(self):
        strategy = UndetectedStrategy()

        with pytest.raises(CrawlError, match="undetected browser automation is disabled"):
            await strategy.fetch("https://example.com")

    @pytest.mark.asyncio
    async def test_cloudscraper_strategy_is_disabled_for_safe_collection(self):
        strategy = CloudscraperStrategy()

        with pytest.raises(CrawlError, match="cloudscraper challenge-solving is disabled"):
            await strategy.fetch("https://example.com")
