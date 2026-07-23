"""Port de busca sobre o índice (léxica agora; híbrida na Etapa 3)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SearchHit(BaseModel):
    model_config = ConfigDict(frozen=True)

    chunk_id: UUID
    document_id: UUID
    title: str | None
    uri: str
    snippet: str
    score: float
    explanation: str  # por que este resultado (playground/req. transparência)


class SearchPort(ABC):
    @abstractmethod
    async def lexical(self, *, user_id: UUID, query: str, limit: int = 10) -> list[SearchHit]: ...

    @abstractmethod
    async def hybrid(
        self,
        *,
        user_id: UUID,
        query: str,
        query_vector: tuple[float, ...] | None,
        limit: int = 10,
    ) -> list[SearchHit]:
        """Fusão léxico+vetorial via RRF. Sem vetor (ou sem embeddings no
        índice), degrada para léxica — nunca falha por ausência de IA."""


# canário anti-truncamento
