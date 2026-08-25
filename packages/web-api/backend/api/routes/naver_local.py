"""Naver Place search helpers for the Local page.

The user-facing iframe/search UX stays available even when structured Naver
search is unavailable.  API failures return empty results explicitly; this
module never fabricates stores, coordinates, ratings, or fuel prices.
"""
from __future__ import annotations

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from api.schemas.common import ApiResponse

logger = logging.getLogger(__name__)
router = APIRouter()

_executor = ThreadPoolExecutor(max_workers=2)

KNOWN_LOCATIONS = {
    "오리역": {"name": "오리역", "lat": 37.339823, "lng": 127.108996},
    "판교역": {"name": "판교역", "lat": 37.394761, "lng": 127.111217},
    "강남역": {"name": "강남역", "lat": 37.497952, "lng": 127.027619},
    "서울역": {"name": "서울역", "lat": 37.554678, "lng": 126.970606},
    "분당": {"name": "분당", "lat": 37.3826, "lng": 127.1189},
}


def _parse_fuel_price(value) -> int | None:
    if not value:
        return None
    try:
        return int(str(value).replace(",", "").replace("원", "").strip())
    except (TypeError, ValueError):
        return None


@router.get("/geocode")
async def geocode(query: str = Query(..., description="위치명 또는 'lat,lng' 좌표")):
    """Resolve a coordinate pair, known location, or a real Naver search result."""
    raw = query.strip()
    if "," in raw:
        try:
            lat_s, lng_s = [part.strip() for part in raw.split(",", 1)]
            lat, lng = float(lat_s), float(lng_s)
            return ApiResponse(data={"name": "현재 위치", "lat": lat, "lng": lng})
        except ValueError:
            pass

    loc = KNOWN_LOCATIONS.get(raw)
    if loc is None:
        for key, value in KNOWN_LOCATIONS.items():
            if key in raw or raw in key:
                loc = value
                break

    if loc is None:
        loop = asyncio.get_running_loop()
        places = await loop.run_in_executor(
            _executor,
            _search_via_playwright_sync,
            raw,
            37.4979,
            127.0276,
            1,
        )
        if places:
            first = places[0]
            try:
                loc = {
                    "name": first.get("name") or raw,
                    "lat": float(first.get("y") or first.get("lat")),
                    "lng": float(first.get("x") or first.get("lng")),
                    "source": "naver",
                }
            except (TypeError, ValueError):
                loc = None

    if loc is None:
        return ApiResponse(
            success=False,
            data=None,
            error="위치를 찾을 수 없습니다. 네이버 지도 검색을 직접 이용해 주세요.",
        )
    return ApiResponse(data=loc)


