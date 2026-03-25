"""
DI 컨테이너.

프로젝트에서 유일하게 모든 구체 모듈을 import하고 조립하는 곳.
각 모듈은 여기서 주입받은 계약 인터페이스만 사용한다.
"""

from __future__ import annotations

import logging
from typing import Optional

from core.events import EventBus

logger = logging.getLogger(__name__)


class Container:
    """
    의존성 주입 컨테이너.

    모든 모듈의 구체 구현을 알고 조립하는 유일한 장소.
    각 모듈은 Container를 모르고, 주입받은 계약 인터페이스만 사용.

    Usage:
        container = Container()
        container.bootstrap()       # 모든 모듈 초기화 & 조립
        container.start()           # 서버 시작
    """

    def __init__(self) -> None:
        self.event_bus: EventBus = EventBus()

        # 계약 구현체 (bootstrap에서 초기화)
        self._engine = None
        self._storage = None
        self._file_storage = None
        self._scheduler = None
        self._crawler_registry = None
        self._api_app = None

    def bootstrap(self) -> None:
        """모든 모듈 초기화 및 의존성 연결."""
        logger.info("컨테이너 부트스트랩 시작...")

        # 1. 저장소 초기화
        self._init_storage()

        # 2. 크롤러 플러그인 검색 & 등록
        self._init_crawlers()

        # 3. 엔진 초기화 (이벤트버스 + 크롤러 주입)
        self._init_engine()

        # 4. 스케줄러 초기화
        self._init_scheduler()

        # 5. API 서버 초기화
        self._init_api()

        logger.info("컨테이너 부트스트랩 완료.")

    def _init_storage(self) -> None:
        """저장소 모듈 초기화."""
        # TODO: Phase 1 완료 후 구현
        # from storage.db import DBStorage
        # from storage.filesystem import FileSystemStorage
        # self._storage = DBStorage(config.DATABASE_URL)
        # self._file_storage = FileSystemStorage(config.IMAGE_STORAGE_PATH)
        logger.info("저장소: 미구현 (Phase 1)")

    def _init_crawlers(self) -> None:
        """크롤러 플러그인 자동 검색."""
        # TODO: Phase 3~6에서 구현
        # from crawlers.registry import CrawlerRegistry
        # self._crawler_registry = CrawlerRegistry.discover("crawlers/")
        logger.info("크롤러 레지스트리: 미구현 (Phase 3~6)")

    def _init_engine(self) -> None:
        """크롤링 엔진 초기화."""
        # TODO: Phase 2에서 구현
        # from engine.executor import StrategyExecutor
        # self._engine = StrategyExecutor(self.event_bus, self._crawler_registry)
        logger.info("엔진: 미구현 (Phase 2)")

    def _init_scheduler(self) -> None:
        """스케줄러 초기화."""
        # TODO: Phase 7에서 구현
        logger.info("스케줄러: 미구현 (Phase 7)")

    def _init_api(self) -> None:
        """API 서버 초기화."""
        # TODO: Phase 7에서 구현
        logger.info("API: 미구현 (Phase 7)")

    # --- 접근자 (계약 타입으로 반환) ---

    @property
    def engine(self):
        """EngineContract 구현체."""
        return self._engine

    @property
    def storage(self):
        """StorageContract 구현체."""
        return self._storage

    @property
    def file_storage(self):
        """FileStorageContract 구현체."""
        return self._file_storage

    @property
    def scheduler(self):
        """SchedulerContract 구현체."""
        return self._scheduler

    @property
    def api_app(self):
        """FastAPI 앱."""
        return self._api_app
