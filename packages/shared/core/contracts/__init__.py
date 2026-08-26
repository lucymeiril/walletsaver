"""core.contracts 패키지 — 현재 런타임 모듈 간 인터페이스."""

from .crawler import CrawlerContract
from .storage import StorageContract

__all__ = [
    "CrawlerContract",
    "StorageContract",
]
