"""
의존성 주입(DI) 컨테이너 — 프로젝트에서 유일하게 "누가 누구를 사용하는가"를 아는 곳.

왜 존재하는가:
    모듈 간 직접 import를 허용하면 순환 의존·테스트 불가·교체 불가 문제가 생긴다.
    이 컨테이너가 모든 구체 구현을 import하고 조립하는 유일한 장소이므로,
    각 모듈은 core/contracts 인터페이스만 알면 되고 구체 구현은 모른다.
    테스트 시 이 컨테이너만 Mock으로 바꾸면 전체를 격리 테스트할 수 있다.
어디서 쓰이는가:
    main.py에서 Container()를 생성하고 bootstrap()으로 전체 시스템을 조립한다.
    config.py를 직접 import하는 유일한 파일이기도 하다.
"""

from __future__ import annotations

import logging
from typing import Optional

from core.events import EventBus

logger = logging.getLogger(__name__)


class Container:
    """
    의존성 주입 컨테이너 — 조립 전담, 비즈니스 로직 없음.

    왜 "유일한 조립 장소"인가:
        모듈 A가 모듈 B를 직접 import하면 B를 교체할 때 A도 수정해야 한다.
        Container가 A에 B의 인터페이스를 주입하면 B 교체 시 Container만 수정하면 된다.
    bootstrap() 순서가 중요한 이유:
        저장소 → 크롤러 → 엔진 → 스케줄러 → API 순서로 초기화해야
        각 단계에서 이전 단계의 의존성을 주입받을 수 있다.
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
        """저장소 모듈 초기화 — DBStorage를 생성하고 테이블을 자동 생성."""
        try:
            from storage.db import DBStorage
            self._storage = DBStorage()
            self._storage.init_db()
            logger.info("저장소: DBStorage 초기화 완료")
        except Exception as e:
            logger.warning(f"저장소 초기화 실패 (mock 모드로 동작): {e}")
            self._storage = None

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
        """API 서버 초기화 — FastAPI 앱을 생성하고 의존성 주입."""
        from api.app import create_app
        self._api_app = create_app(
            storage=self._storage,
            engine=self._engine,
            event_bus=self.event_bus,
        )
        logger.info("API: FastAPI 앱 초기화 완료")

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
