"""
FastAPI 앱 팩토리 — 공개 읽기와 저빈도 쓰기 저장소를 분리한다.

상품/카테고리/마트 가격/가격 이력은 public snapshot에서 읽고,
사용자 기능·핫딜 등 아직 main DB가 필요한 경로는 main storage를 사용한다.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def create_app(storage=None, engine=None, event_bus=None) -> FastAPI:
    """팩토리 패턴 — 테스트에서는 명시 storage를 그대로 주입할 수 있다."""
    app = FastAPI(
        title="지갑 지키미 API",
        description="물가 비교 서비스 백엔드",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://localhost:3000",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # storage가 명시되지 않은 실제 실행에서는 public read snapshot과 main
    # application DB를 분리한다. Snapshot이 아직 생성되지 않은 첫 실행만
    # main storage를 read fallback으로 사용한다.
    if storage is None:
        try:
            import logging
            import os
            import sys

            web_api_path = os.path.dirname(os.path.dirname(__file__))
            db_admin_path = os.path.normpath(
                os.path.join(
                    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
                    "db-admin",
                    "backend",
                )
            )
            if db_admin_path not in sys.path:
                sys.path.insert(0, db_admin_path)

            from storage.db import DBStorage

            main_db_path = os.path.abspath(os.path.join(db_admin_path, "walletguardian.db"))
            main_storage = DBStorage(f"sqlite:///{main_db_path}")

            # Restore web-api's services package before importing SplitStorage.
            if web_api_path in sys.path:
                sys.path.remove(web_api_path)
            sys.path.insert(0, web_api_path)
            for module_name, module in list(sys.modules.items()):
                if module_name == "services" or module_name.startswith("services."):
                    module_file = str(getattr(module, "__file__", "") or "")
                    if module_file.startswith(os.path.join(db_admin_path, "services")):
                        del sys.modules[module_name]

            from services.split_storage import PublicSnapshotStorage, SplitStorage

            project_root = os.path.dirname(
                os.path.dirname(os.path.dirname(db_admin_path))
            )
            safe_public_db_path = os.path.abspath(
                os.path.join(project_root, ".walletsavior", "public_snapshot.sqlite")
            )
            public_db_path = os.path.abspath(
                os.getenv("WALLETSAVIOR_PUBLIC_DB", safe_public_db_path)
            )
            if os.path.normcase(public_db_path) == os.path.normcase(main_db_path):
                logging.error(
                    "Ignoring unsafe WALLETSAVIOR_PUBLIC_DB pointing at main DB: %s",
                    public_db_path,
                )
                public_db_path = safe_public_db_path

            public_storage = None
            if os.path.isfile(public_db_path):
                public_storage = PublicSnapshotStorage(public_db_path)
                logging.info("Public snapshot read enabled: %s", public_db_path)
            else:
                logging.warning(
                    "Public snapshot missing; product reads temporarily use main DB: %s",
                    public_db_path,
                )

            storage = SplitStorage(main=main_storage, public=public_storage)
            logging.info("Main application storage connected: %s", main_db_path)
        except Exception as e:
            import logging

            logging.warning("DB 연결 실패, mock 데이터 사용: %s", e)
            storage = None

    app.state.storage = storage
    app.state.engine = engine
    app.state.event_bus = event_bus

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
    from api.routes.profile import router as profile_router

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
    app.include_router(profile_router)

    @app.get("/api/health")
    def health():
        """헬스체크 + public snapshot 사용 여부."""
        current_storage = app.state.storage
        return {
            "status": "ok",
            "version": "0.1.0",
            "public_snapshot": bool(
                current_storage is not None
                and getattr(current_storage, "public_enabled", False)
            ),
        }

    @app.get("/api/dashboard")
    def dashboard():
        """홈 화면 통합 데이터 — 구 웹 프론트가 기대하는 응답 shape."""
        current_storage = app.state.storage
        hotdeals = []
        recent_products = []
        category_summary = []
        if current_storage is not None:
            try:
                hotdeals = current_storage.get_hotdeals(category="all", per_page=8)
            except Exception:
                hotdeals = []
            try:
                recent_products = current_storage.search_products("", per_page=8)
            except Exception:
                recent_products = []
        if not hotdeals or not recent_products:
            from api.mock_responses import MOCK_HOTDEALS, MOCK_PRODUCTS

            hotdeals = hotdeals or MOCK_HOTDEALS[:8]
            recent_products = recent_products or MOCK_PRODUCTS[:8]
        category_counts = {}
        for product in recent_products:
            cat = product.get("cat") or product.get("category") or "기타"
            top = str(cat).split(" > ")[0] if cat else "기타"
            category_counts[top] = category_counts.get(top, 0) + 1
        category_summary = [
            {"category": name, "name": name, "count": count}
            for name, count in sorted(category_counts.items(), key=lambda item: item[0])
        ]
        trending_keywords = [
            {"keyword": keyword, "text": keyword, "count": 0}
            for keyword in ["우유", "계란", "삼겹살", "사과", "라면", "양파"]
        ]
        return {
            "success": True,
            "data": {
                "hotdeals": hotdeals,
                "category_summary": category_summary,
                "recent_products": recent_products,
                "trending_keywords": trending_keywords,
            },
            "error": None,
            "meta": None,
        }

    return app
