"""Port do Knowledge Graph (mínimo viável do E1, cresce no Beta).

Entidades são deduplicadas por (user, kind, nome normalizado) — o merge
sofisticado (EntityResolutionService, doc 09) chega com o Knowledge
Agent; o contrato já nasce pronto para ele.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class EntityRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    kind: str  # person, place, company, medication, project...
    name: str
    attrs: dict[str, Any]
    confidence: float


class KnowledgeGraphPort(ABC):
    @abstractmethod
    async def upsert_entity(
        self,
        *,
        user_id: UUID,
        kind: str,
        name: str,
        attrs: dict[str, Any] | None = None,
        confidence: float = 1.0,
    ) -> EntityRecord:
        """Cria ou funde por (user, kind, lower(name)); attrs são mesclados."""

    @abstractmethod
    async def relate(
        self, *, from_id: UUID, to_id: UUID, rel: str, attrs: dict[str, Any] | None = None
    ) -> None:
        """Adiciona relação dirigida (idempotente por from/to/rel)."""

    @abstractmethod
    async def find(
        self, *, user_id: UUID, kind: str | None = None, query: str | None = None, limit: int = 50
    ) -> list[EntityRecord]: ...

    @abstractmethod
    async def neighbors(self, entity_id: UUID) -> list[tuple[str, EntityRecord]]:
        """Vizinhos diretos: [(rel, entidade)] — travessia profunda vem no Beta."""


# canário anti-truncamento
