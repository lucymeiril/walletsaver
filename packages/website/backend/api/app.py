"""
FastAPI 앱 팩토리 — container.py가 의존성을 주입하여 앱을 생성한다.

왜 팩토리 패턴인가:
    테스트 시 mock storage를 주입할 수 있고,
    main.py와 container.py가 각각 독립적으로 앱을 생성할 수 있다.
어디서 쓰이는가:
    container.py._init_api() → create_app(storage, engine, event_bus)
    main.py "server" 명령 → uvicorn으로 이 앱을 서빙.

라우터 구조:
    api/routes/ 디렉토리에 도메인별 라우터 파일을 배치한다.
    (routes/products.py, routes/hotdeals.py, routes/marts.py, routes/gas.py, routes/crawlers.py, routes/users.py)
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def create_app(storage=None, engine=None, event_bus=None) -> FastAPI:
    """
    팩토리 패턴 — container.py가 의존성 주입하여 앱 생성.

    storage가 None이면 각 라우터가 mock 데이터를 반환하므로
    DB 없이도 즉시 프론트엔드 개발이 가능하다.
    """
    app = FastAPI(
        title="지갑 지키미 API",
        description="물가 비교 서비스 백엔드 — 정부 공공데이터 + 마트 할인 + 커뮤니티 핫딜",
        version="0.1.0",
    )

    # CORS — 프론트엔드 개발 서버 허용
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",   # Vite dev server
            "http://localhost:3000",   # CRA / Next.js dev
            "http://127.0.0.1:5173",
            "http://127.0.0.1:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # storage가 없으면 db-admin의 DBStorage로 자동 연결 시도
    if storage is None:
        try:
            import sys, os, logging
            db_admin_path = os.path.normpath(os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
                "db-admin", "backend"
            ))
            if db_admin_path not in sys.path:
                sys.path.insert(0, db_admin_path)

            from storage.db import DBStorage

            db_path = os.path.join(db_admin_path, "walletguardian.db")
            storage = DBStorage(f"sqlite:///{db_path}")
            storage.init_db()
            logging.info(f"✅ DB 연결 성공: {db_path}")
        except Exception as e:
            import logging
            logging.warning(f"DB 연결 실패, mock 데이터 사용: {e}")
            storage = None

    # 의존성을 app.state에 저장 — 라우터에서 request.app.state.storage로 접근
    app.state.storage = storage
    app.state.engine = engine
    app.state.event_bus = event_bus

    # 라우터 등록 — 도메인별 분리
    from api.routes.products import router as products_router
    from api.routes.hotdeals import router as hotdeals_router
    from api.routes.marts import router as marts_router
    from api.routes.gas import router as gas_router
    from api.routes.crawlers import router as crawlers_router
    from api.routes.users import router as users_router
    from api.routes.auth import router as auth_router
    from api.routes.community import router as community_router
    from api.routes.search import router as search_router
    from api.routes.restaurants import router as restaurants_router
    from api.routes.naver_local import router as naver_local_router

    app.include_router(products_router, prefix="/api/products", tags=["Products"])
    app.include_router(hotdeals_router, prefix="/api/hotdeals", tags=["Hotdeals"])
    app.include_router(marts_router, prefix="/api/marts", tags=["Marts"])
    app.include_router(gas_router, prefix="/api/gas", tags=["Gas Stations"])
    app.include_router(crawlers_router, prefix="/api/crawlers", tags=["Crawlers"])
    app.include_router(users_router, prefix="/api/users", tags=["Users"])
    app.include_router(auth_router)
    app.include_router(community_router, prefix="/api/posts", tags=["Community"])
    app.include_router(search_router, prefix="/api/search", tags=["Search"])
    app.include_router(restaurants_router, prefix="/api", tags=["Restaurants"])
    app.include_router(naver_local_router, prefix="/api/local", tags=["Local / Naver"])

    @app.get("/api/health")
    def health():
        """헬스체크 — 로드밸런서·모니터링용."""
        return {"status": "ok", "version": "0.1.0"}

    return app
