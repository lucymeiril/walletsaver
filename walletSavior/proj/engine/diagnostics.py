"""
크롤링 실패 자동 진단 엔진 — AI가 크롤러를 스스로 고치기 위한 첫 단계.

왜 존재하는가:
    크롤러가 실패했을 때 사람이 로그를 읽고 원인을 파악하는 건 스케일이 안 된다.
    실패 원인을 자동 분류하고, 심각도를 매기고, 대응 방안을 추천해야
    (1) 대시보드에서 즉시 상황을 파악할 수 있고
    (2) 향후 자동 복구(프록시 교체, 셀렉터 업데이트 등)를 구현할 수 있다.
어디서 쓰이는가:
    executor에서 cascade 전체 실패 시 → CRAWL_FAILED 이벤트 →
    이 엔진의 analyze() → DiagnosisReport → 대시보드·알림 시스템.
    의존: core/ 만
"""

from __future__ import annotations

import logging
from core.models import (
    CrawlResult,
    CrawlStatus,
    StrategyFailure,
    DiagnosisReport,
    ErrorType,
)

logger = logging.getLogger(__name__)

# 에러 타입 → 한국어 설명 매핑
ERROR_DESCRIPTIONS: dict[ErrorType, str] = {
    ErrorType.HTTP_ERROR: "HTTP 응답 에러 (4xx/5xx)",
    ErrorType.CAPTCHA_DETECTED: "CAPTCHA가 감지되었습니다",
    ErrorType.IP_BANNED: "IP가 차단되었습니다",
    ErrorType.JS_CHALLENGE: "JavaScript 챌린지가 감지되었습니다 (Cloudflare 등)",
    ErrorType.DOM_CHANGED: "페이지 DOM 구조가 변경되었습니다 (CSS 셀렉터 불일치)",
    ErrorType.TIMEOUT: "요청 시간이 초과되었습니다",
    ErrorType.LOGIN_REQUIRED: "로그인이 필요합니다",
    ErrorType.EMPTY_RESPONSE: "빈 응답이 반환되었습니다",
    ErrorType.PARSE_ERROR: "데이터 파싱 중 오류가 발생했습니다",
    ErrorType.NETWORK_ERROR: "네트워크 연결 오류",
    ErrorType.UNKNOWN: "알 수 없는 오류",
}

# 에러 타입 → 추천 대응 매핑
ERROR_RECOMMENDATIONS: dict[ErrorType, str] = {
    ErrorType.HTTP_ERROR: "URL이 변경되었거나 서버 점검 중일 수 있습니다. URL을 확인하고 나중에 다시 시도하세요.",
    ErrorType.CAPTCHA_DETECTED: "CAPTCHA 해결 서비스를 연동하거나, 요청 간격을 늘리고 프록시를 교체해 보세요.",
    ErrorType.IP_BANNED: "프록시를 교체하고 요청 간격을 늘리세요. User-Agent도 변경해 보세요.",
    ErrorType.JS_CHALLENGE: "cloudscraper 또는 브라우저 기반 전략(Selenium/Playwright)을 사용하세요.",
    ErrorType.DOM_CHANGED: "대시보드에서 CSS 셀렉터를 업데이트하세요. 대상 사이트 구조가 변경된 것으로 보입니다.",
    ErrorType.TIMEOUT: "REQUEST_TIMEOUT 값을 늘리거나, 네트워크 상태를 확인하세요.",
    ErrorType.LOGIN_REQUIRED: "인증 정보(.env)를 설정하거나, 크롤러에 로그인 로직을 추가하세요.",
    ErrorType.EMPTY_RESPONSE: "JavaScript 렌더링 대기 시간을 늘리거나, 브라우저 전략을 사용하세요.",
    ErrorType.PARSE_ERROR: "파싱 로직을 확인하세요. 데이터 형식이 변경되었을 수 있습니다.",
    ErrorType.NETWORK_ERROR: "네트워크 연결을 확인하세요. DNS 또는 방화벽 문제일 수 있습니다.",
    ErrorType.UNKNOWN: "로그를 상세히 확인하고, 수동으로 대상 사이트에 접근해 보세요.",
}

