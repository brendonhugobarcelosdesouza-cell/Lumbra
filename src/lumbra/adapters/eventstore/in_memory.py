"""Event Store in-memory (testes e desktop lite).

Adaptador PostgreSQL (`events_log` particionado, doc 08) chega na etapa
de persistência, atrás do mesmo port.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from lumbra.domain.events import DomainEvent
from lumbra.ports.event_store import EventStorePort


class InMemoryEventStore(EventStorePort):
    def __init__(self) -> None:
        self._log: list[DomainEvent] = []
        self._seen: set[UUID] = set()

    async def append(self, event: DomainEvent) -> None:
        if event.event_id in self._seen:  # idempotência por event_id
            return
        self._seen.add(event.event_id)
        self._log.append(event)

    async def read(
        self,
        *,
        event_types: tuple[str, ...] | None = None,
        user_id: UUID | None = None,
        since: datetime | None = None,
        limit: int = 1000,
    ) -> list[DomainEvent]:
        result = [
            e
            for e in self._log
            if (event_types is None or e.type in event_types)
            and (user_id is None or e.user_id == user_id)
            and (since is None or e.occurred_at >= since)
        ]
        return result[:limit]
