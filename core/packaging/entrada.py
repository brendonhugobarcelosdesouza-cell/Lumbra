"""Ponto de entrada do Nó congelado.

Existe separado do ``lumbra.cli.main`` por causa de uma armadilha do
Windows: um executável congelado que cria processos filhos precisa chamar
``freeze_support()`` ANTES de qualquer outra coisa. Sem isso, cada
subprocesso reexecuta o programa inteiro do começo — e o resultado é uma
bomba de garfo, com Nós nascendo sem parar até a máquina engasgar.

O Nó cria filhos: o ``pg_ctl`` que sobe e desliga o Postgres.
"""

import multiprocessing
import sys


def main() -> int:
    multiprocessing.freeze_support()
    from lumbra.cli.main import main as cli

    return int(cli())


if __name__ == "__main__":
    sys.exit(main())
