"""
네이버 플레이스 실시간 검색 API — 위치 기반 가게/식당/주유소 정보.

Playwright sync API를 스레드 풀에서 실행하여 네이버 지도의 봇 감지를 우회한다.
Windows asyncio ProactorEventLoop에서는 Playwright async API가 작동하지 않으므로,
sync API + ThreadPoolExecutor 조합으로 해결한다.
네이버는 headless 브라우저를 감지하여 API 응답을 차단하므로,
--disable-blink-features=AutomationControlled 등 stealth 설정이 필수다.

엔드포인트:
    GET /api/local/naver-search       — 네이버 지도 기반 주변 가게 검색
    GET /api/local/subcategory-search  — 서브카테고리 드릴다운 재검색
    GET /api/local/geocode             — 장소명 → 좌표 변환
    GET /api/local/area-explore        — 위치 + 반경 기반 카테고리별 탐색
"""

import asyncio
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from api.schemas.common import ApiResponse

logger = logging.getLogger(__name__)

router = APIRouter()

# ──────────────────────────────────────────────
# 카테고리 트리 (area-explore에서 자동 분류에 사용)
# ──────────────────────────────────────────────
CATEGORY_TREE: dict = {
    "주유소": {"icon": "⛽", "keywords": ["주유소", "충전소"], "subcategories": {}},
    "음식": {
        "icon": "🍽️",
        "keywords": ["음식점", "식당", "맛집"],
        "subcategories": {
            "한식": ["한식", "한정식", "불고기", "비빔밥", "삼겹살", "갈비"],
            "중식": ["중식", "중국집", "짜장", "짬뽕"],
            "일식": ["일식", "초밥", "스시", "돈까스", "라멘", "우동"],
            "분식": ["분식", "떡볶이", "김밥"],
            "고기": ["고기", "삼겹살", "갈비", "소고기", "돼지고기", "양고기", "곱창"],
            "카페": ["카페", "커피", "디저트", "베이커리"],
            "치킨": ["치킨", "통닭"],
            "피자": ["피자"],
            "패스트푸드": ["패스트푸드", "버거", "맥도날드"],
        },
    },
    "병원": {
        "icon": "🏥",
        "keywords": ["병원", "의원", "클리닉"],
        "subcategories": {
            "내과": ["내과"], "치과": ["치과"], "안과": ["안과"], "피부과": ["피부과"],
        },
    },
    "미용": {
        "icon": "💇",
        "keywords": ["미용실", "헤어", "네일", "뷰티"],
        "subcategories": {
            "미용실": ["미용실", "헤어"], "네일": ["네일"],
        },
    },
    "편의시설": {
        "icon": "🏪",
        "keywords": ["편의점", "마트", "슈퍼"],
        "subcategories": {
            "편의점": ["편의점", "GS25", "CU", "세븐일레븐"],
            "마트": ["마트", "이마트", "홈플러스", "롯데마트"],
        },
    },
    "숙소": {
        "icon": "🏨",
        "keywords": ["호텔", "모텔", "숙소", "펜션", "게스트하우스"],
        "subcategories": {},
    },
}


def _parse_fuel_price(value) -> int | None:
    """'1,785' 형태의 연료 가격 문자열 → 정수 변환."""
    if not value:
        return None
    try:
        return int(str(value).replace(",", "").replace("원", "").strip())
    except (ValueError, TypeError):
        return None


# ──────────────────────────────────────────────
# Playwright 브라우저 풀 (재사용으로 검색 속도 2.3× 향상)
# ──────────────────────────────────────────────

class _BrowserPool:
    """Persistent Playwright browser pool for faster repeated searches.

    Cold start: ~5.5s. Warm (reused browser): ~2.4s.
    Auto-closes after idle_timeout to free resources.
    """

    def __init__(self, idle_timeout: int = 300):
        self._lock = threading.Lock()
        self._pw = None
        self._browser = None
        self._idle_timeout = idle_timeout
        self._last_used: float = 0
        self._cleanup_timer: Optional[threading.Timer] = None

    def get_browser(self):
        """브라우저 인스턴스를 반환한다. 없으면 새로 생성. Thread-safe."""
        with self._lock:
            self._last_used = time.time()
            if self._browser and self._browser.is_connected():
                return self._browser
            self._cleanup()
            from playwright.sync_api import sync_playwright
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            self._schedule_cleanup()
            return self._browser

    def _schedule_cleanup(self):
        if self._cleanup_timer:
            self._cleanup_timer.cancel()
        self._cleanup_timer = threading.Timer(self._idle_timeout, self._maybe_cleanup)
        self._cleanup_timer.daemon = True
        self._cleanup_timer.start()

    def _maybe_cleanup(self):
        with self._lock:
            if time.time() - self._last_used >= self._idle_timeout:
                self._cleanup()

    def _cleanup(self):
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._pw:
            try:
                self._pw.stop()
            except Exception:
                pass
            self._pw = None


