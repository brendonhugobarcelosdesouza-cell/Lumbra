"""Port de armazenamento de documentos e chunks (etapas finais do pipeline)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class IngestOutcome(StrEnum):
    """Resultado da deduplicação na entrada do pipeline (req. 7 do E1-2)."""

    NEW = "new"  # documento nunca visto
    NEW_VERSION = "new_version"  # mesmo uri, conteúdo mudou
    UNCHANGED = "unchanged"  # hash idêntico ao da versão atual — nada a fazer


class DocumentRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    user_id: UUID
    source: str
    uri: str
    mime_type: str | None
    title: str | None
    doc_kind: str | None
    metadata: dict[str, Any]
    version: int
    processing_state: str


class VersionRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: int
    parent_version: int | None
    content_hash: str  # hex
    reason: str
    created_at: datetime
    indexed_at: datetime | None


class DocumentStorePort(ABC):
    @abstractmethod
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
        """Dedup + versionamento (reqs. 2 e 7): NEW cria v1; NEW_VERSION
        incrementa a versão com parent e motivo; UNCHANGED não toca em nada."""

    @abstractmethod
    async def versions(self, document_id: UUID) -> list[VersionRecord]:
        """Histórico completo, mais recente primeiro."""

    @abstractmethod
    async def list_by_user(self, user_id: UUID, *, limit: int = 100) -> list[DocumentRecord]: ...

    @abstractmethod
    async def chunks_of(self, document_id: UUID) -> list[str]: ...

    @abstractmethod
    async def set_chunk_embeddings(
        self, document_id: UUID, vectors: list[tuple[float, ...]]
    ) -> int:
        """Grava vetores nos chunks (por ordinal). Retorna quantos atualizou."""

    @abstractmethod
    async def replace_chunks(self, document_id: UUID, texts: list[str]) -> int:
        """Substitui os chunks do documento (reindexação). Retorna o total."""

    @abstractmethod
    async def get(self, document_id: UUID) -> DocumentRecord:
        """Levanta DocumentNotFoundError se não existir."""


class DocumentNotFoundError(Exception):
    pass


# canário anti-truncamento
