"""EventStorePort sobre PostgreSQL (events_log, doc 08) — auditoria durável."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from lumbra.adapters.persistence.database import Database
from lumbra.adapters.persistence.models import EventLogModel
from lumbra.domain.events import DomainEvent
from lumbra.ports.event_store import EventStorePort


class PostgresEventStore(EventStorePort):
    def __init__(self, db: Database) -> None:
        self._db = db

    async def append(self, event: DomainEvent) -> None:
        stmt = (
            pg_insert(EventLogModel)
            .values(
                id=event.event_id,
                user_id=event.user_id,
                type=event.type,
                schema_version=event.schema_version,
                correlation_id=event.correlation_id,
                causation_id=event.causation_id,
                producer=event.producer,
                payload=event.payload,
                occurred_at=event.occurred_at,
            )
            .on_conflict_do_nothing(index_elements=["id"])  # idempotência por event_id
        )
        async with self._db.session() as session:
            await session.execute(stmt)

    async def read(
        self,
        *,
        event_types: tuple[str, ...] | None = None,
        user_id: UUID | None = None,
        since: datetime | None = None,
        limit: int = 1000,
    ) -> list[DomainEvent]:
        stmt = select(EventLogModel).order_by(EventLogModel.occurred_at).limit(limit)
        if event_types is not None:
            stmt = stmt.where(EventLogModel.type.in_(event_types))
        if user_id is not None:
            stmt = stmt.where(EventLogModel.user_id == user_id)
        if since is not None:
            stmt = stmt.where(EventLogModel.occurred_at >= since)
        async with self._db.session() as session:
            rows = (await session.execute(stmt)).scalars().all()
        return [
            DomainEvent(
                event_id=r.id,
                type=r.type,
                schema_version=r.schema_version,
                occurred_at=r.occurred_at,
                user_id=r.user_id,
                correlation_id=r.correlation_id or r.id,
                causation_id=r.causation_id,
                producer=r.producer,
                payload=r.payload,
            )
            for r in rows
        ]


# canário anti-truncamento
