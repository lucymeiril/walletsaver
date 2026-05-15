"""Shared helpers for community hotdeal source connectors."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Iterable, Optional
from urllib.parse import parse_qs, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

from core.models import HotdealPost


def normalize_source_url(url: str) -> str:
    """Return a stable URL for source-owned identity while preserving the post address."""
    parsed = urlparse(url or "")
    if not parsed.scheme or not parsed.netloc:
        return url or ""
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", parsed.query, ""))


def extract_source_record_key(source_id: str, url: str) -> str:
    """Build a source-owned key from common community post URL shapes, falling back to URL hash."""
    normalized = normalize_source_url(url)
    parsed = urlparse(normalized)
    query = parse_qs(parsed.query)
    for key in ("no", "wr_id", "document_srl", "article_id", "id"):
        value = query.get(key, [""])[0]
        if value and re.search(r"\d", value):
            return f"{source_id}:{key}:{value}"

    path = parsed.path.rstrip("/")
    patterns = (
        r"/(?:hotdeal|jirum|saleinfo|views|deal|d)/(\d+)$",
        r"/b/hotdeal/(\d+)$",
        r"/(\d+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, path)
        if match:
            return f"{source_id}:post:{match.group(1)}"

    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]
    return f"{source_id}:url:{digest}"


def parse_post_datetime(value: str | None) -> Optional[datetime]:
    """Parse explicit fixture/live post dates without inventing dates from vague relative labels."""
    if not value:
        return None
    text = value.strip()
    if not text or any(token in text for token in ("방금", "분 전", "시간 전", "어제")):
        return None
    text = text.replace("Z", "+00:00")
    for fmt in (None, "%Y-%m-%d %H:%M", "%Y.%m.%d %H:%M", "%Y-%m-%d", "%Y.%m.%d"):
        try:
            if fmt is None:
                return datetime.fromisoformat(text)
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def apply_source_facts(
    item: HotdealPost,
    *,
    source_id: str,
    source_url: str | None = None,
    post_date_text: str | None = None,
) -> HotdealPost:
    """Attach source-owned URL/key/date facts while keeping parser-owned title/price/category fields."""
    canonical_url = normalize_source_url(source_url or item.url)
    item.source_url = canonical_url
    item.source_record_key = extract_source_record_key(source_id, canonical_url or item.url)
    if not item.post_date:
        item.post_date = parse_post_datetime(post_date_text)
    if post_date_text and not item.period:
        item.period = post_date_text.strip()
    return item


def dedupe_hotdeal_posts(items: Iterable[HotdealPost]) -> list[HotdealPost]:
    """Deduplicate by source-owned key first, then canonical URL."""
    valid: list[HotdealPost] = []
    seen: set[str] = set()
    for item in items:
        key = item.source_record_key or normalize_source_url(item.source_url or item.url)
        if key in seen:
            continue
        seen.add(key)
        if len(item.title) < 3:
            continue
        valid.append(item)
    return valid


class HotdealCollectorMixin:
    """Bounded, testable source collection loop for community hotdeal connectors."""

    SOURCE_ID = "hotdeal"
    PAGE_ENCODING = "utf-8"

    def _fetch_collection_page(self, url: str) -> str:
        headers = self._anti_detect.get_random_headers() if hasattr(self, "_anti_detect") else {}
        response = self._retry_request(url, headers=headers, timeout=15)
        response.encoding = getattr(self, "PAGE_ENCODING", "utf-8")
        if response.status_code != 200:
            raise RuntimeError(f"HTTP {response.status_code}")
        return response.text

    async def collect_pages(
        self,
        *,
        max_pages: int = 1,
        start_url: str | None = None,
        since_source_keys: set[str] | None = None,
        since_post_date: datetime | None = None,
    ) -> list[HotdealPost]:
        """Collect a bounded number of pages and stop on known keys/date cutoff.

        This method is intentionally opt-in and bounded; normal crawl() behavior remains unchanged.
        """
        if max_pages < 1:
            return []
        max_pages = min(max_pages, 5)
        since_source_keys = since_source_keys or set()
        url = start_url or self.info.target_url
        collected: list[HotdealPost] = []
        visited: set[str] = set()

        for _ in range(max_pages):
            if not url or url in visited:
                break
            visited.add(url)
            raw_data = self._fetch_collection_page(url)
            page_items = await self.parse(raw_data)
            page_items = await self.validate(page_items)
            stop_after_page = False
            for item in page_items:
                if item.source_record_key in since_source_keys:
                    stop_after_page = True
                    continue
                if since_post_date and item.post_date:
                    try:
                        is_cutoff = item.post_date <= since_post_date
                    except TypeError:
                        is_cutoff = item.post_date.replace(tzinfo=None) <= since_post_date.replace(tzinfo=None)
                    if is_cutoff:
                        stop_after_page = True
                        continue
                collected.append(item)
            if stop_after_page:
                break
            next_url = self.discover_next_page(raw_data, current_url=url)
            if not next_url or next_url in visited:
                break
            url = next_url
        return dedupe_hotdeal_posts(collected)

    def discover_next_page(self, raw_data: str, *, current_url: str | None = None) -> str | None:
        soup = BeautifulSoup(raw_data, "html.parser")
        selectors = (
            "a[rel='next'][href]",
            "a.next[href]",
            "a.pagination-next[href]",
            "li.next a[href]",
            "a[href][aria-label*='Next']",
            "a[href][aria-label*='다음']",
        )
        for selector in selectors:
            link = soup.select_one(selector)
            if link and link.get("href"):
                base = current_url or self.info.target_url
                return urljoin(base, link["href"])
        return None
