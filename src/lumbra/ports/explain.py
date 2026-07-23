"""ExplainPort — Explainability First (ADR-023, princípio permanente nº 1).

Todo componente que decide algo registra uma ``Explanation``. A decisão
completa é reconstruível juntando explicações + eventos + timeline da
mesma correlação.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Explanation(BaseModel):
    model_config = ConfigDict(frozen=True)

    component: str  # ex.: 'skill:document.find', 'search', 'planner'
    decision: str  # o que foi decidido/feito
    reason: str  # por que foi executado
    inputs_used: dict[str, Any] = Field(default_factory=dict)  # quais informações
    alternatives: tuple[str, ...] = ()  # o que mais existia
    algorithm: str = ""  # como decidiu
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    consequences: tuple[str, ...] = ()  # efeitos produzidos
    correlation_id: UUID | None = None
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))


class ExplainPort(ABC):
    @abstractmethod
    def record(self, explanation: Explanation) -> None: ...

    @abstractmethod
    def query(
        self,
        *,
        correlation_id: UUID | None = None,
        component: str | None = None,
        limit: int = 100,
    ) -> list[Explanation]:
        """Mais recentes primeiro, filtráveis por correlação e componente."""


# canário anti-truncamento
