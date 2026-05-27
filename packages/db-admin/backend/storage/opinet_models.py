"""오피넷 주유소 가격 전용 SQLAlchemy 모델.

기존 4사 mart Product/price_history와 분리된 자체 테이블을 사용한다.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class OpinetBase(DeclarativeBase):
    pass


class GasStationBrand(str, enum.Enum):
    SK = "SK"
    GS = "GS"
    HD_HYUNDAI = "HD현대오일뱅크"
    S_OIL = "S-OIL"
    ALTTEUL = "알뜰"
    OTHER = "기타"


class GasFuelType(str, enum.Enum):
    GASOLINE = "gasoline"
    PREMIUM = "premium"
    DIESEL = "diesel"
    KEROSENE = "kerosene"
    LPG = "lpg"


class GasPriceSource(str, enum.Enum):
    OPINET = "opinet"
    OTHER = "other"


def _enum_values(enum_cls: type[enum.Enum]) -> list[str]:
    return [member.value for member in enum_cls]


class GasStation(OpinetBase):
    __tablename__ = "opinet_gas_stations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    station_code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    brand: Mapped[GasStationBrand] = mapped_column(
        SAEnum(GasStationBrand, values_callable=_enum_values, native_enum=False, name="opinet_gas_station_brand"),
        nullable=False,
        default=GasStationBrand.OTHER,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    address: Mapped[str] = mapped_column(String(500), nullable=False)
    sido: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    sigungu: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lng: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    has_self_service: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_opinet_gas_stations_region", "sido", "sigungu"),
        Index("ix_opinet_gas_stations_location", "lat", "lng"),
    )


class GasStationPrice(OpinetBase):
    __tablename__ = "opinet_gas_station_prices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("opinet_gas_stations.id", ondelete="CASCADE"), nullable=False)
    fuel_type: Mapped[GasFuelType] = mapped_column(
        SAEnum(GasFuelType, values_callable=_enum_values, native_enum=False, name="opinet_gas_fuel_type"),
        nullable=False,
    )
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    source: Mapped[GasPriceSource] = mapped_column(
        SAEnum(GasPriceSource, values_callable=_enum_values, native_enum=False, name="opinet_gas_price_source"),
        nullable=False,
        default=GasPriceSource.OPINET,
    )

    __table_args__ = (
        UniqueConstraint("station_id", "fuel_type", "observed_at", "source", name="uq_opinet_price_station_fuel_observed_source"),
        Index("ix_opinet_prices_station_observed", "station_id", "observed_at"),
        Index("ix_opinet_prices_fuel_price", "fuel_type", "price"),
    )


__all__ = [
    "OpinetBase",
    "GasStation",
    "GasStationPrice",
    "GasStationBrand",
    "GasFuelType",
    "GasPriceSource",
]
