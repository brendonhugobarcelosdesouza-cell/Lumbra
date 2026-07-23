"""Port da memória: contrato entre o domínio e o armazenamento."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MemoryItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    user_id: UUID
    kind: str
    content: str
    importance: float = Field(ge=0.0, le=1.0)
    source_ref: dict[str, Any] = Field(default_factory=dict)
    access_count: int = 0
    expires_at: datetime | None = None
    last_accessed_at: datetime
    created_at: datetime
    archived_at: datetime | None = None


class MemoryHit(BaseModel):
    """Resultado de recall com explicação componente a componente."""

    model_config = ConfigDict(frozen=True)

    item: MemoryItem
    score: float
    explanation: str


class MemoryNotFoundError(Exception):
    pass


class MemoryStorePort(ABC):
    @abstractmethod
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
    ) -> MemoryItem: ...

    @abstractmethod
    async def get(self, memory_id: UUID) -> MemoryItem: ...

    @abstractmethod
    async def get_many(self, memory_ids: Sequence[UUID]) -> dict[UUID, MemoryItem]:
        """Busca em lote. Existe para evitar N+1 na busca, que resolve
        dezenas de candidatos por consulta."""

    @abstractmethod
    async def touch_many(self, updates: Sequence[tuple[UUID, float]]) -> None:
        """Reconsolidação em lote (id, nova_importância)."""
        for memory_id, importance in updates:
            await self.touch(memory_id, new_importance=importance)

    @abstractmethod
    async def touch(self, memory_id: UUID, *, new_importance: float) -> None:
        """Registra acesso: last_accessed_at=now, access_count+1, importância."""

    @abstractmethod
    async def list_by_user(
        self, user_id: UUID, *, kind: str | None = None, include_archived: bool = False
    ) -> list[MemoryItem]: ...

    @abstractmethod
    async def search_rows(
        self,
        *,
        user_id: UUID,
        query: str,
        query_vector: tuple[float, ...] | None,
        kinds: tuple[str, ...] | None,
        pool: int,
    ) -> tuple[list[tuple[UUID, int]], list[tuple[UUID, float]]]:
        """Duas listas ranqueadas de candidatos ativos: léxica [(id, pos)]
        e vetorial [(id, similaridade)] — a fusão acontece no domínio."""

    @abstractmethod
    async def forget(self, memory_id: UUID) -> None:
        """Exclusão REAL (direito do usuário). Levanta MemoryNotFoundError."""

    @abstractmethod
    async def archive(self, memory_id: UUID) -> None: ...

    @abstractmethod
    async def expire_temporary(self, *, now: datetime) -> int:
        """Arquiva memórias temporary vencidas. Retorna quantas."""


# canário anti-truncamento
