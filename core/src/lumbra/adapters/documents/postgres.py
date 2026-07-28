"""DocumentStorePort sobre PostgreSQL — dedup, versionamento e chunks."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select, update

from lumbra.adapters.persistence.database import Database
from lumbra.adapters.persistence.models import (
    ChunkModel,
    DocumentModel,
    DocumentVersionModel,
)
from lumbra.domain.document_structure import ChunkMeta
from lumbra.ports.document_store import (
    DocumentNotFoundError,
    DocumentRecord,
    DocumentStorePort,
    IngestOutcome,
    VersionRecord,
)
from lumbra.shared.ids import uuid7


def _to_domain(row: DocumentModel) -> DocumentRecord:
    return DocumentRecord(
        id=row.id,
        user_id=row.user_id,
        source=row.source,
        uri=row.uri,
        mime_type=row.mime_type,
        title=row.title,
        doc_kind=row.doc_kind,
        metadata=row.meta,
        version=row.version,
        processing_state=row.processing_state,
    )


class PostgresDocumentStore(DocumentStorePort):
    def __init__(self, db: Database) -> None:
        self._db = db

    async def register(
        self,
        *,
        user_id: UUID,
        source: str,
        uri: str,
        content_hash: bytes,
        mime_type: str | None = None,
        title: str | None = None,
        doc_kind: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[DocumentRecord, IngestOutcome]:
        async with self._db.session() as session:
            existing = (
                await session.execute(
                    select(DocumentModel).where(
                        DocumentModel.user_id == user_id,
                        DocumentModel.source == source,
                        DocumentModel.uri == uri,
                    )
                )
            ).scalar_one_or_none()

            if existing is None:
                row = DocumentModel(
                    id=uuid7(),
                    user_id=user_id,
                    source=source,
                    uri=uri,
                    mime_type=mime_type,
                    content_hash=content_hash,
                    title=title,
                    doc_kind=doc_kind,
                    meta=metadata or {},
                    version=1,
                    processing_state="pending",
                )
                session.add(row)
                session.add(
                    DocumentVersionModel(
                        id=uuid7(),
                        document_id=row.id,
                        version=1,
                        parent_version=None,
                        content_hash=content_hash,
                        reason="initial",
                    )
                )
                await session.flush()
                await session.refresh(row)
                return _to_domain(row), IngestOutcome.NEW

            if existing.content_hash == content_hash:
                return _to_domain(existing), IngestOutcome.UNCHANGED

            parent = existing.version
            existing.version = parent + 1
            existing.content_hash = content_hash
            existing.reindex_reason = "content_changed"
            existing.processing_state = "pending"
            existing.error = None
            if mime_type is not None:
                existing.mime_type = mime_type
            if title is not None:
                existing.title = title
            session.add(
                DocumentVersionModel(
                    id=uuid7(),
                    document_id=existing.id,
                    version=existing.version,
                    parent_version=parent,
                    content_hash=content_hash,
                    reason="content_changed",
                )
            )
            await session.flush()
            await session.refresh(existing)
            return _to_domain(existing), IngestOutcome.NEW_VERSION

    async def versions(self, document_id: UUID) -> list[VersionRecord]:
        async with self._db.session() as session:
            rows = (
                (
                    await session.execute(
                        select(DocumentVersionModel)
                        .where(DocumentVersionModel.document_id == document_id)
                        .order_by(DocumentVersionModel.version.desc())
                    )
                )
                .scalars()
                .all()
            )
        return [
            VersionRecord(
                version=r.version,
                parent_version=r.parent_version,
                content_hash=r.content_hash.hex(),
                reason=r.reason,
                created_at=r.created_at,
                indexed_at=r.indexed_at,
            )
            for r in rows
        ]

    async def replace_chunks(
        self, document_id: UUID, texts: list[str], metas: list[ChunkMeta] | None = None
    ) -> int:
        metas = metas or []
        async with self._db.session() as session:
            await session.execute(delete(ChunkModel).where(ChunkModel.document_id == document_id))
            session.add_all(
                ChunkModel(
                    id=uuid7(),
                    document_id=document_id,
                    ordinal=i,
                    text=t,
                    section_path=(m.breadcrumb() or None) if m else None,
                    block_type=(m.block_type.value if m and m.block_type else None),
                    page=(m.page if m else None),
                )
                for i, (t, m) in enumerate(
                    zip(texts, metas + [None] * (len(texts) - len(metas)), strict=True)
                )
            )
        return len(texts)

    async def chunks_of(self, document_id: UUID) -> list[str]:
        async with self._db.session() as session:
            rows = (
                (
                    await session.execute(
                        select(ChunkModel.text)
                        .where(ChunkModel.document_id == document_id)
                        .order_by(ChunkModel.ordinal)
                    )
                )
                .scalars()
                .all()
            )
        return list(rows)

    async def set_chunk_embeddings(
        self, document_id: UUID, vectors: list[tuple[float, ...]]
    ) -> int:
        async with self._db.session() as session:
            rows = (
                (
                    await session.execute(
                        select(ChunkModel)
                        .where(ChunkModel.document_id == document_id)
                        .order_by(ChunkModel.ordinal)
                    )
                )
                .scalars()
                .all()
            )
            updated = 0
            for row, vector in zip(rows, vectors, strict=False):
                row.embedding = list(vector)
                updated += 1
        return updated

    async def list_by_user(self, user_id: UUID, *, limit: int = 100) -> list[DocumentRecord]:
        async with self._db.session() as session:
            rows = (
                (
                    await session.execute(
                        select(DocumentModel)
                        .where(DocumentModel.user_id == user_id)
                        .order_by(DocumentModel.uri)
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
        return [_to_domain(r) for r in rows]

    async def get(self, document_id: UUID) -> DocumentRecord:
        async with self._db.session() as session:
            row = await session.get(DocumentModel, document_id)
        if row is None:
            raise DocumentNotFoundError
        return _to_domain(row)

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
