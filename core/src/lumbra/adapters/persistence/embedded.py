"""Postgres que o próprio Nó sobe, sem Docker (P2-f.1, ADR-069).

A Lumbra sempre exigiu ``docker compose up postgres``. Para quem desenvolve,
tudo bem. Para o critério do P2 — *a Lumbra vira o primeiro programa aberto
ao ligar o computador* — é fatal: ninguém instala Docker Desktop para abrir
um aplicativo pessoal.

A saída não é abrir mão do Postgres. Metade do que a plataforma sabe fazer
depende dele: busca full-text em português com pesos, ``pgvector`` para a
busca semântica, transações de verdade na fila de aprovações. Trocar por
SQLite jogaria fora meses de trabalho e mudaria o comportamento do produto.

A saída é o Postgres deixar de ser um *serviço a instalar* e virar um
*detalhe do Nó*: o ``pgserver`` traz o binário do PostgreSQL 16 com pgvector
dentro do pacote Python, inicia sob o usuário comum, sem daemon, sem porta
privilegiada e sem instalação. Já era dependência de teste aqui há semanas —
todo teste de integração roda contra ele. A novidade não é a tecnologia; é
promovê-la de ferramenta de teste a modo de execução.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lumbra.shared.config import DatabaseSettings
from lumbra.shared.logging import get_logger

_log = get_logger("lumbra.persistence.embedded")


def traduzir_uri(uri: str) -> str:
    """Converte a URI do ``pgserver`` no DSN que o SQLAlchemy/asyncpg espera.

    Os dois sistemas não conversam do mesmo jeito e o formato denuncia isso:
    em Linux e macOS o servidor escuta num **socket Unix** (sem porta, sem
    rede — o banco pessoal nem fica alcançável por TCP, o que é uma boa
    propriedade de privacidade); no Windows, que não tem socket Unix, ele
    escuta em TCP local.

    Estava duplicado no ``conftest`` dos testes de integração. Como agora é o
    jeito de o produto rodar, e não um detalhe de teste, mora aqui.
    """
    if "host=" in uri:  # socket Unix: o caminho do diretório vai no host
        socket_dir = uri.split("host=")[1]
        return f"postgresql+asyncpg://postgres@/postgres?host={socket_dir}"
    return uri.replace("postgresql://", "postgresql+asyncpg://")


class ServidorEmbutido:
    """O Postgres do Nó. Um por pasta de dados.

    Pedir o mesmo diretório duas vezes devolve o mesmo servidor — o
    ``pgserver`` conta quantos processos estão usando e só desliga quando o
    último solta. É o que torna seguro chamar isto do CLI *e* da fábrica da
    aplicação (com ``--reload``, são processos diferentes), sem que um
    derrube o banco debaixo do outro.
    """

    def __init__(self, pasta: Path) -> None:
        self.pasta = pasta
        # a pasta-mãe precisa existir: o pgserver cria só o último nível
        pasta.parent.mkdir(parents=True, exist_ok=True)
        self._servidor = self._iniciar(pasta)
        self.dsn = traduzir_uri(self._servidor.get_uri())
        _log.info("postgres_embutido_no_ar", pasta=str(pasta))

    @staticmethod
    def _iniciar(pasta: Path) -> Any:
        try:
            import pgserver
        except ImportError as exc:  # pragma: no cover - depende do ambiente
            raise RuntimeError(
                "LUMBRA_PERSISTENCE=embedded exige o pacote 'pgserver'. "
                "Instale com `pip install pgserver` ou use "
                "LUMBRA_PERSISTENCE=postgres com um banco próprio."
            ) from exc
        return pgserver.get_server(pasta, cleanup_mode="stop")

    def parar(self) -> None:
        """Solta a nossa referência. O servidor só cai quando o último solta."""
        self._servidor.cleanup()
        _log.info("postgres_embutido_liberado", pasta=str(self.pasta))


def preparar_banco(
    settings: DatabaseSettings, *, embutido: bool
) -> tuple[str, ServidorEmbutido | None]:
    """Devolve o DSN a usar e, quando somos nós que subimos, o servidor.

    Um único ponto de decisão para o CLI e para a fábrica da aplicação. Sem
    isto, cada um resolveria o DSN à sua maneira e o dia em que divergissem
    o sintoma seria "as migrações foram para um banco e o Nó para outro" —
    que aparece como tabela faltando, não como erro de configuração.
    """
    if not embutido:
        return settings.dsn.get_secret_value(), None
    from lumbra.shared.paths import pasta_do_banco

    pasta = Path(settings.embedded_dir) if settings.embedded_dir else pasta_do_banco()
    servidor = ServidorEmbutido(pasta)
    return servidor.dsn, servidor


# canário anti-truncamento
