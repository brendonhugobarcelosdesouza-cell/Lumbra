"""Integração: RedisStreamsEventBus contra Redis real.

Requer Redis em LUMBRA_REDIS__URL (padrão: localhost:6379).
Execute com: pytest -m integration
"""

import asyncio
import uuid

import pytest
from redis.asyncio import Redis

from lumbra.adapters.eventbus.redis_streams import RedisStreamsEventBus
from lumbra.domain.events import EventPayload, EventRegistry
from lumbra.ports.event_bus import ConsumerSpec
from lumbra.shared.config import RedisSettings

pytestmark = pytest.mark.integration


@pytest.fixture()
def settings() -> RedisSettings:
    # prefixo único por teste: isolamento total entre execuções
    return RedisSettings(
        stream_prefix=f"lumbra-test-{uuid.uuid4().hex[:8]}",
        consumer_block_ms=200,
        retry_min_idle_ms=200,
        max_delivery_attempts=2,
    )


@pytest.fixture()
async def redis(settings: RedisSettings):
    client = Redis.from_url(settings.url.get_secret_value())
    try:
        await client.ping()
    except Exception:
        pytest.skip("Redis indisponível")
    yield client
    # limpeza das chaves do teste
    keys = [k async for k in client.scan_iter(f"{settings.stream_prefix}:*")]
    if keys:
        await client.delete(*keys)
    await client.aclose()


@pytest.fixture()
def reg() -> EventRegistry:
    registry = EventRegistry()

    @registry.event("chat.message_received")
    class _Msg(EventPayload):
        text: str

    @registry.event("doc.stage")
    class _Stage(EventPayload):
        document_id: str
        step: int

        def partition_key(self) -> str:
            return f"document:{self.document_id}"

    return registry


def _msg(reg: EventRegistry, text: str):
    cls = reg.payload_class("chat.message_received")
    return reg.envelope(cls(text=text), producer="it")


def _stage(reg: EventRegistry, document_id: str, step: int):
    cls = reg.payload_class("doc.stage")
    return reg.envelope(cls(document_id=document_id, step=step), producer="it")


async def _wait_until(predicate, timeout: float = 5.0):
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.05)
    return False


async def test_publish_consume_ack(redis, reg, settings):
    seen = []

    async def handler(event):
        seen.append(event)

    bus = RedisStreamsEventBus(redis, reg, settings)
    bus.register(ConsumerSpec("it-consumer", ("chat.*",), handler))
    await bus.start()
    try:
        event = _msg(reg, "olá integração")
        await bus.publish(event)
        assert await _wait_until(lambda: len(seen) == 1)
        assert seen[0].event_id == event.event_id
        assert seen[0].payload["text"] == "olá integração"
    finally:
        await bus.stop()


async def test_duplicate_delivery_is_idempotent(redis, reg, settings):
    seen = []

    async def handler(event):
        seen.append(event)

    bus = RedisStreamsEventBus(redis, reg, settings)
    bus.register(ConsumerSpec("it-consumer", ("chat.message_received",), handler))
    await bus.start()
    try:
        event = _msg(reg, "x")
        await bus.publish(event)
        await bus.publish(event)  # mesmo event_id em duas mensagens
        await asyncio.sleep(1.0)
        assert len(seen) == 1
    finally:
        await bus.stop()


async def test_retry_then_dlq_and_redrive(redis, reg, settings):
    calls = {"n": 0}
    healthy = {"on": False}

    async def handler(event):
        calls["n"] += 1
        if not healthy["on"]:
            raise RuntimeError("boom")

    bus = RedisStreamsEventBus(redis, reg, settings)
    bus.register(ConsumerSpec("it-consumer", ("chat.*",), handler))
    await bus.start()
    try:
        event = _msg(reg, "vai falhar")
        await bus.publish(event)

        # max_delivery_attempts=2 → 2 falhas e DLQ
        assert await _wait_until_async(
            lambda: bus.dead_letters("it-consumer"), lambda v: len(v) == 1
        )
        assert calls["n"] == 2

        # corrige o handler e faz redrive
        healthy["on"] = True
        assert await bus.redrive("it-consumer", event.event_id) is True
        assert await _wait_until(lambda: calls["n"] >= 3, timeout=8.0)
        assert await bus.dead_letters("it-consumer") == []
    finally:
        await bus.stop()


