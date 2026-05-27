"""Alembic env.py — WalletSavior 마이그레이션 설정."""
import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from storage.models import Base
# p1-db-orm-wire: canonical_models.py 의 CanonicalBase도 함께 import
from storage.canonical_models import CanonicalBase
from storage.opinet_models import OpinetBase

config = context.config

# DATABASE_URL 환경변수가 있으면 우선 사용
database_url = os.getenv("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)
else:
    url = config.get_main_option("sqlalchemy.url")
    if url and "changeme" in url:
        raise RuntimeError(
            "SECURITY: Default credentials detected in alembic.ini. "
            "Set DATABASE_URL environment variable."
        )

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# p1-db-orm-wire: legacy + canonical metadata 를 모두 autogenerate 대상으로 설정.
# MetaData.tables 딕셔너리를 합산하여 단일 target_metadata 구성.
import sqlalchemy as _sa
_combined_meta = _sa.MetaData()

for table in Base.metadata.tables.values():
    table.to_metadata(_combined_meta)

for table in CanonicalBase.metadata.tables.values():
    if table.name not in _combined_meta.tables:
        table.to_metadata(_combined_meta)

for table in OpinetBase.metadata.tables.values():
    if table.name not in _combined_meta.tables:
        table.to_metadata(_combined_meta)

target_metadata = _combined_meta


def run_migrations_offline() -> None:
    """오프라인(SQL 생성만) 모드."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """온라인(DB 직접 연결) 모드."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
