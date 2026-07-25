"""Integração: PostgresDeviceStore (migração 0008, ADR-045).

O adapter Postgres tem de honrar o MESMO contrato do in-memory — os testes
unitários já cobrem a semântica; aqui garantimos que a migração e o SQL
real se comportam igual (unicidade de chave, ciclo de vida, ordenação).
"""

import uuid

import pytest

from lumbra.adapters.devices.postgres import PostgresDeviceStore
from lumbra.adapters.security import keys
from lumbra.adapters.users.postgres import PostgresUserStore
from lumbra.ports.devices import (
    DeviceNotFoundError,
    DevicePlatform,
    DeviceState,
    DeviceStateError,
    DuplicatePublicKeyError,
)

pytestmark = pytest.mark.integration


async def _user(db):
    return await PostgresUserStore(db).create(
        email=f"dev-{uuid.uuid4().hex[:8]}@lumbra.app", password_hash="h"
    )


def _pub() -> str:
    return keys.generate_keypair()[1]


class TestCicloDeVida:
    async def test_registra_pareia_revoga(self, db):
        store = PostgresDeviceStore(db)
        user = await _user(db)
        d = await store.create(
            user_id=user.id,
            name="Pixel",
            platform=DevicePlatform.ANDROID,
            public_key=_pub(),
            scopes=("chat:read", "memory:read"),
        )
        assert d.state is DeviceState.PENDING
        assert set(d.scopes) == {"chat:read", "memory:read"}

        ativo = await store.activate(d.id)
        assert ativo.state is DeviceState.ACTIVE and ativo.paired_at is not None

        revogado = await store.revoke(d.id)
        assert revogado.state is DeviceState.REVOKED and revogado.revoked_at is not None
        with pytest.raises(DeviceStateError):
            await store.activate(d.id)

    async def test_revoke_idempotente(self, db):
        store = PostgresDeviceStore(db)
        user = await _user(db)
        d = await store.create(
            user_id=user.id, name="A", platform=DevicePlatform.WEB, public_key=_pub()
        )
        r1 = await store.revoke(d.id)
        r2 = await store.revoke(d.id)
        assert r1.revoked_at == r2.revoked_at


class TestUnicidadeEBusca:
    async def test_chave_publica_unica(self, db):
        store = PostgresDeviceStore(db)
        user = await _user(db)
        pub = _pub()
        await store.create(user_id=user.id, name="A", platform=DevicePlatform.LINUX, public_key=pub)
        with pytest.raises(DuplicatePublicKeyError):
            await store.create(
                user_id=user.id, name="B", platform=DevicePlatform.LINUX, public_key=pub
            )

    async def test_busca_por_chave_e_ausente(self, db):
        store = PostgresDeviceStore(db)
        user = await _user(db)
        pub = _pub()
        criado = await store.create(
            user_id=user.id, name="A", platform=DevicePlatform.MACOS, public_key=pub
        )
        assert (await store.get_by_public_key(pub)).id == criado.id
        with pytest.raises(DeviceNotFoundError):
            await store.get(uuid.uuid4())

    async def test_lista_por_usuario_esconde_revogados(self, db):
        store = PostgresDeviceStore(db)
        user = await _user(db)
        a = await store.create(
            user_id=user.id, name="A", platform=DevicePlatform.LINUX, public_key=_pub()
        )
        b = await store.create(
            user_id=user.id, name="B", platform=DevicePlatform.ANDROID, public_key=_pub()
        )
        await store.revoke(b.id)
        visiveis = await store.list_by_user(user.id)
        assert [d.id for d in visiveis] == [a.id]
        assert len(await store.list_by_user(user.id, include_revoked=True)) == 2


# canário anti-truncamento
