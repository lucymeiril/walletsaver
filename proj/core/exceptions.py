"""
공통 예외 정의.

모든 모듈이 사용하는 예외 클래스.
에러 타입 분류를 통해 진단 시스템과 연동된다.
"""

from core.models import ErrorType


class WalletGuardianError(Exception):
    """프로젝트 최상위 예외."""
    pass


class CrawlError(WalletGuardianError):
    """크롤링 실패 예외. 에러 타입 분류 포함."""

    def __init__(
        self,
        message: str,
        error_type: ErrorType = ErrorType.UNKNOWN,
        status_code: int | None = None,
        strategy_name: str = "",
    ):
        super().__init__(message)
        self.error_type = error_type
        self.status_code = status_code
        self.strategy_name = strategy_name


class CrawlerBlockedError(CrawlError):
    """봇 차단 (IP 밴, 캡챠 등)."""

    def __init__(self, message: str, strategy_name: str = ""):
        super().__init__(
            message,
            error_type=ErrorType.IP_BANNED,
            strategy_name=strategy_name,
        )


class CaptchaDetectedError(CrawlError):
    """캡챠 감지."""

    def __init__(self, message: str = "CAPTCHA detected", strategy_name: str = ""):
        super().__init__(
            message,
            error_type=ErrorType.CAPTCHA_DETECTED,
            strategy_name=strategy_name,
        )


class DOMChangedError(CrawlError):
    """DOM 구조 변경 (셀렉터 불일치)."""

    def __init__(self, message: str, strategy_name: str = ""):
        super().__init__(
            message,
            error_type=ErrorType.DOM_CHANGED,
            strategy_name=strategy_name,
        )


class AllStrategiesFailedError(WalletGuardianError):
    """모든 크롤링 전략이 실패."""

    def __init__(self, crawler_name: str, failures: list | None = None):
        self.crawler_name = crawler_name
        self.failures = failures or []
        super().__init__(
            f"[{crawler_name}] 모든 전략 실패 ({len(self.failures)}개 시도)"
        )


class StorageError(WalletGuardianError):
    """저장소 관련 예외."""
    pass


class ConfigError(WalletGuardianError):
    """설정 관련 예외 (API 키 누락 등)."""
    pass
