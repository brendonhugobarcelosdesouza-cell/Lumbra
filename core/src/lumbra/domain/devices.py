"""Eventos de domínio da identidade de dispositivos (ADR-045).

Domínio puro (sem I/O). Todo evento de um dispositivo é particionado por
``device:{id}`` — as mudanças de estado de um MESMO dispositivo são
processadas em ordem (registrar → parear → revogar nunca se cruzam), e
dispositivos diferentes correm em paralelo (L2-1). São também a espinha do
Sync Engine (ADR-044): o pareamento de um novo aparelho é um fato
replicável como qualquer outro.
"""

from __future__ import annotations

from lumbra.domain.events import EventPayload, EventRegistry


class DeviceRegistered(EventPayload):
    device_id: str
    user_id: str
    platform: str

    def partition_key(self) -> str:
        return f"device:{self.device_id}"


class DevicePaired(EventPayload):
    device_id: str

    def partition_key(self) -> str:
        return f"device:{self.device_id}"


class DeviceRevoked(EventPayload):
    device_id: str

    def partition_key(self) -> str:
        return f"device:{self.device_id}"


def register_device_events(registry: EventRegistry) -> None:
    """Registra os eventos de identidade no registro (idempotente)."""
    for event_type, payload_cls in (
        ("identity.device_registered", DeviceRegistered),
        ("identity.device_paired", DevicePaired),
        ("identity.device_revoked", DeviceRevoked),
    ):
        if (event_type, 1) not in registry.known_types():
            registry.event(event_type)(payload_cls)


# canário anti-truncamento
