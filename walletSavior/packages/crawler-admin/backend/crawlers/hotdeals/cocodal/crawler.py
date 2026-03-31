"""
코코달 핫딜 크롤러 (비활성).

cocodal.in / cocodal.co.kr 사이트가 현재 접속 불가 상태이다.
사이트 복구가 확인되면 파싱 로직을 구현하여 활성화한다.

용도: 핫딜 참고 데이터 (baseline 오염 방지 — HotdealPost로 저장)
의존: core/ 만
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from core.contracts.crawler import CrawlerContract
from core.models import CrawlerInfo, CrawlerGroup, CrawlResult, CrawlStatus, HotdealPost
from engine.anti_detect import AntiDetect

logger = logging.getLogger(__name__)


class CocodalCrawler(CrawlerContract):
    """코코달 핫딜 크롤러 — 현재 비활성 (사이트 접속 불가)."""

    BASE_URL = "https://cocodal.in"
    DEAL_URL = "https://cocodal.in/"

    def __init__(self, anti_detect: Optional[AntiDetect] = None):
        self._anti_detect = anti_detect or AntiDetect(delay_min=0.5, delay_max=1.5)

    @property
    def info(self) -> CrawlerInfo:
        return CrawlerInfo(
            name="코코달",
            version="1.0.0",
            group=CrawlerGroup.HOTDEAL,
            description="코코달 핫딜 크롤러 — 현재 사이트 접속 불가 (비활성)",
            target_url=self.DEAL_URL,
            strategies=["requests"],
        )

    async def crawl(self) -> CrawlResult:
        """코코달 핫딜 크롤링 — 사이트 접속 불가로 즉시 FAILED 반환."""
        started_at = datetime.now()
        logger.warning("[코코달] 사이트 접속 불가 — cocodal.in/cocodal.co.kr 모두 다운")

        return CrawlResult(
            status=CrawlStatus.FAILED,
            crawler_name=self.info.name,
            error_msg="사이트 접속 불가 — cocodal.in, cocodal.co.kr 모두 응답 없음. 향후 복구 시 활성화 예정.",
            started_at=started_at,
            finished_at=datetime.now(),
        )

    async def parse(self, raw_data: str) -> list[HotdealPost]:
        """파싱 미구현 — 사이트 복구 후 HTML 구조 분석하여 구현 예정."""
        return []

    async def validate(self, items: list[HotdealPost]) -> list[HotdealPost]:
        """유효성 검증 — 사이트 복구 후 구현 예정."""
        return items
