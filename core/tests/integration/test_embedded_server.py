"""O Postgres embutido de ponta a ponta (P2-f.1, ADR-069).

Este teste é a resposta a uma pergunta que nenhum teste unitário responde:
*a Lumbra roda numa máquina sem Docker?* Ele sobe um PostgreSQL de verdade a
partir do pacote Python, aplica TODAS as migrações e confere que o que a
plataforma precisa está lá — pgvector e os índices de busca. Se algum dia o
``pgserver`` mudar de versão e perder o pgvector, é aqui que dói, e não na
máquina de quem instalou.
"""

import tempfile
from pathlib import Path

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def servidor():
    pytest.importorskip("pgserver", reason="pgserver indisponível")
    from lumbra.adapters.persistence.embedded import ServidorEmbutido

    pasta = Path(tempfile.mkdtemp(prefix="lumbra-embutido-")) / "postgres"
    servidor = ServidorEmbutido(pasta)
    yield servidor
    servidor.parar()


@pytest.fixture(scope="module")
def dsn_migrado(servidor):
    import os

    from alembic import command
    from alembic.config import Config

    from lumbra.shared.config import get_settings

    anterior = os.environ.get("LUMBRA_DATABASE__DSN")
    os.environ["LUMBRA_DATABASE__DSN"] = servidor.dsn
    get_settings.cache_clear()
    command.upgrade(Config("alembic.ini"), "head")
    yield servidor.dsn
    if anterior is None:
        os.environ.pop("LUMBRA_DATABASE__DSN", None)
    else:
        os.environ["LUMBRA_DATABASE__DSN"] = anterior
    get_settings.cache_clear()


async def _consultar(dsn: str, sql: str, **parametros: object):
    from pydantic import SecretStr

    from lumbra.adapters.persistence.database import Database
    from lumbra.shared.config import DatabaseSettings

    db = Database(DatabaseSettings(dsn=SecretStr(dsn)))
    try:
        async with db.session() as sessao:
            resultado = await sessao.execute(text(sql), parametros or None)
            return resultado.scalar_one_or_none()
    finally:
        await db.dispose()


async def test_sobe_um_postgres_de_verdade_sem_docker(dsn_migrado):
    versao = await _consultar(dsn_migrado, "SHOW server_version")
    assert versao is not None


async def test_traz_o_pgvector_junto(dsn_migrado):
    """Sem pgvector não há busca semântica — sobraria busca por palavra.

    É a razão de não trocarmos Postgres por SQLite no caminho do instalador.
    """
    versao = await _consultar(
        dsn_migrado, "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
    )
    assert versao is not None


async def test_todas_as_migracoes_aplicam(dsn_migrado):
    revisao = await _consultar(dsn_migrado, "SELECT version_num FROM alembic_version")
    assert revisao is not None
    tabelas = await _consultar(
        dsn_migrado,
        "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'",
    )
    assert tabelas and tabelas > 10


@pytest.mark.parametrize(
    "indice",
    [
        "ix_chunks_embedding",
        "ix_chunks_tsv",
        "ix_memory_items_embedding",
        "ix_memory_items_tsv",
    ],
)
async def test_os_indices_de_busca_existem(dsn_migrado, indice):
    """Migração que aplica sem erro mas não cria o índice deixa a busca
    lenta em silêncio — o pior tipo de regressão, porque não quebra nada."""
    achado = await _consultar(
        dsn_migrado, "SELECT 1 FROM pg_indexes WHERE indexname = :nome", nome=indice
    )
    assert achado == 1


async def test_pedir_a_mesma_pasta_devolve_o_mesmo_servidor(servidor):
    """A garantia que torna seguro chamar isto do CLI E da aplicação.

    Sob ``--reload`` são processos diferentes olhando para a mesma pasta; se
    o segundo tentasse subir um servidor novo, um derrubaria o outro.
    """
    from lumbra.adapters.persistence.embedded import ServidorEmbutido

    outro = ServidorEmbutido(servidor.pasta)
    assert outro.dsn == servidor.dsn


# canário anti-truncamento
