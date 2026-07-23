"""Envelope e registro de eventos de domínio (doc 10).

Este módulo é DOMÍNIO PURO: sem I/O, sem dependência de infraestrutura.
O Event Bus (adaptador) transporta envelopes; a validação de forma e
versionamento acontece aqui, uma única vez, para todo o sistema.

Conceitos:

* ``EventPayload`` — classe-base de payloads tipados e imutáveis.
* ``event`` — decorador que registra um payload sob ``(type, version)``.
* ``DomainEvent`` — envelope padrão (event_id, type, schema_version,
  occurred_at, user_id, correlation_id, causation_id, producer, payload).
* ``EventRegistry`` — resolve ``(type, version) -> payload class`` e
  decodifica envelopes brutos com validação completa.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, ClassVar, TypeVar
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from lumbra.shared.ids import uuid7

# ``contexto.evento_no_passado`` — ex.: chat.message_received
EVENT_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")

TPayload = TypeVar("TPayload", bound="EventPayload")


class EventError(Exception):
    """Erro-base de eventos."""


class UnknownEventTypeError(EventError):
    def __init__(self, event_type: str, version: int) -> None:
        super().__init__(f"Evento não registrado: {event_type} v{version}")
        self.event_type = event_type
        self.version = version


class DuplicateEventTypeError(EventError):
    def __init__(self, event_type: str, version: int) -> None:
        super().__init__(f"Evento já registrado: {event_type} v{version}")


class InvalidEventTypeNameError(EventError, ValueError):
    """Herda ValueError para que o Pydantic a converta em ValidationError
    quando levantada dentro de um field_validator (envelope bruto)."""

    def __init__(self, event_type: str) -> None:
        super().__init__(
            f"Nome de evento inválido: {event_type!r} "
            "(esperado 'contexto.evento_no_passado', ex.: 'chat.message_received')"
        )


class EventPayload(BaseModel):
    """Payload tipado e imutável de um evento de domínio."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Preenchidos pelo decorador ``event``:
    event_type: ClassVar[str]
    schema_version: ClassVar[int]

    def partition_key(self) -> str | None:
        """Chave de particionamento do evento (L2-1).

        Eventos da MESMA chave são processados em ordem; chaves diferentes,
        em paralelo. Cada payload que representa uma entidade sobrescreve
        este método para devolver o identificador dela (``document_id``,
        ``memory_id``, ``conversation_id``, ``user_id``...). O Event Bus
        NUNCA conhece esses campos: quem define a chave é o payload, então
        novos tipos de entidade não exigem mudança no bus.

        O padrão é ``None`` — eventos sem entidade não têm ordem a preservar
        e são distribuídos livremente entre os workers (ver ``routing_key``
        no envelope, que cai para o ``event_id`` nesse caso)."""
        return None


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


class DomainEvent(BaseModel):
    """Envelope padrão de todo evento que cruza o Event Bus."""

    model_config = ConfigDict(frozen=True)

    event_id: UUID = Field(default_factory=uuid7)
    type: str
    schema_version: int = Field(ge=1)
    occurred_at: AwareDatetime = Field(default_factory=_utcnow)
    user_id: UUID | None = None
    correlation_id: UUID = Field(default_factory=uuid7)
    causation_id: UUID | None = None
    producer: str
    payload: dict[str, Any]
    # chave de particionamento resolvida do payload na criação do envelope
    # (ver EventPayload.partition_key). Viaja no envelope serializado, então
    # o consumidor a lê sem redecodificar o payload tipado.
    partition_key: str | None = None

    @field_validator("type")
    @classmethod
    def _validate_type(cls, value: str) -> str:
        if not EVENT_TYPE_PATTERN.match(value):
            raise InvalidEventTypeNameError(value)
        return value

    @property
    def context(self) -> str:
        """Bounded context produtor — prefixo antes do ponto."""
        return self.type.split(".", 1)[0]

    @property
    def routing_key(self) -> str:
        """Chave para o despacho particionado, com o fallback documentado:
        na ausência de ``partition_key`` (evento sem entidade), usa o
        ``event_id`` — cada evento vira sua própria partição, sem ordem a
        garantir e com paralelismo máximo."""
        return self.partition_key or str(self.event_id)

    def follows(self, cause: DomainEvent) -> DomainEvent:
        """Deriva um envelope encadeado: herda correlação, aponta causação."""
        return self.model_copy(
            update={"correlation_id": cause.correlation_id, "causation_id": cause.event_id}
        )


class EventRegistry:
    """Registro de tipos de evento — fonte única de verdade de esquemas.

    Consumidores e produtores compartilham o mesmo registro; um payload
    desconhecido ou malformado falha AQUI, nunca dentro de um handler.
    """

    def __init__(self) -> None:
        self._by_key: dict[tuple[str, int], type[EventPayload]] = {}

    def event(
        self, event_type: str, *, version: int = 1
    ) -> Callable[[type[TPayload]], type[TPayload]]:
        """Decorador: ``@registry.event("chat.message_received")``."""
        if not EVENT_TYPE_PATTERN.match(event_type):
            raise InvalidEventTypeNameError(event_type)
        key = (event_type, version)
        if key in self._by_key:
            raise DuplicateEventTypeError(event_type, version)

        def decorator(payload_cls: type[TPayload]) -> type[TPayload]:
            payload_cls.event_type = event_type
            payload_cls.schema_version = version
            self._by_key[key] = payload_cls
            return payload_cls

        return decorator

    def payload_class(self, event_type: str, version: int = 1) -> type[EventPayload]:
        try:
            return self._by_key[(event_type, version)]
        except KeyError:
            raise UnknownEventTypeError(event_type, version) from None

    def known_types(self) -> frozenset[tuple[str, int]]:
        return frozenset(self._by_key)

    # -------------------------------------------------- produção/consumo

    def envelope(
        self,
        payload: EventPayload,
        *,
        producer: str,
        user_id: UUID | None = None,
        correlation_id: UUID | None = None,
        causation_id: UUID | None = None,
    ) -> DomainEvent:
        """Cria o envelope canônico a partir de um payload registrado."""
        cls = type(payload)
        key = (getattr(cls, "event_type", ""), getattr(cls, "schema_version", 0))
        if self._by_key.get(key) is not cls:
            raise UnknownEventTypeError(cls.__name__, key[1])
        extra: dict[str, Any] = {}
        if correlation_id is not None:
            extra["correlation_id"] = correlation_id
        return DomainEvent(
            type=cls.event_type,
            schema_version=cls.schema_version,
            user_id=user_id,
            causation_id=causation_id,
            producer=producer,
            payload=payload.model_dump(mode="json"),
            partition_key=payload.partition_key(),
            **extra,
        )

    def decode(self, envelope: DomainEvent) -> EventPayload:
        """Valida e materializa o payload tipado de um envelope."""
        cls = self.payload_class(envelope.type, envelope.schema_version)
        return cls.model_validate(envelope.payload)


# Registro global do processo. Módulos registram seus eventos na importação;
# testes podem criar registries isolados.
registry = EventRegistry()
