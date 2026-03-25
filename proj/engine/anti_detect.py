"""
안티봇 탐지 회피 모듈 (AntiDetect).

User-Agent 풀, 프록시 로테이션, 브라우저 핑거프린트 관리.

의존: core/ 만
"""

from __future__ import annotations

import logging
import random
from typing import Optional

logger = logging.getLogger(__name__)

# 실제 브라우저 User-Agent 풀 (2024~2025 최신)
USER_AGENTS: list[str] = [
    # Chrome - Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    # Chrome - Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    # Firefox - Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
    # Firefox - Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:133.0) Gecko/20100101 Firefox/133.0",
    # Edge
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
    # Safari - Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
    # Chrome - Mobile
    "Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/131.0.6778.103 Mobile/15E148 Safari/604.1",
]

# 일반적인 Accept 헤더 조합
ACCEPT_HEADERS: list[dict[str, str]] = [
    {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
    },
    {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "ko,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
    },
    {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.8,en-US;q=0.5,en;q=0.3",
        "Accept-Encoding": "gzip, deflate, br, zstd",
    },
]


class AntiDetect:
    """
    안티봇 탐지 회피 관리자.

    User-Agent, 프록시, 요청 헤더를 무작위화하여
    봇 탐지를 회피한다.
    """

    def __init__(
        self,
        proxies: Optional[list[str]] = None,
        delay_min: float = 1.0,
        delay_max: float = 5.0,
    ) -> None:
        self._proxies = proxies or []
        self._proxy_index = 0
        self._delay_min = delay_min
        self._delay_max = delay_max
        self._used_uas: list[str] = []

    def get_random_user_agent(self) -> str:
        """랜덤 User-Agent를 반환한다."""
        ua = random.choice(USER_AGENTS)
        self._used_uas.append(ua)
        return ua

    def get_random_headers(self) -> dict[str, str]:
        """
        랜덤 요청 헤더 세트를 반환한다.
        User-Agent + Accept 헤더 조합.
        """
        headers = dict(random.choice(ACCEPT_HEADERS))
        headers["User-Agent"] = self.get_random_user_agent()
        headers["Connection"] = "keep-alive"
        headers["Upgrade-Insecure-Requests"] = "1"
        headers["Sec-Fetch-Dest"] = "document"
        headers["Sec-Fetch-Mode"] = "navigate"
        headers["Sec-Fetch-Site"] = "none"
        headers["Sec-Fetch-User"] = "?1"
        return headers

    def get_next_proxy(self) -> Optional[str]:
        """
        다음 프록시를 반환한다 (라운드 로빈).
        프록시가 없으면 None.
        """
        if not self._proxies:
            return None
        proxy = self._proxies[self._proxy_index % len(self._proxies)]
        self._proxy_index += 1
        return proxy

    def get_random_proxy(self) -> Optional[str]:
        """랜덤 프록시를 반환한다."""
        if not self._proxies:
            return None
        return random.choice(self._proxies)

    def get_random_delay(self) -> float:
        """랜덤 딜레이(초)를 반환한다."""
        return random.uniform(self._delay_min, self._delay_max)

    def add_proxy(self, proxy: str) -> None:
        """프록시 추가."""
        if proxy not in self._proxies:
            self._proxies.append(proxy)

    def remove_proxy(self, proxy: str) -> None:
        """프록시 제거 (차단된 프록시 등)."""
        if proxy in self._proxies:
            self._proxies.remove(proxy)

    @property
    def proxy_count(self) -> int:
        return len(self._proxies)

    @property
    def has_proxies(self) -> bool:
        return len(self._proxies) > 0
