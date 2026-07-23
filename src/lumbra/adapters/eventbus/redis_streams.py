"""Event Bus sobre Redis Streams (ADR-004, ADR-014).

Topologia:

* Um stream por tipo de evento: ``{prefix}:events:{tipo}`` — consumo
  seletivo sem filtragem no cliente.
* Um consumer group por consumidor em cada stream assinado; padrões
  (``ctx.*``, ``*``) são expandidos contra o ``EventRegistry`` no
  ``start()`` — o catálogo de eventos é a fonte de verdade.
* Idempotência: chave ``{prefix}:dedup:{consumer}:{event_id}`` com TTL
  (``SET NX``); segunda entrega do mesmo evento é ACK sem reprocesso.
* Retry / recuperação após crash: mensagem não-ACK (handler falhou ou o
  processo morreu antes do ACK) reaparece via ``XPENDING`` + ``XCLAIM``
  após ``retry_min_idle_ms``; ao exceder ``max_delivery_attempts`` vai
  para a DLQ ``{prefix}:dlq:{consumer}`` (limitada por ``dlq_maxlen``) e é
  ACK no stream de origem.
* Redrive: reenfileira do DLQ para o stream de origem e remove a entrada.
* Resiliência (L2-2): ``publish`` e o laço de consumo reentram com backoff
  exponencial (com teto) em quedas de conexão; o consumo particiona por
  chave (ADR-038) com paralelismo configurável por ``consumer_concurrency``.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError
from redis.exceptions import TimeoutError as RedisTimeoutError

from lumbra.domain.events import DomainEvent, EventRegistry
from lumbra.ports.event_bus import (
    BusAlreadyStartedError,
    ConsumerAlreadyRegisteredError,
    ConsumerSpec,
    DeadLetter,
    EventBusPort,
    pattern_matches,
)
from lumbra.shared.config import RedisSettings
from lumbra.shared.logging import get_logger
from lumbra.shared.partitioning import DispatcherMetrics, PartitionedDispatcher

if TYPE_CHECKING:
    from collections.abc import Sequence

_log = get_logger("lumbra.eventbus.redis")

_ENVELOPE_FIELD = b"envelope"

# quedas de conexão que merecem backoff+reentrega (não erros de lógica)
_TRANSIENT = (RedisConnectionError, RedisTimeoutError)


def backoff_ms(attempt: int, *, base_ms: int, cap_ms: int) -> float:
    """Backoff exponencial com teto: ``base * 2^(attempt-1)``, limitado a
    ``cap``. ``attempt`` começa em 1; ``attempt<=0`` não espera.

    Determinístico (sem jitter): é uma plataforma pessoal de um processo,
    não há efeito manada a amortecer, e o determinismo facilita o teste."""
    if attempt <= 0:
        return 0.0
    return float(min(cap_ms, base_ms * (2 ** (attempt - 1))))


class RedisStreamsEventBus(EventBusPort):
    """Implementação distribuída do Event Bus para o perfil cloud/desktop completo."""

    def __init__(
        self,
        redis: Redis,
        registry: EventRegistry,
        settings: RedisSettings,
    ) -> None:
        self._redis = redis
        self._registry = registry
        self._settings = settings
        self._consumers: dict[str, ConsumerSpec] = {}
        self._streams_by_consumer: dict[str, list[str]] = {}
        # um dispatcher por consumidor: paraleliza o processamento por chave
        # de partição, preservando a ordem dentro de cada entidade (L2-1)
        self._dispatchers: dict[str, PartitionedDispatcher] = {}
        self._workers: list[asyncio.Task[None]] = []
        self._started = False
        self._stopping = asyncio.Event()

    # ------------------------------------------------------------ chaves

    def _stream_key(self, event_type: str) -> str:
        return f"{self._settings.stream_prefix}:events:{event_type}"

    def _dlq_key(self, consumer: str) -> str:
        return f"{self._settings.stream_prefix}:dlq:{consumer}"

    def _dedup_key(self, consumer: str, event_id: UUID) -> str:
        return f"{self._settings.stream_prefix}:dedup:{consumer}:{event_id}"

    # ------------------------------------------------------------ registro

    def register(self, consumer: ConsumerSpec) -> None:
        if self._started:
            raise BusAlreadyStartedError
        if consumer.name in self._consumers:
            raise ConsumerAlreadyRegisteredError(consumer.name)
        self._consumers[consumer.name] = consumer

    def _resolve_streams(self, spec: ConsumerSpec) -> list[str]:
        """Expande padrões contra o catálogo de eventos registrado."""
        known = sorted({event_type for event_type, _version in self._registry.known_types()})
        matched = {
            event_type
            for event_type in known
            for pattern in spec.patterns
            if pattern_matches(pattern, event_type)
        }
        # tipos exatos são assinados mesmo se ainda não constam do registro
        matched.update(p for p in spec.patterns if "*" not in p)
        return sorted(self._stream_key(event_type) for event_type in matched)

    # ------------------------------------------------------------ ciclo de vida

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._stopping.clear()
        for spec in self._consumers.values():
            streams = self._resolve_streams(spec)
            self._streams_by_consumer[spec.name] = streams
            for stream in streams:
                await self._ensure_group(stream, spec.name)
            dispatcher = PartitionedDispatcher(
                workers=self._settings.consumer_concurrency, name=f"redis:{spec.name}"
            )
            await dispatcher.start()
            self._dispatchers[spec.name] = dispatcher
            self._workers.append(asyncio.create_task(self._consume_loop(spec)))

    async def stop(self) -> None:
        if not self._started:
            return
        self._stopping.set()
        # 1) o leitor para de submeter; 2) drena o que já foi lido; 3) encerra
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        for dispatcher in self._dispatchers.values():
            await dispatcher.stop(drain=True)
        self._dispatchers.clear()
        self._started = False

    def dispatcher_metrics(self, consumer: str) -> DispatcherMetrics:
        """Instantâneo de métricas do dispatcher do consumidor (L2-3)."""
        return self._dispatchers[consumer].metrics()

    async def _ensure_group(self, stream: str, group: str) -> None:
        try:
            await self._redis.xgroup_create(stream, group, id="0", mkstream=True)
        except ResponseError as exc:  # grupo já existe — idempotente
            if "BUSYGROUP" not in str(exc):
                raise

    # ------------------------------------------------------------ publicação

    async def publish(self, event: DomainEvent) -> None:
        # reentrega em blip de rede: um xadd repetido pode duplicar a
        # mensagem, mas o dedup do consumidor a torna idempotente (ADR-014).
        # Melhor duplicar e ser entregue do que perder o evento.
        attempt = 0
        while True:
            try:
                await self._redis.xadd(
                    self._stream_key(event.type),
                    {_ENVELOPE_FIELD: event.model_dump_json()},
                    maxlen=self._settings.stream_maxlen,
                    approximate=True,
                )
                return
            except _TRANSIENT as exc:
                attempt += 1
                if attempt > self._settings.publish_max_retries:
                    raise
                delay = self._backoff(attempt)
                _log.warning(
                    "publish_retry",
                    event_type=event.type,
                    event_id=str(event.event_id),
                    attempt=attempt,
                    backoff_s=round(delay, 3),
                    error=repr(exc),
                )
                await asyncio.sleep(delay)

    def _backoff(self, attempt: int) -> float:
        return (
            backoff_ms(
                attempt,
                base_ms=self._settings.reconnect_backoff_base_ms,
                cap_ms=self._settings.reconnect_backoff_cap_ms,
            )
            / 1000
        )

    # ------------------------------------------------------------ consumo

    async def _consume_loop(self, spec: ConsumerSpec) -> None:
        streams = self._streams_by_consumer[spec.name]
        if not streams:
            return
        block_ms = min(self._settings.consumer_block_ms, 1_000)
        falhas = 0  # ciclos consecutivos com erro, para o backoff exponencial
        while not self._stopping.is_set():
            try:
                response = await self._redis.xreadgroup(
                    groupname=spec.name,
                    consumername=f"{spec.name}-worker",
                    streams=dict.fromkeys(streams, ">"),
                    count=32,
                    block=block_ms,
                )
                for stream_name, messages in _read_response(response):
                    for message_id, fields in messages:
                        await self._submit(spec, stream_name, message_id, fields, 1)
                await self._reclaim_pending(spec)
                falhas = 0  # ciclo saudável: zera o backoff
            except asyncio.CancelledError:  # pragma: no cover
                raise
            except Exception as exc:
                # Redis fora do ar, timeout, etc.: recua exponencialmente em
                # vez de martelar. O redis-py reconecta na próxima chamada.
                falhas += 1
                delay = self._backoff(falhas)
                _log.error(
                    "consume_loop_error",
                    consumer=spec.name,
                    error=repr(exc),
                    falhas=falhas,
                    backoff_s=round(delay, 3),
                )
                await asyncio.sleep(delay)

    async def _submit(
        self,
        spec: ConsumerSpec,
        stream: str,
        message_id: bytes | str,
        fields: dict[Any, Any],
        delivery_count: int,
    ) -> None:
        """Roteia a mensagem para o dispatcher pela chave de partição do
        evento — mesma entidade no mesmo worker (ordem), entidades
        diferentes em paralelo. A submissão espera se o worker estiver
        afogado (backpressure), segurando a leitura do stream."""
        raw = fields.get(_ENVELOPE_FIELD) or fields.get("envelope")
        if raw is None:  # mensagem estranha: ACK e segue
            await self._redis.xack(stream, spec.name, message_id)
            return
        event = DomainEvent.model_validate_json(raw)
        await self._dispatchers[spec.name].submit(
            event.routing_key,
            lambda: self._process(spec, stream, message_id, event, delivery_count),
            reprocess=delivery_count > 1,
        )

    async def _process(
        self,
        spec: ConsumerSpec,
        stream: str,
        message_id: bytes | str,
        event: DomainEvent,
        delivery_count: int,
    ) -> None:
        max_attempts = spec.max_attempts or self._settings.max_delivery_attempts

        dedup_key = self._dedup_key(spec.name, event.event_id)
        is_new = await self._redis.set(dedup_key, "1", nx=True, ex=self._settings.dedup_ttl_seconds)
        if not is_new:
            await self._redis.xack(stream, spec.name, message_id)
            return

        try:
            await spec.handler(event)
        except Exception as exc:
            # libera o dedup para permitir a reentrega
            await self._redis.delete(dedup_key)
            if delivery_count >= max_attempts:
                await self._to_dlq(spec, stream, message_id, event, delivery_count, exc)
            else:
                _log.warning(
                    "event_retry_scheduled",
                    consumer=spec.name,
                    event_type=event.type,
                    event_id=str(event.event_id),
                    delivery_count=delivery_count,
                )
                # sem ACK: XAUTOCLAIM reentrega após retry_min_idle_ms
        else:
            await self._redis.xack(stream, spec.name, message_id)

    async def _reclaim_pending(self, spec: ConsumerSpec) -> None:
        """Reprocessa mensagens pendentes (falhas ou consumidores mortos).

        É o mecanismo de recuperação após crash: uma mensagem lida mas não
        confirmada (o processo morreu antes do ACK) fica no PEL; passado o
        ``retry_min_idle_ms``, qualquer instância a reclama e reprocessa. As
        reclamadas voltam pelo MESMO dispatcher, roteadas pela chave —
        preservam a ordem por entidade também na reentrega.

        Usa XPENDING+XCLAIM, e não XAUTOCLAIM (que seria uma chamada só): o
        XPENDING devolve ``times_delivered`` por mensagem, que é o que
        decide quando parar de reentregar e mandar para a DLQ. O XAUTOCLAIM
        não expõe esse contador — trocá-lo custaria a garantia de retry
        limitado."""
        for stream in self._streams_by_consumer[spec.name]:
            pending: Sequence[dict[str, Any]] = await self._redis.xpending_range(
                stream,
                spec.name,
                min="-",
                max="+",
                count=64,
                idle=self._settings.retry_min_idle_ms,
            )
            for entry in pending:
                message_id = entry["message_id"]
                claimed = await self._redis.xclaim(
                    stream,
                    spec.name,
                    f"{spec.name}-worker",
                    min_idle_time=self._settings.retry_min_idle_ms,
                    message_ids=[message_id],
                )
                # XCLAIM incrementa o contador: a entrega corrente é times_delivered + 1
                for claimed_id, fields in _entries(claimed):
                    await self._submit(
                        spec, stream, claimed_id, fields, int(entry["times_delivered"]) + 1
                    )

    async def _to_dlq(
        self,
        spec: ConsumerSpec,
        stream: str,
        message_id: bytes | str,
        event: DomainEvent,
        attempts: int,
        exc: Exception,
    ) -> None:
        _log.error(
            "event_dead_lettered",
            consumer=spec.name,
            event_type=event.type,
            event_id=str(event.event_id),
            attempts=attempts,
            error=repr(exc),
        )
        await self._redis.xadd(
            self._dlq_key(spec.name),
            {
                _ENVELOPE_FIELD: event.model_dump_json(),
                b"attempts": str(attempts),
                b"last_error": repr(exc)[:500],
                b"failed_at": datetime.now(tz=UTC).isoformat(),
                b"origin_stream": stream,
            },
            maxlen=self._settings.dlq_maxlen,  # DLQ não cresce sem limite (L2-2)
            approximate=True,
        )
        await self._redis.xack(stream, spec.name, message_id)

    # ------------------------------------------------------------ DLQ

    async def dead_letters(self, consumer: str, *, limit: int = 100) -> list[DeadLetter]:
        raw = await self._redis.xrange(self._dlq_key(consumer), count=limit)
        letters: list[DeadLetter] = []
        for _message_id, fields in _entries(raw):
            letters.append(
                DeadLetter(
                    consumer=consumer,
                    event=DomainEvent.model_validate_json(_field(fields, "envelope")),
                    attempts=int(_field(fields, "attempts")),
                    last_error=_field(fields, "last_error"),
                    failed_at=datetime.fromisoformat(_field(fields, "failed_at")),
                )
            )
        return letters

    async def redrive(self, consumer: str, event_id: UUID) -> bool:
        dlq = self._dlq_key(consumer)
        raw = await self._redis.xrange(dlq)
        for message_id, fields in _entries(raw):
            event = DomainEvent.model_validate_json(_field(fields, "envelope"))
            if event.event_id != event_id:
                continue
            await self._redis.delete(self._dedup_key(consumer, event_id))
            await self.publish(event)
            await self._redis.xdel(dlq, message_id)
            return True
        return False


def _read_response(raw: Any) -> list[tuple[str, list[tuple[bytes | str, dict[Any, Any]]]]]:
    """Normaliza a resposta de XREADGROUP (tipagem do redis-py admite unions amplas)."""
    out: list[tuple[str, list[tuple[bytes | str, dict[Any, Any]]]]] = []
    for item in raw or []:
        stream_name, messages = item[0], item[1]
        out.append((_as_str(stream_name), _entries(messages)))
    return out


def _entries(raw: Any) -> list[tuple[bytes | str, dict[Any, Any]]]:
    """Normaliza a resposta de XRANGE (tipagem do redis-py admite Nones)."""
    result: list[tuple[bytes | str, dict[Any, Any]]] = []
    for item in raw or []:
        message_id, fields = item
        if message_id is not None and fields is not None:
            result.append((message_id, fields))
    return result


def _as_str(value: bytes | str) -> str:
    return value.decode() if isinstance(value, bytes) else value


def _field(fields: dict[Any, Any], name: str) -> str:
    value = fields.get(name.encode(), fields.get(name))
    if value is None:
        raise ValueError(f"campo ausente na entrada da DLQ: {name}")
    return _as_str(value)


# fim do módulo — canário anti-truncamento
