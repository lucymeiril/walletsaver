"""알구몬 핫딜 크롤러 스켈레톤.

라이브 HTML 구조는 Round R G5 메인 Playwright 정찰 뒤 확정한다.
현재 구현은 fixture 전용 placeholder 마크업과 과거 오프라인 테스트 샘플만 파싱하며,
네트워크 호출 없이 핫딜 전용 파이프라인 계약을 검증한다.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

from core.contracts.crawler import CrawlerContract
from core.models import CrawlerGroup, CrawlerInfo, CrawlResult, CrawlStatus, HotdealPost
from crawlers.hotdeals.common import apply_source_facts, dedupe_hotdeal_posts

logger = logging.getLogger(__name__)

TRACKING_QUERY_KEYS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid"}


@dataclass(frozen=True)
class HotdealRecord:
    source_site: str
    source_native_id: str
    title: str
    url: str
    posted_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    price: Optional[int] = None
    original_price: Optional[int] = None
    discount_rate: Optional[float] = None
    shop_name: str = ""
    category_raw: str = ""
    tags: list[str] = field(default_factory=list)
    is_active: bool = True
    fetched_at: datetime = field(default_factory=datetime.now)
    hash_dedup: str = ""

    def to_hotdeal_post(self) -> HotdealPost:
        item = HotdealPost(
            title=self.title,
            url=self.url,
            source_community="알구몬",
            price=self.price,
            original_price=self.original_price,
            price_evidence=str(self.price) if self.price is not None else "",
            category=self.category_raw,
            category_hints=[self.category_raw] if self.category_raw else [],
            post_date=self.posted_at,
            crawled_at=self.fetched_at,
        )
        return apply_source_facts(item, source_id=self.source_site, source_url=self.url)

    def model_dump(self, mode: str = "python") -> dict:
        data = asdict(self)
        if mode == "json":
            for key in ("posted_at", "expires_at", "fetched_at"):
                if data[key] is not None:
                    data[key] = data[key].isoformat()
        return data


class AlgumonCrawler(CrawlerContract):
    """알구몬 핫딜 수집기 — 현재는 fixture fallback 전용."""

    BASE_URL = "https://www.algumon.com"
    SOURCE_ID = "algumon"
    DEAL_URL = "https://www.algumon.com/n/deal"
    FIXTURE_PATH = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "algumon" / "sample_list.html"

    @property
    def info(self) -> CrawlerInfo:
        return CrawlerInfo(
            name="알구몬",
            version="3.0.0-g5b",
            group=CrawlerGroup.HOTDEAL,
            description="알구몬 핫딜 목록 fixture 기반 수집 스켈레톤",
            target_url=self.DEAL_URL,
            strategies=["fixture"],
        )

    def crawl_list(self, html: str | None = None) -> list[HotdealRecord]:
        """알구몬 목록 HTML을 HotdealRecord로 변환한다.

        TODO(Round R G5): Playwright 정찰 결과로 실제 algumon.com selector를 교체한다.
        """
        raw_html = html if html is not None else self._load_fixture_html()
        return self.parse_list_html(raw_html)

    async def crawl(self) -> CrawlResult:
        """네트워크 호출 없이 fixture fallback 결과를 CrawlResult로 반환한다."""
        started_at = datetime.now()
        try:
            records = self.crawl_list()
            posts = [record.to_hotdeal_post() for record in records]
            posts = dedupe_hotdeal_posts(posts)
            finished_at = datetime.now()
            return CrawlResult(
                status=CrawlStatus.SUCCESS,
                crawler_name=self.info.name,
                strategy_used="fixture",
                items_count=len(posts),
                items=[item.model_dump(mode="json") for item in posts],
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=(finished_at - started_at).total_seconds(),
                quality_details={"fixture_fallback": True, "source_site": self.SOURCE_ID},
            )
        except Exception as exc:
            logger.error("[알구몬] fixture 크롤링 실패: %s", exc, exc_info=True)
            return CrawlResult(
                status=CrawlStatus.FAILED,
                crawler_name=self.info.name,
                error_msg=str(exc),
                started_at=started_at,
                finished_at=datetime.now(),
            )

    async def parse(self, raw_data: str) -> list[HotdealPost]:
        records = self.parse_list_html(raw_data)
        return [record.to_hotdeal_post() for record in records]

    async def validate(self, items: list[HotdealPost]) -> list[HotdealPost]:
        return dedupe_hotdeal_posts(items)

    def parse_list_html(self, html: str) -> list[HotdealRecord]:
        soup = BeautifulSoup(html, "html.parser")
        records: list[HotdealRecord] = []

        records.extend(self._parse_fixture_json(soup))
        records.extend(self._parse_placeholder_cards(soup))
        if not records:
            records.extend(self._parse_legacy_offline_cards(soup))

        deduped: dict[str, HotdealRecord] = {}
        for record in records:
            deduped.setdefault(record.hash_dedup, record)
        return list(deduped.values())

    def _parse_fixture_json(self, soup: BeautifulSoup) -> list[HotdealRecord]:
        script = soup.select_one('script[type="application/json"][data-fixture="algumon-list"]')
        if not script or not script.string:
            return []
        payload = json.loads(script.string)
        return [self._record_from_mapping(item) for item in payload.get("items", [])]

    def _parse_placeholder_cards(self, soup: BeautifulSoup) -> list[HotdealRecord]:
        records: list[HotdealRecord] = []
        for card in soup.select("[data-hotdeal-record]"):
            records.append(self._record_from_mapping({
                "source_native_id": card.get("data-native-id", ""),
                "title": self._text(card, "[data-field='title']"),
                "url": card.select_one("[data-field='title'][href], a[data-field='url'][href]").get("href", "") if card.select_one("[data-field='title'][href], a[data-field='url'][href]") else card.get("data-url", ""),
                "posted_at": card.get("data-posted-at"),
                "expires_at": card.get("data-expires-at"),
                "price": self._text(card, "[data-field='price']"),
                "original_price": self._text(card, "[data-field='original_price']"),
                "discount_rate": self._text(card, "[data-field='discount_rate']"),
                "shop_name": self._text(card, "[data-field='shop_name']"),
                "category_raw": self._text(card, "[data-field='category_raw']"),
                "tags": [tag.get_text(strip=True) for tag in card.select("[data-field='tags'] [data-tag]")],
            }))
        return records

    def _parse_legacy_offline_cards(self, soup: BeautifulSoup) -> list[HotdealRecord]:
        records: list[HotdealRecord] = []
        for card in soup.select(".deal-card-content"):
            link = card.select_one("a[href]")
            if not link:
                continue
            price_text = self._text(card, ".deal-price-text, [class*='price']")
            source_text = card.get_text(" ", strip=True)
            records.append(self._record_from_mapping({
                "source_native_id": self._extract_native_id(link.get("href", "")),
                "title": link.get_text(strip=True),
                "url": link.get("href", ""),
                "price": price_text,
                "shop_name": source_text.split("|")[0].strip() if "|" in source_text else "",
                "category_raw": "legacy-offline",
            }))
        return records

    def _record_from_mapping(self, data: dict) -> HotdealRecord:
        url = self.normalize_url(str(data.get("url") or ""))
        native_id = str(data.get("source_native_id") or self._extract_native_id(url))
        title = str(data.get("title") or "").strip()
        price = self._coerce_price(data.get("price"))
        original_price = self._coerce_price(data.get("original_price"))
        discount_rate = self._coerce_discount_rate(data.get("discount_rate"))
        tags = data.get("tags") or []
        if isinstance(tags, str):
            tags = [part.strip() for part in tags.split(",") if part.strip()]
        record_seed = f"{self.SOURCE_ID}|{native_id or url}"
        return HotdealRecord(
            source_site=self.SOURCE_ID,
            source_native_id=native_id,
            title=title,
            url=url,
            posted_at=self._parse_datetime(data.get("posted_at")),
            expires_at=self._parse_datetime(data.get("expires_at")),
            price=price,
            original_price=original_price,
            discount_rate=discount_rate,
            shop_name=str(data.get("shop_name") or "").strip(),
            category_raw=str(data.get("category_raw") or "").strip(),
            tags=list(tags),
            is_active=bool(data.get("is_active", True)),
            hash_dedup=hashlib.sha256(record_seed.encode("utf-8")).hexdigest(),
        )

    def normalize_url(self, url: str) -> str:
        absolute = urljoin(self.BASE_URL, (url or "").strip())
        parsed = urlparse(absolute)
        query = urlencode([(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k not in TRACKING_QUERY_KEYS])
        return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), "", query, ""))

    def _extract_native_id(self, url: str) -> str:
        match = re.search(r"/(?:l/d|n/deal)/(\d+)", url or "")
        return match.group(1) if match else ""

    def _extract_price(self, text: str | None) -> Optional[int]:
        return self._coerce_price(text)

    def _coerce_price(self, value) -> Optional[int]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return int(value)
        text = str(value).strip()
        if not text:
            return None
        if "무료" in text:
            return 0
        match = re.search(r"(\d{1,3}(?:,\d{3})+|\d{3,})\s*원?", text)
        return int(match.group(1).replace(",", "")) if match else None

    def _coerce_discount_rate(self, value) -> Optional[float]:
        if value in (None, ""):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        match = re.search(r"\d+(?:\.\d+)?", str(value))
        return float(match.group(0)) if match else None

    def _parse_datetime(self, value) -> Optional[datetime]:
        if not value:
            return None
        text = str(value).replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None

    def _load_fixture_html(self) -> str:
        return self.FIXTURE_PATH.read_text(encoding="utf-8")

    def _text(self, node, selector: str) -> str:
        found = node.select_one(selector)
        return found.get_text(" ", strip=True) if found else ""


__all__ = ["AlgumonCrawler", "HotdealRecord"]
