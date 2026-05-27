"""
전단지(Flyer) 서비스 — 마트별 디지털 전단지 데이터를 제공.

각 마트의 공식 전단지 페이지 URL과, 가능한 경우 전단지 이미지를 스크래핑하여 반환한다.
스크래핑이 실패하면 웹 URL만 반환하고, 프론트엔드가 링크로 안내한다.
"""

import logging
import asyncio
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

# ── 마트별 전단지 소스 정보 ──────────────────────────────────
MART_FLYER_SOURCES = {
    "emart": {
        "name": "이마트",
        "color": "#FFD700",
        "web_url": "https://emart.ssg.com/event/leaflet.ssg",
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
    """이마트 SSG 전단지 이미지 URL 스크래핑을 시도한다."""
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
        }

        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(
                "https://emart.ssg.com/event/leaflet.ssg", headers=headers
            )
            if resp.status_code != 200:
                logger.warning("Emart flyer page returned %d", resp.status_code)
                return []

            html = resp.text
            images = _extract_flyer_images_from_html(html, "https://emart.ssg.com")
            if images:
                return images

            # Try SSG event/leaflet API patterns
            resp2 = await client.get(
                "https://emart.ssg.com/disp/leaflet.ssg",
                headers=headers,
            )
            if resp2.status_code == 200:
                images = _extract_flyer_images_from_html(
                    resp2.text, "https://emart.ssg.com"
                )
                if images:
                    return images

    except ImportError:
        logger.debug("httpx not installed — skipping Emart flyer scraping")
    except Exception as e:
        logger.warning("Emart flyer scrape failed: %s", e)
    return []


def _extract_flyer_images_from_html(html: str, base_url: str) -> list[dict]:
    """HTML에서 전단지 이미지 URL을 추출."""
    import re

    images = []
    # SSG/Emart leaflet images are typically large JPGs in the page
    # Pattern 1: img tags with leaflet/flyer-related src
    img_pattern = re.compile(
        r'<img[^>]+src=["\']([^"\']+(?:leaflet|flyer|event|전단)[^"\']*\.(?:jpg|jpeg|png|webp))["\']',
        re.IGNORECASE,
    )
    for match in img_pattern.finditer(html):
        url = match.group(1)
        if not url.startswith("http"):
            url = urljoin(base_url, url)
        images.append({"image_url": url, "page_number": len(images) + 1})

    # Pattern 2: Background images in style attributes
    bg_pattern = re.compile(
        r'url\(["\']?([^"\')\s]+(?:leaflet|flyer|event)[^"\')\s]*\.(?:jpg|jpeg|png|webp))["\']?\)',
        re.IGNORECASE,
    )
    for match in bg_pattern.finditer(html):
        url = match.group(1)
        if not url.startswith("http"):
            url = urljoin(base_url, url)
        images.append({"image_url": url, "page_number": len(images) + 1})

    # Pattern 3: Large images (likely flyer pages) from CDN
    cdn_pattern = re.compile(
        r'["\']?(https?://[^"\'>\s]+ssgcdn\.com[^"\'>\s]*\.(?:jpg|jpeg|png|webp))["\']?',
        re.IGNORECASE,
    )
    seen = set()
    for match in cdn_pattern.finditer(html):
        url = match.group(1)
        if url not in seen and any(
            kw in url.lower()
            for kw in ["leaflet", "event", "flyer", "1200", "800", "banner"]
        ):
            seen.add(url)
            images.append({"image_url": url, "page_number": len(images) + 1})

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
