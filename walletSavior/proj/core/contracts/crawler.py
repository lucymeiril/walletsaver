"""
크롤러 계약 (CrawlerContract).

모든 크롤러 플러그인은 이 인터페이스를 구현해야 한다.
engine/, api/ 등 다른 모듈은 구체 크롤러를 모르고 이 계약만 안다.
"""

from abc import ABC, abstractmethod
from core.models import CrawlResult, CrawlerInfo


class CrawlerContract(ABC):
    """크롤러 플러그인이 구현해야 하는 계약."""

    @property
    @abstractmethod
    def info(self) -> CrawlerInfo:
        """크롤러 메타 정보 (이름, 그룹, 버전, 사용 전략 등)."""
        ...

    @abstractmethod
    async def crawl(self) -> CrawlResult:
        """
        크롤링을 수행한다.

        Returns:
            CrawlResult: 크롤링 결과 (수집 데이터, 상태, 에러 등)

        Raises:
            CrawlError: 모든 전략이 실패했을 때
        """
        ...

    @abstractmethod
    async def parse(self, raw_data: str) -> list[dict]:
        """
        원본 데이터(HTML/JSON)를 파싱하여 구조화된 데이터로 변환한다.

        Args:
            raw_data: 크롤링으로 가져온 원본 문자열

        Returns:
            구조화된 딕셔너리 리스트
        """
        ...

    @abstractmethod
    async def validate(self, items: list[dict]) -> list[dict]:
        """
        파싱된 데이터의 유효성을 검증한다.

        Args:
            items: 파싱된 데이터 리스트

        Returns:
            유효한 데이터만 필터링된 리스트
        """
        ...

    async def setup(self) -> None:
        """크롤링 전 초기화 (선택)."""
        pass

    async def teardown(self) -> None:
        """크롤링 후 정리 (선택)."""
        pass