async def test_partitioned_order_preserved_under_concurrency(redis, reg, settings):
    """Com concorrência>1, os passos de um MESMO documento chegam em ordem;
    documentos distintos podem ser processados em paralelo (L2-1)."""
    settings = settings.model_copy(update={"consumer_concurrency": 8})
    vistos: dict[str, list[int]] = {"A": [], "B": [], "C": []}

    async def handler(event):
        await asyncio.sleep(0.002)  # jitter para expor corrida de ordem
        vistos[event.payload["document_id"]].append(event.payload["step"])

    bus = RedisStreamsEventBus(redis, reg, settings)
    bus.register(ConsumerSpec("it-consumer", ("doc.*",), handler))
    await bus.start()
    try:
        for step in range(20):
            for doc in vistos:
                await bus.publish(_stage(reg, doc, step))
        assert await _wait_until(lambda: sum(len(v) for v in vistos.values()) == 60, timeout=15.0)
        for doc, passos in vistos.items():
            assert passos == list(range(20)), f"ordem quebrada em {doc}"
        # o dispatcher realmente distribuiu entre workers
        assert bus.dispatcher_metrics("it-consumer").total_processed == 60
    finally:
        await bus.stop()


async def test_recovery_after_worker_crash(redis, reg, settings):
    """Mensagem lida por um worker que 'morreu' antes do ACK (ficou no PEL)
    é reclamada e processada por outra instância — recuperação após falha
    (L2-2)."""
    settings = settings.model_copy(update={"retry_min_idle_ms": 200})
    seen = []

    async def handler(event):
        seen.append(event)

    stream = f"{settings.stream_prefix}:events:doc.stage"
    group = "it-consumer"
    event = _stage(reg, "D", 1)

    # simula o crash: cria o grupo, injeta a mensagem e a entrega a um
    # worker que "morre" sem confirmar — ela fica pendente no PEL dele
    await redis.xgroup_create(stream, group, id="0", mkstream=True)
    await redis.xadd(stream, {b"envelope": event.model_dump_json()})
    morto = await redis.xreadgroup(
        groupname=group, consumername="worker-morto", streams={stream: ">"}, count=1
    )
    assert morto  # a mensagem está no PEL do worker morto, sem ACK

    # sobe uma instância viva: o reader não vê a mensagem em ">" (já foi
    # entregue), mas o reclaim a rouba do worker morto após o idle
    bus = RedisStreamsEventBus(redis, reg, settings)
    bus.register(ConsumerSpec(group, ("doc.*",), handler))
    await bus.start()
    try:
        assert await _wait_until(lambda: len(seen) == 1, timeout=10.0)
        assert seen[0].payload["document_id"] == "D"
    finally:
        await bus.stop()


async def test_health_reports_metrics_and_lag(redis, reg, settings):
    """A saúde do bus reporta throughput, backlog/pendentes e DLQ (L2-3)."""
    seen = []

    async def handler(event):
        seen.append(event)

    bus = RedisStreamsEventBus(redis, reg, settings)
    bus.register(ConsumerSpec("it-consumer", ("chat.*",), handler))
    await bus.start()
    try:
        for i in range(5):
            await bus.publish(_msg(reg, f"m{i}"))
        assert await _wait_until(lambda: len(seen) == 5, timeout=10.0)

        health = await bus.health()
        assert health.kind == "redis"
        (ch,) = health.consumers
        assert ch.consumer == "it-consumer"
        assert ch.dispatcher.total_processed == 5
        assert ch.backlog == 0  # tudo entregue e consumido
        assert ch.pending == 0  # tudo confirmado
        assert ch.dead_letters == 0
    finally:
        await bus.stop()


async def test_load_throughput_redis(redis, reg, settings):
    """Carga no Redis real: mede throughput ponta a ponta e confirma que a
    saúde reporta backlog zerado ao fim (L2-4). Instrumento, não gate."""
    settings = settings.model_copy(update={"consumer_concurrency": 8})
    processados = 0

    async def handler(_event):
        nonlocal processados
        processados += 1

    bus = RedisStreamsEventBus(redis, reg, settings)
    bus.register(ConsumerSpec("it-consumer", ("doc.*",), handler))
    await bus.start()
    total = 2_000
    try:
        inicio = asyncio.get_event_loop().time()
        for i in range(total):
            await bus.publish(_stage(reg, f"d{i % 200}", i))
        assert await _wait_until(lambda: processados == total, timeout=30.0)
        elapsed = asyncio.get_event_loop().time() - inicio
        health = await bus.health()
        print(  # noqa: T201 - baseline imprime numeros
            f"\nbus Redis (8 workers): {total} eventos em {elapsed * 1000:.0f}ms "
            f"-> {total / elapsed:,.0f} ev/s | backlog {health.consumers[0].backlog}"
        )
        assert health.consumers[0].backlog == 0
    finally:
        await bus.stop()


async def _wait_until_async(coro_factory, check, timeout: float = 8.0):
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if check(await coro_factory()):
            return True
        await asyncio.sleep(0.1)
    return False
