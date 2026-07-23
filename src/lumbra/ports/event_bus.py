"""Port do Event Bus — contrato único de comunicação entre módulos (ADR-001).

Semântica garantida por qualquer implementação:

* Entrega **at-least-once**: consumidores DEVEM ser idempotentes; as
  implementações deduplicam por ``(consumer, event_id)`` como defesa
  adicional, mas a garantia formal é at-least-once.
* **Ordem por consumidor**: cada consumidor processa seus eventos em
  série (um worker); paralelismo é entre consumidores.
* **Retry com limite**: handler que levanta exceção é reentregue até
  ``max_attempts``; depois o evento vai para a **DLQ** do consumidor.
* **Redrive**: eventos na DLQ podem ser reenfileirados após correção.

Padrões de assinatura: tipo exato (``chat.message_received``),
contexto inteiro (``chat.*``) ou tudo (``*``).
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from lumbra.domain.events import DomainEvent

EventHandler = Callable[[DomainEvent], Awaitable[None]]

_CONSUMER_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_PATTERN_RE = re.compile(r"^(\*|[a-z][a-z0-9_]*\.(\*|[a-z][a-z0-9_]*))$")


class EventBusError(Exception):
    """Erro-base do Event Bus."""


class ConsumerAlreadyRegisteredError(EventBusError):
    def __init__(self, name: str) -> None:
        super().__init__(f"Consumidor já registrado: {name}")


class BusAlreadyStartedError(EventBusError):
    def __init__(self) -> None:
        super().__init__("Registro de consumidores deve ocorrer antes de start()")


class InvalidSubscriptionError(EventBusError):
    def __init__(self, detail: str) -> None:
        super().__init__(f"Assinatura inválida: {detail}")


def pattern_matches(pattern: str, event_type: str) -> bool:
    """Casa um padrão de assinatura com um tipo de evento concreto."""
    if pattern == "*":
        return True
    if pattern.endswith(".*"):
        return event_type.split(".", 1)[0] == pattern[:-2]
    return pattern == event_type


@dataclass(frozen=True, slots=True)
class ConsumerSpec:
    """Declaração de um consumidor de eventos.

    ``max_attempts=None`` usa o padrão da implementação/configuração.
    """

    name: str
    patterns: tuple[str, ...]
    handler: EventHandler
    max_attempts: int | None = None

    def __post_init__(self) -> None:
        if not _CONSUMER_NAME_RE.match(self.name):
            raise InvalidSubscriptionError(
                f"nome de consumidor inválido: {self.name!r} (esperado kebab-case)"
            )
        if not self.patterns:
            raise InvalidSubscriptionError(f"consumidor {self.name!r} sem padrões")
        for pattern in self.patterns:
            if not _PATTERN_RE.match(pattern):
                raise InvalidSubscriptionError(
                    f"padrão inválido: {pattern!r} (use 'ctx.evento', 'ctx.*' ou '*')"
                )
        if self.max_attempts is not None and self.max_attempts < 1:
            raise InvalidSubscriptionError("max_attempts deve ser >= 1")

    def accepts(self, event_type: str) -> bool:
        return any(pattern_matches(p, event_type) for p in self.patterns)


@dataclass(frozen=True, slots=True)
class DeadLetter:
    """Evento que esgotou as tentativas de entrega para um consumidor."""

    consumer: str
    event: DomainEvent
    attempts: int
    last_error: str
    failed_at: datetime


class EventBusPort(ABC):
    """Contrato do Event Bus. Módulos dependem DESTE tipo, nunca de adapters."""

    @abstractmethod
    def register(self, consumer: ConsumerSpec) -> None:
        """Registra um consumidor. Deve ocorrer antes de ``start()``."""

    @abstractmethod
    async def publish(self, event: DomainEvent) -> None:
        """Publica um envelope validado para todos os consumidores compatíveis."""

    @abstractmethod
    async def start(self) -> None:
        """Inicia a entrega. Idempotente."""

    @abstractmethod
    async def stop(self) -> None:
        """Para a entrega graciosamente (aguarda handlers em voo)."""

    @abstractmethod
    async def dead_letters(self, consumer: str, *, limit: int = 100) -> list[DeadLetter]:
        """Inspeciona a DLQ de um consumidor (mais antigos primeiro)."""

    @abstractmethod
    async def redrive(self, consumer: str, event_id: UUID) -> bool:
        """Reenfileira um evento da DLQ. Retorna False se não encontrado."""
