"""O segredo de assinatura de tokens desta instalação (P2-f.2, ADR-070).

O ``lumbra up`` se recusa a subir com o segredo de JWT de desenvolvimento, e
está certo: ele é público, está no código, e qualquer pessoa que o conheça
forja um token. Só que a instrução que vinha junto — "defina
LUMBRA_SECURITY__JWT_SECRET com 32 bytes aleatórios" — é uma tarefa de
administrador de servidor. Num aplicativo pessoal ela significa que a
Lumbra não abre na primeira execução e manda o dono aprender variável de
ambiente antes de escrever a primeira anotação.

As duas saídas óbvias são ruins. Afrouxar a checagem deixaria toda
instalação com a MESMA chave conhecida — pior que não ter autenticação,
porque parece que tem. Exigir a variável transfere ao usuário um trabalho
que a máquina faz melhor.

A saída boa é a terceira: a instalação gera o próprio segredo na primeira
partida e o guarda ao lado dos dados. Cada Lumbra passa a ter uma chave
única que ninguém — nem nós — conhece.
"""

from __future__ import annotations

import os
import platform
import secrets
from pathlib import Path

from lumbra.shared.logging import get_logger
from lumbra.shared.paths import pasta_de_dados

_log = get_logger("lumbra.segredo")

_ARQUIVO = "jwt.secret"


def caminho_do_segredo() -> Path:
    return pasta_de_dados() / _ARQUIVO


def segredo_desta_instalacao() -> str:
    """Lê o segredo local; se não existir, cria um.

    Idempotente de propósito: é chamado a cada partida, e a partida número
    mil precisa ler a MESMA chave da primeira — um segredo novo invalidaria
    todas as sessões e o usuário seria deslogado sem entender por quê.
    """
    arquivo = caminho_do_segredo()
    if arquivo.exists():
        guardado = arquivo.read_text(encoding="utf-8").strip()
        if guardado:
            return guardado

    novo = secrets.token_urlsafe(48)
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(novo, encoding="utf-8")
    _restringir(arquivo)
    _log.info("segredo_local_criado", arquivo=str(arquivo))
    return novo


def _restringir(arquivo: Path) -> None:
    """Só o dono lê.

    No Windows não fazemos nada: ``%LOCALAPPDATA%`` já é por usuário, e
    mexer em ACL daqui erraria mais do que protegeria. Em POSIX o diretório
    pessoal costuma ser legível por outros, então o modo importa.
    """
    # ver a nota em paths.py: sys.platform é resolvido estaticamente pelo
    # mypy e faria este `return` parecer código morto num dos dois sistemas
    if platform.system() == "Windows":
        return
    try:
        os.chmod(arquivo, 0o600)  # noqa: PTH101 - Path.chmod não aceita follow_symlinks aqui
    except OSError as exc:  # pragma: no cover - depende do sistema de arquivos
        _log.warning("segredo_local_sem_restricao", erro=repr(exc))


# canário anti-truncamento
