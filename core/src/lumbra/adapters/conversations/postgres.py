"""ConversationStorePort sobre PostgreSQL."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select, update

from lumbra.adapters.persistence.database import Database
from lumbra.adapters.persistence.models import (
    ConversationModel,
    MessageModel,
    MessageSourceModel,
)
from lumbra.ports.conversations import (
    Citation,
    Conversation,
    ConversationNotFoundError,
    ConversationStorePort,
    Message,
)
from lumbra.shared.ids import uuid7


def _to_conversation(row: ConversationModel) -> Conversation:
    return Conversation(
        id=row.id,
        user_id=row.user_id,
        title=row.title,
        model_policy=dict(row.model_policy or {}),
        created_at=row.created_at,
        last_message_at=row.last_message_at,
    )


def _to_message(row: MessageModel, citations: tuple[Citation, ...] = ()) -> Message:
    return Message(
        id=row.id,
        conversation_id=row.conversation_id,
        role=row.role,
        content=row.content,
        tokens_in=row.tokens_in,
        tokens_out=row.tokens_out,
        provider=row.provider,
        model=row.model,
        created_at=row.created_at,
        citations=citations,
    )


class PostgresConversationStore(ConversationStorePort):
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self, *, user_id: UUID, title: str | None, model_policy: dict[str, Any]
    ) -> Conversation:
        row = ConversationModel(
            id=uuid7(),
            user_id=user_id,
            title=title,
            model_policy=model_policy,
            created_at=datetime.now(tz=UTC),
            last_message_at=None,
        )
        async with self._db.session() as session:
            session.add(row)
            await session.flush()
            return _to_conversation(row)

    async def get(self, conversation_id: UUID) -> Conversation:
        async with self._db.session() as session:
            row = await session.get(ConversationModel, conversation_id)
            if row is None:
                raise ConversationNotFoundError(str(conversation_id))
            return _to_conversation(row)

    async def list_by_user(self, user_id: UUID, *, limit: int = 50) -> list[Conversation]:
        stmt = (
            select(ConversationModel)
            .where(ConversationModel.user_id == user_id)
            .order_by(ConversationModel.created_at.desc())
            .limit(limit)
        )
        async with self._db.session() as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [_to_conversation(r) for r in rows]

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
        now = datetime.now(tz=UTC)
        row = MessageModel(
            id=uuid7(),
            conversation_id=conversation_id,
            role=role,
            content=content,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            provider=provider,
            model=model,
            created_at=now,
        )
        async with self._db.session() as session:
            session.add(row)
            await session.flush()
            for citation in citations:
                session.add(
                    MessageSourceModel(
                        message_id=row.id,
                        ordinal=citation.ordinal,
                        kind=citation.kind,
                        ref_id=citation.ref_id,
                        title=citation.title,
                        uri=citation.uri,
                        score=citation.score,
                        snippet=citation.snippet,
                    )
                )
            await session.execute(
                update(ConversationModel)
                .where(ConversationModel.id == conversation_id)
                .values(last_message_at=now)
            )
            return _to_message(row, citations)

    async def history(self, conversation_id: UUID, *, limit: int = 50) -> list[Message]:
        async with self._db.session() as session:
            rows = (
                (
                    await session.execute(
                        select(MessageModel)
                        .where(MessageModel.conversation_id == conversation_id)
                        .order_by(MessageModel.created_at)
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
            if not rows:
                return []
            sources = (
                (
                    await session.execute(
                        select(MessageSourceModel)
                        .where(MessageSourceModel.message_id.in_([r.id for r in rows]))
                        .order_by(MessageSourceModel.ordinal)
                    )
                )
                .scalars()
                .all()
            )
        by_message: dict[UUID, list[Citation]] = {}
        for source in sources:
            by_message.setdefault(source.message_id, []).append(
                Citation(
                    ordinal=source.ordinal,
                    kind=source.kind,
                    ref_id=source.ref_id,
                    title=source.title,
                    uri=source.uri,
                    score=source.score,
                    snippet=source.snippet,
                )
            )
        return [_to_message(row, tuple(by_message.get(row.id, []))) for row in rows]

    async def set_title(self, conversation_id: UUID, title: str) -> None:
        async with self._db.session() as session:
            await session.execute(
                update(ConversationModel)
                .where(ConversationModel.id == conversation_id)
                .values(title=title)
            )

    async def set_model_policy(self, conversation_id: UUID, policy: dict[str, Any]) -> None:
        async with self._db.session() as session:
            await session.execute(
                update(ConversationModel)
                .where(ConversationModel.id == conversation_id)
                .values(model_policy=policy)
            )

    async def delete(self, conversation_id: UUID) -> None:
        async with self._db.session() as session:
            await session.execute(
                delete(ConversationModel).where(ConversationModel.id == conversation_id)
            )


# canário anti-truncamento
