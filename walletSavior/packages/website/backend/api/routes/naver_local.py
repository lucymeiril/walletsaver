"""
네이버 플레이스 실시간 검색 API — 위치 기반 가게/식당/주유소 정보.

네이버 플레이스는 공식 API를 제공하지 않으므로,
백엔드에서 Playwright를 통해 실시간 크롤링하여 데이터를 반환한다.

엔드포인트:
    GET /api/local/naver-search — 네이버 지도 기반 주변 가게 검색
"""

import logging
from fastapi import APIRouter, Query
from api.schemas.common import ApiResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/naver-search")
async def naver_place_search(
    query: str = Query("맛집", description="검색어 (예: 주유소, 한식, 카페)"),
    lat: float = Query(37.4979, description="위도"),
    lng: float = Query(127.0276, description="경도"),
    max_items: int = Query(20, ge=1, le=50, description="최대 결과 수"),
):
    """네이버 플레이스 실시간 검색.

    사용자가 지도에서 검색하거나 위치를 이동하면
    백엔드에서 네이버 지도를 Playwright로 크롤링하여 결과를 반환한다.
    """
    try:
        # 크롤러 동적 임포트 — crawler-admin 패키지 의존성 분리
        import sys
        import os
        crawler_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "..",
                         "crawler-admin", "backend")
        )
        if crawler_path not in sys.path:
            sys.path.insert(0, crawler_path)

        from crawlers.location.naver_place.crawler import NaverPlaceCrawler
        crawler = NaverPlaceCrawler()
        result = await crawler.crawl(
            query=query, lat=lat, lng=lng, max_items=max_items
        )

        return ApiResponse(
            success=result.status.value in ("success", "partial"),
            data={
                "items": result.items,
                "count": result.items_count,
                "query": query,
                "lat": lat,
                "lng": lng,
            },
            message=f"'{query}' 검색 결과 {result.items_count}건" if result.items else "검색 결과 없음",
        )

    except ImportError as e:
        logger.warning(f"[네이버 검색] 크롤러 임포트 실패: {e}")
        return ApiResponse(
            success=False,
            data={"items": [], "count": 0},
            message="네이버 플레이스 크롤러를 사용할 수 없습니다 (playwright 미설치)",
        )
    except Exception as e:
        logger.error(f"[네이버 검색] 오류: {e}", exc_info=True)
        return ApiResponse(
            success=False,
            data={"items": [], "count": 0},
            message=f"검색 실패: {str(e)}",
        )
