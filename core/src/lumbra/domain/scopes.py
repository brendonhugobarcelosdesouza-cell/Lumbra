"""Escopos: a álgebra de permissão da plataforma (ADRs 045 e 047).

Domínio puro (sem I/O). Um escopo é uma capacidade nomeada que o usuário
concede a um dispositivo ou plugin, no formato ``recurso:ação`` com
qualificadores opcionais (``recurso:ação:alvo``), separados por ``:``.

Exemplos (ADR-047): ``memory:read``, ``skills:invoke:chat.send``,
``events:subscribe:document.*``.

Um escopo CONCEDIDO pode ser mais amplo que o EXIGIDO por uma operação; a
função central é ``concede(concedidos, exigido)``, que responde "este
conjunto de concessões autoriza esta operação?". Curingas de concessão:

* ``*`` sozinho como último segmento — cobre um-ou-mais segmentos mais
  profundos: ``memory:*`` cobre ``memory:read`` e ``memory:read:x``.
* ``*`` sozinho num segmento interno — cobre exatamente um segmento:
  ``*:read`` cobre ``memory:read``.
* sufixo ``.*`` num segmento — prefixo pontilhado: ``document.*`` cobre
  ``document.created`` (usado em nomes de evento).
* ``*`` isolado como escopo inteiro — concede tudo (administrador).

A verificação é sempre least-privilege: na dúvida, NÃO concede.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

# um segmento é '*' isolado, um nome (letras/números/_/-/.) ou um prefixo
# pontilhado terminado em '.*' (ex.: 'document.*')
_SEGMENTO = re.compile(r"^(?:\*|[a-z0-9_][a-z0-9_.-]*\*?)$")


class InvalidScopeError(ValueError):
    def __init__(self, scope: str) -> None:
        super().__init__(
            f"escopo inválido: {scope!r} (esperado 'recurso:ação[:alvo]', ex.: 'memory:read')"
        )


def parse_scope(scope: str) -> tuple[str, ...]:
    """Valida e quebra um escopo em segmentos. Levanta InvalidScopeError."""
    if not scope or scope.startswith(":") or scope.endswith(":"):
        raise InvalidScopeError(scope)
    segmentos = tuple(scope.split(":"))
    if any(not _SEGMENTO.match(seg) for seg in segmentos):
        raise InvalidScopeError(scope)
    return segmentos


def scope_cobre(concedido: str, exigido: str) -> bool:
    """Um único escopo concedido cobre o exigido?"""
    g = parse_scope(concedido)
    r = parse_scope(exigido)
    for i, seg in enumerate(g):
        if seg == "*":
            if i == len(g) - 1:
                # '*' final: cobre um-ou-mais segmentos restantes
                return len(r) > i
            # '*' interno: cobre exatamente um segmento (precisa existir)
            if i >= len(r):
                return False
            continue
        if i >= len(r):
            return False
        if seg.endswith(".*"):
            if not r[i].startswith(seg[:-1]):  # 'document.*' -> prefixo 'document.'
                return False
        elif r[i] != seg:
            return False
    # sem '*' final: casamento exato de estrutura
    return len(r) == len(g)


def concede(concedidos: Iterable[str], exigido: str) -> bool:
    """O conjunto de escopos concedidos autoriza a operação exigida?"""
    return any(scope_cobre(c, exigido) for c in concedidos)


@dataclass(frozen=True)
class ScopeSet:
    """Conjunto imutável de escopos concedidos, validado na construção.

    É o objeto que um dispositivo ou plugin carrega. Duplicatas são
    colapsadas; a ordem não importa para a verificação. Escopo malformado
    levanta ``InvalidScopeError`` direto (erro de domínio), não embrulhado."""

    scopes: frozenset[str]

    def __post_init__(self) -> None:
        normalizado = frozenset(self.scopes)
        for scope in normalizado:
            parse_scope(scope)  # levanta InvalidScopeError se malformado
        object.__setattr__(self, "scopes", normalizado)

    def concede(self, exigido: str) -> bool:
        return concede(self.scopes, exigido)

    def __iter__(self) -> Iterator[str]:
        return iter(sorted(self.scopes))


# ---------------------------------------------------------------- catálogo
# Escopos que as rotas da Platform API exigem. Fonte única para o Core (o
# guard de rota no P1-b.4 referencia estas constantes) e para o pareamento
# (o que um dispositivo/plugin pode pedir). Um plugin pode declarar escopos
# fora deste catálogo desde que bem-formados; estes são os que a plataforma
# própria conhece e documenta.

SCOPE_CHAT_READ = "chat:read"
SCOPE_CHAT_WRITE = "chat:write"
SCOPE_MEMORY_READ = "memory:read"
SCOPE_MEMORY_WRITE = "memory:write"
SCOPE_MEMORY_DELETE = "memory:delete"
SCOPE_SKILLS_READ = "skills:read"
SCOPE_SKILLS_INVOKE = "skills:invoke"
SCOPE_SYSTEM_READ = "system:read"
SCOPE_DEVICES_READ = "devices:read"
SCOPE_DEVICES_WRITE = "devices:write"
SCOPE_EVENTS_SUBSCRIBE = "events:subscribe"

CATALOGO: frozenset[str] = frozenset(
    {
        SCOPE_CHAT_READ,
        SCOPE_CHAT_WRITE,
        SCOPE_MEMORY_READ,
        SCOPE_MEMORY_WRITE,
        SCOPE_MEMORY_DELETE,
        SCOPE_SKILLS_READ,
        SCOPE_SKILLS_INVOKE,
        SCOPE_SYSTEM_READ,
        SCOPE_DEVICES_READ,
        SCOPE_DEVICES_WRITE,
        SCOPE_EVENTS_SUBSCRIBE,
    }
)


# canário anti-truncamento
