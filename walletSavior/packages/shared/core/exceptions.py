"""
구조화된 예외 계층 — "왜 실패했는가"를 코드로 표현한다.

왜 존재하는가:
    파이썬 기본 Exception만 쓰면 except에서 문자열 파싱으로 원인을 추측해야 한다.
    ErrorType을 품은 커스텀 예외를 쓰면 DiagnosticsEngine이 catch 즉시
    원인 분류 → 심각도 산정 → 대응 추천을 자동으로 수행할 수 있다.
어디서 쓰이는가:
    strategies/base.py가 모든 예외를 CrawlError로 래핑 → executor가 catch해서
    StrategyFailure 생성 → DiagnosticsEngine.analyze()가 DiagnosisReport 생성.
"""

from .models import ErrorType


class WalletGuardianError(Exception):
    """프로젝트 최상위 예외 — 외부 라이브러리 예외와 우리 예외를 구분하는 경계선."""
    pass


class CrawlError(WalletGuardianError):
    """
    크롤링 실패 예외 — error_type 필드로 DiagnosticsEngine이 자동 진단한다.

    BaseStrategy.fetch()에서 모든 예외가 이 타입으로 래핑되므로,
    executor는 CrawlError만 catch하면 모든 실패를 일관되게 처리할 수 있다.
    """

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
    """봇 차단 (IP 밴, 캡챠 등) — 프록시 교체·딜레이 증가가 필요한 상황."""

    def __init__(self, message: str, strategy_name: str = ""):
        super().__init__(
            message,
            error_type=ErrorType.IP_BANNED,
            strategy_name=strategy_name,
        )


class CaptchaDetectedError(CrawlError):
    """캡챠 감지 — 현재 전략을 포기하고 브라우저 기반 전략으로 cascade해야 한다."""

    def __init__(self, message: str = "CAPTCHA detected", strategy_name: str = ""):
        super().__init__(
            message,
            error_type=ErrorType.CAPTCHA_DETECTED,
            strategy_name=strategy_name,
        )


class DOMChangedError(CrawlError):
    """대상 사이트가 HTML 구조를 변경함 — 셀렉터 업데이트가 필요하다는 신호."""

    def __init__(self, message: str, strategy_name: str = ""):
        super().__init__(
            message,
            error_type=ErrorType.DOM_CHANGED,
            strategy_name=strategy_name,
        )


class AllStrategiesFailedError(WalletGuardianError):
    """cascade 전체 실패 — 모든 전략이 소진되어 더 이상 시도할 수 없는 최종 상태."""

    def __init__(self, crawler_name: str, failures: list | None = None):
        self.crawler_name = crawler_name
        self.failures = failures or []
        super().__init__(
            f"[{crawler_name}] 모든 전략 실패 ({len(self.failures)}개 시도)"
        )


class StorageError(WalletGuardianError):
    """저장소 계층(DB, 파일) 예외 — 크롤링 자체는 성공했으나 결과 저장에 실패."""
    pass


class ConfigError(WalletGuardianError):
    """필수 설정 누락 예외 — .env에 API 키가 없거나 DB URL이 잘못된 경우 부트스트랩 시 즉시 실패시킨다."""
    pass
