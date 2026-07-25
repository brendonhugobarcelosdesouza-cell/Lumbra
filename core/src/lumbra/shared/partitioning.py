"""Despacho particionado: paralelismo entre chaves, ordem dentro da chave.

Primitiva genérica de concorrência (sem dependência de domínio ou de
infraestrutura). O Event Bus a usa para processar eventos, mas serve a
qualquer subsistema que precise de "processar em paralelo, preservando a
ordem por entidade".

Modelo (estilo Kafka): N workers, cada um com sua fila FIFO. Uma chave de
partição é roteada por ``crc32(chave) % N`` — SEMPRE para o mesmo worker.
Disso saem as duas garantias:

* **ordem por chave**: eventos da mesma chave caem na mesma fila e são
  processados um de cada vez, na ordem de submissão;
* **paralelismo entre chaves**: chaves diferentes tendem a cair em filas
  diferentes e rodam em paralelo, até o limite de workers.

O roteamento usa ``crc32`` (não o ``hash()`` embutido, que é aleatorizado
por processo) para ser DETERMINÍSTICO: a mesma chave vai ao mesmo worker
em qualquer processo, sempre.

Isolamento de falha: se um item levanta exceção, o worker a registra e
segue para o próximo — um item ruim (ou um handler que falha) nunca derruba
o worker nem afeta os demais.
"""

from __future__ import annotations

import asyncio
import time
import zlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from lumbra.shared.logging import get_logger

_log = get_logger("lumbra.partitioning")

Work = Callable[[], Awaitable[None]]


@dataclass(frozen=True)
class WorkerStats:
    """Instantâneo de um worker."""

    worker: int
    processed: int
    failed: int
    queue_depth: int


@dataclass(frozen=True)
class DispatcherMetrics:
    """Instantâneo agregado — alimenta a observabilidade (L2-3).

    Cobre os seis sinais pedidos: eventos por worker (``per_worker``),
    tamanho das filas (``queue_depth`` por worker), tempo médio de espera
    (fila) e de processamento, throughput e eventos reprocessados.
    """

    name: str
    workers: int
    total_processed: int
    total_failed: int
    total_reprocessed: int
    inflight: int
    avg_wait_ms: float
    avg_processing_ms: float
    throughput_per_s: float
    per_worker: tuple[WorkerStats, ...]


@dataclass
class _Item:
    key: str
    work: Work
    enqueued_at: float


class PartitionedDispatcher:
    """Pool de workers com roteamento determinístico por chave de partição."""

    def __init__(
        self, *, workers: int, queue_maxsize: int = 10_000, name: str = "dispatcher"
    ) -> None:
        if workers < 1:
            raise ValueError("workers deve ser >= 1")
        self._n = workers
        self._name = name
        # fila limitada = backpressure: quem submete espera quando o worker
        # está afogado, em vez de estourar a memória
        self._queues: list[asyncio.Queue[_Item]] = [
            asyncio.Queue(maxsize=queue_maxsize) for _ in range(workers)
        ]
        self._tasks: list[asyncio.Task[None]] = []
        # acumuladores de métrica (loop único, sem locks)
        self._processed = [0] * workers
        self._failed = [0] * workers
        self._reprocessed = 0
        self._inflight = 0
        self._wait_sum = 0.0
        self._wait_count = 0
        self._proc_sum = 0.0
        self._proc_count = 0
        self._started_at: float | None = None

    @property
    def name(self) -> str:
        return self._name

    def worker_for(self, key: str) -> int:
        """Worker determinístico de uma chave (crc32 estável, não hash())."""
        return zlib.crc32(key.encode("utf-8")) % self._n

    # ------------------------------------------------------------ ciclo de vida

    async def start(self) -> None:
        if self._tasks:
            return
        self._started_at = time.monotonic()
        self._tasks = [asyncio.create_task(self._run(i)) for i in range(self._n)]

    async def submit(self, key: str, work: Work, *, reprocess: bool = False) -> None:
        """Enfileira ``work`` no worker da ``key``. Aguarda se a fila encher
        (backpressure). ``reprocess=True`` contabiliza reentregas."""
        if reprocess:
            self._reprocessed += 1
        item = _Item(key=key, work=work, enqueued_at=time.monotonic())
        await self._queues[self.worker_for(key)].put(item)

    async def join(self) -> None:
        """Aguarda todo o trabalho submetido ser processado (uso em testes
        e no shutdown gracioso)."""
        await asyncio.gather(*(q.join() for q in self._queues))

    async def stop(self, *, drain: bool = True) -> None:
        """Para os workers. Com ``drain`` (padrão), espera esvaziar as filas
        antes — nenhum trabalho aceito é perdido."""
        if not self._tasks:
            return
        if drain:
            await self.join()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    # ------------------------------------------------------------ worker

    async def _run(self, index: int) -> None:
        queue = self._queues[index]
        while True:
            item = await queue.get()
            self._inflight += 1
            wait = time.monotonic() - item.enqueued_at
            self._wait_sum += wait
            self._wait_count += 1
            started = time.monotonic()
            try:
                await item.work()
                self._processed[index] += 1
            except asyncio.CancelledError:
                # cancelamento durante o trabalho: devolve e propaga
                self._inflight -= 1
                queue.task_done()
                raise
            except Exception as exc:  # isolamento: um item ruim não mata o worker
                self._failed[index] += 1
                _log.error(
                    "dispatcher_work_failed",
                    dispatcher=self._name,
                    worker=index,
                    key=item.key,
                    error=repr(exc),
                )
            finally:
                self._proc_sum += time.monotonic() - started
                self._proc_count += 1
                self._inflight -= 1
                queue.task_done()

    # ------------------------------------------------------------ métricas

    def metrics(self) -> DispatcherMetrics:
        elapsed = (time.monotonic() - self._started_at) if self._started_at else 0.0
        total_processed = sum(self._processed)
        return DispatcherMetrics(
            name=self._name,
            workers=self._n,
            total_processed=total_processed,
            total_failed=sum(self._failed),
            total_reprocessed=self._reprocessed,
            inflight=self._inflight,
            avg_wait_ms=(self._wait_sum / self._wait_count * 1000) if self._wait_count else 0.0,
            avg_processing_ms=(self._proc_sum / self._proc_count * 1000)
            if self._proc_count
            else 0.0,
            throughput_per_s=(total_processed / elapsed) if elapsed > 0 else 0.0,
            per_worker=tuple(
                WorkerStats(
                    worker=i,
                    processed=self._processed[i],
                    failed=self._failed[i],
                    queue_depth=self._queues[i].qsize(),
                )
                for i in range(self._n)
            ),
        )


# canário anti-truncamento
