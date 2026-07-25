"""API de dispositivos: registrar, parear, listar e revogar (P1-b.4, ADR-045).

Camada fina sobre o ``DeviceStorePort``: valida entrada (chave Ed25519 bem
formada, escopos bem formados), garante que o dispositivo pertence ao dono
autenticado, publica os eventos ``identity.*`` e devolve o recurso. Toda
rota exige escopo (``devices:read``/``devices:write``); o dono, com ``*``,
passa em tudo — dispositivos e plugins passam só no que lhes foi concedido.

Nota (backlog): o registro aqui é FEITO PELO DONO já autenticado. A prova
de posse da chave privada pelo próprio dispositivo (desafio-resposta
Ed25519 → token de dispositivo) e o pareamento por QR entram quando o
cliente mobile precisar (P3). A chave pública já fica guardada para isso.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from lumbra.adapters.security import keys
from lumbra.adapters.security.tokens import Claims, TokenService
from lumbra.api.auth import make_require_scope
from lumbra.domain.devices import (
    DevicePaired,
    DeviceRegistered,
    DeviceRevoked,
    register_device_events,
)
from lumbra.domain.scopes import (
    SCOPE_DEVICES_READ,
    SCOPE_DEVICES_WRITE,
    InvalidScopeError,
    ScopeSet,
)
from lumbra.kernel.kernel import LumbraKernel
from lumbra.ports.devices import (
    Device,
    DeviceNotFoundError,
    DevicePlatform,
    DeviceState,
    DeviceStateError,
    DeviceStorePort,
    DuplicatePublicKeyError,
)


class DeviceRegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    platform: DevicePlatform
    public_key: str = Field(min_length=1)
    scopes: list[str] = Field(default_factory=list)


class DeviceResponse(BaseModel):
    id: str
    name: str
    platform: DevicePlatform
    public_key: str
    state: DeviceState
    scopes: list[str]
    created_at: str
    paired_at: str | None
    last_seen_at: str | None
    revoked_at: str | None

    @classmethod
    def of(cls, d: Device) -> DeviceResponse:
        return cls(
            id=str(d.id),
            name=d.name,
            platform=d.platform,
            public_key=d.public_key,
            state=d.state,
            scopes=list(d.scopes),
            created_at=d.created_at.isoformat(),
            paired_at=d.paired_at.isoformat() if d.paired_at else None,
            last_seen_at=d.last_seen_at.isoformat() if d.last_seen_at else None,
            revoked_at=d.revoked_at.isoformat() if d.revoked_at else None,
        )


def build_devices_router(
    kernel: LumbraKernel, store: DeviceStorePort, tokens: TokenService
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/devices", tags=["devices"])
    register_device_events(kernel.events)
    require_scope = make_require_scope(tokens)
    _read = require_scope(SCOPE_DEVICES_READ)
    _write = require_scope(SCOPE_DEVICES_WRITE)

    async def _owned(device_id: UUID, claims: Claims) -> Device:
        """Busca o dispositivo garantindo posse. 404 (não 403) quando não é
        do dono: não vazamos a existência de dispositivos de terceiros."""
        try:
            device = await store.get(device_id)
        except DeviceNotFoundError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "dispositivo não encontrado") from None
        if device.user_id != claims.subject:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "dispositivo não encontrado")
        return device

    @router.post("", status_code=status.HTTP_201_CREATED)
    async def register(
        body: DeviceRegisterRequest,
        claims: Claims = Depends(_write),
    ) -> DeviceResponse:
        # chave Ed25519 e escopos precisam ser bem-formados: 422, não 500
        try:
            keys.load_public_key(body.public_key)
        except keys.InvalidPublicKeyError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
        try:
            escopos = tuple(ScopeSet(scopes=set(body.scopes)))
        except InvalidScopeError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
        try:
            device = await store.create(
                user_id=claims.subject,
                name=body.name,
                platform=body.platform,
                public_key=body.public_key,
                scopes=escopos,
            )
        except DuplicatePublicKeyError:
            raise HTTPException(status.HTTP_409_CONFLICT, "chave pública já registrada") from None
        await kernel.publish(
            DeviceRegistered(
                device_id=str(device.id), user_id=str(device.user_id), platform=device.platform
            ),
            user_id=claims.subject,
        )
        return DeviceResponse.of(device)

    @router.get("")
    async def list_devices(
        claims: Claims = Depends(_read),
        include_revoked: bool = Query(False),
    ) -> list[DeviceResponse]:
        devices = await store.list_by_user(claims.subject, include_revoked=include_revoked)
        return [DeviceResponse.of(d) for d in devices]

    @router.get("/{device_id}")
    async def get_device(
        device_id: UUID,
        claims: Claims = Depends(_read),
    ) -> DeviceResponse:
        return DeviceResponse.of(await _owned(device_id, claims))

    @router.post("/{device_id}/pair")
    async def pair(
        device_id: UUID,
        claims: Claims = Depends(_write),
    ) -> DeviceResponse:
        await _owned(device_id, claims)
        try:
            device = await store.activate(device_id)
        except DeviceStateError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
        await kernel.publish(DevicePaired(device_id=str(device_id)), user_id=claims.subject)
        return DeviceResponse.of(device)

    @router.post("/{device_id}/revoke")
    async def revoke(
        device_id: UUID,
        claims: Claims = Depends(_write),
    ) -> DeviceResponse:
        device_previo = await _owned(device_id, claims)
        device = await store.revoke(device_id)
        if device_previo.state is not DeviceState.REVOKED:  # publica só na transição real
            await kernel.publish(DeviceRevoked(device_id=str(device_id)), user_id=claims.subject)
        return DeviceResponse.of(device)

    return router


# canário anti-truncamento
