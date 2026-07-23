"""Testes do InMemoryEventBus: entrega, ordem, retry, DLQ, idempotência, redrive."""

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
