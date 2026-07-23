"""Event Bus in-memory (asyncio).

Usos: testes (determinístico via ``drain()``) e modo desktop lite, onde
um único processo dispensa Redis. Cumpre integralmente o contrato de
``EventBusPort``: at-least-once, ordem por consumidor, retry, DLQ,
dedup por ``(consumer, event_id)`` e redrive.
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

_log = get_logger("lumbra.eventbus.inmemory")

_QueueItem = tuple[DomainEvent, int]  # (evento, tentativa corrente)


class InMemoryEventBus(EventBusPort):
    """Implementação in-process do Event Bus."""

    def __init__(
        self,
        *,
        default_max_attempts: int = 3,
        retry_delay_seconds: float = 0.0,
    ) -> None:
        if default_max_attempts < 1:
            raise ValueError("default_max_attempts deve ser >= 1")
        self._default_max_attempts = default_max_attempts
        self._retry_delay = retry_delay_seconds
        self._consumers: dict[str, ConsumerSpec] = {}
        self._queues: dict[str, asyncio.Queue[_QueueItem]] = {}
        self._processed: dict[str, set[UUID]] = {}
        self._dead: dict[str, list[DeadLetter]] = {}
        self._workers: list[asyncio.Task[None]] = []
        self._started = False

    # ------------------------------------------------------------ registro

    def register(self, consumer: ConsumerSpec) -> None:
        if self._started:
            raise BusAlreadyStartedError
        if consumer.name in self._consumers:
            raise ConsumerAlreadyRegisteredError(consumer.name)
        self._consumers[consumer.name] = consumer
        self._queues[consumer.name] = asyncio.Queue()
        self._processed[consumer.name] = set()
        self._dead[consumer.name] = []

    # ------------------------------------------------------------ ciclo de vida

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        for spec in self._consumers.values():
            self._workers.append(asyncio.create_task(self._worker(spec)))

    async def stop(self) -> None:
        if not self._started:
            return
        await self.drain()
        for task in self._workers:
            task.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        self._started = False

    async def drain(self) -> None:
        """Aguarda todas as filas esvaziarem (inclui retries). Só para testes/shutdown."""
        await asyncio.gather(*(queue.join() for queue in self._queues.values()))

    # ------------------------------------------------------------ publicação

    async def publish(self, event: DomainEvent) -> None:
        for spec in self._consumers.values():
            if spec.accepts(event.type):
                await self._queues[spec.name].put((event, 1))

    # ------------------------------------------------------------ DLQ

    async def dead_letters(self, consumer: str, *, limit: int = 100) -> list[DeadLetter]:
        return list(self._dead.get(consumer, []))[:limit]

    async def redrive(self, consumer: str, event_id: UUID) -> bool:
        queue = self._dead.get(consumer)
        if queue is None:
            return False
        for index, letter in enumerate(queue):
            if letter.event.event_id == event_id:
                del queue[index]
                self._processed[consumer].discard(event_id)
                await self._queues[consumer].put((letter.event, 1))
                return True
        return False

    # ------------------------------------------------------------ worker

    async def _worker(self, spec: ConsumerSpec) -> None:
        queue = self._queues[spec.name]
        max_attempts = spec.max_attempts or self._default_max_attempts
        while True:
            event, attempt = await queue.get()
            try:
                if event.event_id in self._processed[spec.name]:
                    continue  # idempotência: já processado com sucesso
                await spec.handler(event)
                self._processed[spec.name].add(event.event_id)
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
                    await queue.put((event, attempt + 1))
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
            finally:
                queue.task_done()
