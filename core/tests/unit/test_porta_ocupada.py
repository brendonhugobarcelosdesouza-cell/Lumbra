"""Uma Lumbra por computador — e dizer isso em vez de `[Errno 10048]`.

Encontrado com duas Lumbras na mesma máquina: a instalada e a de
desenvolvimento. Elas já não disputavam mais o banco (pastas de dados
separadas), mas as duas escutam em 8000.

O `lumbra up` só descobria isso no FIM: acordava o Postgres embutido,
aplicava migrações, rodava o diagnóstico inteiro — e então tentava escutar,
falhava e desligava tudo. Trabalho jogado fora, e na tela do app aparecia o
texto cru do Windows sobre "utilização de cada endereço de soquete", que não
diz a ninguém o que fazer.

A causa quase sempre é uma só, banal e fácil de nomear: já existe uma Lumbra
rodando. Perguntar isso primeiro custa 400 ms.
"""

from __future__ import annotations

import socket
from contextlib import closing

from lumbra.cli.main import _porta_ocupada


def _porta_livre() -> int:
    """Pede ao sistema uma porta que ninguém está usando agora."""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_porta_com_alguem_escutando_e_detectada():
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as servidor:
        servidor.bind(("127.0.0.1", 0))
        servidor.listen(1)
        porta = int(servidor.getsockname()[1])
        assert _porta_ocupada("127.0.0.1", porta)


def test_porta_sem_ninguem_esta_livre():
    # a porta é obtida e liberada antes da sonda: janela mínima, mas real —
    # por isso o teste pergunta ao sistema em vez de fixar um número, que
    # poderia colidir com qualquer coisa na máquina de quem roda
    assert not _porta_ocupada("127.0.0.1", _porta_livre())
