"""
크롤러 관리 API — 대시보드에서 크롤러 상태 확인 + 수동 실행.

엔드포인트:
    GET  /api/crawlers           — 등록된 크롤러 목록 + 최근 상태
    POST /api/crawlers/{name}/run — 특정 크롤러 즉시 실행 트리거
"""

from fastapi import APIRouter, Request, HTTPException

router = APIRouter()


@router.get("")
async def list_crawlers(request: Request):
    """
    등록된 크롤러 목록 — 최근 실행 상태 포함.

    storage에서 crawl_logs를 조회하여 각 크롤러의 마지막 상태를 표시.
    """
    storage = request.app.state.storage
    if storage is None:
        # DB 미연결: 기본 크롤러 목록만 반환 (상태 없음)
        default_crawlers = [
            {"name": "kamis",    "group": "public",  "status": "idle", "last_run": None, "items_count": 0, "description": "농산물유통정보 공공 API"},
            {"name": "opinet",   "group": "public",  "status": "idle", "last_run": None, "items_count": 0, "description": "오피넷 주유소 가격"},
            {"name": "emart",    "group": "marts",   "status": "idle", "last_run": None, "items_count": 0, "description": "이마트 전단 할인"},
            {"name": "homeplus", "group": "marts",   "status": "idle", "last_run": None, "items_count": 0, "description": "홈플러스 전단 할인"},
            {"name": "lotte",    "group": "marts",   "status": "idle", "last_run": None, "items_count": 0, "description": "롯데마트 전단 할인"},
            {"name": "costco",   "group": "marts",   "status": "idle", "last_run": None, "items_count": 0, "description": "코스트코 할인"},
            {"name": "ppomppu",  "group": "hotdeals", "status": "idle", "last_run": None, "items_count": 0, "description": "뽐뿌 핫딜"},
            {"name": "eomisae",  "group": "hotdeals", "status": "idle", "last_run": None, "items_count": 0, "description": "어미새 핫딜"},
        ]
        return default_crawlers

    # DB에서 크롤러별 최근 로그 조회
    logs = await storage.get_crawl_logs(limit=100)
    # 크롤러 이름별로 가장 최근 로그 추출
    latest: dict = {}
    for log in logs:
        name = log["crawler_name"]
        if name not in latest:
            latest[name] = log

    return [
        {
            "name": name,
            "status": log["status"],
            "last_run": log["started_at"],
            "items_count": log["items_count"],
            "duration_seconds": log["duration_seconds"],
        }
        for name, log in latest.items()
    ]


@router.post("/{name}/run")
async def run_crawler(request: Request, name: str):
    """
    크롤러 즉시 실행 — engine을 통해 크롤링 트리거.

    엔진이 없으면 (Phase 2 미구현) 안내 메시지 반환.
    """
    engine = request.app.state.engine
    if engine is None:
        return {
            "status": "not_available",
            "message": f"크롤러 '{name}' 엔진이 아직 구현되지 않았습니다 (Phase 2 예정)",
        }

    # TODO: engine.execute_crawler(name)
    return {"status": "triggered", "crawler": name}
