"""Port de conversas: histórico do chat e citações por mensagem."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Citation(BaseModel):
    """Fonte usada numa resposta — verificável pelo usuário (E2-02)."""

    model_config = ConfigDict(frozen=True)

    ordinal: int  # [1], [2]... referenciado no texto
    kind: str  # document | memory
    ref_id: UUID  # chunk_id ou memory_id
    title: str | None = None
    uri: str | None = None
    score: float | None = None
    snippet: str | None = None


class Message(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    conversation_id: UUID
    role: str
    content: str
    tokens_in: int | None = None
    tokens_out: int | None = None
    provider: str | None = None
    model: str | None = None
    created_at: datetime
    citations: tuple[Citation, ...] = ()


class Conversation(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    user_id: UUID
    title: str | None = None
    model_policy: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    last_message_at: datetime | None = None


class ConversationNotFoundError(Exception):
    pass


class ConversationStorePort(ABC):
    @abstractmethod
    async def create(
        self, *, user_id: UUID, title: str | None, model_policy: dict[str, Any]
    ) -> Conversation: ...

    @abstractmethod
    async def get(self, conversation_id: UUID) -> Conversation: ...

    @abstractmethod
    async def list_by_user(self, user_id: UUID, *, limit: int = 50) -> list[Conversation]: ...

    @abstractmethod
    async def add_message(
        self,
        *,
        conversation_id: UUID,
        role: str,
        content: str,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
        provider: str | None = None,
        model: str | None = None,
        citations: tuple[Citation, ...] = (),
    ) -> Message: ...

    @abstractmethod
    async def history(self, conversation_id: UUID, *, limit: int = 50) -> list[Message]:
        """Mensagens em ordem cronológica, com citações."""

    @abstractmethod
    async def set_title(self, conversation_id: UUID, title: str) -> None: ...

    @abstractmethod
    async def set_model_policy(self, conversation_id: UUID, policy: dict[str, Any]) -> None: ...

    @abstractmethod
    async def delete(self, conversation_id: UUID) -> None: ...


# canário anti-truncamento
