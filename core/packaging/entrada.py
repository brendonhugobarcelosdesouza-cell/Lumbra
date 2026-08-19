"""Ponto de entrada do Nó congelado.

Existe separado do ``lumbra.cli.main`` por causa de duas coisas que só
importam quando o Nó vira um executável.

A primeira é uma armadilha do Windows: um executável congelado que cria
processos filhos precisa chamar ``freeze_support()`` ANTES de qualquer
outra coisa. Sem isso, cada subprocesso reexecuta o programa inteiro do
começo — e o resultado é uma bomba de garfo, com Nós nascendo sem parar
até a máquina engasgar. O Nó cria filhos: o ``pg_ctl`` que sobe e desliga
o Postgres.

A segunda é o log. Rodando no terminal, quem falha aparece na tela.
Lançado pelo app, o Nó escreve num cano que ninguém guarda — e a única
pista de uma falha some junto com o processo. Foi assim que uma exceção
não tratada chegou até o usuário como oito linhas truncadas num quadro
vermelho, com o traceback perdido. Um programa instalado que falha precisa
deixar rastro.
"""

import multiprocessing
import sys
from contextlib import suppress
from typing import Any, TextIO

_LIMITE_DO_LOG = 2 * 1024 * 1024  # 2 MB: o suficiente para várias partidas


class _Duplo:
    """Escreve nos dois lugares: no cano de quem chamou e no arquivo.

    Continua alimentando a saída padrão porque o app lê dali para mostrar o
    motivo da falha na hora — o arquivo é para depois, quando alguém for
    entender o que houve.
    """

    def __init__(self, original: TextIO, arquivo: TextIO) -> None:
        self._original = original
        self._arquivo = arquivo

    def write(self, texto: str) -> int:
        # o log nunca pode derrubar aquilo que ele observa: disco cheio,
        # arquivo removido no meio da execucao, permissao perdida - nada
        # disso justifica matar o No
        with suppress(Exception):
            self._arquivo.write(texto)
            self._arquivo.flush()
        return self._original.write(texto)

    def flush(self) -> None:
        with suppress(Exception):
            self._arquivo.flush()
        self._original.flush()

    def __getattr__(self, nome: str) -> Any:
        return getattr(self._original, nome)


def main() -> int:
    multiprocessing.freeze_support()
    # importado da CLI em vez de copiado: esta função já existiu AQUI e só
    # aqui, e o resultado foi o `lumbra` do repositório — que entra por
    # `[project.scripts]` e nunca passa por este arquivo — seguir cuspindo
    # "produ??o" na tela de erro do app. Uma correção só vale onde ela roda.
    from lumbra.cli.main import falar_utf8
    from lumbra.cli.main import main as cli

    falar_utf8()
    _guardar_o_que_dizemos()
    return int(cli())


def _guardar_o_que_dizemos() -> None:
    """Duplica saída e erro para ``<pasta de dados>/logs/no.log``.

    Só quando congelado: no repositório o terminal já guarda, e um arquivo
    de log a mais só atrapalharia quem desenvolve.
    """
    if not getattr(sys, "frozen", False):
        return
    try:
        from lumbra.shared.paths import pasta_de_dados

        destino = pasta_de_dados() / "logs"
        destino.mkdir(parents=True, exist_ok=True)
        arquivo = destino / "no.log"
        # corta pela raiz em vez de rotacionar: aqui o que importa e a
        # ULTIMA partida, e um esquema de rotacao seria peso sem uso
        if arquivo.exists() and arquivo.stat().st_size > _LIMITE_DO_LOG:
            arquivo.unlink()
        aberto = arquivo.open("a", encoding="utf-8", errors="replace")
    except Exception:  # sem permissão, disco cheio: seguimos sem arquivo
        return
    aberto.write(f"\n{'=' * 60}\nlumbra {' '.join(sys.argv[1:])}\n{'=' * 60}\n")
    sys.stdout = _Duplo(sys.stdout, aberto)
    sys.stderr = _Duplo(sys.stderr, aberto)


if __name__ == "__main__":
    sys.exit(main())


# canário anti-truncamento