def _search_via_playwright_sync(query: str, lat: float, lng: float, max_items: int) -> list[dict]:
    """Search Naver Map in a browser and extract its structured place response."""
    from playwright.sync_api import sync_playwright

    api_data: dict = {}

    def handle_response(response):
        if "allSearch" in response.url and response.status == 200:
            try:
                body = response.json()
                if isinstance(body, dict) and "result" in body:
                    api_data["response"] = body
            except Exception:
                pass

    items: list[dict] = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1920, "height": 1080},
                locale="ko-KR",
                timezone_id="Asia/Seoul",
                geolocation={"latitude": lat, "longitude": lng},
                permissions=["geolocation"],
            )
            page = context.new_page()
            page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            page.on("response", handle_response)
            page.goto(f"https://map.naver.com/p/search/{query}", timeout=20000)
            page.wait_for_timeout(5000)
            browser.close()
    except Exception as exc:
        logger.warning("[네이버 검색] structured search failed: %s", exc)
        return []

    data = api_data.get("response") or {}
    result = data.get("result") or {}
    place_data = result.get("place") or {}
    place_list = place_data.get("list") or []

    for place in place_list[:max_items]:
        category = place.get("category", "")
        if isinstance(category, list):
            category = category[0] if category else ""
        item = {
            "name": place.get("name", ""),
            "category": category,
            "address": place.get("roadAddress") or place.get("address", ""),
            "tel": place.get("tel", ""),
            "x": place.get("x", ""),
            "y": place.get("y", ""),
            "distance": place.get("distance", ""),
            "url": (
                f"https://map.naver.com/p/entry/place/{place.get('id', '')}"
                if place.get("id")
                else ""
            ),
            "image_url": place.get("thumUrl") or place.get("imageUrl", ""),
            "rating": place.get("reviewCount", 0),
            "menu_info": place.get("menuInfo", ""),
        }
        petrol = place.get("petrolInfo")
        if petrol and isinstance(petrol, dict):
            item["petrol_info"] = {
                "gasoline": _parse_fuel_price(petrol.get("gasPrice")),
                "premium_gasoline": _parse_fuel_price(petrol.get("hGasPrice")),
                "diesel": _parse_fuel_price(petrol.get("dieselPrice")),
                "lpg": _parse_fuel_price(petrol.get("lpgPrice")),
                "is_self": bool(petrol.get("isSelf")),
                "is_24h": bool(petrol.get("is24Opened")),
                "has_car_wash": bool(petrol.get("hasCarWash")),
                "brand": (petrol.get("petrolCompany") or {}).get("name", "").strip(),
                "updated_at": petrol.get("updateDate") or petrol.get("updatedAt"),
            }
        if item["name"]:
            items.append(item)

    return items


async def _search(query: str, lat: float, lng: float, max_items: int) -> list[dict]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _executor,
        _search_via_playwright_sync,
        query,
        lat,
        lng,
        max_items,
    )


@router.get("/naver-search")
async def naver_place_search(
    query: str = Query("맛집", description="검색어 (예: 주유소, 한식, 카페)"),
    lat: float = Query(37.4979, description="위도"),
    lng: float = Query(127.0276, description="경도"),
    max_items: int = Query(20, ge=1, le=50, description="최대 결과 수"),
):
    try:
        items = await _search(query, lat, lng, max_items)
        source = "naver" if items else "unavailable"
    except Exception as exc:
        logger.error("[네이버 검색] search failed: %s", exc)
        items = []
        source = "unavailable"

    return ApiResponse(
        data={
            "items": items,
            "count": len(items),
            "query": query,
            "lat": lat,
            "lng": lng,
            "source": source,
        },
    )


@router.get("/area-explore-stream")
async def area_explore_stream(
    categories: str = Query("음식,카페,주유소,마트,편의점"),
    location_name: str | None = Query(None),
    lat: float = Query(37.4979),
    lng: float = Query(127.0276),
    max_items: int = Query(30, ge=1, le=100),
):
    """Stream real category searches; unavailable categories contain no fake rows."""
    names = [category.strip() for category in categories.split(",") if category.strip()]

    async def event_stream():
        per_category = max(1, min(8, max_items // max(1, len(names))))
        for name in names:
            try:
                items = await _search(name, lat, lng, per_category)
            except Exception as exc:
                logger.warning("[네이버 검색] category %s failed: %s", name, exc)
                items = []
            payload = {
                "name": name,
                "location_name": location_name or "",
                "items": items,
                "source": "naver" if items else "unavailable",
            }
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.05)
        yield "data: {\"done\": true}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/subcategory-search")
async def subcategory_search(
    location: str = Query(""),
    subcategory: str = Query(...),
    lat: float = Query(37.4979),
    lng: float = Query(127.0276),
    max_items: int = Query(30, ge=1, le=100),
):
    try:
        items = await _search(subcategory, lat, lng, min(max_items, 30))
    except Exception as exc:
        logger.warning("[네이버 검색] subcategory %s failed: %s", subcategory, exc)
        items = []

    return ApiResponse(data={
        "items": items,
        "location": location,
        "subcategory": subcategory,
        "source": "naver" if items else "unavailable",
    })
