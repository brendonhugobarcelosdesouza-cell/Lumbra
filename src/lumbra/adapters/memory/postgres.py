"""MemoryStorePort sobre PostgreSQL (pgvector + tsvector)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Float, case, func, select, update

from lumbra.adapters.persistence.database import Database
from lumbra.adapters.persistence.models import MemoryItemModel
from lumbra.ports.memory import MemoryItem, MemoryNotFoundError, MemoryStorePort
from lumbra.shared.ids import uuid7


def _to_item(row: MemoryItemModel) -> MemoryItem:
    return MemoryItem(
        id=row.id,
        user_id=row.user_id,
        kind=row.kind,
        content=row.content,
        importance=row.importance,
        source_ref=dict(row.source_ref or {}),
        access_count=row.access_count,
        expires_at=row.expires_at,
        last_accessed_at=row.last_accessed_at,
        created_at=row.created_at,
        archived_at=row.archived_at,
    )


class PostgresMemoryStore(MemoryStorePort):
    def __init__(self, db: Database) -> None:
        self._db = db

    async def add(
        self,
        *,
        user_id: UUID,
        kind: str,
        content: str,
        importance: float,
        embedding: tuple[float, ...] | None,
        source_ref: dict[str, Any],
        expires_at: datetime | None,
    ) -> MemoryItem:
        now = datetime.now(tz=UTC)
        row = MemoryItemModel(
            id=uuid7(),
            user_id=user_id,
            kind=kind,
            content=content,
            importance=importance,
            source_ref=source_ref,
            access_count=0,
            embedding=list(embedding) if embedding is not None else None,
            expires_at=expires_at,
            last_accessed_at=now,
            created_at=now,
            archived_at=None,
        )
        async with self._db.session() as session:
            session.add(row)
            await session.flush()
            return _to_item(row)

    async def get(self, memory_id: UUID) -> MemoryItem:
        async with self._db.session() as session:
            row = await session.get(MemoryItemModel, memory_id)
            if row is None:
                raise MemoryNotFoundError(str(memory_id))
            return _to_item(row)

    async def get_many(self, memory_ids: Sequence[UUID]) -> dict[UUID, MemoryItem]:
        if not memory_ids:
            return {}
        stmt = select(MemoryItemModel).where(MemoryItemModel.id.in_(list(memory_ids)))
        async with self._db.session() as session:
            rows = (await session.execute(stmt)).scalars().all()
            return {row.id: _to_item(row) for row in rows}

    async def touch_many(self, updates: Sequence[tuple[UUID, float]]) -> None:
        """Uma única ida ao banco para todas as reconsolidações do recall.

        Um UPDATE com CASE em vez de N updates: o recall de uma busca toca
        todos os itens retornados, e fazer isso em série era o gargalo.
        """
        if not updates:
            return
        importancia = case(
            *[(MemoryItemModel.id == mid, imp) for mid, imp in updates],
            else_=MemoryItemModel.importance,
        )
        async with self._db.session() as session:
            await session.execute(
                update(MemoryItemModel)
                .where(MemoryItemModel.id.in_([mid for mid, _ in updates]))
                .values(
                    last_accessed_at=datetime.now(tz=UTC),
                    access_count=MemoryItemModel.access_count + 1,
                    importance=importancia,
                )
                .execution_options(synchronize_session=False)
            )

    async def touch(self, memory_id: UUID, *, new_importance: float) -> None:
        async with self._db.session() as session:
            await session.execute(
                update(MemoryItemModel)
                .where(MemoryItemModel.id == memory_id)
                .values(
                    last_accessed_at=datetime.now(tz=UTC),
                    access_count=MemoryItemModel.access_count + 1,
                    importance=new_importance,
                )
            )

    async def list_by_user(
        self, user_id: UUID, *, kind: str | None = None, include_archived: bool = False
    ) -> list[MemoryItem]:
        stmt = select(MemoryItemModel).where(MemoryItemModel.user_id == user_id)
        if kind is not None:
            stmt = stmt.where(MemoryItemModel.kind == kind)
        if not include_archived:
            stmt = stmt.where(MemoryItemModel.archived_at.is_(None))
        stmt = stmt.order_by(MemoryItemModel.created_at.desc())
        async with self._db.session() as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [_to_item(r) for r in rows]

    async def search_rows(
        self,
        *,
        user_id: UUID,
        query: str,
        query_vector: tuple[float, ...] | None,
        kinds: tuple[str, ...] | None,
        pool: int,
    ) -> tuple[list[tuple[UUID, int]], list[tuple[UUID, float]]]:
        def _base(stmt: Any) -> Any:
            stmt = stmt.where(
                MemoryItemModel.user_id == user_id, MemoryItemModel.archived_at.is_(None)
            )
            if kinds:
                stmt = stmt.where(MemoryItemModel.kind.in_(kinds))
            return stmt

        tsquery = func.websearch_to_tsquery("portuguese", query)
        rank = func.ts_rank(MemoryItemModel.tsv, tsquery).cast(Float)
        lex_stmt = _base(
            select(MemoryItemModel.id)
            .where(MemoryItemModel.tsv.op("@@")(tsquery))
            .order_by(rank.desc())
            .limit(pool)
        )
        lexical: list[tuple[UUID, int]] = []
        vector: list[tuple[UUID, float]] = []
        async with self._db.session() as session:
            for position, (memory_id,) in enumerate((await session.execute(lex_stmt)).all(), 1):
                lexical.append((memory_id, position))
            if query_vector is not None:
                distance = MemoryItemModel.embedding.cosine_distance(list(query_vector))
                vec_stmt = _base(
                    select(MemoryItemModel.id, distance.label("distance"))
                    .where(MemoryItemModel.embedding.is_not(None))
                    .order_by(distance)
                    .limit(pool)
                )
                for memory_id, dist in (await session.execute(vec_stmt)).all():
                    vector.append((memory_id, 1.0 - float(dist)))
        return lexical, vector

    async def forget(self, memory_id: UUID) -> None:
        async with self._db.session() as session:
            row = await session.get(MemoryItemModel, memory_id)
            if row is None:
                raise MemoryNotFoundError(str(memory_id))
            await session.delete(row)

    async def archive(self, memory_id: UUID) -> None:
        async with self._db.session() as session:
            await session.execute(
                update(MemoryItemModel)
                .where(MemoryItemModel.id == memory_id)
                .values(archived_at=datetime.now(tz=UTC))
            )

    async def expire_temporary(self, *, now: datetime) -> int:
        async with self._db.session() as session:
            result = await session.execute(
                update(MemoryItemModel)
                .where(
                    MemoryItemModel.kind == "temporary",
                    MemoryItemModel.archived_at.is_(None),
                    MemoryItemModel.expires_at.is_not(None),
                    MemoryItemModel.expires_at <= now,
                )
                .values(archived_at=now)
            )
            return int(getattr(result, "rowcount", 0) or 0)


# canário anti-truncamento
