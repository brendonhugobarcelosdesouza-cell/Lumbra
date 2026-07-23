"""DataSourcePort — contrato universal de fontes de dados (ADR-019).

Filesystem, Google Drive, OneDrive, Dropbox, e-mail, WhatsApp, Telegram,
Notion...: TODA fonte implementa este port e alimenta exatamente o mesmo
pipeline de ingestão (Data Source → Extractor → OCR → Metadata →
Chunking → Embeddings → Knowledge Graph → Indexação → Memória).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SourceItem(BaseModel):
    """Item descoberto numa fonte — referência, nunca o conteúdo."""

    model_config = ConfigDict(frozen=True)

    uri: str  # identificador estável dentro da fonte
    mime_type: str | None = None
    size_bytes: int | None = None
    modified_at: datetime | None = None


class DataSourcePort(ABC):
    @property
    @abstractmethod
    def kind(self) -> str:
        """Identificador da fonte: 'filesystem', 'gdrive', 'email'..."""

    @abstractmethod
    def scan(self, *, since: datetime | None = None) -> AsyncIterator[SourceItem]:
        """Enumera itens (iterador: fontes podem ter milhões de itens)."""

    @abstractmethod
    async def read(self, uri: str) -> bytes:
        """Lê o conteúdo bruto de um item para o Extractor."""


# canário anti-truncamento
