"""
전단지(Flyer) 서비스 — 마트별 디지털 전단지 데이터를 제공.

각 마트의 공식 전단지 페이지 URL과, 가능한 경우 전단지 이미지를 스크래핑하여 반환한다.
스크래핑이 실패하면 웹 URL만 반환하고, 프론트엔드가 링크로 안내한다.
"""

import logging
import re
import asyncio
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

# ── 이마트 전단지 URL ────────────────────────────────────────
# http://emart.kr/Wl7I 의 최종 리다이렉트 목적지
EMART_LEAFLET_URL = (
    "https://eapp.emart.com/leaflet/leafletView_EL.do?trcknCode=main_leaflet"
)

# ── 마트별 전단지 소스 정보 ──────────────────────────────────
MART_FLYER_SOURCES = {
    "emart": {
        "name": "이마트",
        "color": "#FFD700",
        "web_url": EMART_LEAFLET_URL,
        "description": "이마트 디지털 전단지 — 주간 할인 행사",
    },
    "homeplus": {
        "name": "홈플러스",
        "color": "#FF6B35",
        "web_url": "https://www.homeplus.co.kr/app/event/leaflet.do",
        "description": "홈플러스 디지털 전단지 — 주간 행사",
    },
    "lotte": {
        "name": "롯데마트",
        "color": "#E4002B",
        "web_url": "https://www.lotteon.com/p/display/shop/seltDpShop/25348",
        "description": "롯데마트 전단지 — 이번 주 행사",
    },
    "costco": {
        "name": "코스트코",
        "color": "#E31837",
        "web_url": "https://www.costco.co.kr/c/coupon-book/884",
        "description": "코스트코 쿠폰북 — 월간 할인",
    },
}


def _current_flyer_period() -> dict:
    """이번 주 전단지 기간을 계산 (목~수 패턴)."""
    now = datetime.now()
    weekday = now.weekday()  # 0=Mon
    # 전단지는 보통 목요일 시작, 수요일 종료
    days_since_thu = (weekday - 3) % 7
    start = now - timedelta(days=days_since_thu)
    end = start + timedelta(days=6)
    return {
        "valid_from": start.strftime("%Y-%m-%d"),
        "valid_until": end.strftime("%Y-%m-%d"),
        "display_period": f"{start.month}/{start.day}({_weekday_kr(start)}) ~ {end.month}/{end.day}({_weekday_kr(end)})",
    }


def _weekday_kr(dt: datetime) -> str:
    return ["월", "화", "수", "목", "금", "토", "일"][dt.weekday()]


async def _try_scrape_emart_flyer() -> list[dict]:
    """이마트 전단지 이미지 URL을 스크래핑한다.

    eapp.emart.com 전단지 페이지는 서버 사이드 렌더링(SSR)으로,
    <img data-src="..."> 태그에 모든 전단지 페이지 이미지가 포함되어 있다.
    Playwright 없이 httpx만으로 충분하다.
    """
    try:
        import httpx

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
            "Referer": "https://eapp.emart.com/",
        }

        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            resp = await client.get(EMART_LEAFLET_URL, headers=headers)
            if resp.status_code != 200:
                logger.warning("Emart flyer page returned %d", resp.status_code)
                return []

            images = _extract_emart_leaflet_images(resp.text)
            if images:
                logger.info("Emart flyer: scraped %d page images", len(images))
            else:
                logger.warning("Emart flyer: no images found in HTML")
            return images

    except ImportError:
        logger.debug("httpx not installed — skipping Emart flyer scraping")
    except Exception as e:
        logger.warning("Emart flyer scrape failed: %s", e)
    return []


def _extract_emart_leaflet_images(html: str) -> list[dict]:
    """이마트 전단지 HTML에서 페이지별 이미지 URL을 추출한다.

    이마트 전단지 페이지 구조:
      <div class="img_detail d-content" data-width="..." data-height="...">
        <img src="" data-src="https://stimg.emart.com/upload/news_leaflet/..."
             alt="전단 10 면 중 1면 (자세한 내용 아래 참조)" class="none">
        ...
      </div>

    data-src 속성에 실제 이미지 URL이, alt 텍스트에 페이지 번호가 들어있다.
    """
    images: list[dict] = []
    seen_urls: set[str] = set()

    # 패턴: data-src에 news_leaflet 이미지 + alt에 페이지 번호
    # alt 텍스트가 data-src 앞/뒤에 올 수 있으므로 전체 img 태그를 파싱
    img_tag_pattern = re.compile(r"<img\s[^>]*>", re.IGNORECASE | re.DOTALL)
    data_src_pattern = re.compile(
        r'data-src=["\']'
        r"(https?://stimg\.emart\.com/upload/news_leaflet/[^\"']+)"
        r'["\']',
        re.IGNORECASE,
    )
    alt_page_pattern = re.compile(
        r'alt=["\'][^"\']*전단\s*\d+\s*면\s*중\s*(\d+)\s*면',
        re.IGNORECASE,
    )

    for tag_match in img_tag_pattern.finditer(html):
        tag = tag_match.group(0)
        src_match = data_src_pattern.search(tag)
        if not src_match:
            continue

        url = src_match.group(1)
        if url in seen_urls:
            continue
        seen_urls.add(url)

        # alt 텍스트에서 페이지 번호 추출
        page_match = alt_page_pattern.search(tag)
        page_num = int(page_match.group(1)) if page_match else len(images) + 1

        images.append({"image_url": url, "page_number": page_num})

    # 페이지 번호로 정렬
    images.sort(key=lambda x: x["page_number"])
    return images


# ── 캐시 (간단한 인메모리 TTL 캐시) ───────────────────────────
_cache: dict[str, dict] = {}
_CACHE_TTL = timedelta(hours=6)


async def get_flyer_data(store: str) -> Optional[dict]:
    """마트별 전단지 데이터를 반환한다."""
    source = MART_FLYER_SOURCES.get(store)
    if not source:
        return None

    cache_key = f"flyer:{store}"
    cached = _cache.get(cache_key)
    if cached and datetime.now() - cached["fetched_at"] < _CACHE_TTL:
        return cached["data"]

    period = _current_flyer_period()
    flyer_images = []

    # Emart: try scraping
    if store == "emart":
        flyer_images = await _try_scrape_emart_flyer()

    result = {
        "store": store,
        "name": source["name"],
        "color": source["color"],
        "web_url": source["web_url"],
        "description": source["description"],
        "valid_from": period["valid_from"],
        "valid_until": period["valid_until"],
        "display_period": period["display_period"],
        "flyer_pages": flyer_images,
        "has_images": len(flyer_images) > 0,
    }

    _cache[cache_key] = {"data": result, "fetched_at": datetime.now()}
    return result


async def get_all_flyer_data() -> dict[str, dict]:
    """모든 마트의 전단지 데이터를 반환."""
    tasks = {store: get_flyer_data(store) for store in MART_FLYER_SOURCES}
    results = {}
    for store, coro in tasks.items():
        results[store] = await coro
    return results