_pool = _BrowserPool(idle_timeout=300)

# Playwright는 브라우저 인스턴스 생성 비용이 크므로 스레드 풀을 재사용
_executor = ThreadPoolExecutor(max_workers=2)

# ──────────────────────────────────────────────
# 캐시 (geocode + area-explore, TTL 5분)
# ──────────────────────────────────────────────
_cache: dict[str, tuple[float, object]] = {}
_cache_lock = threading.Lock()
_CACHE_TTL = 300  # 5분


def _cache_get(key: str):
    """TTL 기반 캐시 조회. 만료 시 None 반환."""
    with _cache_lock:
        entry = _cache.get(key)
        if entry and time.time() - entry[0] < _CACHE_TTL:
            return entry[1]
        if entry:
            del _cache[key]
    return None


def _cache_set(key: str, value):
    """캐시에 값 저장."""
    with _cache_lock:
        _cache[key] = (time.time(), value)


def _search_via_playwright_sync(query: str, lat: float, lng: float, max_items: int) -> list[dict]:
    """Playwright sync API로 네이버 지도를 검색하고 API 응답을 인터셉트한다.

    브라우저 풀을 재사용하여 warm 검색 시 ~2.4s로 단축.
    response event 감지로 고정 대기(5s) 대신 응답 도착 즉시 반환한다.

    주요 stealth 기법:
    - --disable-blink-features=AutomationControlled: 자동화 플래그 제거
    - navigator.webdriver = undefined: WebDriver 속성 숨김
    - 실제 Chrome User-Agent, viewport, locale, timezone 설정
    """
    api_data: dict = {}

    def handle_response(response):
        """네이버 지도 내부 allSearch API 응답을 캡처한다."""
        if "allSearch" in response.url and response.status == 200:
            try:
                body = response.json()
                if isinstance(body, dict) and "result" in body:
                    api_data["response"] = body
            except Exception:
                pass

    items: list[dict] = []
    context = None
    try:
        browser = _pool.get_browser()
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
        # navigator.webdriver 속성을 숨겨 봇 감지 우회
        page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page.on("response", handle_response)

        url = f"https://map.naver.com/p/search/{query}"
        page.goto(url, timeout=20000)

        # allSearch 응답 도착까지 100ms 간격 폴링 (최대 10초)
        deadline = time.time() + 10
        while "response" not in api_data and time.time() < deadline:
            page.wait_for_timeout(100)

    except Exception as exc:
        logger.warning(f"[네이버 검색] Playwright 크롤링 실패: {exc}")
        return items
    finally:
        if context:
            try:
                context.close()
            except Exception:
                pass

    # 인터셉트된 API 응답에서 장소 목록 추출
    if "response" in api_data:
        items = _extract_place_items(api_data["response"], max_items)

    return items


def _extract_place_items(data: dict, max_items: int) -> list[dict]:
    """allSearch API 응답에서 장소 목록을 추출한다."""
    items: list[dict] = []
    result = data.get("result") or {}
    place_data = result.get("place") or {}
    place_list = place_data.get("list") or []

    for place in place_list[:max_items]:
        # 네이버 카테고리 배열을 콤마로 연결하여 전체 보존 (truncation 방지)
        cat = place.get("category", "")
        if isinstance(cat, list):
            cat = ",".join(cat) if cat else ""
        item = {
            "name": place.get("name", ""),
            "category": cat,
            "address": place.get("roadAddress") or place.get("address", ""),
            "tel": place.get("tel", ""),
            "x": place.get("x", ""),
            "y": place.get("y", ""),
            "distance": place.get("distance", ""),
            "url": (
                f"https://map.naver.com/p/entry/place/{place.get('id', '')}"
                if place.get("id") else ""
            ),
            "image_url": place.get("thumUrl") or place.get("imageUrl", ""),
            "rating": place.get("reviewCount", 0),
            "menu_info": place.get("menuInfo", ""),
        }

        # 주유소: petrolInfo에서 연료 가격 추출
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
            }

        if item["name"]:
            items.append(item)

    return items


