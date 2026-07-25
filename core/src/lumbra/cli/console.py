"""Saída de terminal: cores e símbolos sem dependência extra.

Cores são um detalhe de apresentação, e uma dependência a menos é uma
coisa a menos para dar errado numa instalação limpa. Respeita NO_COLOR e
desliga sozinho quando a saída não é um terminal (pipe, arquivo, CI).
"""

from __future__ import annotations

import os
import sys

_ATIVO = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None

_CORES = {
    "verde": "\033[32m",
    "amarelo": "\033[33m",
    "vermelho": "\033[31m",
    "azul": "\033[34m",
    "cinza": "\033[90m",
    "negrito": "\033[1m",
}
_RESET = "\033[0m"


def cor(texto: str, nome: str) -> str:
    if not _ATIVO or nome not in _CORES:
        return texto
    return f"{_CORES[nome]}{texto}{_RESET}"


def titulo(texto: str) -> None:
    print(f"\n{cor(texto, 'negrito')}")


def linha(texto: str = "") -> None:
    print(texto)


def erro(texto: str) -> None:
    print(cor(f"erro: {texto}", "vermelho"), file=sys.stderr)


# largura fixa para as colunas alinharem no relatório
SIMBOLOS = {"ok": " OK  ", "warn": "AVISO", "fail": "FALHA", "skip": "  -  "}
CORES_STATUS = {"ok": "verde", "warn": "amarelo", "fail": "vermelho", "skip": "cinza"}


def silenciar_logs(verbose: bool = False) -> None:
    """Numa CLI o relatório É a saída: log estruturado de biblioteca só
    atrapalha quem está tentando entender o que está errado. Com
    --verbose tudo volta, para depurar o próprio diagnóstico."""
    import logging
    import warnings

    from lumbra.shared.logging import configure_logging

    if verbose:
        return
    logging.disable(logging.INFO)
    warnings.filterwarnings("ignore")
    os.environ.setdefault("LUMBRA_OBSERVABILITY__LOG_LEVEL", "ERROR")
    # o structlog tem configuração própria: silenciá-lo exige reconfigurar,
    # não basta mexer no logging da biblioteca padrão
    configure_logging(level="ERROR", json_output=False)


# canário anti-truncamento
