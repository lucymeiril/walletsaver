"""
저장소 계약 (StorageContract).

DB 등 수집 데이터 저장 인터페이스.
크롤러, 엔진은 이 계약만 의존한다.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional


class StorageContract(ABC):
    """데이터 저장소가 구현해야 하는 계약."""

    @abstractmethod
    async def save_crawl_log(
        self,
        crawler_name: str,
        status: str,
        items_count: int,
        started_at: datetime,
        finished_at: datetime,
        error_msg: Optional[str] = None,
        diagnosis: Optional[dict] = None,
    ) -> int:
        """
        크롤링 실행 로그를 저장한다.

        Returns:
            생성된 로그 ID
        """
        ...

    @abstractmethod
    async def save_collected_data(
        self,
        crawler_name: str,
        data_type: str,
        items: list[dict],
    ) -> int:
        """
        수집된 데이터를 저장한다.

        Args:
            crawler_name: 크롤러 이름
            data_type: 데이터 유형 (discount, price, hotdeal 등)
            items: 수집된 데이터 리스트

        Returns:
            저장된 항목 수
        """
        ...

    @abstractmethod
    async def get_crawl_logs(
        self,
        crawler_name: Optional[str] = None,
        status: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> list[dict]:
        """크롤링 로그 조회."""
        ...

    @abstractmethod
    async def get_collected_data(
        self,
        data_type: Optional[str] = None,
        crawler_name: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> list[dict]:
        """수집된 데이터 조회."""
        ...