@router.get("/naver-search")
async def naver_place_search(
    query: str = Query("맛집", description="검색어 (예: 주유소, 한식, 카페)"),
    lat: float = Query(37.4979, description="위도"),
    lng: float = Query(127.0276, description="경도"),
    max_items: int = Query(20, ge=1, le=50, description="최대 결과 수"),
):
    """네이버 플레이스 실시간 검색.

    Playwright sync API를 별도 스레드에서 실행하여 네이버 지도 검색 결과를 가져온다.
    Windows asyncio 호환 문제를 스레드 풀 실행으로 해결하고,
    네이버의 봇 감지는 stealth 브라우저 설정으로 우회한다.
    """
    loop = asyncio.get_event_loop()
    try:
        items = await loop.run_in_executor(
            _executor,
            _search_via_playwright_sync,
            query, lat, lng, max_items,
        )
        source = "playwright"
    except Exception as e:
        logger.error(f"[네이버 검색] 검색 실패: {e}")
        items = []
        source = "error"

    return ApiResponse(
        success=len(items) > 0,
        data={
            "items": items,
            "count": len(items),
            "query": query,
            "lat": lat,
            "lng": lng,
            "source": source,
        },
        message=f"'{query}' 검색 결과 {len(items)}건" if items else "검색 결과 없음",
    )


@router.get("/subcategory-search")
async def subcategory_search(
    location: str = Query(..., description="위치명 (예: 오리역)"),
    subcategory: str = Query(..., description="서브카테고리 검색어 (예: 카페)"),
    lat: float = Query(None, description="위도"),
    lng: float = Query(None, description="경도"),
    max_items: int = Query(30, ge=1, le=50, description="최대 결과 수"),
):
    """서브카테고리 드릴다운 검색 — 특정 서브카테고리로 네이버 재검색하여 더 많은 결과 반환.

    예: location="오리역", subcategory="카페" → "오리역 카페" 검색
    기존 area-explore 결과를 필터링하는 대신 네이버에 직접 재검색한다.
    """
    # 좌표가 없으면 geocode로 보완
    if lat is None or lng is None:
        loop = asyncio.get_event_loop()
        geo = await loop.run_in_executor(_executor, _geocode_sync, location)
        if geo and geo.get("lat") and geo.get("lng"):
            lat = geo["lat"]
            lng = geo["lng"]
        else:
            lat = lat or 37.5665
            lng = lng or 126.9780

    query = f"{location} {subcategory}"
    loop = asyncio.get_event_loop()
    try:
        items = await loop.run_in_executor(
            _executor,
            _search_via_playwright_sync,
            query, lat, lng, max_items,
        )
        # 각 아이템에 분류 정보 추가
        for item in items:
            item["classifications"] = _classify_item(item)
        source = "playwright"
    except Exception as e:
        logger.error(f"[서브카테고리 검색] 실패: {e}")
        items = []
        source = "error"

    return ApiResponse(
        success=len(items) > 0,
        data={
            "items": items,
            "count": len(items),
            "query": query,
            "location": location,
            "subcategory": subcategory,
            "lat": lat,
            "lng": lng,
            "source": source,
        },
        message=f"'{query}' 검색 결과 {len(items)}건" if items else "검색 결과 없음",
    )

# ──────────────────────────────────────────────
# Geocode 엔드포인트
# ──────────────────────────────────────────────

def _geocode_sync(query: str) -> dict | None:
    """장소명을 네이버 지도에서 검색하여 좌표를 반환한다."""
    cached = _cache_get(f"geocode:{query}")
    if cached is not None:
        return cached

    items = _search_via_playwright_sync(query, lat=37.5665, lng=126.9780, max_items=1)
    if not items:
        return None

    first = items[0]
    result = {
        "lat": float(first["y"]) if first.get("y") else None,
        "lng": float(first["x"]) if first.get("x") else None,
        "address": first.get("address", ""),
        "name": first.get("name", ""),
    }
    _cache_set(f"geocode:{query}", result)
    return result


@router.get("/geocode")
async def geocode(
    query: str = Query(..., description="장소명 (예: 정자역, 강남역)"),
):
    """장소명 → 좌표 변환 (geocoding).

    네이버 지도 검색 결과의 첫 번째 항목 좌표를 반환한다.
    5분 TTL 캐시로 중복 요청을 최소화한다.
    """
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(_executor, _geocode_sync, query)
    except Exception as e:
        logger.error(f"[Geocode] 실패: {e}")
        result = None

    if result:
        return ApiResponse(success=True, data=result)
    return ApiResponse(success=False, data=None, error=f"'{query}' 위치를 찾을 수 없습니다")


