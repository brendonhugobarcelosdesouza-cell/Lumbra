"""Domínio da memória em cinco camadas (doc 08/09; backlog E1-05/06).

Camadas (``kind``): temporary (curto prazo, expira), episodic (eventos
vividos), semantic (fatos consolidados), procedural (como fazer),
permanent (fixadas pelo usuário — nunca decaem).

A matemática de decaimento é PURA e vive aqui: força efetiva de uma
memória = importância x meia-vida exponencial desde o último acesso.
Acessar uma memória a fortalece (reconsolidação); memórias fracas são
arquivadas pela consolidação — nunca apagadas silenciosamente (quem
apaga é o usuário, princípio de controle total).
"""

from __future__ import annotations

import math
from datetime import datetime
from enum import StrEnum

# meia-vida padrão por camada, em dias (permanent nunca decai)
HALF_LIFE_DAYS: dict[str, float] = {
    "temporary": 1.0,
    "episodic": 30.0,
    "semantic": 180.0,
    "procedural": 365.0,
    "permanent": math.inf,
}

ACCESS_BOOST = 0.05  # reforço de importância a cada recall
ARCHIVE_THRESHOLD = 0.05  # força abaixo disso → arquivada na consolidação


class MemoryKind(StrEnum):
    TEMPORARY = "temporary"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"
    PERMANENT = "permanent"


def decay_factor(*, kind: str, last_accessed_at: datetime, now: datetime) -> float:
    """Fator de decaimento em [0, 1]: 1.0 no acesso, 0.5 após uma meia-vida."""
    half_life = HALF_LIFE_DAYS.get(kind, 30.0)
    if math.isinf(half_life):
        return 1.0
    days = max(0.0, (now - last_accessed_at).total_seconds() / 86400.0)
    return float(0.5 ** (days / half_life))


def effective_strength(
    *, importance: float, kind: str, last_accessed_at: datetime, now: datetime
) -> float:
    """Força efetiva = importância x decaimento. Sempre em [0, 1]."""
    clamped = min(1.0, max(0.0, importance))
    return clamped * decay_factor(kind=kind, last_accessed_at=last_accessed_at, now=now)


def boosted_importance(importance: float, *, boost: float = ACCESS_BOOST) -> float:
    """Reconsolidação: recall reforça a importância, saturando em 1.0."""
    return min(1.0, max(0.0, importance) + boost)


# canário anti-truncamento
