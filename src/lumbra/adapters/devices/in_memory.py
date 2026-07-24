"""Device store in-memory: identidade de dispositivos sem Postgres (P1-b.2).

Cumpre o `DeviceStorePort` para o Nó leve de desenvolvimento e para os
testes. O adaptador Postgres (com migração) chega no P1-b.4 atrás do MESMO
port, mantendo a superfície de API independente do adaptador (Regra 1).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from lumbra.ports.devices import (
    Device,
    DeviceNotFoundError,
    DevicePlatform,
    DeviceState,
    DeviceStateError,
    DeviceStorePort,
    DuplicatePublicKeyError,
)
from lumbra.shared.ids import uuid7


class InMemoryDeviceStore(DeviceStorePort):
    def __init__(self) -> None:
        self._por_id: dict[UUID, Device] = {}
        self._por_chave: dict[str, UUID] = {}

    async def create(
        self,
        *,
        user_id: UUID,
        name: str,
        platform: DevicePlatform,
        public_key: str,
        scopes: tuple[str, ...] = (),
    ) -> Device:
        if public_key in self._por_chave:
            raise DuplicatePublicKeyError(public_key)
        device = Device(
            id=uuid7(),
            user_id=user_id,
            name=name,
            platform=platform,
            public_key=public_key,
            state=DeviceState.PENDING,
            scopes=scopes,
            created_at=datetime.now(tz=UTC),
        )
        self._por_id[device.id] = device
        self._por_chave[public_key] = device.id
        return device

    async def get(self, device_id: UUID) -> Device:
        try:
            return self._por_id[device_id]
        except KeyError:
            raise DeviceNotFoundError from None

    async def get_by_public_key(self, public_key: str) -> Device:
        device_id = self._por_chave.get(public_key)
        if device_id is None:
            raise DeviceNotFoundError
        return self._por_id[device_id]

    async def list_by_user(self, user_id: UUID, *, include_revoked: bool = False) -> list[Device]:
        devices = [
            d
            for d in self._por_id.values()
            if d.user_id == user_id and (include_revoked or d.state is not DeviceState.REVOKED)
        ]
        return sorted(devices, key=lambda d: d.created_at)

    async def activate(self, device_id: UUID) -> Device:
        device = await self.get(device_id)
        if device.state is DeviceState.REVOKED:
            raise DeviceStateError("dispositivo revogado não pode ser pareado")
        atualizado = device.model_copy(
            update={"state": DeviceState.ACTIVE, "paired_at": datetime.now(tz=UTC)}
        )
        self._por_id[device_id] = atualizado
        return atualizado

    async def revoke(self, device_id: UUID) -> Device:
        device = await self.get(device_id)
        if device.state is DeviceState.REVOKED:
            return device  # idempotente
        atualizado = device.model_copy(
            update={"state": DeviceState.REVOKED, "revoked_at": datetime.now(tz=UTC)}
        )
        self._por_id[device_id] = atualizado
        return atualizado

    async def touch(self, device_id: UUID, *, seen_at: datetime) -> None:
        device = self._por_id.get(device_id)
        if device is None:
            raise DeviceNotFoundError
        self._por_id[device_id] = device.model_copy(update={"last_seen_at": seen_at})


# canário anti-truncamento
