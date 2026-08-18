"""O banco embutido desliga junto com o Nó — e só quando é o último.

Este teste usa PROCESSOS de verdade porque foi só neles que os dois bugs
apareceram. Em um processo só, o ``pgserver`` reaproveita a instância em
cache e a contagem de donos nunca se comporta como na vida real: cheguei a
"provar" uma correção que não funcionava.

O que se verifica aqui é o par de invariantes que o dogfooding cobrou:

1. Nó morto à força deixa o PID dele na lista de donos. Sem limpar, a lista
   nunca mais fica com um só e o Postgres sobrevive a TODO encerramento —
   inclusive aos limpos. Foi assim que seis ``postgres.exe`` se acumularam.
2. Com dois Nós no mesmo banco, quem sai não pode derrubar o banco de quem
   fica (ADR-067). Apagar demais é tão ruim quanto apagar de menos.
"""

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

_NO_DE_MENTIRA = """
import sys, pathlib
from lumbra.adapters.persistence.embedded import (
    ServidorEmbutido, parar_embutidos, _servidores,
)

pasta = pathlib.Path(sys.argv[1])
servidor = ServidorEmbutido(pasta)
_servidores[pasta] = servidor
print("PRONTO", flush=True)
try:
    for _ in sys.stdin:   # mesma mecânica do ADR-071
        pass
finally:
    parar_embutidos()     # o encerramento explícito do `lumbra up`
"""


@pytest.fixture()
def roteiro(tmp_path: Path) -> Path:
    caminho = tmp_path / "no_de_mentira.py"
    caminho.write_text(_NO_DE_MENTIRA, encoding="utf-8")
    return caminho


@pytest.fixture()
def pasta() -> Path:
    return Path(tempfile.mkdtemp(prefix="lumbra-encerramento-")) / "postgres"


def _subir_no(roteiro: Path, pasta: Path) -> subprocess.Popen:
    processo = subprocess.Popen(  # noqa: S603 - o roteiro é escrito por este arquivo
        [sys.executable, str(roteiro), str(pasta)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert processo.stdout is not None
    # o Nó também escreve log na saída: procuramos a marca, não a 1ª linha
    for _ in range(50):
        linha = processo.stdout.readline()
        if not linha:
            break
        if linha.strip() == "PRONTO":
            return processo
    raise AssertionError("o Nó de mentira não subiu")


def _encerrar_bem(processo: subprocess.Popen) -> None:
    assert processo.stdin is not None
    processo.stdin.close()  # é o que o app faz ao fechar a janela
    processo.wait(timeout=90)


def _postgres_no_ar(pasta: Path) -> bool:
    from lumbra.adapters.persistence.embedded import dsn_se_estiver_no_ar

    for _ in range(20):  # desligar com checkpoint leva alguns segundos
        if dsn_se_estiver_no_ar(pasta) is None:
            return False
        time.sleep(0.5)
    return True


def _donos(pasta: Path) -> list[int]:
    arquivo = pasta / ".handle_pids.json"
    return json.loads(arquivo.read_text(encoding="utf-8")) if arquivo.exists() else []


@pytest.mark.skipif(sys.platform == "win32", reason="usa SIGKILL para simular a morte à força")
def test_no_morto_a_forca_nao_condena_o_banco_a_viver_para_sempre(roteiro, pasta):
    """O bug que o Brendon encontrou: o Nó encerrava direito e o Postgres
    ficava. A herança era de mortes anteriores."""
    vitima = _subir_no(roteiro, pasta)
    os.kill(vitima.pid, signal.SIGKILL)
    vitima.wait()
    assert _donos(pasta), "a lista devia ter ficado com o PID do morto"

    seguinte = _subir_no(roteiro, pasta)  # limpa os fantasmas ao subir
    _encerrar_bem(seguinte)

    assert not _postgres_no_ar(pasta), "o Postgres sobreviveu a um encerramento limpo"


@pytest.mark.skipif(sys.platform == "win32", reason="usa SIGKILL para sujar o cluster")
def test_cluster_sujo_ainda_consegue_subir(roteiro, pasta):
    """A armadilha permanente: banco sujo que nunca mais abre.

    O ``pgserver`` dá 10 segundos ao ``pg_ctl start``. Um cluster que foi
    interrompido precisa de recuperação, e no Windows ela passa de 30 (o
    Postgres tromba no próprio arquivo de log, que fica dentro do diretório
    de dados, e espera 30 segundos por ele). Resultado: a partir da primeira
    parada suja, TODA partida futura estourava o tempo — e o usuário não
    tinha como sair sozinho.

    Aqui matamos o postmaster à força e exigimos que a próxima partida
    funcione.
    """
    no = _subir_no(roteiro, pasta)
    pid = int((pasta / "postmaster.pid").read_text(encoding="utf-8").splitlines()[0])
    os.kill(pid, signal.SIGKILL)  # o banco fica sujo
    time.sleep(1)
    _encerrar_bem(no)

    from lumbra.adapters.persistence.embedded import dsn_se_estiver_no_ar

    seguinte = _subir_no(roteiro, pasta)  # tem que dar conta da recuperação
    assert dsn_se_estiver_no_ar(pasta) is not None, "o cluster sujo não subiu"
    _encerrar_bem(seguinte)


def test_com_dois_nos_quem_sai_nao_derruba_o_banco_do_outro(roteiro, pasta):
    """A invariante do ADR-067 aplicada ao banco: derrubar o Postgres de um
    Nó vivo daria o pior sintoma possível — "o banco cai sozinho" — sem nada
    apontando para quem fechou a outra janela."""
    primeiro = _subir_no(roteiro, pasta)
    segundo = _subir_no(roteiro, pasta)

    _encerrar_bem(segundo)
    from lumbra.adapters.persistence.embedded import dsn_se_estiver_no_ar

    time.sleep(2)
    assert dsn_se_estiver_no_ar(pasta) is not None, "derrubou o banco de quem ainda usava"

    _encerrar_bem(primeiro)  # o último a sair apaga a luz
    assert not _postgres_no_ar(pasta)


# canário anti-truncamento
