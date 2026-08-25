"""Canonical OPINET fuel-price crawler.

Fixture parsing and live acquisition share the same ``GasStationRecord`` model.
Live collection is explicit: it runs only when ``OPINET_API_KEY`` is configured
and uses OPINET's ``lowTop10.do`` API. There is no guessed HTML/network fallback
that can silently turn page text into fuel prices.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import requests

logger = logging.getLogger(__name__)

_CRAWLER_BACKEND = Path(__file__).resolve().parents[2]
_SHARED_DIR = _CRAWLER_BACKEND.parent.parent / "shared"
for _p in (str(_CRAWLER_BACKEND), str(_SHARED_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from config import OPINET_API_KEY
except ImportError:  # pragma: no cover - standalone fixture tooling
    OPINET_API_KEY = ""

try:
    from core.fuel_canonicalize import canonicalize_opinet
    from .parser import parse_opinet_low_price_html

    _HTML_FIXTURE_IMPORTS_OK = True
except ImportError as exc:  # pragma: no cover - retained saved-HTML compatibility
    logger.warning("[OpinetCrawler] legacy HTML fixture import failed: %s", exc)
    _HTML_FIXTURE_IMPORTS_OK = False


BRANDS = {"SK", "GS", "HD현대오일뱅크", "S-OIL", "알뜰", "E1", "SK가스", "농협", "기타"}
FUEL_TYPES = {"gasoline", "premium", "diesel", "kerosene", "lpg"}
PRICE_SOURCES = {"opinet", "other"}

_BRAND_ALIASES = {
    "SK": "SK", "SK에너지": "SK", "SKE": "SK",
    "GS": "GS", "GS칼텍스": "GS", "GSC": "GS",
    "HD현대오일뱅크": "HD현대오일뱅크", "현대오일뱅크": "HD현대오일뱅크",
    "현대": "HD현대오일뱅크", "HDO": "HD현대오일뱅크",
    "S-OIL": "S-OIL", "S오일": "S-OIL", "SOL": "S-OIL",
    "알뜰": "알뜰", "알뜰주유소": "알뜰", "알뜰(자영)": "알뜰",
    "자영알뜰": "알뜰", "RTE": "알뜰", "RTO": "알뜰", "RTX": "알뜰",
    "E1": "E1", "E1G": "E1", "SK가스": "SK가스", "SKG": "SK가스",
    "농협": "농협", "NHO": "농협", "ETC": "기타",
}

_FUEL_ALIASES = {
    "gasoline": "gasoline", "gasoline_regular": "gasoline", "regular": "gasoline", "B027": "gasoline",
    "premium": "premium", "gasoline_premium": "premium", "B034": "premium",
    "diesel": "diesel", "D047": "diesel",
    "kerosene": "kerosene", "C004": "kerosene",
    "lpg": "lpg", "K015": "lpg", "K105": "lpg",
}

# Product codes are endpoint-specific. These values follow OPINET lowTop10.do.
_API_FUELS: tuple[tuple[str, str], ...] = (
    ("gasoline", "B027"),
    ("premium", "B034"),
    ("diesel", "D047"),
    ("lpg", "K105"),
)


@dataclass(frozen=True)
class GasStationPriceRecord:
    fuel_type: str
    price: int
    observed_at: datetime
    source: str = "opinet"


@dataclass(frozen=True)
class GasStationRecord:
    station_code: str
    brand: str
    name: str
    address: str
    sido: str
    sigungu: str
    lat: float | None = None
    lng: float | None = None
    has_self_service: bool = False
    updated_at: datetime = field(default_factory=datetime.utcnow)
    prices: list[GasStationPriceRecord] = field(default_factory=list)


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if value in (None, ""):
        return datetime.utcnow()
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)


def _parse_price(value: Any) -> int | None:
    if value in (None, "", "-"):
        return None
    try:
        parsed = int(float(str(value).replace(",", "").replace("원", "").strip()))
    except (TypeError, ValueError):
        return None
    # Gross corruption guard only; do not encode a historical expected-price gate.
    return parsed if 100 <= parsed <= 10_000 else None


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_brand(value: str | None) -> str:
    normalized = _BRAND_ALIASES.get((value or "").strip(), "기타")
    return normalized if normalized in BRANDS else "기타"


def normalize_fuel_type(value: str) -> str:
    normalized = _FUEL_ALIASES.get(str(value).strip())
    if normalized not in FUEL_TYPES:
        raise ValueError(f"지원하지 않는 유종: {value}")
    return normalized


def _split_region(address: str, sido: str | None = None, sigungu: str | None = None) -> tuple[str, str]:
    parts = address.split()
    return (
        str(sido or (parts[0] if parts else "")).strip(),
        str(sigungu or (parts[1] if len(parts) > 1 else "")).strip(),
    )


def _record_from_raw(raw: dict[str, Any]) -> GasStationRecord:
    address = str(raw.get("address") or "").strip()
    sido, sigungu = _split_region(address, raw.get("sido"), raw.get("sigungu"))
    observed_at = _parse_dt(raw.get("observed_at"))
    prices: list[GasStationPriceRecord] = []
    for item in raw.get("prices", []):
        fuel_type = normalize_fuel_type(str(item.get("fuel_type")))
        price = _parse_price(item.get("price"))
        if price is None:
            continue
        source = str(item.get("source") or "opinet")
        if source not in PRICE_SOURCES:
            source = "other"
        prices.append(GasStationPriceRecord(
            fuel_type=fuel_type,
            price=price,
            observed_at=_parse_dt(item.get("observed_at") or observed_at),
            source=source,
        ))

    return GasStationRecord(
        station_code=str(raw.get("station_code") or raw.get("opinet_id") or "").strip(),
        brand=normalize_brand(raw.get("brand")),
        name=str(raw.get("name") or "").strip(),
        address=address,
        sido=sido,
        sigungu=sigungu,
        lat=_to_float(raw.get("lat")),
        lng=_to_float(raw.get("lng")),
        has_self_service=bool(raw.get("has_self_service", raw.get("self_service", False))),
        updated_at=_parse_dt(raw.get("updated_at") or observed_at),
        prices=prices,
    )


def _record_from_api_row(raw: dict[str, Any], fuel_type: str, observed_at: datetime) -> GasStationRecord | None:
    name = str(raw.get("OS_NM") or raw.get("OSNAME") or "").strip()
    if not name:
        return None
    price = _parse_price(raw.get("PRICE") or raw.get("OPRICE"))
    if price is None:
        return None

    address = str(raw.get("NEW_ADR") or raw.get("VAN_ADR") or "").strip()
    sido, sigungu = _split_region(address)
    station_code = str(raw.get("UNI_ID") or raw.get("UNITID") or "").strip()
    if not station_code:
        station_code = f"{name}|{address}"

    # lowTop10.do returns KATEC GIS_X/Y, not WGS84 latitude/longitude. Keep
    # canonical lat/lng empty until an explicit coordinate conversion is added.
    return GasStationRecord(
        station_code=station_code,
        brand=normalize_brand(str(raw.get("POLL_DIV_CO") or raw.get("POLL_DIV_CD") or "").strip()),
        name=name,
        address=address,
        sido=sido,
        sigungu=sigungu,
        lat=None,
        lng=None,
        has_self_service=str(raw.get("SELF_YN") or "N").upper() == "Y",
        updated_at=observed_at,
        prices=[GasStationPriceRecord(
            fuel_type=normalize_fuel_type(fuel_type),
            price=price,
            observed_at=observed_at,
        )],
    )


def parse_api_payload(
    payload: dict[str, Any] | str,
    *,
    fuel_type: str,
    observed_at: datetime | None = None,
) -> list[GasStationRecord]:
    """Parse one OPINET ``lowTop10`` response into canonical station records."""
    if isinstance(payload, str):
        payload = json.loads(payload)
    result = payload.get("RESULT", payload)
    rows = result.get("OIL", []) if isinstance(result, dict) else []
    if not isinstance(rows, list):
        return []

    at = observed_at or datetime.utcnow()
    parsed: list[GasStationRecord] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        record = _record_from_api_row(row, fuel_type, at)
        if record is not None:
            parsed.append(record)
    return parsed


def merge_station_records(records: Iterable[GasStationRecord]) -> list[GasStationRecord]:
    """Merge per-fuel API rows by station code without losing canonical metadata."""
    merged: dict[str, GasStationRecord] = {}
    for record in records:
        existing = merged.get(record.station_code)
        if existing is None:
            merged[record.station_code] = record
            continue

        price_map = {price.fuel_type: price for price in existing.prices}
        for price in record.prices:
            price_map[price.fuel_type] = price
        merged[record.station_code] = GasStationRecord(
            station_code=existing.station_code,
            brand=existing.brand if existing.brand != "기타" else record.brand,
            name=existing.name or record.name,
            address=existing.address or record.address,
            sido=existing.sido or record.sido,
            sigungu=existing.sigungu or record.sigungu,
            lat=existing.lat if existing.lat is not None else record.lat,
            lng=existing.lng if existing.lng is not None else record.lng,
            has_self_service=existing.has_self_service or record.has_self_service,
            updated_at=max(existing.updated_at, record.updated_at),
            prices=sorted(price_map.values(), key=lambda item: item.fuel_type),
        )
    return list(merged.values())


def _find_default_fixture() -> Path:
    here = Path(__file__).resolve()
    candidates = []
    for parent in [Path.cwd(), *here.parents]:
        candidates.append(parent / "tests" / "fixtures" / "opinet" / "sample_seoul.json")
        candidates.append(parent / "packages" / "crawler-admin" / "backend" / "tests" / "fixtures" / "opinet" / "sample_seoul.json")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return Path.cwd() / "tests" / "fixtures" / "opinet" / "sample_seoul.json"


class OpinetCrawler:
    """OPINET fixture parser plus explicit live ``lowTop10`` API client."""

    name = "opinet"
    display_name = "오피넷 주유소"
    category = "fuel"
    version = "2.0.1"
    BASE_URL = "https://www.opinet.co.kr"
    API_BASE = f"{BASE_URL}/api"
    SIDO_CODES = (
        "01", "02", "03", "04", "05", "06", "07", "08", "09",
        "10", "11", "14", "15", "16", "17", "18", "19",
    )

    def __init__(
        self,
        fixture_path: Path | str | None = None,
        *,
        api_key: str | None = None,
        request_timeout: int = 15,
        max_retries: int = 3,
    ) -> None:
        self.fixture_path = Path(fixture_path) if fixture_path else _find_default_fixture()
        self.api_key = OPINET_API_KEY if api_key is None else api_key
        self.request_timeout = request_timeout
        self.max_retries = max_retries

    @property
    def live_ready(self) -> bool:
        return bool(str(self.api_key or "").strip())

    def parse_fixture(self, fixture_path: Path | str | None = None) -> list[GasStationRecord]:
        path = Path(fixture_path) if fixture_path else self.fixture_path
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("stations", payload if isinstance(payload, list) else [])
        return [_record_from_raw(row) for row in rows]

    def crawl_region(self, sido: str) -> list[GasStationRecord]:
        """Return saved fixture rows for a region; this method never performs network I/O."""
        wanted = sido.strip()
        return [record for record in self.parse_fixture() if record.sido == wanted or record.sido.startswith(wanted)]

    def crawl_from_fixture(
        self,
        fixture_path: Path,
        source_url: str = BASE_URL,
        observed_at: datetime | None = None,
    ):
        """Support current JSON fixtures plus retained historical HTML samples."""
        if fixture_path.suffix.lower() == ".json":
            return self.parse_fixture(fixture_path)
        if not _HTML_FIXTURE_IMPORTS_OK:
            logger.error("[OpinetCrawler] HTML fixture dependencies are unavailable")
            return []
        at = observed_at or datetime.now()
        html = fixture_path.read_text(encoding="utf-8")
        raw_rows = parse_opinet_low_price_html(html, source_url=source_url)
        return [canonicalize_opinet(row, observed_at=at) for row in raw_rows]

    def _request_low_top10(
        self,
        session: requests.Session,
        *,
        product_code: str,
        area_code: str,
    ) -> dict[str, Any] | None:
        if not self.live_ready:
            return None
        url = f"{self.API_BASE}/lowTop10.do"
        params = {
            "certkey": self.api_key,
            "out": "json",
            "prodcd": product_code,
            "area": area_code,
            "cnt": "10",
        }
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = session.get(url, params=params, timeout=self.request_timeout)
                if response.status_code == 429 and attempt < self.max_retries - 1:
                    time.sleep((2 ** attempt) + random.uniform(0.25, 0.75))
                    continue
                if response.status_code != 200:
                    logger.warning(
                        "[OpinetCrawler] lowTop10 HTTP %s area=%s product=%s",
                        response.status_code, area_code, product_code,
                    )
                    return None
                payload = response.json()
                error_code = (payload.get("RESULT") or {}).get("ERROR_CD")
                if error_code and error_code != "0000":
                    logger.warning(
                        "[OpinetCrawler] lowTop10 API error=%s area=%s product=%s",
                        error_code, area_code, product_code,
                    )
                    return None
                return payload
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, ValueError) as exc:
                last_error = exc
                if attempt < self.max_retries - 1:
                    time.sleep((2 ** attempt) + random.uniform(0.25, 0.75))
        if last_error is not None:
            logger.warning("[OpinetCrawler] lowTop10 request failed: %s", last_error)
        return None

    def live_crawl(
        self,
        *,
        sido_codes: Iterable[str] | None = None,
        fuel_types: Iterable[str] | None = None,
    ) -> list[GasStationRecord]:
        """Fetch real ``lowTop10`` rows when an API key is configured."""
        if not self.live_ready:
            logger.info("[OpinetCrawler] OPINET_API_KEY is not configured; live crawl skipped")
            return []

        wanted_fuels = {normalize_fuel_type(name) for name in (fuel_types or [fuel for fuel, _ in _API_FUELS])}
        areas = tuple(sido_codes or self.SIDO_CODES)
        rows: list[GasStationRecord] = []
        with requests.Session() as session:
            for fuel_type, product_code in _API_FUELS:
                if fuel_type not in wanted_fuels:
                    continue
                for area_code in areas:
                    payload = self._request_low_top10(
                        session,
                        product_code=product_code,
                        area_code=str(area_code),
                    )
                    if payload is not None:
                        rows.extend(parse_api_payload(payload, fuel_type=fuel_type))
        return merge_station_records(rows)

    async def crawl(
        self,
        *,
        sido_codes: Iterable[str] | None = None,
        fuel_types: Iterable[str] | None = None,
    ) -> list[GasStationRecord]:
        """Async service entrypoint that keeps blocking requests off the event loop."""
        return await asyncio.to_thread(
            self.live_crawl,
            sido_codes=sido_codes,
            fuel_types=fuel_types,
        )


Crawler = OpinetCrawler

__all__ = [
    "GasStationPriceRecord",
    "GasStationRecord",
    "OpinetCrawler",
    "Crawler",
    "normalize_brand",
    "normalize_fuel_type",
    "parse_api_payload",
    "merge_station_records",
]
