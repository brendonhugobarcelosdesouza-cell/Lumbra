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
    _falar_utf8()
    from lumbra.cli.main import main as cli

    return int(cli())


def _falar_utf8() -> None:
    """O Nó escreve em UTF-8, sempre.

    Sem isto, o Windows usa a página de código do console (cp850 por aqui) e
    a saída chega assim: "índices" vira "Ýndices", "revisão" vira "revisÒo".
    Parece cosmético, e é enganoso por dois motivos: o app mostra a saída do
    Nó como log, e um diagnóstico ilegível é um diagnóstico que ninguém lê.
    """
    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    sys.exit(main())
