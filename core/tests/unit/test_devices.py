"""Modelo de dispositivos: ciclo de vida da identidade e seus eventos."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from lumbra.adapters.devices.in_memory import InMemoryDeviceStore
from lumbra.adapters.security import keys
from lumbra.domain.devices import (
    DevicePaired,
    DeviceRegistered,
    DeviceRevoked,
    register_device_events,
)
from lumbra.domain.events import EventRegistry
from lumbra.ports.devices import (
    DeviceNotFoundError,
    DevicePlatform,
    DeviceState,
    DeviceStateError,
    DuplicatePublicKeyError,
)


def _pub() -> str:
    return keys.generate_keypair()[1]


class TestCicloDeVida:
    async def test_nasce_pendente(self):
        store = InMemoryDeviceStore()
        d = await store.create(
            user_id=uuid4(), name="Notebook", platform=DevicePlatform.LINUX, public_key=_pub()
        )
        assert d.state is DeviceState.PENDING
        assert d.paired_at is None and d.revoked_at is None

    async def test_parear_ativa_e_marca_data(self):
        store = InMemoryDeviceStore()
        d = await store.create(
            user_id=uuid4(), name="Pixel", platform=DevicePlatform.ANDROID, public_key=_pub()
        )
        ativo = await store.activate(d.id)
        assert ativo.state is DeviceState.ACTIVE
        assert ativo.paired_at is not None

    async def test_revogar_marca_data_e_e_idempotente(self):
        store = InMemoryDeviceStore()
        d = await store.create(
            user_id=uuid4(), name="Web", platform=DevicePlatform.WEB, public_key=_pub()
        )
        r1 = await store.revoke(d.id)
        assert r1.state is DeviceState.REVOKED and r1.revoked_at is not None
        r2 = await store.revoke(d.id)  # idempotente
        assert r2.revoked_at == r1.revoked_at

    async def test_revogado_nao_pareia(self):
        store = InMemoryDeviceStore()
        d = await store.create(
            user_id=uuid4(), name="X", platform=DevicePlatform.IOS, public_key=_pub()
        )
        await store.revoke(d.id)
        with pytest.raises(DeviceStateError):
            await store.activate(d.id)


class TestUnicidadeEBusca:
    async def test_chave_publica_nao_se_repete(self):
        store = InMemoryDeviceStore()
        pub = _pub()
        await store.create(
            user_id=uuid4(), name="A", platform=DevicePlatform.WINDOWS, public_key=pub
        )
        with pytest.raises(DuplicatePublicKeyError):
            await store.create(
                user_id=uuid4(), name="B", platform=DevicePlatform.WINDOWS, public_key=pub
            )

    async def test_busca_por_chave_publica(self):
        store = InMemoryDeviceStore()
        pub = _pub()
        criado = await store.create(
            user_id=uuid4(), name="A", platform=DevicePlatform.MACOS, public_key=pub
        )
        assert (await store.get_by_public_key(pub)).id == criado.id

    async def test_ausente_levanta(self):
        store = InMemoryDeviceStore()
        with pytest.raises(DeviceNotFoundError):
            await store.get(uuid4())

    async def test_listar_esconde_revogados_por_padrao(self):
        store = InMemoryDeviceStore()
        user = uuid4()
        a = await store.create(
            user_id=user, name="A", platform=DevicePlatform.LINUX, public_key=_pub()
        )
        b = await store.create(
            user_id=user, name="B", platform=DevicePlatform.ANDROID, public_key=_pub()
        )
        await store.revoke(b.id)
        visiveis = await store.list_by_user(user)
        assert [d.id for d in visiveis] == [a.id]
        assert len(await store.list_by_user(user, include_revoked=True)) == 2

    async def test_touch_atualiza_last_seen(self):
        store = InMemoryDeviceStore()
        d = await store.create(
            user_id=uuid4(), name="A", platform=DevicePlatform.LINUX, public_key=_pub()
        )
        agora = datetime.now(tz=UTC)
        await store.touch(d.id, seen_at=agora)
        assert (await store.get(d.id)).last_seen_at == agora


class TestEventos:
    def test_particionam_por_dispositivo(self):
        did = "0192abcd-0000-7000-8000-000000000000"
        assert (
            DeviceRegistered(device_id=did, user_id="u", platform="android").partition_key()
            == f"device:{did}"
        )
        assert DevicePaired(device_id=did).partition_key() == f"device:{did}"
        assert DeviceRevoked(device_id=did).partition_key() == f"device:{did}"

    def test_registro_idempotente(self):
        reg = EventRegistry()
        register_device_events(reg)
        register_device_events(reg)  # não deve levantar DuplicateEventTypeError
        assert ("identity.device_registered", 1) in reg.known_types()
        assert ("identity.device_paired", 1) in reg.known_types()
        assert ("identity.device_revoked", 1) in reg.known_types()

    def test_envelope_carrega_partition_key(self):
        reg = EventRegistry()
        register_device_events(reg)
        env = reg.envelope(DevicePaired(device_id="abc"), producer="test")
        assert env.partition_key == "device:abc"
        assert env.routing_key == "device:abc"


# canário anti-truncamento
