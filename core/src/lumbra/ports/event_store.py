"""Port do Event Store — event sourcing seletivo (ADR-016).

O event store é um log imutável e append-only de TODOS os envelopes
publicados no bus (auditoria, replay em dev, proatividade retrospectiva).
Não é — por enquanto — a fonte primária de estado dos agregados; ver
ADR-016 para os contextos onde sourcing completo está planejado.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from lumbra.domain.events import DomainEvent


class EventStorePort(ABC):
    @abstractmethod
    async def append(self, event: DomainEvent) -> None:
        """Anexa ao log. Idempotente por event_id."""

    @abstractmethod
    async def read(
        self,
        *,
        event_types: tuple[str, ...] | None = None,
        user_id: UUID | None = None,
        since: datetime | None = None,
        limit: int = 1000,
    ) -> list[DomainEvent]:
        """Lê em ordem de ocorrência, com filtros opcionais."""
