"""Testes do InMemoryEventBus: entrega, ordem, retry, DLQ, idempotência, redrive."""

import asyncio

import pytest

from lumbra.adapters.eventbus.in_memory import InMemoryEventBus
from lumbra.domain.events import EventPayload, EventRegistry
from lumbra.ports.event_bus import (
    BusAlreadyStartedError,
    ConsumerAlreadyRegisteredError,
    ConsumerSpec,
)


@pytest.fixture()
def reg() -> EventRegistry:
    registry = EventRegistry()

    @registry.event("chat.message_received")
    class _Msg(EventPayload):
        text: str

    @registry.event("health.dose_due")
    class _Dose(EventPayload):
        dose_id: str

    return registry


def _msg(reg: EventRegistry, text: str):
    cls = reg.payload_class("chat.message_received")
    return reg.envelope(cls(text=text), producer="test")


@pytest.fixture()
async def bus():
    bus = InMemoryEventBus(default_max_attempts=3)
    yield bus
    await bus.stop()


class TestDelivery:
    async def test_only_matching_consumers_receive(self, bus, reg):
        chat_seen, health_seen, all_seen = [], [], []

        bus.register(ConsumerSpec("chat-c", ("chat.*",), lambda e: _collect(chat_seen, e)))
        bus.register(ConsumerSpec("health-c", ("health.*",), lambda e: _collect(health_seen, e)))
        bus.register(ConsumerSpec("audit-c", ("*",), lambda e: _collect(all_seen, e)))
        await bus.start()

        await bus.publish(_msg(reg, "olá"))
        dose_cls = reg.payload_class("health.dose_due")
        await bus.publish(reg.envelope(dose_cls(dose_id="d1"), producer="test"))
        await bus.drain()

        assert [e.type for e in chat_seen] == ["chat.message_received"]
        assert [e.type for e in health_seen] == ["health.dose_due"]
        assert len(all_seen) == 2

    async def test_order_preserved_per_consumer(self, bus, reg):
        seen = []
        bus.register(ConsumerSpec("c", ("chat.*",), lambda e: _collect(seen, e)))
        await bus.start()
        for i in range(50):
            await bus.publish(_msg(reg, f"m{i}"))
        await bus.drain()
        assert [e.payload["text"] for e in seen] == [f"m{i}" for i in range(50)]

    async def test_duplicate_event_processed_once(self, bus, reg):
        seen = []
        bus.register(ConsumerSpec("c", ("chat.*",), lambda e: _collect(seen, e)))
        await bus.start()
        event = _msg(reg, "dup")
        await bus.publish(event)
        await bus.publish(event)  # mesmo event_id
        await bus.drain()
        assert len(seen) == 1


class TestRetryAndDlq:
    async def test_retries_then_succeeds(self, bus, reg):
        calls = {"n": 0}

        async def flaky(event):
            calls["n"] += 1
            if calls["n"] < 3:
                raise RuntimeError("transiente")

        bus.register(ConsumerSpec("c", ("chat.*",), flaky, max_attempts=5))
        await bus.start()
        await bus.publish(_msg(reg, "x"))
        await bus.drain()
        assert calls["n"] == 3
        assert await bus.dead_letters("c") == []

    async def test_exhausted_attempts_go_to_dlq(self, bus, reg):
        async def always_fails(event):
            raise RuntimeError("boom")

        bus.register(ConsumerSpec("c", ("chat.*",), always_fails, max_attempts=2))
        await bus.start()
        event = _msg(reg, "x")
        await bus.publish(event)
        await bus.drain()

        letters = await bus.dead_letters("c")
        assert len(letters) == 1
        assert letters[0].event.event_id == event.event_id
        assert letters[0].attempts == 2
        assert "boom" in letters[0].last_error

    async def test_failure_isolated_per_consumer(self, bus, reg):
        seen = []

        async def fails(event):
            raise RuntimeError("boom")

        bus.register(ConsumerSpec("bad", ("chat.*",), fails, max_attempts=1))
        bus.register(ConsumerSpec("good", ("chat.*",), lambda e: _collect(seen, e)))
        await bus.start()
        await bus.publish(_msg(reg, "x"))
        await bus.drain()
        assert len(seen) == 1  # consumidor saudável não é afetado

    async def test_redrive_reprocesses(self, bus, reg):
        attempts = {"n": 0}

        async def fails_once_batch(event):
            attempts["n"] += 1
            if attempts["n"] <= 2:  # falha as 2 primeiras entregas (max_attempts=2)
                raise RuntimeError("boom")

        bus.register(ConsumerSpec("c", ("chat.*",), fails_once_batch, max_attempts=2))
        await bus.start()
        event = _msg(reg, "x")
        await bus.publish(event)
        await bus.drain()
        assert len(await bus.dead_letters("c")) == 1

        assert await bus.redrive("c", event.event_id) is True
        await bus.drain()
        assert await bus.dead_letters("c") == []
        assert attempts["n"] == 3

    async def test_redrive_unknown_returns_false(self, bus, reg):
        bus.register(ConsumerSpec("c", ("chat.*",), _noop))
        await bus.start()
        assert await bus.redrive("c", _msg(reg, "x").event_id) is False


