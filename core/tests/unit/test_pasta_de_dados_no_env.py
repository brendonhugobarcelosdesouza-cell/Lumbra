"""`LUMBRA_DATA_DIR` no `.env` precisa valer.

Descoberto usando o produto. Escrevi `LUMBRA_DATA_DIR=C:\\dev\\lumbra\\.dados`
no `.env` do repositório para separar o banco de desenvolvimento do banco da
Lumbra instalada — e o Nó de desenvolvimento subiu apontando para a pasta
instalada assim mesmo, foi disputar o banco com o outro Nó e morreu.

A causa: `pasta_de_dados()` lê a variável de `os.environ`, não das
configurações. E por bom motivo — ela é consultada por código que não pode
depender de `Settings`, que por sua vez depende dela para achar o `.env`
quando congelado. Mas o efeito era uma linha de configuração que não fazia
NADA e não reclamava.

É a mesma família dos outros erros desta base: **a coisa se apresentou como
funcionando**. Nenhum aviso, nenhum erro — só um caminho diferente no log,
que ninguém lê quando tudo parece bem.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from lumbra.cli.main import _ja_configurado, exportar_pasta_de_dados


@pytest.fixture(autouse=True)
def _sem_heranca(monkeypatch):
    """Cada caso começa sem a variável — senão o teste mediria o ambiente."""
    monkeypatch.delenv("LUMBRA_DATA_DIR", raising=False)


def _com_env(tmp_path: Path, monkeypatch, conteudo: str) -> None:
    (tmp_path / ".env").write_text(conteudo, encoding="utf-8")
    monkeypatch.chdir(tmp_path)


def test_le_a_pasta_do_env(tmp_path, monkeypatch):
    _com_env(tmp_path, monkeypatch, "LUMBRA_DATA_DIR=D:\\lumbra\\dados\n")
    exportar_pasta_de_dados()
    assert os.environ["LUMBRA_DATA_DIR"] == "D:\\lumbra\\dados"


def test_o_ambiente_vence_o_arquivo(tmp_path, monkeypatch):
    # variável no ambiente é a forma mais explícita das duas: quem a definiu
    # está sobrepondo de propósito, provavelmente para uma execução só
    monkeypatch.setenv("LUMBRA_DATA_DIR", "E:\\explicito")
    _com_env(tmp_path, monkeypatch, "LUMBRA_DATA_DIR=D:\\do-arquivo\n")
    exportar_pasta_de_dados()
    assert os.environ["LUMBRA_DATA_DIR"] == "E:\\explicito"


def test_sem_a_linha_nao_inventa_nada(tmp_path, monkeypatch):
    _com_env(tmp_path, monkeypatch, "LUMBRA_PERSISTENCE=embedded\n")
    exportar_pasta_de_dados()
    assert "LUMBRA_DATA_DIR" not in os.environ


def test_sem_env_nenhum_nao_quebra(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    exportar_pasta_de_dados()
    assert "LUMBRA_DATA_DIR" not in os.environ


def test_aspas_e_espacos_nao_entram_no_caminho(tmp_path, monkeypatch):
    # um caminho com aspas sobrando vira uma pasta com aspas no nome, e o
    # Postgres falha lá adiante com um erro que não menciona o `.env`
    _com_env(tmp_path, monkeypatch, '  LUMBRA_DATA_DIR = "D:\\com aspas"  \n')
    exportar_pasta_de_dados()
    assert os.environ["LUMBRA_DATA_DIR"] == "D:\\com aspas"


def test_espacos_valem_para_qualquer_chave(tmp_path, monkeypatch):
    """A mesma correção precisa valer para `_ja_configurado`.

    O leitor de `.env` da CLI é um só, e é o mesmo que decide se o comando
    pode aplicar um padrão. Enquanto ele não reconhecia `CHAVE = valor`, o
    `lumbra up` podia sobrescrever uma escolha explícita do usuário só porque
    ela tinha um espaço antes do `=` — que é justamente o bug que a docstring
    de `_ja_configurado` diz ter vindo consertar.
    """
    _com_env(tmp_path, monkeypatch, "LUMBRA_ENVIRONMENT = local\n")
    assert _ja_configurado("LUMBRA_ENVIRONMENT")
    assert not _ja_configurado("LUMBRA_PERSISTENCE")


def test_comentario_nao_e_configuracao(tmp_path, monkeypatch):
    _com_env(tmp_path, monkeypatch, "# LUMBRA_DATA_DIR=D:\\comentado\n")
    exportar_pasta_de_dados()
    assert "LUMBRA_DATA_DIR" not in os.environ


def test_a_pasta_de_dados_passa_a_seguir_o_env(tmp_path, monkeypatch):
    """O teste que importa: não basta exportar, tem que MUDAR o destino.

    A função podia estar perfeita e `pasta_de_dados()` seguir devolvendo a
    pasta padrão — é a mesma desconexão que deixou a correção de UTF-8 sem
    efeito por um caminho inteiro (adendo do ADR-073).
    """
    from lumbra.shared.paths import pasta_de_dados

    _com_env(tmp_path, monkeypatch, f"LUMBRA_DATA_DIR={tmp_path / 'meus-dados'}\n")
    exportar_pasta_de_dados()
    assert pasta_de_dados() == tmp_path / "meus-dados"
