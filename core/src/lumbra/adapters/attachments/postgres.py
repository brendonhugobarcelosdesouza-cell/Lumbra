"""AttachmentStorePort sobre PostgreSQL."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update

from lumbra.adapters.persistence.database import Database
from lumbra.adapters.persistence.models import ChatAttachmentModel
from lumbra.ports.attachments import (
    Attachment,
    AttachmentNotFoundError,
    AttachmentState,
    AttachmentStorePort,
)
from lumbra.shared.ids import uuid7


def _to_attachment(row: ChatAttachmentModel) -> Attachment:
    return Attachment(
        id=row.id,
        conversation_id=row.conversation_id,
        user_id=row.user_id,
        document_id=row.document_id,
        filename=row.filename,
        mime_type=row.mime_type,
        size_bytes=row.size_bytes,
        storage_uri=row.storage_uri,
        state=AttachmentState(row.state),
        detail=row.detail,
        extracted_chars=row.extracted_chars,
        created_at=row.created_at,
    )


class PostgresAttachmentStore(AttachmentStorePort):
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self,
        *,
        conversation_id: UUID,
        user_id: UUID,
        filename: str,
        mime_type: str | None,
        size_bytes: int,
        storage_uri: str,
    ) -> Attachment:
        row = ChatAttachmentModel(
            id=uuid7(),
            conversation_id=conversation_id,
            user_id=user_id,
            document_id=None,
            filename=filename,
            mime_type=mime_type,
            size_bytes=size_bytes,
            storage_uri=storage_uri,
            state=AttachmentState.PENDING.value,
            created_at=datetime.now(tz=UTC),
        )
        async with self._db.session() as session:
            session.add(row)
            await session.flush()
            return _to_attachment(row)

    async def mark(
        self,
        attachment_id: UUID,
        *,
        state: AttachmentState,
        document_id: UUID | None = None,
        detail: str | None = None,
        extracted_chars: int | None = None,
    ) -> None:
        valores: dict[str, object] = {"state": state.value}
        if document_id is not None:
            valores["document_id"] = document_id
        if detail is not None:
            valores["detail"] = detail
        if extracted_chars is not None:
            valores["extracted_chars"] = extracted_chars
        async with self._db.session() as session:
            await session.execute(
                update(ChatAttachmentModel)
                .where(ChatAttachmentModel.id == attachment_id)
                .values(**valores)
            )

    async def get(self, attachment_id: UUID) -> Attachment:
        async with self._db.session() as session:
            row = await session.get(ChatAttachmentModel, attachment_id)
            if row is None:
                raise AttachmentNotFoundError(str(attachment_id))
            return _to_attachment(row)

    async def list_of_conversation(self, conversation_id: UUID) -> list[Attachment]:
        stmt = (
            select(ChatAttachmentModel)
            .where(ChatAttachmentModel.conversation_id == conversation_id)
            .order_by(ChatAttachmentModel.created_at)
        )
        async with self._db.session() as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [_to_attachment(r) for r in rows]


# canário anti-truncamento