class TestLifecycle:
    async def test_register_after_start_rejected(self, bus):
        await bus.start()
        with pytest.raises(BusAlreadyStartedError):
            bus.register(ConsumerSpec("c", ("*",), _noop))

    async def test_duplicate_consumer_rejected(self, bus):
        bus.register(ConsumerSpec("c", ("*",), _noop))
        with pytest.raises(ConsumerAlreadyRegisteredError):
            bus.register(ConsumerSpec("c", ("*",), _noop))

    async def test_stop_is_graceful_and_idempotent(self, bus, reg):
        seen = []
        bus.register(ConsumerSpec("c", ("*",), lambda e: _collect(seen, e)))
        await bus.start()
        await bus.publish(_msg(reg, "x"))
        await bus.stop()
        await bus.stop()
        assert len(seen) == 1  # evento em voo foi concluído antes de parar


async def _collect(sink: list, event) -> None:
    sink.append(event)


async def _noop(_event) -> None:
    return None


# ---------------------------------------------------------------- concorrência (L2-1)


@pytest.fixture()
def reg_keyed() -> EventRegistry:
    """Registro com um evento que declara partition_key (por entidade)."""
    registry = EventRegistry()

    @registry.event("doc.stage")
    class _Stage(EventPayload):
        document_id: str
        step: int

        def partition_key(self) -> str:
            return f"document:{self.document_id}"

    return registry


def _stage(reg: EventRegistry, document_id: str, step: int):
    cls = reg.payload_class("doc.stage")
    return reg.envelope(cls(document_id=document_id, step=step), producer="test")


class TestConcurrency:
    async def test_ordem_por_entidade_preservada_com_paralelismo(self, reg_keyed):
        """Com vários workers, cada documento mantém a ordem dos seus passos."""
        bus = InMemoryEventBus(concurrency=8)
        vistos: dict[str, list[int]] = {"A": [], "B": [], "C": []}

        async def handler(event) -> None:
            await asyncio.sleep(0.001)  # jitter para expor corrida
            vistos[event.payload["document_id"]].append(event.payload["step"])

        bus.register(ConsumerSpec("c", ("doc.*",), handler))
        await bus.start()
        try:
            for step in range(30):
                for doc in vistos:
                    await bus.publish(_stage(reg_keyed, doc, step))
            await bus.drain()
        finally:
            await bus.stop()
        for doc, passos in vistos.items():
            assert passos == list(range(30)), f"ordem quebrada em {doc}"

    async def test_entidades_diferentes_em_paralelo(self, reg_keyed):
        """Documentos distintos não se bloqueiam entre si."""
        bus = InMemoryEventBus(concurrency=16)
        barreira = asyncio.Event()
        chegaram = 0

        async def handler(_event) -> None:
            nonlocal chegaram
            chegaram += 1
            await asyncio.wait_for(barreira.wait(), timeout=2.0)

        bus.register(ConsumerSpec("c", ("doc.*",), handler))
        await bus.start()
        try:
            for i in range(10):
                await bus.publish(_stage(reg_keyed, f"doc-{i}", 0))
            await asyncio.sleep(0.1)
            assert chegaram == 10, "documentos não rodaram em paralelo"
            barreira.set()
            await bus.drain()
        finally:
            await bus.stop()

    async def test_dedup_sob_concorrencia(self, reg_keyed):
        """O mesmo evento, publicado duas vezes, processa uma só vez mesmo
        com vários workers (a chave garante o mesmo worker)."""
        bus = InMemoryEventBus(concurrency=8)
        contagem = 0

        async def handler(_event) -> None:
            nonlocal contagem
            contagem += 1

        bus.register(ConsumerSpec("c", ("doc.*",), handler))
        await bus.start()
        try:
            evento = _stage(reg_keyed, "X", 1)
            await bus.publish(evento)
            await bus.publish(evento)  # mesmo event_id
            await bus.drain()
        finally:
            await bus.stop()
        assert contagem == 1

    async def test_metricas_expostas(self, reg_keyed):
        bus = InMemoryEventBus(concurrency=4)
        bus.register(ConsumerSpec("c", ("doc.*",), _noop))
        await bus.start()
        try:
            for i in range(20):
                await bus.publish(_stage(reg_keyed, f"d{i % 5}", i))
            await bus.drain()
            m = bus.dispatcher_metrics("c")
            assert m.total_processed == 20
            assert m.workers == 4
        finally:
            await bus.stop()
