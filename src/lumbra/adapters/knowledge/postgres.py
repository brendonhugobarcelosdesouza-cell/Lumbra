"""KnowledgeGraphPort sobre PostgreSQL (ADR-006: grafo relacional)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from lumbra.adapters.persistence.database import Database
from lumbra.adapters.persistence.models import EntityModel, EntityRelationModel
from lumbra.ports.knowledge_graph import EntityRecord, KnowledgeGraphPort
from lumbra.shared.ids import uuid7


def _to_domain(row: EntityModel) -> EntityRecord:
    return EntityRecord(
        id=row.id, kind=row.kind, name=row.name, attrs=row.attrs, confidence=row.confidence
    )


class PostgresKnowledgeGraph(KnowledgeGraphPort):
    def __init__(self, db: Database) -> None:
        self._db = db

    async def upsert_entity(
        self,
        *,
        user_id: UUID,
        kind: str,
        name: str,
        attrs: dict[str, Any] | None = None,
        confidence: float = 1.0,
    ) -> EntityRecord:
        async with self._db.session() as session:
            existing = (
                await session.execute(
                    select(EntityModel).where(
                        EntityModel.user_id == user_id,
                        EntityModel.kind == kind,
                        func.lower(EntityModel.name) == name.strip().lower(),
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                existing.attrs = {**existing.attrs, **(attrs or {})}  # merge de atributos
                existing.confidence = max(existing.confidence, confidence)
                await session.flush()
                await session.refresh(existing)
                return _to_domain(existing)

            row = EntityModel(
                id=uuid7(),
                user_id=user_id,
                kind=kind,
                name=name.strip(),
                attrs=attrs or {},
                confidence=confidence,
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            return _to_domain(row)

    async def relate(
        self, *, from_id: UUID, to_id: UUID, rel: str, attrs: dict[str, Any] | None = None
    ) -> None:
        async with self._db.session() as session:
            existing = (
                await session.execute(
                    select(EntityRelationModel).where(
                        EntityRelationModel.from_id == from_id,
                        EntityRelationModel.to_id == to_id,
                        EntityRelationModel.rel == rel,
                    )
                )
            ).scalar_one_or_none()
            if existing is None:  # idempotência por (from, to, rel)
                session.add(
                    EntityRelationModel(
                        id=uuid7(), from_id=from_id, to_id=to_id, rel=rel, attrs=attrs or {}
                    )
                )

    async def find(
        self, *, user_id: UUID, kind: str | None = None, query: str | None = None, limit: int = 50
    ) -> list[EntityRecord]:
        stmt = select(EntityModel).where(EntityModel.user_id == user_id).limit(limit)
        if kind is not None:
            stmt = stmt.where(EntityModel.kind == kind)
        if query is not None:
            stmt = stmt.where(EntityModel.name.ilike(f"%{query}%"))
        async with self._db.session() as session:
            rows = (await session.execute(stmt)).scalars().all()
        return [_to_domain(r) for r in rows]

    async def neighbors(self, entity_id: UUID) -> list[tuple[str, EntityRecord]]:
        async with self._db.session() as session:
            out = await session.execute(
                select(EntityRelationModel.rel, EntityModel)
                .join(EntityModel, EntityModel.id == EntityRelationModel.to_id)
                .where(EntityRelationModel.from_id == entity_id)
            )
            inbound = await session.execute(
                select(EntityRelationModel.rel, EntityModel)
                .join(EntityModel, EntityModel.id == EntityRelationModel.from_id)
                .where(EntityRelationModel.to_id == entity_id)
            )
            rows = list(out.all()) + list(inbound.all())
        return [(rel, _to_domain(entity)) for rel, entity in rows]


# canário anti-truncamento
