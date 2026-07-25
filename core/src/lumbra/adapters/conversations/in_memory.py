"""Conversation store in-memory: histórico de chat sem Postgres (P1-b.1).

Cumpre o `ConversationStorePort` para que a API de chat funcione no Nó
leve de desenvolvimento — mesma superfície de contrato do modo Postgres
(docs/24, Regra 1). Guarda tudo em memória do processo.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from lumbra.ports.conversations import (
    Citation,
    Conversation,
    ConversationNotFoundError,
    ConversationStorePort,
    Message,
)
from lumbra.shared.ids import uuid7


class InMemoryConversationStore(ConversationStorePort):
    def __init__(self) -> None:
        self._conversas: dict[UUID, Conversation] = {}
        self._mensagens: dict[UUID, list[Message]] = {}

    async def create(
        self, *, user_id: UUID, title: str | None, model_policy: dict[str, Any]
    ) -> Conversation:
        conversa = Conversation(
            id=uuid7(),
            user_id=user_id,
            title=title,
            model_policy=model_policy,
            created_at=datetime.now(tz=UTC),
            last_message_at=None,
        )
        self._conversas[conversa.id] = conversa
        self._mensagens[conversa.id] = []
        return conversa

    async def get(self, conversation_id: UUID) -> Conversation:
        try:
            return self._conversas[conversation_id]
        except KeyError:
            raise ConversationNotFoundError from None

    async def list_by_user(self, user_id: UUID, *, limit: int = 50) -> list[Conversation]:
        conversas = [c for c in self._conversas.values() if c.user_id == user_id]
        conversas.sort(key=lambda c: c.last_message_at or c.created_at, reverse=True)
        return conversas[:limit]

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
    ) -> Message:
        if conversation_id not in self._conversas:
            raise ConversationNotFoundError
        now = datetime.now(tz=UTC)
        mensagem = Message(
            id=uuid7(),
            conversation_id=conversation_id,
            role=role,
            content=content,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            provider=provider,
            model=model,
            created_at=now,
            citations=citations,
        )
        self._mensagens[conversation_id].append(mensagem)
        conversa = self._conversas[conversation_id]
        self._conversas[conversation_id] = conversa.model_copy(update={"last_message_at": now})
        return mensagem

    async def history(self, conversation_id: UUID, *, limit: int = 50) -> list[Message]:
        if conversation_id not in self._conversas:
            raise ConversationNotFoundError
        return self._mensagens[conversation_id][-limit:]

    async def set_title(self, conversation_id: UUID, title: str) -> None:
        conversa = self._conversas.get(conversation_id)
        if conversa is None:
            raise ConversationNotFoundError
        self._conversas[conversation_id] = conversa.model_copy(update={"title": title})

    async def set_model_policy(self, conversation_id: UUID, policy: dict[str, Any]) -> None:
        conversa = self._conversas.get(conversation_id)
        if conversa is None:
            raise ConversationNotFoundError
        self._conversas[conversation_id] = conversa.model_copy(update={"model_policy": policy})

    async def delete(self, conversation_id: UUID) -> None:
        if conversation_id not in self._conversas:
            raise ConversationNotFoundError
        del self._conversas[conversation_id]
        self._mensagens.pop(conversation_id, None)


# canário anti-truncamento
