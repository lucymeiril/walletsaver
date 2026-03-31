"""
크롤링 엔진 계약 (EngineContract).

크롤링 전략 실행, 진단 등 엔진 기능의 인터페이스.
api/, scheduler/ 등은 이 계약만 의존한다.
"""

from abc import ABC, abstractmethod
from ..models import CrawlResult, CrawlRequest, DiagnosisReport


class EngineContract(ABC):
    """크롤링 엔진이 구현해야 하는 계약."""

    @abstractmethod
    async def execute(self, request: CrawlRequest) -> CrawlResult:
        """
        크롤링 요청을 실행한다.
        전략을 자동으로 cascade 시도한다.

        Args:
            request: 크롤링 요청 (URL, 크롤러 이름, 옵션 등)

        Returns:
            CrawlResult: 성공 또는 실패 결과
        """
        ...

    @abstractmethod
    async def execute_crawler(self, crawler_name: str) -> CrawlResult:
        """
        등록된 크롤러를 이름으로 찾아 실행한다.

        Args:
            crawler_name: 크롤러 이름 (예: "이마트")

        Returns:
            CrawlResult
        """
        ...

    @abstractmethod
    async def diagnose(self, result: CrawlResult) -> DiagnosisReport:
        """
        실패한 크롤링 결과를 분석하여 진단 리포트를 생성한다.

        Args:
            result: 실패한 CrawlResult

        Returns:
            DiagnosisReport: 실패 원인, 분류, 추천 대응
        """
        ...

    @abstractmethod
    def list_crawlers(self) -> list[str]:
        """등록된 크롤러 이름 목록."""
        ...

    @abstractmethod
    def get_crawler_status(self, crawler_name: str) -> dict:
        """특정 크롤러의 현재 상태."""
        ...


class StrategyContract(ABC):
    """크롤링 전략이 구현해야 하는 계약."""

    @property
    @abstractmethod
    def name(self) -> str:
        """전략 이름 (예: 'requests', 'selenium_stealth')."""
        ...

    @property
    @abstractmethod
    def difficulty(self) -> int:
        """복잡도 (1=가벼움, 5=무거움). 낮을수록 먼저 시도."""
        ...

    @abstractmethod
    async def fetch(self, url: str, **options) -> str:
        """
        URL에서 콘텐츠를 가져온다.

        Args:
            url: 대상 URL
            **options: 전략별 추가 옵션

        Returns:
            HTML 또는 JSON 문자열

        Raises:
            CrawlError: 실패 시 (에러 타입 포함)
        """
        ...

    @abstractmethod
    async def cleanup(self) -> None:
        """리소스 정리 (브라우저 종료 등)."""
        ...
