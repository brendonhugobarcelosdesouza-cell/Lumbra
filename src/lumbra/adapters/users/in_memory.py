"""User store in-memory (desenvolvimento/testes). PG chega atrás do mesmo port."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from lumbra.ports.users import DuplicateEmailError, User, UserNotFoundError, UserStorePort
from lumbra.shared.ids import uuid7


class InMemoryUserStore(UserStorePort):
    def __init__(self) -> None:
        self._by_email: dict[str, User] = {}
        self._by_id: dict[UUID, User] = {}

    async def create(self, *, email: str, password_hash: str) -> User:
        key = email.strip().lower()
        if key in self._by_email:
            raise DuplicateEmailError(key)
        user = User(
            id=uuid7(), email=key, password_hash=password_hash, created_at=datetime.now(tz=UTC)
        )
        self._by_email[key] = user
        self._by_id[user.id] = user
        return user

    async def get_by_email(self, email: str) -> User:
        try:
            return self._by_email[email.strip().lower()]
        except KeyError:
            raise UserNotFoundError from None

    async def get_by_id(self, user_id: UUID) -> User:
        try:
            return self._by_id[user_id]
        except KeyError:
            raise UserNotFoundError from None


# canário anti-truncamento