# ──────────────────────────────────────────────
# Area Explore 엔드포인트
# ──────────────────────────────────────────────

_DEFAULT_CATEGORIES = "주유소,음식,카페,병원,미용,편의시설"

# 카테고리 → 검색 키워드 매핑
_CATEGORY_SEARCH_KEYWORDS: dict[str, str] = {
    "주유소": "주유소",
    "음식": "맛집",
    "카페": "카페",
    "병원": "병원",
    "미용": "미용실",
    "편의시설": "편의점 마트",
    "숙소": "숙소 호텔",
}


def _classify_item(item: dict) -> list[dict]:
    """네이버가 제공하는 category 필드를 직접 사용하여 상위 카테고리로 분류한다.

    CATEGORY_TREE 키워드 매칭 대신, 네이버 원본 카테고리 문자열을 그대로 서브카테고리로 보존한다.
    예: category="카페,디저트" → [{"category": "음식", "subcategories": ["카페,디저트"]}]
    """
    cat_str = item.get("category") or ""
    matches: list[dict] = []

    # 주유소/충전소 판별
    if any(kw in cat_str for kw in ("주유소", "충전소")):
        matches.append({"category": "주유소", "subcategories": [cat_str]})
        return matches

    # 음식 관련 키워드 (카페 포함)
    _FOOD_KEYWORDS = (
        "카페", "식당", "음식점", "한식", "중식", "일식", "분식",
        "고기", "치킨", "피자", "빵", "디저트", "커피", "베이커리",
        "뷔페", "패밀리레스토랑", "패스트푸드", "국수", "면",
        "해산물", "맛집", "삼겹살", "갈비", "곱창", "양식",
        "초밥", "스시", "돈까스", "라멘", "우동", "떡볶이",
        "김밥", "버거", "통닭", "한정식", "불고기", "비빔밥",
        "중국집", "짜장", "짬뽕", "소고기", "돼지고기", "양고기",
    )
    if any(kw in cat_str for kw in _FOOD_KEYWORDS):
        matches.append({"category": "음식", "subcategories": [cat_str]})

    # 병원/의료 판별
    if any(kw in cat_str for kw in ("병원", "의원", "약국", "치과", "한의원", "안과", "피부과", "내과", "클리닉")):
        matches.append({"category": "병원", "subcategories": [cat_str]})

    # 미용 판별
    if any(kw in cat_str for kw in ("미용", "헤어", "네일", "뷰티")):
        matches.append({"category": "미용", "subcategories": [cat_str]})

    # 편의시설 판별
    if any(kw in cat_str for kw in ("편의점", "마트", "슈퍼", "지하철", "역")):
        matches.append({"category": "편의시설", "subcategories": [cat_str]})

    # 숙소 판별
    if any(kw in cat_str for kw in ("호텔", "모텔", "펜션", "게스트하우스", "숙소")):
        matches.append({"category": "숙소", "subcategories": [cat_str]})

    return matches


def _area_explore_sync(
    location_name: str,
    lat: float,
    lng: float,
    categories: list[str],
    max_items_per_category: int,
) -> dict:
    """위치 기반 카테고리별 탐색. 순차 검색 (ban 방지)."""
    result_categories: list[dict] = []

    for i, cat in enumerate(categories):
        cat_result = _search_single_category_sync(
            location_name, lat, lng, cat, max_items_per_category,
        )
        result_categories.append(cat_result)

        # ban 방지: 카테고리 간 1초 간격
        if i < len(categories) - 1:
            time.sleep(1)

    return {
        "location_name": location_name,
        "lat": lat,
        "lng": lng,
        "categories": result_categories,
        "total_count": sum(c["count"] for c in result_categories),
    }


def _search_single_category_sync(
    location_name: str,
    lat: float,
    lng: float,
    cat: str,
    max_items: int,
) -> dict:
    """단일 카테고리 검색 — SSE 스트리밍에서 사용."""
    cache_key = f"area:{location_name}:{cat}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    search_keyword = _CATEGORY_SEARCH_KEYWORDS.get(cat, cat)
    query = f"{location_name} {search_keyword}"
    items = _search_via_playwright_sync(query, lat, lng, max_items)

    for item in items:
        item["classifications"] = _classify_item(item)

    tree_info = CATEGORY_TREE.get(cat, {})
    cat_result = {
        "name": cat,
        "icon": tree_info.get("icon", "📍"),
        "count": len(items),
        "items": items,
    }
    _cache_set(cache_key, cat_result)
    return cat_result


