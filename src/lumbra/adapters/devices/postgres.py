"""DeviceStorePort sobre PostgreSQL — mesma interface do in-memory (P1-b.4)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from lumbra.adapters.persistence.database import Database
from lumbra.adapters.persistence.models import DeviceModel
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


def _to_domain(row: DeviceModel) -> Device:
    return Device(
        id=row.id,
        user_id=row.user_id,
        name=row.name,
        platform=DevicePlatform(row.platform),
        public_key=row.public_key,
        state=DeviceState(row.state),
        scopes=tuple(row.scopes),
        created_at=row.created_at,
        paired_at=row.paired_at,
        last_seen_at=row.last_seen_at,
        revoked_at=row.revoked_at,
    )


class PostgresDeviceStore(DeviceStorePort):
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self,
        *,
        user_id: UUID,
        name: str,
        platform: DevicePlatform,
        public_key: str,
        scopes: tuple[str, ...] = (),
    ) -> Device:
        row = DeviceModel(
            id=uuid7(),
            user_id=user_id,
            name=name,
            platform=platform.value,
            public_key=public_key,
            state=DeviceState.PENDING.value,
            scopes=list(scopes),
            created_at=datetime.now(tz=UTC),
        )
        try:
            async with self._db.session() as session:
                session.add(row)
                await session.flush()
                await session.refresh(row)
                return _to_domain(row)
        except IntegrityError:
            raise DuplicatePublicKeyError(public_key) from None

    async def get(self, device_id: UUID) -> Device:
        async with self._db.session() as session:
            row = await session.get(DeviceModel, device_id)
        if row is None:
            raise DeviceNotFoundError
        return _to_domain(row)

    async def get_by_public_key(self, public_key: str) -> Device:
        async with self._db.session() as session:
            result = await session.execute(
                select(DeviceModel).where(DeviceModel.public_key == public_key)
            )
            row = result.scalar_one_or_none()
        if row is None:
            raise DeviceNotFoundError
        return _to_domain(row)

    async def list_by_user(self, user_id: UUID, *, include_revoked: bool = False) -> list[Device]:
        stmt = select(DeviceModel).where(DeviceModel.user_id == user_id)
        if not include_revoked:
            stmt = stmt.where(DeviceModel.state != DeviceState.REVOKED.value)
        stmt = stmt.order_by(DeviceModel.created_at)
        async with self._db.session() as session:
            rows = (await session.execute(stmt)).scalars().all()
        return [_to_domain(r) for r in rows]

    async def activate(self, device_id: UUID) -> Device:
        async with self._db.session() as session:
            row = await session.get(DeviceModel, device_id)
            if row is None:
                raise DeviceNotFoundError
            if row.state == DeviceState.REVOKED.value:
                raise DeviceStateError("dispositivo revogado não pode ser pareado")
            row.state = DeviceState.ACTIVE.value
            row.paired_at = datetime.now(tz=UTC)
            await session.flush()
            await session.refresh(row)
            return _to_domain(row)

    async def revoke(self, device_id: UUID) -> Device:
        async with self._db.session() as session:
            row = await session.get(DeviceModel, device_id)
            if row is None:
                raise DeviceNotFoundError
            if row.state != DeviceState.REVOKED.value:  # idempotente
                row.state = DeviceState.REVOKED.value
                row.revoked_at = datetime.now(tz=UTC)
                await session.flush()
                await session.refresh(row)
            return _to_domain(row)

    async def touch(self, device_id: UUID, *, seen_at: datetime) -> None:
        async with self._db.session() as session:
            row = await session.get(DeviceModel, device_id)
            if row is None:
                raise DeviceNotFoundError
            row.last_seen_at = seen_at
            await session.flush()


# canário anti-truncamento
