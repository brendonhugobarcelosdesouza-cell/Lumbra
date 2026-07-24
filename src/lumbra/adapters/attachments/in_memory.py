"""Attachment store in-memory: anexos de chat sem Postgres (P1-b.1).

Cumpre o `AttachmentStorePort` para o Nó leve de desenvolvimento. O blob
em si continua no `FilesystemBlobStore` (bytes em disco); aqui ficam só os
metadados do vínculo anexo↔conversa.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from lumbra.ports.attachments import (
    Attachment,
    AttachmentNotFoundError,
    AttachmentState,
    AttachmentStorePort,
)
from lumbra.shared.ids import uuid7


class InMemoryAttachmentStore(AttachmentStorePort):
    def __init__(self) -> None:
        self._por_id: dict[UUID, Attachment] = {}

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
        anexo = Attachment(
            id=uuid7(),
            conversation_id=conversation_id,
            user_id=user_id,
            document_id=None,
            filename=filename,
            mime_type=mime_type,
            size_bytes=size_bytes,
            storage_uri=storage_uri,
            state=AttachmentState.PENDING,
            detail=None,
            extracted_chars=None,
            created_at=datetime.now(tz=UTC),
        )
        self._por_id[anexo.id] = anexo
        return anexo

    async def mark(
        self,
        attachment_id: UUID,
        *,
        state: AttachmentState,
        document_id: UUID | None = None,
        detail: str | None = None,
        extracted_chars: int | None = None,
    ) -> None:
        anexo = self._por_id.get(attachment_id)
        if anexo is None:
            raise AttachmentNotFoundError
        self._por_id[attachment_id] = anexo.model_copy(
            update={
                "state": state,
                "document_id": document_id if document_id is not None else anexo.document_id,
                "detail": detail,
                "extracted_chars": extracted_chars
                if extracted_chars is not None
                else anexo.extracted_chars,
            }
        )

    async def get(self, attachment_id: UUID) -> Attachment:
        try:
            return self._por_id[attachment_id]
        except KeyError:
            raise AttachmentNotFoundError from None

    async def list_of_conversation(self, conversation_id: UUID) -> list[Attachment]:
        anexos = [a for a in self._por_id.values() if a.conversation_id == conversation_id]
        return sorted(anexos, key=lambda a: a.created_at)


# canário anti-truncamento
