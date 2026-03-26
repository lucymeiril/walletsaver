"""
core.exceptions 테스트 (TDD).

예외 계층 구조, 에러 타입 분류, 메시지 포맷을 검증한다.
"""

import pytest

from core.exceptions import (
    WalletGuardianError,
    CrawlError,
    CrawlerBlockedError,
    CaptchaDetectedError,
    DOMChangedError,
    AllStrategiesFailedError,
    StorageError,
    ConfigError,
)
from core.models import ErrorType


class TestExceptionHierarchy:
    """예외 상속 구조 테스트."""

    def test_crawl_error_is_base(self):
        with pytest.raises(WalletGuardianError):
            raise CrawlError("test")

    def test_blocked_is_crawl_error(self):
        with pytest.raises(CrawlError):
            raise CrawlerBlockedError("IP banned")

    def test_captcha_is_crawl_error(self):
        with pytest.raises(CrawlError):
            raise CaptchaDetectedError()

    def test_dom_changed_is_crawl_error(self):
        with pytest.raises(CrawlError):
            raise DOMChangedError("selector not found")

    def test_all_strategies_failed_is_base(self):
        with pytest.raises(WalletGuardianError):
            raise AllStrategiesFailedError("이마트")

    def test_storage_error_is_base(self):
        with pytest.raises(WalletGuardianError):
            raise StorageError("DB connection failed")

    def test_config_error_is_base(self):
        with pytest.raises(WalletGuardianError):
            raise ConfigError("API key missing")


class TestCrawlError:
    """CrawlError 속성 테스트."""

    def test_default_error_type(self):
        err = CrawlError("something failed")
        assert err.error_type == ErrorType.UNKNOWN

    def test_custom_error_type(self):
        err = CrawlError("timeout", error_type=ErrorType.TIMEOUT, status_code=408)
        assert err.error_type == ErrorType.TIMEOUT
        assert err.status_code == 408

    def test_strategy_name(self):
        err = CrawlError("fail", strategy_name="selenium")
        assert err.strategy_name == "selenium"


class TestCrawlerBlockedError:

    def test_default_type(self):
        err = CrawlerBlockedError("blocked")
        assert err.error_type == ErrorType.IP_BANNED

    def test_message(self):
        err = CrawlerBlockedError("IP blocked by server")
        assert "IP blocked" in str(err)


class TestCaptchaDetectedError:

    def test_default_message(self):
        err = CaptchaDetectedError()
        assert err.error_type == ErrorType.CAPTCHA_DETECTED
        assert "CAPTCHA" in str(err)


class TestDOMChangedError:

    def test_error_type(self):
        err = DOMChangedError("div.product-list not found")
        assert err.error_type == ErrorType.DOM_CHANGED


class TestAllStrategiesFailedError:

    def test_message_format(self):
        err = AllStrategiesFailedError("이마트", failures=["a", "b", "c"])
        assert "이마트" in str(err)
        assert "3" in str(err)
        assert err.crawler_name == "이마트"
        assert len(err.failures) == 3

    def test_empty_failures(self):
        err = AllStrategiesFailedError("홈플러스")
        assert err.failures == []
