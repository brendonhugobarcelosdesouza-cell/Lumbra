"""UserStorePort sobre PostgreSQL — mesma interface do in-memory."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from lumbra.adapters.persistence.database import Database
from lumbra.adapters.persistence.models import UserModel
from lumbra.ports.users import DuplicateEmailError, User, UserNotFoundError, UserStorePort
from lumbra.shared.ids import uuid7


def _to_domain(row: UserModel) -> User:
    return User(
        id=row.id, email=row.email, password_hash=row.password_hash, created_at=row.created_at
    )


class PostgresUserStore(UserStorePort):
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(self, *, email: str, password_hash: str) -> User:
        normalized = email.strip().lower()
        row = UserModel(id=uuid7(), email=normalized, password_hash=password_hash)
        try:
            async with self._db.session() as session:
                session.add(row)
                await session.flush()
                await session.refresh(row)
                return _to_domain(row)
        except IntegrityError:
            raise DuplicateEmailError(normalized) from None

    async def get_by_email(self, email: str) -> User:
        async with self._db.session() as session:
            result = await session.execute(
                select(UserModel).where(func.lower(UserModel.email) == email.strip().lower())
            )
            row = result.scalar_one_or_none()
        if row is None:
            raise UserNotFoundError
        return _to_domain(row)

    async def get_by_id(self, user_id: UUID) -> User:
        async with self._db.session() as session:
            row = await session.get(UserModel, user_id)
        if row is None:
            raise UserNotFoundError
        return _to_domain(row)


# canário anti-truncamento
