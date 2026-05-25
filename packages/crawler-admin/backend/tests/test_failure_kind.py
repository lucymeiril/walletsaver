"""p1-crawler-anchor-failure-kind 회귀 테스트.

테스트 커버리지:
  1. CrawlerFailureKind enum 값 검증
  2. error_type_to_failure_kind 매핑 전수 검사
  3. StrategyFailure.failure_kind 자동 설정 (model_post_init)
  4. 마트 크롤러 CrawlResult.errors에서 failure_kind가 일관되게 보고되는지 검증
  5. failure_kind 명시 지정 시 override
"""
from __future__ import annotations

import pytest

from core.models import (
    CrawlerFailureKind,
    ErrorType,
    StrategyFailure,
    error_type_to_failure_kind,
)


# ─── 1. enum 값 집합 ─────────────────────────────────────────────────────────

def test_crawler_failure_kind_values():
    required = {"network", "parse", "empty", "cap", "waf", "timeout", "unknown"}
    actual = {fk.value for fk in CrawlerFailureKind}
    assert required == actual, f"누락된 failure_kind: {required - actual}"


# ─── 2. error_type → failure_kind 매핑 전수 검사 ────────────────────────────

@pytest.mark.parametrize("error_type,expected_kind", [
    (ErrorType.NETWORK_ERROR, CrawlerFailureKind.NETWORK),
    (ErrorType.TIMEOUT, CrawlerFailureKind.TIMEOUT),
    (ErrorType.PARSE_ERROR, CrawlerFailureKind.PARSE),
    (ErrorType.DOM_CHANGED, CrawlerFailureKind.PARSE),
    (ErrorType.EMPTY_RESPONSE, CrawlerFailureKind.EMPTY),
    (ErrorType.CAPTCHA_DETECTED, CrawlerFailureKind.CAP),
    (ErrorType.JS_CHALLENGE, CrawlerFailureKind.CAP),
    (ErrorType.IP_BANNED, CrawlerFailureKind.WAF),
    (ErrorType.HTTP_ERROR, CrawlerFailureKind.WAF),
    (ErrorType.LOGIN_REQUIRED, CrawlerFailureKind.WAF),
    (ErrorType.UNKNOWN, CrawlerFailureKind.UNKNOWN),
])
def test_error_type_to_failure_kind_mapping(error_type, expected_kind):
    assert error_type_to_failure_kind(error_type) == expected_kind


def test_all_error_types_are_mapped():
    """모든 ErrorType 값이 매핑에서 처리된다 (UNKNOWN fallback 포함)."""
    for et in ErrorType:
        result = error_type_to_failure_kind(et)
        assert isinstance(result, CrawlerFailureKind)


# ─── 3. StrategyFailure.failure_kind 자동 설정 ──────────────────────────────

def test_strategy_failure_auto_sets_failure_kind_from_error_type():
    sf = StrategyFailure(
        strategy_name="requests",
        error_type=ErrorType.NETWORK_ERROR,
        error_msg="connection refused",
    )
    assert sf.failure_kind == CrawlerFailureKind.NETWORK


def test_strategy_failure_timeout_maps_to_timeout():
    sf = StrategyFailure(
        strategy_name="playwright",
        error_type=ErrorType.TIMEOUT,
        error_msg="timed out after 15s",
    )
    assert sf.failure_kind == CrawlerFailureKind.TIMEOUT


def test_strategy_failure_captcha_maps_to_cap():
    sf = StrategyFailure(
        strategy_name="requests",
        error_type=ErrorType.CAPTCHA_DETECTED,
        error_msg="blocked by captcha",
    )
    assert sf.failure_kind == CrawlerFailureKind.CAP


def test_strategy_failure_empty_response_maps_to_empty():
    sf = StrategyFailure(
        strategy_name="requests",
        error_type=ErrorType.EMPTY_RESPONSE,
        error_msg="0 products",
    )
    assert sf.failure_kind == CrawlerFailureKind.EMPTY


# ─── 4. 명시적 override ──────────────────────────────────────────────────────

def test_strategy_failure_explicit_failure_kind_overrides_auto():
    sf = StrategyFailure(
        strategy_name="requests",
        error_type=ErrorType.HTTP_ERROR,  # HTTP_ERROR → WAF
        error_msg="403",
        failure_kind=CrawlerFailureKind.CAP,  # 명시 override
    )
    assert sf.failure_kind == CrawlerFailureKind.CAP


# ─── 5. 마트 크롤러 CrawlResult errors failure_kind 일관성 ───────────────────

def test_crawl_result_errors_all_have_failure_kind():
    """CrawlResult.errors 목록에 있는 모든 StrategyFailure가 failure_kind를 가진다."""
    from core.models import CrawlResult, CrawlStatus
    from datetime import datetime

    result = CrawlResult(
        status=CrawlStatus.FAILED,
        crawler_name="이마트",
        errors=[
            StrategyFailure(
                strategy_name="requests",
                error_type=ErrorType.NETWORK_ERROR,
                error_msg="conn err",
            ),
            StrategyFailure(
                strategy_name="playwright",
                error_type=ErrorType.TIMEOUT,
                error_msg="timeout",
            ),
            StrategyFailure(
                strategy_name="requests",
                error_type=ErrorType.CAPTCHA_DETECTED,
                error_msg="captcha",
            ),
        ],
        started_at=datetime.now(),
    )
    for sf in result.errors:
        assert sf.failure_kind is not None, f"failure_kind 누락: {sf}"

    kinds = {sf.failure_kind for sf in result.errors}
    assert CrawlerFailureKind.NETWORK in kinds
    assert CrawlerFailureKind.TIMEOUT in kinds
    assert CrawlerFailureKind.CAP in kinds


# ─── 6. failure_kind JSON 직렬화 ─────────────────────────────────────────────

def test_strategy_failure_json_includes_failure_kind():
    sf = StrategyFailure(
        strategy_name="requests",
        error_type=ErrorType.WAF if hasattr(ErrorType, "WAF") else ErrorType.IP_BANNED,
        error_msg="blocked",
    )
    d = sf.model_dump(mode="json")
    assert "failure_kind" in d
    assert d["failure_kind"] in {fk.value for fk in CrawlerFailureKind}
