"""WalletSavior Phase F4 — 오피넷 raw 데이터 정규화.

product_canonicalize.py 패턴 준수.
오피넷 저가주유소 테이블 row를 FuelStation + FuelPriceObservation 으로 변환.

canonicalize_opinet(raw, observed_at) → FuelCanonicalizationResult
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from core.fuel_models import FuelKind, FuelPriceObservation, FuelStation, normalize_address

# ── 브랜드 정규화 매핑 ──────────────────────────────────────────────────────
_BRAND_MAP: dict[str, str] = {
    "SK에너지": "SK에너지",
    "SK": "SK에너지",
    "GS칼텍스": "GS칼텍스",
    "GS": "GS칼텍스",
    "현대오일뱅크": "현대오일뱅크",
    "현대": "현대오일뱅크",
    "S-OIL": "S-OIL",
    "S오일": "S-OIL",
    "알뜰(자영)": "알뜰주유소",
    "자영알뜰": "알뜰주유소",
    "알뜰주유소": "알뜰주유소",
    "알뜰(고속도로)": "알뜰주유소(고속)",
    "농협(계통)": "농협",
    "농협": "농협",
    "E1": "E1",
    "SK가스": "SK가스",
    "SK네트웍스": "SK네트웍스",
}

# FuelKind → raw dict field name 매핑
_FUEL_FIELD_MAP: dict[FuelKind, str] = {
    FuelKind.GASOLINE_REGULAR: "gasoline_regular",
    FuelKind.GASOLINE_PREMIUM: "gasoline_premium",
    FuelKind.DIESEL: "diesel",
    FuelKind.LPG: "lpg",
}


def normalize_brand(raw_brand: str) -> str:
    """오피넷 브랜드명을 표준화된 브랜드명으로 정규화."""
    raw = raw_brand.strip()
    return _BRAND_MAP.get(raw, raw)


def parse_price(s: str) -> Optional[int]:
    """가격 문자열 → 정수 원/L. '-' 또는 빈 문자열이면 None."""
    if s is None:
        return None
    s = str(s).strip().replace(",", "").replace(" ", "")
    if s in ("-", "", "0"):
        return None
    try:
        val = int(float(s))
        return val if val > 0 else None
    except (ValueError, TypeError):
        return None


def extract_sido_sigungu(address: str) -> tuple[str, str]:
    """주소에서 시도·시군구 추출.

    예: "서울특별시 강서구 허준로 123" → ("서울특별시", "강서구")
    예: "경기도 수원시 팔달구 인계로 123" → ("경기도", "수원시")
    """
    parts = normalize_address(address).split()
    sido = parts[0] if parts else ""
    sigungu = parts[1] if len(parts) > 1 else ""
    return sido, sigungu


@dataclass
class FuelCanonicalizationResult:
    """오피넷 단일 raw row 정규화 결과."""

    station: Optional[FuelStation] = None
    price_observations: list[FuelPriceObservation] = field(default_factory=list)
    error: Optional[str] = None


def canonicalize_opinet(
    raw: dict,
    observed_at: Optional[datetime] = None,
) -> FuelCanonicalizationResult:
    """오피넷 raw row → FuelStation + FuelPriceObservation 리스트.

    raw 구조 (파서 출력):
        {
            "name": "강서알뜰주유소",
            "brand": "알뜰(자영)",
            "address": "서울특별시 강서구 허준로 123",
            "self_service": True,
            "gasoline_regular": "1598",
            "gasoline_premium": None,
            "diesel": "1448",
            "lpg": None,
            "opinet_id": "A0012345",
            "source_url": "https://www.opinet.co.kr/searRgSelect.do",
        }

    반환:
        FuelCanonicalizationResult — 성공 시 station + observations,
        실패 시 error 메시지.
    """
    if observed_at is None:
        observed_at = datetime.now()

    try:
        name = (raw.get("name") or "").strip()
        brand_raw = (raw.get("brand") or "").strip()
        address = (raw.get("address") or "").strip()

        if not name or not address:
            return FuelCanonicalizationResult(
                error=f"필수 필드 누락: name={name!r}, address={address!r}"
            )

        brand = normalize_brand(brand_raw) if brand_raw else "알수없음"
        sido, sigungu = extract_sido_sigungu(address)
        self_service = bool(raw.get("self_service", False))
        opinet_id = raw.get("opinet_id") or None
        lat = raw.get("lat")
        lng = raw.get("lng")

        station = FuelStation.build(
            brand=brand,
            name=name,
            address=address,
            sido=sido,
            sigungu=sigungu,
            self_service=self_service,
            opinet_id=opinet_id,
            lat=float(lat) if lat is not None else None,
            lng=float(lng) if lng is not None else None,
        )

        observations: list[FuelPriceObservation] = []
        for fuel_kind, field_name in _FUEL_FIELD_MAP.items():
            price_raw = raw.get(field_name)
            if price_raw is None:
                continue
            price = parse_price(str(price_raw))
            if price is None:
                continue
            obs = FuelPriceObservation.build(
                station_id=station.id,
                fuel_kind=fuel_kind,
                price=price,
                observed_at=observed_at,
                source_url=raw.get("source_url"),
            )
            observations.append(obs)

        return FuelCanonicalizationResult(station=station, price_observations=observations)

    except Exception as exc:
        return FuelCanonicalizationResult(error=str(exc))
