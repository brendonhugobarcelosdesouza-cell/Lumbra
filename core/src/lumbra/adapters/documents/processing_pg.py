"""ProcessingStorePort sobre PostgreSQL: estado, contexto de retomada e timeline."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from lumbra.adapters.persistence.database import Database
from lumbra.adapters.persistence.models import (
    DocumentModel,
    DocumentProcessingModel,
    DocumentTimelineModel,
    DocumentVersionModel,
)
from lumbra.domain.pipeline import PipelineContext, ProcessingState
from lumbra.ports.pipeline import ProcessingStorePort, TimelineEntry
from lumbra.shared.ids import uuid7


class PostgresProcessingStore(ProcessingStorePort):
    def __init__(self, db: Database) -> None:
        self._db = db

    async def set_state(
        self, document_id: UUID, state: ProcessingState, *, error: str | None = None
    ) -> None:
        async with self._db.session() as session:
            await session.execute(
                update(DocumentModel)
                .where(DocumentModel.id == document_id)
                .values(processing_state=state.value, error=error)
            )

    async def get_state(self, document_id: UUID) -> ProcessingState:
        async with self._db.session() as session:
            value = (
                await session.execute(
                    select(DocumentModel.processing_state).where(DocumentModel.id == document_id)
                )
            ).scalar_one()
        return ProcessingState(value)

    async def save_context(self, document_id: UUID, context: PipelineContext) -> None:
        stmt = (
            pg_insert(DocumentProcessingModel)
            .values(document_id=document_id, context=context.model_dump(mode="json"))
            .on_conflict_do_update(
                index_elements=["document_id"],
                set_={"context": context.model_dump(mode="json"), "updated_at": func.now()},
            )
        )
        async with self._db.session() as session:
            await session.execute(stmt)

    async def load_context(self, document_id: UUID) -> PipelineContext:
        async with self._db.session() as session:
            row = await session.get(DocumentProcessingModel, document_id)
        if row is None:
            return PipelineContext()
        return PipelineContext.model_validate(row.context)

    async def reset_context(self, document_id: UUID) -> None:
        async with self._db.session() as session:
            row = await session.get(DocumentProcessingModel, document_id)
            if row is not None:
                await session.delete(row)

    async def add_timeline(self, document_id: UUID, entry: TimelineEntry) -> None:
        async with self._db.session() as session:
            session.add(
                DocumentTimelineModel(
                    id=uuid7(),
                    document_id=document_id,
                    stage=entry.stage,
                    started_at=entry.started_at,
                    duration_ms=entry.duration_ms,
                    success=entry.success,
                    message=entry.message,
                    metrics=entry.metrics,
                )
            )

    async def get_timeline(self, document_id: UUID) -> list[TimelineEntry]:
        async with self._db.session() as session:
            rows = (
                (
                    await session.execute(
                        select(DocumentTimelineModel)
                        .where(DocumentTimelineModel.document_id == document_id)
                        .order_by(DocumentTimelineModel.started_at)
                    )
                )
                .scalars()
                .all()
            )
        return [
            TimelineEntry(
                stage=r.stage,
                started_at=r.started_at,
                duration_ms=r.duration_ms,
                success=r.success,
                message=r.message,
                metrics=r.metrics,
            )
            for r in rows
        ]

    async def mark_indexed(self, document_id: UUID) -> None:
        async with self._db.session() as session:
            now = func.now()
            await session.execute(
                update(DocumentModel).where(DocumentModel.id == document_id).values(indexed_at=now)
            )
            doc = await session.get(DocumentModel, document_id)
            if doc is not None:
                await session.execute(
                    update(DocumentVersionModel)
                    .where(
                        DocumentVersionModel.document_id == document_id,
                        DocumentVersionModel.version == doc.version,
                    )
                    .values(indexed_at=now)
                )


# canário anti-truncamento
