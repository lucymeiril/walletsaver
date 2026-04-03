"""
전략 ① — requests + BeautifulSoup.

가장 가벼운 전략. 정적 HTML, API 응답에 사용.
difficulty: 1
"""

from __future__ import annotations

import logging
from typing import Optional

import requests as req_lib

from core.exceptions import CrawlError
from core.models import ErrorType
from engine.anti_detect import AntiDetect
from engine.strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


class RequestsStrategy(BaseStrategy):
    """requests 라이브러리로 HTTP GET."""

    def __init__(
        self,
        anti_detect: Optional[AntiDetect] = None,
        timeout: int = 30,
    ) -> None:
        super().__init__(anti_detect)
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "requests"

    @property
    def difficulty(self) -> int:
        return 1

    async def _do_fetch(self, url: str, **options) -> str:
        headers = options.get("headers") or self._anti_detect.get_random_headers()
        proxy = self._anti_detect.get_random_proxy()
        proxies = {"http": proxy, "https": proxy} if proxy else None
        timeout = options.get("timeout", self._timeout)

        try:
            response = req_lib.get(
                url,
                headers=headers,
                proxies=proxies,
                timeout=timeout,
                allow_redirects=True,
            )
        except req_lib.exceptions.Timeout:
            raise CrawlError("요청 시간 초과", error_type=ErrorType.TIMEOUT, strategy_name=self.name)
        except req_lib.exceptions.ConnectionError as e:
            raise CrawlError(f"네트워크 오류: {e}", error_type=ErrorType.NETWORK_ERROR, strategy_name=self.name)
        except req_lib.exceptions.RequestException as e:
            raise CrawlError(str(e), error_type=ErrorType.UNKNOWN, strategy_name=self.name)

        # 응답 분석
        self._check_response(response)
        return response.text

    def _check_response(self, response: req_lib.Response) -> None:
        """응답 상태를 검사하고 적절한 에러 타입으로 변환."""
        if response.status_code == 403:
            body = response.text.lower()
            if "captcha" in body or "recaptcha" in body:
                raise CrawlError(
                    "CAPTCHA detected",
                    error_type=ErrorType.CAPTCHA_DETECTED,
                    status_code=403,
                    strategy_name=self.name,
                )
            raise CrawlError(
                "403 Forbidden — IP 차단 가능성",
                error_type=ErrorType.IP_BANNED,
                status_code=403,
                strategy_name=self.name,
            )

        if response.status_code == 503:
            body = response.text.lower()
            if "cloudflare" in body or "challenge" in body:
                raise CrawlError(
                    "Cloudflare JS Challenge",
                    error_type=ErrorType.JS_CHALLENGE,
                    status_code=503,
                    strategy_name=self.name,
                )

        if response.status_code >= 400:
            raise CrawlError(
                f"HTTP {response.status_code}",
                error_type=ErrorType.HTTP_ERROR,
                status_code=response.status_code,
                strategy_name=self.name,
            )

        if not response.text or len(response.text.strip()) < 10:
            raise CrawlError(
                "빈 응답",
                error_type=ErrorType.EMPTY_RESPONSE,
                strategy_name=self.name,
            )
