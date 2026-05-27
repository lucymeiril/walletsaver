"""Round R G5-c: 오피넷 주유소/주간 가격 누적 테이블.

Revision ID: r_g5c_opinet
Revises: TODO
Create Date: 2026-05-26 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "r_g5c_opinet"
down_revision: Union[str, Sequence[str], None] = "g5b0hotdeal"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


BRAND_VALUES = ("SK", "GS", "HD현대오일뱅크", "S-OIL", "알뜰", "기타")
FUEL_VALUES = ("gasoline", "premium", "diesel", "kerosene", "lpg")
SOURCE_VALUES = ("opinet", "other")


def upgrade() -> None:
    op.create_table(
        "opinet_gas_stations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("station_code", sa.String(length=64), nullable=False),
        sa.Column("brand", sa.Enum(*BRAND_VALUES, name="opinet_gas_station_brand", native_enum=False), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("address", sa.String(length=500), nullable=False),
        sa.Column("sido", sa.String(length=50), nullable=False),
        sa.Column("sigungu", sa.String(length=80), nullable=False),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lng", sa.Float(), nullable=True),
        sa.Column("has_self_service", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("station_code", name="uq_opinet_gas_stations_station_code"),
    )
    op.create_index("ix_opinet_gas_stations_sido", "opinet_gas_stations", ["sido"])
    op.create_index("ix_opinet_gas_stations_sigungu", "opinet_gas_stations", ["sigungu"])
    op.create_index("ix_opinet_gas_stations_region", "opinet_gas_stations", ["sido", "sigungu"])
    op.create_index("ix_opinet_gas_stations_location", "opinet_gas_stations", ["lat", "lng"])

    op.create_table(
        "opinet_gas_station_prices",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("station_id", sa.Integer(), sa.ForeignKey("opinet_gas_stations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("fuel_type", sa.Enum(*FUEL_VALUES, name="opinet_gas_fuel_type", native_enum=False), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("source", sa.Enum(*SOURCE_VALUES, name="opinet_gas_price_source", native_enum=False), nullable=False, server_default="opinet"),
        sa.UniqueConstraint("station_id", "fuel_type", "observed_at", "source", name="uq_opinet_price_station_fuel_observed_source"),
    )
    op.create_index("ix_opinet_prices_station_observed", "opinet_gas_station_prices", ["station_id", "observed_at"])
    op.create_index("ix_opinet_prices_fuel_price", "opinet_gas_station_prices", ["fuel_type", "price"])


def downgrade() -> None:
    op.drop_index("ix_opinet_prices_fuel_price", table_name="opinet_gas_station_prices")
    op.drop_index("ix_opinet_prices_station_observed", table_name="opinet_gas_station_prices")
    op.drop_table("opinet_gas_station_prices")
    op.drop_index("ix_opinet_gas_stations_location", table_name="opinet_gas_stations")
    op.drop_index("ix_opinet_gas_stations_region", table_name="opinet_gas_stations")
    op.drop_index("ix_opinet_gas_stations_sigungu", table_name="opinet_gas_stations")
    op.drop_index("ix_opinet_gas_stations_sido", table_name="opinet_gas_stations")
    op.drop_table("opinet_gas_stations")
