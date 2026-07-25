"""Port de dispositivos: a identidade multi-dispositivo da plataforma (ADR-045).

Um dispositivo (desktop, Android, iPhone, web, ou um plugin — ADR-047) é
uma identidade por par de chaves Ed25519. O Nó guarda a chave pública e o
conjunto de escopos que o usuário concedeu; a privada nunca sai do
dispositivo. Ciclo de vida: ``pending`` (chave apresentada, aguardando o
usuário aprovar no pareamento) → ``active`` (pareado) → ``revoked``
(acesso cassado — como esquecer um aparelho perdido).

Modelo e port aqui (como ``users``/``memory``); os eventos de domínio em
``domain/devices.py``; o adaptador Postgres chega no P1-b.4 atrás do MESMO
port. Escopos são ``tuple[str, ...]`` por ora — o modelo e a verificação
de escopo entram no P1-b.3.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DevicePlatform(StrEnum):
    WINDOWS = "windows"
    LINUX = "linux"
    MACOS = "macos"
    ANDROID = "android"
    IOS = "ios"
    WEB = "web"
    PLUGIN = "plugin"  # integração externa (ADR-047): também é um "dispositivo"


class DeviceState(StrEnum):
    PENDING = "pending"  # chave apresentada, aguardando aprovação do usuário
    ACTIVE = "active"  # pareado e autorizado
    REVOKED = "revoked"  # acesso cassado


class DeviceError(Exception):
    pass


class DeviceNotFoundError(DeviceError):
    pass


class DuplicatePublicKeyError(DeviceError):
    """Uma chave pública identifica UM dispositivo — não se reusa."""

    def __init__(self, public_key: str) -> None:
        super().__init__(f"chave pública já registrada: {public_key[:16]}…")


class DeviceStateError(DeviceError):
    """Transição de estado inválida (ex.: parear um dispositivo revogado)."""


class Device(BaseModel):
    """Identidade de um dispositivo. ``public_key`` é base64 dos 32 bytes
    crus da Ed25519; a privada correspondente vive só no dispositivo."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    user_id: UUID
    name: str
    platform: DevicePlatform
    public_key: str
    state: DeviceState
    scopes: tuple[str, ...] = ()
    created_at: datetime
    paired_at: datetime | None = None
    last_seen_at: datetime | None = None
    revoked_at: datetime | None = None


class DeviceStorePort(ABC):
    @abstractmethod
    async def create(
        self,
        *,
        user_id: UUID,
        name: str,
        platform: DevicePlatform,
        public_key: str,
        scopes: tuple[str, ...] = (),
    ) -> Device:
        """Registra um dispositivo em ``pending``. Levanta
        DuplicatePublicKeyError se a chave já existir."""

    @abstractmethod
    async def get(self, device_id: UUID) -> Device:
        """Busca por id. Levanta DeviceNotFoundError."""

    @abstractmethod
    async def get_by_public_key(self, public_key: str) -> Device:
        """Busca pela chave pública (identidade de autenticação).
        Levanta DeviceNotFoundError."""

    @abstractmethod
    async def list_by_user(
        self, user_id: UUID, *, include_revoked: bool = False
    ) -> list[Device]: ...

    @abstractmethod
    async def activate(self, device_id: UUID) -> Device:
        """Pareia: pending → active, grava ``paired_at``. Levanta
        DeviceStateError se já revogado, DeviceNotFoundError se ausente."""

    @abstractmethod
    async def revoke(self, device_id: UUID) -> Device:
        """Cassa o acesso: → revoked, grava ``revoked_at``. Idempotente
        sobre um já revogado."""

    @abstractmethod
    async def touch(self, device_id: UUID, *, seen_at: datetime) -> None:
        """Registra atividade: atualiza ``last_seen_at``."""


# canário anti-truncamento
