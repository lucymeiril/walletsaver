"""
FastAPI 앱 팩토리 — container.py가 의존성을 주입하여 앱을 생성한다.

왜 팩토리 패턴인가:
    테스트 시 mock storage를 주입할 수 있고,
    main.py와 container.py가 각각 독립적으로 앱을 생성할 수 있다.
어디서 쓰이는가:
    container.py._init_api() → create_app(storage, engine, event_bus)
    main.py "server" 명령 → uvicorn으로 이 앱을 서빙.

라우터 구조:
    api/routes/ 디렉토리 대신 api/ 내에 도메인별 라우터 파일을 배치한다.
    (products.py, hotdeals.py, marts.py, gas.py, crawlers.py, users.py)
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

    # 의존성을 app.state에 저장 — 라우터에서 request.app.state.storage로 접근
    app.state.storage = storage
    app.state.engine = engine
    app.state.event_bus = event_bus

    # 라우터 등록 — 도메인별 분리
    from api.route_products import router as products_router
    from api.route_hotdeals import router as hotdeals_router
    from api.route_marts import router as marts_router
    from api.route_gas import router as gas_router
    from api.route_crawlers import router as crawlers_router
    from api.route_users import router as users_router

    app.include_router(products_router, prefix="/api/products", tags=["Products"])
    app.include_router(hotdeals_router, prefix="/api/hotdeals", tags=["Hotdeals"])
    app.include_router(marts_router, prefix="/api/marts", tags=["Marts"])
    app.include_router(gas_router, prefix="/api/gas", tags=["Gas Stations"])
    app.include_router(crawlers_router, prefix="/api/crawlers", tags=["Crawlers"])
    app.include_router(users_router, prefix="/api/users", tags=["Users"])

    @app.get("/api/health")
    def health():
        """헬스체크 — 로드밸런서·모니터링용."""
        return {"status": "ok", "version": "0.1.0"}

    return app
