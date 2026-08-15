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

import os
import subprocess
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


def pasta_do_banco_de(settings: DatabaseSettings) -> Path:
    """Onde mora o banco embutido, segundo esta configuração."""
    from lumbra.shared.paths import pasta_do_banco

    return (Path(settings.embedded_dir) if settings.embedded_dir else pasta_do_banco()).resolve()


def dsn_se_estiver_no_ar(pasta: Path) -> str | None:
    """O DSN do servidor JÁ rodando nesta pasta, ou ``None``. Nunca inicia.

    Existe porque diagnosticar não pode ser um ato destrutivo. O
    ``lumbra doctor`` chegou a SUBIR o Postgres para responder "seu banco
    está bem?", e a ideia parecia elegante até encontrar um cluster
    precisando de recuperação: cada execução do diagnóstico disparava mais
    uma partida, o ``pg_ctl`` desistia aos 10 segundos (limite fixo da
    biblioteca) enquanto a recuperação do Postgres pedia 30, e o ciclo não
    tinha como terminar. O diagnóstico virou parte do problema que fora
    chamado para explicar.

    Ferramenta de diagnóstico observa. Quem age é ``lumbra up``.
    """
    try:
        from pgserver.postgres_server import PostmasterInfo
    except ImportError:  # pragma: no cover - depende do ambiente
        return None
    if not pasta.exists():
        return None
    try:
        info = PostmasterInfo.read_from_pgdata(pasta)
        if info is None or not info.is_running() or info.status != "ready":
            return None
        return traduzir_uri(info.get_uri())
    except Exception as exc:  # ler estado alheio nunca pode derrubar o doctor
        _log.warning("postmaster_ilegivel", pasta=str(pasta), erro=repr(exc))
        return None


def _processo_vivo(pid: int) -> bool:
    """Vivo de verdade — zumbi não conta.

    ``pid_exists`` devolve ``True`` para processo já morto cujo pai ainda não
    o recolheu. Contar um zumbi como dono do banco mantém o Postgres de pé
    por causa de alguém que já morreu, que é exatamente o erro que estamos
    consertando.
    """
    try:
        import psutil

        return bool(psutil.Process(pid).status() != psutil.STATUS_ZOMBIE)
    except Exception:
        return False  # não existe, ou não conseguimos olhar: não segura o banco


def limpar_donos_fantasmas(pasta: Path) -> int:
    """Remove da lista de donos os processos que já morreram.

    O ``pgserver`` conta quem está usando o servidor num arquivo
    (``.handle_pids.json``) e só desliga o Postgres quando o processo que sai
    é o ÚLTIMO da lista. Elegante — e frágil de um jeito que só aparece
    depois: todo Nó que morre sem se despedir deixa o PID dele ali para
    sempre, e a partir daí a lista NUNCA mais fica com um só. O servidor
    passa a sobreviver a todo encerramento, inclusive aos limpos.

    Foi exatamente o que aconteceu: o Nó já encerrava com dignidade
    (ADR-071), o ``lumbra.exe`` sumia direitinho, e seis ``postgres.exe``
    continuavam de pé — herdados de mortes anteriores, quando o encerramento
    ainda era à força.

    Um PID pode ser reaproveitado pelo sistema, então "existe" não prova que
    é o mesmo processo. O erro possível aqui é conservador: mantemos um dono
    a mais e o servidor sobrevive — que é o estado de hoje, não uma piora.
    """
    import json

    arquivo = pasta / ".handle_pids.json"
    if not arquivo.exists():
        return 0
    try:
        pids = json.loads(arquivo.read_text(encoding="utf-8"))
        vivos = [pid for pid in pids if _processo_vivo(pid)]
    except Exception as exc:  # arquivo ilegível ou psutil ausente: não é fatal
        _log.warning("donos_do_banco_ilegiveis", pasta=str(pasta), erro=repr(exc))
        return 0
    if len(vivos) == len(pids):
        return 0
    arquivo.write_text(json.dumps(vivos), encoding="utf-8")
    _log.info("donos_fantasmas_removidos", quantos=len(pids) - len(vivos), pasta=str(pasta))
    return len(pids) - len(vivos)


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
        # antes de somar o nosso nome à lista de donos, tira os mortos dela —
        # senão herdamos a contagem errada e o banco nunca mais desliga
        limpar_donos_fantasmas(pasta)
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

    pasta = pasta_do_banco_de(settings)
    # Um servidor por pasta POR PROCESSO. Sem isto, o `lumbra up` anunciava
    # "postgres embutido no ar" quatro vezes seguidas — uma por chamador — e
    # três delas eram mentira: o servidor já estava de pé. Log repetido não
    # é só feio; ensina o leitor a ignorar a linha que importa.
    servidor = _servidores.get(pasta) or ServidorEmbutido(pasta)
    _servidores[pasta] = servidor
    return servidor.dsn, servidor


