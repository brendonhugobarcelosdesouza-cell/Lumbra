"""Port de anexos de conversa (E2-03).

Um anexo é um DOCUMENTO com vínculo a uma conversa — não uma entidade
paralela. O arquivo passa pelo mesmo pipeline (extração/OCR, chunking,
embeddings, grafo), então perguntar sobre algo recém-anexado e perguntar
sobre algo indexado há meses seguem o mesmo caminho e produzem o mesmo
tipo de citação verificável.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AttachmentState(StrEnum):
    PENDING = "pending"  # salvo, ainda não processado
    READY = "ready"  # texto extraído e indexado
    UNSUPPORTED = "unsupported"  # tipo sem extrator (ex.: imagem sem OCR)
    FAILED = "failed"  # extração quebrou


class Attachment(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    conversation_id: UUID
    user_id: UUID
    document_id: UUID | None
    filename: str
    mime_type: str | None
    size_bytes: int
    storage_uri: str
    state: AttachmentState
    detail: str | None = None
    extracted_chars: int | None = None
    created_at: datetime


class AttachmentNotFoundError(Exception):
    pass


class BlobStorePort(ABC):
    """Onde os bytes ficam. Sistema de arquivos hoje; S3/MinIO amanhã,
    sem tocar no resto — o resto só conhece a URI."""

    @abstractmethod
    async def save(self, data: bytes, *, filename: str, owner: UUID) -> str:
        """Grava e devolve a URI de leitura."""

    @abstractmethod
    async def read(self, uri: str) -> bytes: ...

    @abstractmethod
    async def delete(self, uri: str) -> None: ...


class AttachmentStorePort(ABC):
    @abstractmethod
    async def create(
        self,
        *,
        conversation_id: UUID,
        user_id: UUID,
        filename: str,
        mime_type: str | None,
        size_bytes: int,
        storage_uri: str,
    ) -> Attachment: ...

    @abstractmethod
    async def mark(
        self,
        attachment_id: UUID,
        *,
        state: AttachmentState,
        document_id: UUID | None = None,
        detail: str | None = None,
        extracted_chars: int | None = None,
    ) -> None: ...

    @abstractmethod
    async def get(self, attachment_id: UUID) -> Attachment: ...

    @abstractmethod
    async def list_of_conversation(self, conversation_id: UUID) -> list[Attachment]: ...


# canário anti-truncamento
