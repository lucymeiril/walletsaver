"""Bounded Algumon transport; current live markup remains unverified.

Fixture and historical parser helpers are offline contracts, never a fallback
for a supplier response. A successful HTTP response alone is not parsed-post evidence.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup
import requests

from core.contracts.crawler import CrawlerContract
from core.models import CrawlerGroup, CrawlerInfo, CrawlResult, CrawlStatus, ErrorType, HotdealPost, StrategyFailure
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
    """One ordinary public response, held until a live parser is source-proven."""

    BASE_URL = "https://www.algumon.com"
    SOURCE_ID = "algumon"
    DEAL_URL = "https://www.algumon.com/n/deal"
    FIXTURE_PATH = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "algumon" / "sample_list.html"
    MAX_RESPONSE_BYTES = 1024 * 1024
    MAX_RESPONSE_SECONDS = 20

    @property
    def info(self) -> CrawlerInfo:
        return CrawlerInfo(
            name="알구몬",
            version="3.0.0-g5b",
            group=CrawlerGroup.HOTDEAL,
            description="알구몬 단일 공개 HTTP 응답 확인; 실제 목록 파서 검증 미완료",
            target_url=self.DEAL_URL,
            strategies=["requests"],
        )

    def crawl_list(self, html: str | None = None) -> list[HotdealRecord]:
        """알구몬 목록 HTML을 HotdealRecord로 변환한다.

        TODO(Round R G5): Playwright 정찰 결과로 실제 algumon.com selector를 교체한다.
        """
        raw_html = html if html is not None else self._load_fixture_html()
        return self.parse_list_html(raw_html)

    async def crawl(self) -> CrawlResult:
        """Capture once off the event loop, without presenting offline rows as live."""
        started_at = datetime.now(timezone.utc)
        capture = {"request_url": self.DEAL_URL, "http_receipt_status": "not_recorded"}
        try:
            capture, body = await asyncio.to_thread(self._fetch_source_once)
            status = capture['status_code']
            if status in {401, 403, 429}:
                reason = 'http_access_denied'
            elif status != 200:
                reason = 'nonproduct_response'
            elif not capture['body_capture_complete']:
                reason = ('response_body_unavailable' if capture.get('failure_type') else 'response_capture_limit')
            elif capture['content_type'] not in {'text/html', 'application/xhtml+xml'}:
                reason = 'unsupported_content_type'
            else:
                # This inspection establishes denial/fixture markers only.
                # None of the existing selectors is a verified current live parser.
                soup = BeautifulSoup(body.decode('utf-8', errors='replace'), 'html.parser')
                fixture = bool(soup.select_one('[data-fixture], [data-fixture-source], [data-hotdeal-record]'))
                for element in soup.select('script, style, noscript'):
                    element.decompose()
                visible = soup.get_text(' ', strip=True).lower()
                challenge = any(marker in visible for marker in (
                    'verify you are human', 'complete the captcha', 'access denied', 'request blocked',
                    '접근이 차단', '비정상적인 접근',
                ))
                reason = ('visible_access_challenge' if challenge else
                    'offline_fixture_body' if fixture else 'unsupported_live_body')
        except Exception as exc:
            # Exception text can contain proxy credentials or response data.
            capture['failure_type'] = type(exc).__name__
            reason = 'transport_unavailable'
        finished_at = datetime.now(timezone.utc)
        quality = {"source_site": self.SOURCE_ID, "fixture_fallback": False,
            "source_stopped": True, "source_stop_status": capture.get('status_code'),
            "source_stop_reason": reason, "live_parser_verified": False,
            "fetch": capture, "counts": {"parsed": 0, "valid": 0},
            "collection": {"mode": "bounded_http_no_fixture_fallback", "max_requests": 1,
                "max_response_bytes": self.MAX_RESPONSE_BYTES, "auth_bypass_attempted": False}}
        error_type = (ErrorType.HTTP_ERROR if reason in {'http_access_denied', 'nonproduct_response'}
            else ErrorType.NETWORK_ERROR if reason == 'transport_unavailable' else ErrorType.UNKNOWN)
        return CrawlResult(status=CrawlStatus.FAILED, crawler_name=self.info.name, strategy_used='requests',
            items_count=0, items=[], started_at=started_at, finished_at=finished_at,
            duration_seconds=(finished_at - started_at).total_seconds(), error_msg=reason,
            errors=[StrategyFailure(strategy_name='requests', error_type=error_type,
                error_msg=reason, status_code=capture.get('status_code'))], quality_details=quality,
            raw_data=json.dumps({"diagnostic_kind": "algumon_transport_only", "reason": reason,
                "fetch": capture}, ensure_ascii=False, sort_keys=True))

    def _fetch_source_once(self) -> tuple[dict, bytes]:
        """Normal environment proxy/CA trust, one GET, bounded body; no cookies/login."""
        session = requests.Session()
        # Retain trust_env for proxy/CA, while avoiding implicit provider netrc auth.
        session.auth = lambda prepared: prepared
        response = None
        deadline = time.monotonic() + self.MAX_RESPONSE_SECONDS
        try:
            response = session.get(self.DEAL_URL, timeout=(5, 10), allow_redirects=False, stream=True)
            received_at = datetime.now(timezone.utc)
            content_type = str(response.headers.get('Content-Type', '')).split(';', 1)[0].strip().lower()
            content_type = content_type if re.fullmatch(r'[a-z0-9.+-]+/[a-z0-9.+-]+', content_type) else None
            capture = {'request_url': self.DEAL_URL, 'response_url': getattr(response, 'url', None),
                'status_code': response.status_code, 'content_type': content_type,
                'source_response_received_at': received_at.isoformat(),
                'http_receipt_status': 'received_response', 'body_capture_complete': True,
                'body_sha256': None, 'bytes_received': 0, 'raw_body_retained': False}
            body = bytearray()
            try:
                for chunk in response.iter_content(chunk_size=65536):
                    capture['bytes_received'] += len(chunk)
                    if len(body) + len(chunk) > self.MAX_RESPONSE_BYTES or time.monotonic() > deadline:
                        capture['body_capture_complete'] = False
                        break
                    body.extend(chunk)
            except requests.RequestException as exc:
                capture['body_capture_complete'] = False
                capture['failure_type'] = type(exc).__name__
            if capture['body_capture_complete']:
                capture['body_sha256'] = hashlib.sha256(body).hexdigest()
            return capture, bytes(body)
        finally:
            if response is not None:
                response.close()
            session.close()

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
