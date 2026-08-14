"""Onde a Lumbra guarda os dados do usuário.

Enquanto o Nó era um projeto rodado do repositório, ``./data`` bastava: o
diretório atual era sempre o mesmo. Instalado, isso vira uma armadilha — o
banco nasceria dentro de ``Program Files`` (sem permissão de escrita) ou na
pasta de onde o atalho foi clicado, e "onde estão meus dados?" não teria
resposta. Um programa que guarda dados pessoais precisa de um endereço fixo.
"""

from __future__ import annotations

import os
import platform
from pathlib import Path

_NOME = "Lumbra"

# ``platform.system()`` e não ``sys.platform``: o mypy resolve ``sys.platform``
# ESTATICAMENTE, para o sistema de quem está checando. Numa máquina Windows
# ele conclui que os ramos de macOS e Linux são inalcançáveis; no CI (Linux),
# que o ramo do Windows é. Justamente num arquivo cuja razão de existir é
# diferenciar sistemas, isso transforma o modo estrito em ruído.
_SISTEMA = platform.system()


def pasta_de_dados() -> Path:
    """A pasta de dados do usuário, segundo a convenção de cada sistema.

    ``LUMBRA_DATA_DIR`` vence tudo: é como se põe a Lumbra num disco externo,
    num volume cifrado ou numa pasta sincronizada — decisão de quem é dono
    dos dados, não nossa.
    """
    definido = os.environ.get("LUMBRA_DATA_DIR")
    if definido:
        return Path(definido).expanduser()

    if _SISTEMA == "Windows":
        # LOCALAPPDATA e não APPDATA: em domínio corporativo, APPDATA é
        # sincronizado com o servidor a cada login. Um diretório de Postgres
        # viajando pela rede seria lento e corromperia com dois logins.
        base = os.environ.get("LOCALAPPDATA")
        raiz = Path(base) if base else Path.home() / "AppData" / "Local"
        return raiz / _NOME
    if _SISTEMA == "Darwin":
        return Path.home() / "Library" / "Application Support" / _NOME

    # Linux e afins: XDG. Minúsculo porque é a convenção lá.
    base = os.environ.get("XDG_DATA_HOME")
    raiz = Path(base) if base else Path.home() / ".local" / "share"
    return raiz / _NOME.lower()


def pasta_do_banco() -> Path:
    """Diretório de dados do Postgres embutido (P2-f.1)."""
    return pasta_de_dados() / "postgres"


# canário anti-truncamento
