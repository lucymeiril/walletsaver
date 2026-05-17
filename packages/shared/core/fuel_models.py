"""WalletSavior Phase F4 — 주유소 도메인 모델 (Pydantic v2).

오피넷(opinet.co.kr) 기반 주유소 가격 데이터의 공통 언어를 정의한다.
크롤러는 raw 데이터를 이 모델로 변환하고,
DB·API·검색·시각화는 이 모델만 다룬다.

canonical_id: SHA1(brand|address_normalized)
가격 단위: 원/L (정수)
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class FuelKind(str, Enum):
    GASOLINE_REGULAR = "gasoline_regular"   # 휘발유 (일반)
    GASOLINE_PREMIUM = "gasoline_premium"   # 고급휘발유
    DIESEL = "diesel"                       # 경유
    LPG = "lpg"                             # LPG


def normalize_address(addr: str) -> str:
    """주소 정규화: 연속 공백 단일화 + 앞뒤 공백 제거."""
    return re.sub(r"\s+", " ", addr.strip())


class FuelStation(BaseModel):
    """주유소 기본 정보 — 오피넷 기반 주유소 데이터의 표준 단위.

    id:
        SHA1(brand|address_normalized) — 결정적 해시.
        브랜드+주소로 같은 주유소 식별.
        opinet_id가 변경되더라도 brand+address가 같으면 동일 id.

    sido / sigungu:
        행정구역 — 시도(특별시/광역시/도) / 시군구.
        지역별 가격 등급 계산의 그룹 단위.
    """

    id: str
    brand: str
    name: str
    address: str
    sido: str
    sigungu: str
    lat: Optional[float] = None
    lng: Optional[float] = None
    self_service: bool = False
    has_car_wash: bool = False
    has_convenience: bool = False
    opinet_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    @staticmethod
    def make_id(brand: str, address: str) -> str:
        """결정적 canonical id 생성.

        SHA1(brand|address_normalized).
        brand·address가 같으면 항상 같은 id → 멱등 upsert 가능.
        """
        addr_norm = normalize_address(address)
        raw = f"{brand.strip()}|{addr_norm}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    @classmethod
    def build(
        cls,
        brand: str,
        name: str,
        address: str,
        sido: str,
        sigungu: str,
        **kwargs,
    ) -> "FuelStation":
        """brand+address로 id를 자동 계산해서 생성하는 팩토리."""
        return cls(
            id=cls.make_id(brand, address),
            brand=brand,
            name=name,
            address=address,
            sido=sido,
            sigungu=sigungu,
            **kwargs,
        )


class FuelPriceObservation(BaseModel):
    """특정 주유소·특정 시점·특정 유종의 가격 스냅샷.

    station_id:
        FuelStation.id FK.

    fuel_kind:
        FuelKind enum — 휘발유/고급휘발유/경유/LPG.

    price:
        원/L (정수). 오피넷 표시 가격 그대로.

    observed_at:
        크롤러 수집 시각.
    """

    id: str
    station_id: str
    fuel_kind: FuelKind
    price: int                      # 원/L
    observed_at: datetime = Field(default_factory=datetime.now)
    source_url: Optional[str] = None

    @staticmethod
    def make_id(station_id: str, fuel_kind: FuelKind, observed_at: datetime) -> str:
        raw = f"{station_id}|{fuel_kind.value}|{observed_at.strftime('%Y%m%d')}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    @classmethod
    def build(
        cls,
        station_id: str,
        fuel_kind: FuelKind,
        price: int,
        observed_at: Optional[datetime] = None,
        **kwargs,
    ) -> "FuelPriceObservation":
        if observed_at is None:
            observed_at = datetime.now()
        return cls(
            id=cls.make_id(station_id, fuel_kind, observed_at),
            station_id=station_id,
            fuel_kind=fuel_kind,
            price=price,
            observed_at=observed_at,
            **kwargs,
        )
