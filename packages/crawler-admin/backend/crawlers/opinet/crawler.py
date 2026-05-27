"""오피넷 주유소 가격 fixture-only 크롤러 스켈레톤.

Round R G5-c 범위에서는 오피넷 라이브 HTTP/API 구조를 추측하지 않는다.
`crawl_region()`은 JSON fixture만 읽어 정규화된 `GasStationRecord` 목록을 반환한다.
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_CRAWLER_BACKEND = Path(__file__).resolve().parents[2]
_SHARED_DIR = _CRAWLER_BACKEND.parent.parent / "shared"
for _p in (str(_CRAWLER_BACKEND), str(_SHARED_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from core.fuel_canonicalize import FuelCanonicalizationResult, canonicalize_opinet
    from .parser import parse_opinet_low_price_html

    _HTML_FIXTURE_IMPORTS_OK = True
except ImportError as _e:  # pragma: no cover - optional legacy fixture path
    logger.warning("[OpinetCrawler] legacy HTML fixture import 실패: %s", _e)
    _HTML_FIXTURE_IMPORTS_OK = False


BRANDS = {"SK", "GS", "HD현대오일뱅크", "S-OIL", "알뜰", "기타"}
FUEL_TYPES = {"gasoline", "premium", "diesel", "kerosene", "lpg"}
PRICE_SOURCES = {"opinet", "other"}

_BRAND_ALIASES = {
    "SK": "SK",
    "SK에너지": "SK",
    "GS": "GS",
    "GS칼텍스": "GS",
    "HD현대오일뱅크": "HD현대오일뱅크",
    "현대오일뱅크": "HD현대오일뱅크",
    "현대": "HD현대오일뱅크",
    "S-OIL": "S-OIL",
    "S오일": "S-OIL",
    "알뜰": "알뜰",
    "알뜰주유소": "알뜰",
    "알뜰(자영)": "알뜰",
    "자영알뜰": "알뜰",
}

_FUEL_ALIASES = {
    "gasoline": "gasoline",
    "gasoline_regular": "gasoline",
    "regular": "gasoline",
    "premium": "premium",
    "gasoline_premium": "premium",
    "diesel": "diesel",
    "kerosene": "kerosene",
    "lpg": "lpg",
}


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
        parsed = int(str(value).replace(",", "").strip())
    except ValueError:
        return None
    return parsed if parsed > 0 else None


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
    return (sido or (parts[0] if parts else ""), sigungu or (parts[1] if len(parts) > 1 else ""))


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
        prices.append(
            GasStationPriceRecord(
                fuel_type=fuel_type,
                price=price,
                observed_at=_parse_dt(item.get("observed_at") or observed_at),
                source=source,
            )
        )

    return GasStationRecord(
        station_code=str(raw.get("station_code") or raw.get("opinet_id") or "").strip(),
        brand=normalize_brand(raw.get("brand")),
        name=str(raw.get("name") or "").strip(),
        address=address,
        sido=sido,
        sigungu=sigungu,
        lat=float(raw["lat"]) if raw.get("lat") is not None else None,
        lng=float(raw["lng"]) if raw.get("lng") is not None else None,
        has_self_service=bool(raw.get("has_self_service", raw.get("self_service", False))),
        updated_at=_parse_dt(raw.get("updated_at") or observed_at),
        prices=prices,
    )


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
    """오피넷 fixture-only 주유소 가격 크롤러."""

    name = "opinet"
    display_name = "오피넷 주유소"
    category = "fuel"
    version = "1.1.0"
    live_ready = False

    def __init__(self, fixture_path: Path | str | None = None) -> None:
        self.fixture_path = Path(fixture_path) if fixture_path else _find_default_fixture()

    def parse_fixture(self, fixture_path: Path | str | None = None) -> list[GasStationRecord]:
        path = Path(fixture_path) if fixture_path else self.fixture_path
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("stations", payload if isinstance(payload, list) else [])
        return [_record_from_raw(row) for row in rows]

    def crawl_region(self, sido: str) -> list[GasStationRecord]:
        """시도 단위 fixture 레코드 반환. 라이브 HTTP 호출은 수행하지 않는다."""
        wanted = sido.strip()
        return [record for record in self.parse_fixture() if record.sido == wanted or record.sido.startswith(wanted)]

    def crawl_from_fixture(
        self,
        fixture_path: Path,
        source_url: str = "https://www.opinet.co.kr",
        observed_at: Optional[datetime] = None,
    ):
        """레거시 HTML fixture 호환 및 신규 JSON fixture 파싱."""
        if fixture_path.suffix.lower() == ".json":
            return self.parse_fixture(fixture_path)
        if not _HTML_FIXTURE_IMPORTS_OK:
            logger.error("[OpinetCrawler] HTML fixture 의존성 미충족")
            return []
        if observed_at is None:
            observed_at = datetime.now()
        html = fixture_path.read_text(encoding="utf-8")
        raw_rows = parse_opinet_low_price_html(html, source_url=source_url)
        return [canonicalize_opinet(row, observed_at=observed_at) for row in raw_rows]

    def live_crawl(self, *args: Any, **kwargs: Any) -> list[GasStationRecord]:
        logger.warning("[OpinetCrawler] live_ready=False: 라이브 호출은 비활성화되어 있습니다")
        return []


Crawler = OpinetCrawler

__all__ = [
    "GasStationPriceRecord",
    "GasStationRecord",
    "OpinetCrawler",
    "Crawler",
    "normalize_brand",
    "normalize_fuel_type",
]
