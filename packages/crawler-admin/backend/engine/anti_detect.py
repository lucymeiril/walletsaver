"""
봇 탐지 회피 모듈 — 크롤러가 "사람처럼" 보이게 만든다.

왜 존재하는가:
    대형마트 사이트들은 봇 탐지 시스템(Cloudflare, Incapsula 등)을 운영한다.
    매번 같은 User-Agent·IP·요청 패턴으로 접근하면 즉시 차단당한다.
    이 모듈이 요청마다 (1) User-Agent를 랜덤화하고 (2) 프록시를 로테이션하고
    (3) 불규칙한 딜레이를 삽입하여 자동화된 접근 패턴을 숨긴다.
어디서 쓰이는가:
    BaseStrategy에 주입되어 모든 전략의 fetch() 호출 전에 자동 적용된다.
    container.py에서 config의 프록시·딜레이 설정으로 초기화.
    의존: core/ 만
"""

from __future__ import annotations

import logging
import random
from typing import Optional

logger = logging.getLogger(__name__)

# 실제 브라우저 User-Agent 풀 (2024~2025 최신)
# 왜 다양한 브라우저/OS 조합을 넣는가: 모든 요청이 같은 Chrome/Windows이면
# 봇 탐지 시스템이 "자동화 도구" 패턴으로 인식한다.
# 실제 한국 인터넷 사용자의 브라우저 점유율에 맞춰 Chrome > Edge > Safari > Firefox 비율로 구성.
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

# Accept 헤더 조합 — 브라우저별로 미세하게 다른 Accept 패턴을 재현하여 핑거프린트 다양화
ACCEPT_HEADERS: list[dict[str, str]] = [
    {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate",
    },
    {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "ko,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
    },
    {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.8,en-US;q=0.5,en;q=0.3",
        "Accept-Encoding": "gzip, deflate",
    },
]


class AntiDetect:
    """
    봇 탐지 회피 관리자 — 요청마다 User-Agent·프록시·딜레이를 무작위화한다.

    왜 랜덤인가:
        고정 패턴은 시간대별 요청 빈도·User-Agent·IP 조합으로 즉시 탐지된다.
        무작위화하면 봇 탐지 시스템의 "동일 클라이언트" 패턴 매칭을 회피할 수 있다.
    딜레이 범위(기본 1~5초):
        인간의 평균 페이지 체류 시간(2~4초)에 맞춘 것이며,
        config.py의 CRAWL_DELAY_MIN/MAX로 사이트별 조정 가능.
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
        실제 브라우저가 보내는 것과 동일한 헤더 세트를 조합한다.

        Sec-Fetch-* 헤더는 최신 Chrome이 자동으로 보내는 헤더로,
        이걸 빠뜨리면 "이건 브라우저가 아니다"라는 강력한 신호가 된다.
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
        라운드 로빈으로 다음 프록시 반환 — 특정 IP에 요청이 집중되는 것을 방지한다.

        왜 랜덤이 아닌 라운드 로빈인가: 균등 분배로 프록시별 부하를 일정하게 유지해야
        특정 프록시만 차단되는 상황을 방지할 수 있다.
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
        """인간처럼 불규칙한 간격을 생성 — 일정한 간격은 봇 탐지의 가장 쉬운 단서."""
        return random.uniform(self._delay_min, self._delay_max)

    def add_proxy(self, proxy: str) -> None:
        """프록시 추가."""
        if proxy not in self._proxies:
            self._proxies.append(proxy)

    def remove_proxy(self, proxy: str) -> None:
        """차단 감지된 프록시를 풀에서 제거 — executor가 IP_BANNED 에러 시 호출."""
        if proxy in self._proxies:
            self._proxies.remove(proxy)

    @property
    def proxy_count(self) -> int:
        return len(self._proxies)

    @property
    def has_proxies(self) -> bool:
        return len(self._proxies) > 0
