# -*- mode: python ; coding: utf-8 -*-
"""Congela o Nó num executável que não exige Python instalado (P2-f.3).

O Python é a parte fácil. O difícil são as coisas que NÃO são código e que
o empacotador não tem como adivinhar sozinho — e o sintoma de esquecer
qualquer uma delas é sempre o mesmo, e cruel: funciona na máquina de quem
compilou, quebra na de quem instalou.

São quatro, e cada uma quebra de um jeito diferente:

* o **PostgreSQL** que vem dentro do ``pgserver`` (~40 MB de binários).
  Sem ele: "não foi possível conectar ao banco", num modo cujo nome é
  justamente "embutido";
* as **migrações do Alembic**, que são arquivos ``.py`` carregados pelo
  CAMINHO, não importados. O empacotador ignora ``.py`` que ninguém
  importa; sem eles, o banco sobe vazio e a primeira consulta reclama de
  tabela inexistente;
* o **onnxruntime** do ``fastembed``, cujas bibliotecas nativas não
  aparecem em nenhum ``import``. Sem elas: sem busca semântica;
* os **adaptadores** escolhidos por configuração. O composition root
  importa todos no topo, então estes o empacotador enxerga — mas é aqui
  que a lista mora, caso um dia passem a ser carregados por nome.

Modo **onedir**, e não onefile, de propósito: onefile extrai o pacote
inteiro num diretório temporário a CADA partida. Com o PostgreSQL junto,
isso são centenas de MB copiados toda vez que a pessoa abre a Lumbra.
"""

from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

CORE = Path(SPECPATH).parent  # noqa: F821 - SPECPATH é injetado pelo PyInstaller
PACOTE = CORE / "src" / "lumbra"

datas = []
binaries = []
hiddenimports = []

# 1. PostgreSQL 16 + pgvector, inteiros.
datas += collect_data_files("pgserver", include_py_files=False)
binaries += collect_dynamic_libs("pgserver")

# 2. Migrações: arquivos .py lidos do disco pelo Alembic, nunca importados.
#    Vão como DADOS, no mesmo lugar relativo que `_config_alembic` procura.
datas += [
    (str(PACOTE / "adapters" / "persistence" / "migrations"), "lumbra/adapters/persistence/migrations"),
]
datas += collect_data_files("alembic")  # templates do próprio Alembic

# 3. Embeddings locais.
datas += collect_data_files("fastembed")
binaries += collect_dynamic_libs("onnxruntime")
hiddenimports += collect_submodules("onnxruntime")

# 4. O que é escolhido em tempo de execução.
hiddenimports += collect_submodules("uvicorn")
hiddenimports += collect_submodules("lumbra.adapters")
hiddenimports += ["asyncpg", "pgvector.sqlalchemy", "argon2", "email_validator"]

analise = Analysis(  # noqa: F821
    [str(CORE / "packaging" / "entrada.py")],
    pathex=[str(CORE / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # o Nó não tem interface gráfica: tudo isto entraria a passeio, e
    # cada MB a mais é um MB no instalador de alguém
    excludes=["tkinter", "matplotlib", "IPython", "pytest", "notebook"],
    noarchive=False,
)

pyz = PYZ(analise.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    analise.scripts,
    [],
    exclude_binaries=True,
    name="lumbra",
    console=True,  # o app consome esta saída como log do Nó (ADR-067)
    debug=False,
    strip=False,
    upx=False,  # UPX quebra DLLs assinadas e assusta antivírus
)

col = COLLECT(  # noqa: F821
    exe,
    analise.binaries,
    analise.datas,
    strip=False,
    upx=False,
    name="no",  # o app procura por uma pasta `no/` ao seu lado (ADR-067)
)
