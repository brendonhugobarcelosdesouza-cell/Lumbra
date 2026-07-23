"""Event Bus in-memory (asyncio).

Usos: testes (determinístico via ``drain()``) e modo desktop lite, onde
um único processo dispensa Redis. Cumpre integralmente o contrato de
``EventBusPort``: at-least-once, retry, DLQ, dedup por
``(consumer, event_id)`` e redrive.

Ordem (L2-1): cada consumidor tem um ``PartitionedDispatcher``. Com
``concurrency=1`` (padrão), há um único worker e a ordem é global por
consumidor — o comportamento determinístico que os testes esperam. Com
``concurrency>1``, a garantia passa a ser ordem por ``routing_key``
(mesma entidade em ordem, entidades diferentes em paralelo).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from lumbra.domain.events import DomainEvent
from lumbra.ports.event_bus import (
    BusAlreadyStartedError,
    ConsumerAlreadyRegisteredError,
    ConsumerSpec,
    DeadLetter,
    EventBusPort,
)
from lumbra.shared.logging import get_logger
from lumbra.shared.partitioning import DispatcherMetrics, PartitionedDispatcher

_log = get_logger("lumbra.eventbus.inmemory")


class InMemoryEventBus(EventBusPort):
    """Implementação in-process do Event Bus."""

    def __init__(
        self,
        *,
        default_max_attempts: int = 3,
        retry_delay_seconds: float = 0.0,
        concurrency: int = 1,
    ) -> None:
        if default_max_attempts < 1:
            raise ValueError("default_max_attempts deve ser >= 1")
        if concurrency < 1:
            raise ValueError("concurrency deve ser >= 1")
        self._default_max_attempts = default_max_attempts
        self._retry_delay = retry_delay_seconds
        self._concurrency = concurrency
        self._consumers: dict[str, ConsumerSpec] = {}
        self._dispatchers: dict[str, PartitionedDispatcher] = {}
        self._processed: dict[str, set[UUID]] = {}
        self._dead: dict[str, list[DeadLetter]] = {}
        self._started = False

    # ------------------------------------------------------------ registro

    def register(self, consumer: ConsumerSpec) -> None:
        if self._started:
            raise BusAlreadyStartedError
        if consumer.name in self._consumers:
            raise ConsumerAlreadyRegisteredError(consumer.name)
        self._consumers[consumer.name] = consumer
        self._dispatchers[consumer.name] = PartitionedDispatcher(
            workers=self._concurrency, name=f"inmem:{consumer.name}"
        )
        self._processed[consumer.name] = set()
        self._dead[consumer.name] = []

    # ------------------------------------------------------------ ciclo de vida

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        for dispatcher in self._dispatchers.values():
            await dispatcher.start()

    async def stop(self) -> None:
        if not self._started:
            return
        await self.drain()
        for dispatcher in self._dispatchers.values():
            await dispatcher.stop(drain=False)  # já drenado acima
        self._started = False

    async def drain(self) -> None:
        """Aguarda todas as filas esvaziarem (inclui retries). Só para testes/shutdown."""
        await asyncio.gather(*(d.join() for d in self._dispatchers.values()))

    def dispatcher_metrics(self, consumer: str) -> DispatcherMetrics:
        """Instantâneo de métricas do dispatcher do consumidor (L2-3)."""
        return self._dispatchers[consumer].metrics()

    # ------------------------------------------------------------ publicação

    async def publish(self, event: DomainEvent) -> None:
        for spec in self._consumers.values():
            if spec.accepts(event.type):
                await self._enqueue(spec, event, attempt=1)

    async def _enqueue(self, spec: ConsumerSpec, event: DomainEvent, attempt: int) -> None:
        # roteia pela chave de partição: mesma entidade -> mesmo worker -> ordem
        await self._dispatchers[spec.name].submit(
            event.routing_key,
            lambda: self._process(spec, event, attempt),
            reprocess=attempt > 1,
        )

    async def _process(self, spec: ConsumerSpec, event: DomainEvent, attempt: int) -> None:
        max_attempts = spec.max_attempts or self._default_max_attempts
        if event.event_id in self._processed[spec.name]:
            return  # idempotência: já processado com sucesso
        try:
            await spec.handler(event)
        except Exception as exc:
            if attempt < max_attempts:
                _log.warning(
                    "event_retry",
                    consumer=spec.name,
                    event_type=event.type,
                    event_id=str(event.event_id),
                    attempt=attempt,
                )
                if self._retry_delay:
                    await asyncio.sleep(self._retry_delay)
                # re-submete ANTES de retornar: o drain() enxerga a reentrega
                await self._enqueue(spec, event, attempt + 1)
            else:
                _log.error(
                    "event_dead_lettered",
                    consumer=spec.name,
                    event_type=event.type,
                    event_id=str(event.event_id),
                    attempts=attempt,
                    error=repr(exc),
                )
                self._dead[spec.name].append(
                    DeadLetter(
                        consumer=spec.name,
                        event=event,
                        attempts=attempt,
                        last_error=repr(exc),
                        failed_at=datetime.now(tz=UTC),
                    )
                )
        else:
            self._processed[spec.name].add(event.event_id)

    # ------------------------------------------------------------ DLQ

    async def dead_letters(self, consumer: str, *, limit: int = 100) -> list[DeadLetter]:
        return list(self._dead.get(consumer, []))[:limit]

    async def redrive(self, consumer: str, event_id: UUID) -> bool:
        queue = self._dead.get(consumer)
        if queue is None:
            return False
        spec = self._consumers[consumer]
        for index, letter in enumerate(queue):
            if letter.event.event_id == event_id:
                del queue[index]
                self._processed[consumer].discard(event_id)
                await self._enqueue(spec, letter.event, attempt=1)
                return True
        return False


# canário anti-truncamento
