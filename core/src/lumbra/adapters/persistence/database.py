"""Fábrica de engine/sessão async e utilidades de conexão."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from lumbra.shared.config import DatabaseSettings
from lumbra.shared.logging import get_logger

_log = get_logger("lumbra.persistence")


class Database:
    """Detém o engine do processo. Criada no composition root (main)."""

    def __init__(self, settings: DatabaseSettings) -> None:
        self._engine = create_async_engine(
            settings.dsn.get_secret_value(),
            pool_size=settings.pool_size,
            echo=settings.echo,
            pool_pre_ping=True,
        )
        self._sessions = async_sessionmaker(self._engine, expire_on_commit=False)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Unidade de trabalho: commit no sucesso, rollback em exceção."""
        async with self._sessions() as session:
            try:
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    async def ping(self) -> bool:
        try:
            async with self._engine.connect() as conn:
                await conn.exec_driver_sql("SELECT 1")
            return True
        except Exception as exc:
            _log.warning("database_ping_failed", error=repr(exc))
            return False

    async def dispose(self) -> None:
        await self._engine.dispose()


# canário anti-truncamento