@router.get("/area-explore-stream")
async def area_explore_stream(
    location_name: str = Query(None, description="장소명"),
    lat: float = Query(None, description="위도"),
    lng: float = Query(None, description="경도"),
    categories: str = Query(_DEFAULT_CATEGORIES, description="콤마 구분 카테고리"),
    max_items: int = Query(30, ge=1, le=50, description="카테고리당 최대 결과 수"),
):
    """SSE 스트리밍: 카테고리별 결과를 하나씩 반환하여 프론트엔드에서 점진적 로딩."""
    if not location_name and (lat is None or lng is None):
        async def error_gen():
            yield f"data: {json.dumps({'error': 'location_name 또는 lat/lng 좌표를 제공해야 합니다'}, ensure_ascii=False)}\n\n"
        return StreamingResponse(error_gen(), media_type="text/event-stream")

    if location_name and (lat is None or lng is None):
        loop = asyncio.get_event_loop()
        geo = await loop.run_in_executor(_executor, _geocode_sync, location_name)
        if geo and geo.get("lat") and geo.get("lng"):
            lat = geo["lat"]
            lng = geo["lng"]
        else:
            lat = lat or 37.5665
            lng = lng or 126.9780

    if not location_name:
        location_name = ""

    cat_list = [c.strip() for c in categories.split(",") if c.strip()]

    async def event_generator():
        loop = asyncio.get_event_loop()
        for i, cat in enumerate(cat_list):
            try:
                result = await loop.run_in_executor(
                    _executor,
                    _search_single_category_sync,
                    location_name, lat, lng, cat, max_items,
                )
                yield f"data: {json.dumps(result, ensure_ascii=False)}\n\n"
            except Exception as exc:
                logger.error(f"[SSE] 카테고리 '{cat}' 검색 실패: {exc}")
                yield f"data: {json.dumps({'name': cat, 'icon': '❌', 'count': 0, 'items': [], 'error': str(exc)}, ensure_ascii=False)}\n\n"

            # ban 방지: 카테고리 간 1초 간격
            if i < len(cat_list) - 1:
                await asyncio.sleep(1)

        yield f"data: {json.dumps({'done': True, 'location_name': location_name, 'lat': lat, 'lng': lng}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/area-explore")
async def area_explore(
    location_name: str = Query(None, description="장소명 (예: 정자역). lat/lng 대신 사용 가능"),
    lat: float = Query(None, description="위도"),
    lng: float = Query(None, description="경도"),
    radius: float = Query(2, description="반경 (km) — 참고 정보, 네이버 검색 범위는 자동"),
    categories: str = Query(_DEFAULT_CATEGORIES, description="콤마 구분 카테고리"),
    max_items: int = Query(30, ge=1, le=50, description="카테고리당 최대 결과 수"),
):
    """위치 + 반경 기반 카테고리별 장소 탐색.

    location_name 또는 lat/lng를 필수로 제공해야 한다.
    location_name이 없으면 lat/lng로 geocode 역변환을 시도하지 않고
    좌표를 검색 컨텍스트로만 사용한다.
    """
    if not location_name and (lat is None or lng is None):
        return ApiResponse(
            success=False,
            error="location_name 또는 lat/lng 좌표를 제공해야 합니다",
        )

    # location_name이 있으면 geocode로 좌표 보완
    if location_name and (lat is None or lng is None):
        loop = asyncio.get_event_loop()
        geo = await loop.run_in_executor(_executor, _geocode_sync, location_name)
        if geo and geo.get("lat") and geo.get("lng"):
            lat = geo["lat"]
            lng = geo["lng"]
        else:
            lat = lat or 37.5665
            lng = lng or 126.9780

    # location_name이 없으면 좌표만으로 검색 (검색어에 지역명 없이)
    if not location_name:
        location_name = ""

    cat_list = [c.strip() for c in categories.split(",") if c.strip()]
    if not cat_list:
        return ApiResponse(success=False, error="카테고리를 하나 이상 지정해야 합니다")

    loop = asyncio.get_event_loop()
    try:
        data = await loop.run_in_executor(
            _executor,
            _area_explore_sync,
            location_name, lat, lng, cat_list, max_items,
        )
    except Exception as e:
        logger.error(f"[Area Explore] 실패: {e}")
        return ApiResponse(success=False, error=str(e))

    return ApiResponse(
        success=data["total_count"] > 0,
        data=data,
    )
