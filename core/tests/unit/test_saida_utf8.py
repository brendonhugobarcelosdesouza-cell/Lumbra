"""O Nó fala UTF-8 pelos DOIS caminhos de entrada.

Esta correção já existia e já estava certa — e mesmo assim o desenvolvedor
via `produ??o` na tela de erro do app. Ela morava em `packaging/entrada.py`,
que só roda no executável congelado; o `lumbra` do repositório entra por
`[project.scripts]` direto em `lumbra.cli.main:main` e nunca passava por lá.

É a mesma armadilha do script de build que verificava `core/src` e esquecia
`core/packaging`: a correção parcial dá a mesma sensação de resolvido e não
entrega o mesmo resultado. Por isso o teste olha os dois caminhos, e não a
função isolada.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from lumbra.cli.main import falar_utf8


class _FluxoQueAnota:
    """Finge ser stdout: guarda como foi reconfigurado."""

    def __init__(self) -> None:
        self.reconfigurado: dict[str, Any] = {}

    def reconfigure(self, **kwargs: Any) -> None:
        self.reconfigurado = kwargs


def test_reconfigura_saida_e_erro_para_utf8(monkeypatch) -> None:
    saida, erro = _FluxoQueAnota(), _FluxoQueAnota()
    monkeypatch.setattr(sys, "stdout", saida)
    monkeypatch.setattr(sys, "stderr", erro)

    falar_utf8()

    for fluxo in (saida, erro):
        assert fluxo.reconfigurado["encoding"] == "utf-8"
        # `replace` e não `strict`: um byte estranho no log de uma falha não
        # pode virar uma segunda falha em cima da primeira
        assert fluxo.reconfigurado["errors"] == "replace"


def test_fluxo_sem_reconfigure_nao_quebra(monkeypatch) -> None:
    # sob PyInstaller a saída às vezes é um objeto simples, sem `reconfigure`
    monkeypatch.setattr(sys, "stdout", object())
    monkeypatch.setattr(sys, "stderr", object())
    falar_utf8()  # não levanta


def test_o_arranque_congelado_usa_a_mesma_funcao() -> None:
    """O executável congelado não pode ter a própria cópia.

    Duas cópias divergem, e a que fica para trás é sempre a que ninguém está
    olhando. Se um dia `entrada.py` voltar a definir a sua, este teste cai.
    """
    entrada = Path(__file__).resolve().parents[2] / "packaging" / "entrada.py"
    texto = entrada.read_text(encoding="utf-8")
    assert "def _falar_utf8" not in texto, (
        "packaging/entrada.py voltou a definir a própria versão; "
        "importe `falar_utf8` de lumbra.cli.main"
    )
    assert "falar_utf8" in texto, "o arranque congelado parou de chamar falar_utf8"
