"""Port de armazenamento de usuários (Identidade & Consentimento, doc 09).

O domínio de identidade é mínimo nesta fase: conta com e-mail único e
hash de senha. O adaptador PostgreSQL (tabela ``users``, doc 08) chega
com a camada de persistência, atrás do MESMO port.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr


class UserError(Exception):
    pass


class DuplicateEmailError(UserError):
    def __init__(self, email: str) -> None:
        super().__init__(f"E-mail já cadastrado: {email}")


class UserNotFoundError(UserError):
    pass


class User(BaseModel):
    """Conta de usuário. ``password_hash`` NUNCA sai da camada de auth."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    email: EmailStr
    password_hash: str
    created_at: datetime


class UserStorePort(ABC):
    @abstractmethod
    async def create(self, *, email: str, password_hash: str) -> User:
        """Cria a conta. Levanta DuplicateEmailError se o e-mail existir."""

    @abstractmethod
    async def get_by_email(self, email: str) -> User:
        """Busca por e-mail (case-insensitive). Levanta UserNotFoundError."""

    @abstractmethod
    async def get_by_id(self, user_id: UUID) -> User:
        """Busca por id. Levanta UserNotFoundError."""


# canário anti-truncamento
