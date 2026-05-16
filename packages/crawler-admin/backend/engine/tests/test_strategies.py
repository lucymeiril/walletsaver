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


class TestOperatorWorkbenchStrategies:
    """운영자 워크밴치 정책상 회피/스텔스 라이브러리 사용은 *허용*된다.

    과거에 "stealth 키워드/AutomationControlled 등은 코드에 존재 금지"라는
    *작업 마비형* 테스트가 있었지만, 사용자가 명시적으로 정책을 뒤집었다.
    여기서는 의도와 단일 진실 정책이 살아 있는지만 검증한다.
    """

    def test_operator_workbench_policy_allows_stealth_and_handoff(self):
        from pipeline.operator_workbench_policy import OPERATOR_WORKBENCH_POLICY

        assert OPERATOR_WORKBENCH_POLICY["automation_flag_hiding_allowed"] is True
        assert OPERATOR_WORKBENCH_POLICY["automated_captcha_attempt"] is True
        assert OPERATOR_WORKBENCH_POLICY["challenge_solver_libraries_allowed"] is True
        assert OPERATOR_WORKBENCH_POLICY["human_handoff_required_on_auto_failure"] is True
        # 변하지 않는 금지선.
        assert OPERATOR_WORKBENCH_POLICY["third_party_credential_automation"] is False
        assert OPERATOR_WORKBENCH_POLICY["bypass_code_in_live_web_backend"] is False

    @pytest.mark.asyncio
    async def test_undetected_strategy_body_is_restored(self):
        """본체가 살아있고 의존성 미설치 시 명확한 안내를 던진다.

        이전처럼 "disabled" 문구로 즉시 raise하면 다시 본체가 죽은 것이다.
        """
        strategy = UndetectedStrategy()
        try:
            await strategy.fetch("about:blank")
        except CrawlError as exc:
            message = str(exc)
            assert "disabled" not in message.lower(), \
                "본체가 다시 비활성화되어 있다. operator_workbench_policy 의도를 확인하라."

    @pytest.mark.asyncio
    async def test_cloudscraper_strategy_body_is_restored(self):
        strategy = CloudscraperStrategy()
        try:
            await strategy.fetch("https://example.invalid")
        except CrawlError as exc:
            message = str(exc)
            assert "disabled" not in message.lower(), \
                "본체가 다시 비활성화되어 있다. operator_workbench_policy 의도를 확인하라."

