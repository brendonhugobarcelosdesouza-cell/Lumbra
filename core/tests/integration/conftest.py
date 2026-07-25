"""Fixtures de integração: PostgreSQL real (pgserver, com pgvector) + migrações."""

import tempfile

import pytest
from alembic import command
from alembic.config import Config

from lumbra.shared.config import DatabaseSettings


@pytest.fixture(scope="session")
def pg_dsn() -> str:
    pgserver = pytest.importorskip("pgserver", reason="pgserver indisponível")
    server = pgserver.get_server(tempfile.mkdtemp(prefix="lumbra-pg-"))
    uri = server.get_uri()
    if "host=" in uri:  # Linux/macOS: socket Unix
        socket_dir = uri.split("host=")[1]
        dsn = f"postgresql+asyncpg://postgres@/postgres?host={socket_dir}"
    else:  # Windows: TCP local
        dsn = uri.replace("postgresql://", "postgresql+asyncpg://")

    # aplica migrações uma vez por sessão de testes
    import os

    os.environ["LUMBRA_DATABASE__DSN"] = dsn
    from lumbra.shared.config import get_settings

    get_settings.cache_clear()
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")
    yield dsn
    get_settings.cache_clear()
    os.environ.pop("LUMBRA_DATABASE__DSN", None)


@pytest.fixture()
async def db(pg_dsn: str):
    from lumbra.adapters.persistence.database import Database

    database = Database(DatabaseSettings(dsn=pg_dsn))  # type: ignore[arg-type]
    yield database
    await database.dispose()