# 에러 심각도 가중치 — _determine_overall_type()에서 "가장 심각한 원인"을 결정하는 기준.
# 높을수록 심각: IP_BANNED(10)은 프록시 풀 전체 교체가 필요하고,
# PARSE_ERROR(2)는 셀렉터만 고치면 된다. 이 차이가 대응 우선순위를 결정한다.
ERROR_SEVERITY: dict[ErrorType, int] = {
    ErrorType.IP_BANNED: 10,
    ErrorType.CAPTCHA_DETECTED: 9,
    ErrorType.JS_CHALLENGE: 7,
    ErrorType.LOGIN_REQUIRED: 6,
    ErrorType.DOM_CHANGED: 5,
    ErrorType.HTTP_ERROR: 4,
    ErrorType.EMPTY_RESPONSE: 3,
    ErrorType.TIMEOUT: 3,
    ErrorType.PARSE_ERROR: 2,
    ErrorType.NETWORK_ERROR: 2,
    ErrorType.UNKNOWN: 1,
}


class DiagnosticsEngine:
    """
    크롤링 실패 진단 엔진 — 실패한 CrawlResult를 분석하여 원인·대응을 자동으로 도출한다.

    왜 별도 클래스인가:
        진단 로직이 executor에 섞이면 executor가 비대해지고 테스트가 어려워진다.
        독립된 엔진으로 분리하면 진단 규칙을 확장(예: ML 기반 패턴 인식)해도
        executor는 건드릴 필요가 없다.
    """

    def analyze(self, result: CrawlResult) -> DiagnosisReport:
        """
        실패한 크롤링 결과를 분석한다.

        Args:
            result: 실패한 CrawlResult

        Returns:
            DiagnosisReport: 진단 리포트
        """
        if not result.errors:
            return DiagnosisReport(
                crawler_name=result.crawler_name,
                overall_error_type=ErrorType.UNKNOWN,
                summary="에러 정보가 없습니다.",
                failures=[],
                recommendation="크롤러 로그를 상세히 확인하세요.",
            )

        # 가장 심각한 에러 타입 결정
        overall_type = self._determine_overall_type(result.errors)

        # 요약 생성
        summary = self._build_summary(result.crawler_name, result.errors, overall_type)

        # 추천 대응
        recommendation = ERROR_RECOMMENDATIONS.get(overall_type, ERROR_RECOMMENDATIONS[ErrorType.UNKNOWN])

        return DiagnosisReport(
            crawler_name=result.crawler_name,
            overall_error_type=overall_type,
            summary=summary,
            failures=result.errors,
            recommendation=recommendation,
        )

    def analyze_failure(self, failure: StrategyFailure) -> dict:
        """
        개별 전략 실패를 분석한다.

        Returns:
            {"error_type": str, "description": str, "recommendation": str, "severity": int}
        """
        return {
            "error_type": failure.error_type.value,
            "description": ERROR_DESCRIPTIONS.get(failure.error_type, "알 수 없는 오류"),
            "recommendation": ERROR_RECOMMENDATIONS.get(failure.error_type, "로그를 확인하세요."),
            "severity": ERROR_SEVERITY.get(failure.error_type, 1),
        }

    def _determine_overall_type(self, errors: list[StrategyFailure]) -> ErrorType:
        """가장 심각한 에러 타입을 결정 — ERROR_SEVERITY 가중치 기준으로 최악의 원인을 대표로 삼는다."""
        if not errors:
            return ErrorType.UNKNOWN

        return max(
            errors,
            key=lambda e: ERROR_SEVERITY.get(e.error_type, 0),
        ).error_type

    def _build_summary(
        self,
        crawler_name: str,
        errors: list[StrategyFailure],
        overall_type: ErrorType,
    ) -> str:
        """사람이 읽을 수 있는 요약을 생성한다."""
        desc = ERROR_DESCRIPTIONS.get(overall_type, "알 수 없는 오류")

        strategies = [e.strategy_name for e in errors]
        strategies_str = ", ".join(strategies)

        return (
            f"[{crawler_name}] {desc}. "
            f"{len(errors)}개 전략 시도 실패 ({strategies_str})."
        )
