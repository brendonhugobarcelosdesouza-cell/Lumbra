"""Ambiente Alembic (async). DSN vem de Settings (LUMBRA_DATABASE__DSN)."""

from __future__ import annotations

import asyncio
from typing import Any

from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config

from lumbra.adapters.persistence.models import Base
from lumbra.shared.config import get_settings

target_metadata = Base.metadata


def _dsn() -> str:
    return get_settings().database.dsn.get_secret_value()


def run_migrations_offline() -> None:
    context.configure(url=_dsn(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Any) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async() -> None:
    engine = async_engine_from_config({"sqlalchemy.url": _dsn()}, prefix="sqlalchemy.")
    async with engine.connect() as connection:
        await connection.run_sync(_do_run_migrations)
        await connection.commit()
    await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(_run_async())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