_servidores: dict[Path, ServidorEmbutido] = {}


def _donos_vivos(pasta: Path) -> list[int]:
    import json

    arquivo = pasta / ".handle_pids.json"
    if not arquivo.exists():
        return []
    try:
        pids = json.loads(arquivo.read_text(encoding="utf-8"))
    except Exception:
        return []
    meu = os.getpid()
    return [pid for pid in pids if pid != meu and _processo_vivo(pid)]


def _desligar_postmaster(pasta: Path) -> bool:
    """Manda o Postgres parar, direto. Devolve se conseguiu.

    Chamamos o executável em vez de ``pgserver.pg_ctl`` porque aquela função
    é montada em tempo de execução (o verificador de tipos não a enxerga) e
    porque o tempo limite importa: a biblioteca fixa 10 segundos, e foi
    exatamente esse limite que impediu a recuperação de um cluster que
    precisava de 30.

    ``-m fast`` derruba as conexões abertas mas fecha o checkpoint direito —
    é o desligamento educado. O violento já custou caro uma vez.
    """
    try:
        from pgserver._commands import POSTGRES_BIN_PATH

        executavel = POSTGRES_BIN_PATH / ("pg_ctl.exe" if os.name == "nt" else "pg_ctl")
        resultado = subprocess.run(  # noqa: S603 - caminho vem do pacote, não do usuário
            [str(executavel), "-D", str(pasta), "-w", "-t", "60", "-m", "fast", "stop"],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
    except Exception as exc:
        _log.warning("postmaster_nao_desligou", pasta=str(pasta), erro=repr(exc))
        return False
    if resultado.returncode != 0:
        _log.warning(
            "postmaster_nao_desligou", pasta=str(pasta), saida=resultado.stderr.strip()[:300]
        )
        return False
    _log.info("postmaster_desligado", pasta=str(pasta))
    return True


def parar_embutidos() -> None:
    """Desliga o que nós subimos — sem depender de contagem alheia.

    Duas tentativas, nesta ordem, e a segunda existe porque a primeira já
    falhou em silêncio.

    A primeira é pedir ao ``pgserver`` (``cleanup``), que consulta a lista de
    donos em ``.handle_pids.json`` e só desliga se formos o último. Elegante,
    e quebrado por herança: todo Nó morto à força deixou o PID dele naquela
    lista para sempre, e a partir daí ela nunca mais tem um só. O sintoma foi
    o Nó encerrando com dignidade enquanto seis ``postgres.exe`` ficavam de
    pé.

    A segunda é olhar nós mesmos: se não sobrou nenhum dono VIVO, o banco não
    é de mais ninguém e nós o desligamos. É o que garante o resultado em vez
    de torcer por ele — e continua respeitando a invariante do ADR-067,
    porque um Nó vivo na lista nos faz recuar.
    """
    for pasta, servidor in list(_servidores.items()):
        try:
            servidor.parar()
        except Exception as exc:  # encerrar nunca pode virar um erro novo
            _log.warning("falha_ao_parar_embutido", pasta=str(pasta), erro=repr(exc))
        limpar_donos_fantasmas(pasta)
        restantes = _donos_vivos(pasta)
        if restantes:
            _log.info("banco_fica_de_pe_para_outro_no", pasta=str(pasta), donos=restantes)
            continue
        if dsn_se_estiver_no_ar(pasta) is not None:
            _desligar_postmaster(pasta)
    _servidores.clear()


# canário anti-truncamento
