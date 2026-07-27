"""Contrato público da Platform API v1 — geração canônica e verificação.

O contrato OpenAPI é a única porta da plataforma (docs/24, Regra 1) e por
isso é um ARTEFATO versionado: ``contracts/platform-api-v1.json``. O teste
``tests/api/test_contract.py`` falha se a superfície da API mudar sem que
o snapshot seja regenerado — mudança de contrato passa a ser um ato
intencional, revisável no diff, nunca um efeito colateral.

Para regenerar (na raiz do repositório)::

    python -m lumbra.api.contract
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

CONTRACT_RELPATH = Path("contracts") / "platform-api-v1.json"

# A superfície canônica é a do app padrão em ambiente LOCAL com persistência
# postgres: hoje os routers de chat/memória (e o Developer Console) só são
# montados quando os stores persistentes existem, então "postgres" é a
# configuração que expõe a superfície COMPLETA — e a geração não abre
# conexão alguma (engines conectam preguiçosamente; openapi() não inicia o
# kernel). Eventbus em memória pelo mesmo motivo. As variáveis são forçadas
# para que o snapshot não dependa do .env de quem gera.
#
# Registro honesto (backlog #12): a superfície da API depender do adaptador
# é um defeito perante a Regra 1 (docs/24) — um cliente contra um Nó em
# modo memória veria menos rotas. A correção (routers sempre montados,
# respondendo 501/503 quando o store não existe) fica para o P1-b.
_CANONICAL_ENV = {
    "LUMBRA_ENVIRONMENT": "local",
    "LUMBRA_PERSISTENCE": "postgres",
    "LUMBRA_EVENTBUS": "memory",
}


def _make_codegen_portable(schema: dict[str, Any]) -> dict[str, Any]:
    """Achata o ``anyOf:[string,integer]`` do ``loc`` do ValidationError.

    O ``loc`` (caminho do erro de validação) do FastAPI mistura strings e
    índices inteiros. O gerador Dart produz código INVÁLIDO para ``anyOf``
    de primitivos (uma classe ``ValidationErrorLocInner`` quebrada). Como
    ``loc`` é um detalhe de erro que clientes não consomem tipado, mapeá-lo
    para tipo livre (``{}`` = any) mantém o contrato honesto (segue aceitando
    string ou inteiro) e portável para geração de cliente. É a única
    concessão do contrato à realidade do codegen, e documentada.
    """
    try:
        loc = schema["components"]["schemas"]["ValidationError"]["properties"]["loc"]
        if isinstance(loc.get("items"), dict) and "anyOf" in loc["items"]:
            loc["items"] = {}
    except (KeyError, TypeError):
        pass
    return schema


def openapi_schema() -> dict[str, Any]:
    """Esquema OpenAPI do app padrão, gerado em configuração canônica."""
    saved = {key: os.environ.get(key) for key in _CANONICAL_ENV}
    os.environ.update(_CANONICAL_ENV)
    from lumbra.shared.config import get_settings

    get_settings.cache_clear()
    try:
        from lumbra.api.main import create_default_app

        return _make_codegen_portable(create_default_app().openapi())
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()


def canonical_json() -> str:
    """Serialização canônica: chaves ordenadas, UTF-8, newline final."""
    return json.dumps(openapi_schema(), sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def repo_root() -> Path:
    """Raiz do repositório (primeiro ancestral com pyproject.toml)."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return Path.cwd()


def write_contract() -> Path:
    """(Re)escreve o snapshot. Uso: ``python -m lumbra.api.contract``."""
    target = repo_root() / CONTRACT_RELPATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(canonical_json(), encoding="utf-8")
    return target


if __name__ == "__main__":
    write_contract()


# canário anti-truncamento
