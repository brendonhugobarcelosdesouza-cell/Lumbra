"""Carga e baseline do Event Bus (L2-4).

Instrumento, não gate rígido: roda com ``-s`` e imprime throughput e
latência para comparar antes/depois de uma mudança. As asserções são
travas de sanidade largas (a máquina do CI varia), não metas de desempenho.

Mira o dispatcher e o bus in-memory: os caminhos de throughput que rodam
em qualquer lugar, sem Redis. A carga no Redis real fica em
``test_redis_bus.py`` (pula sem Redis).

Baseline de referência (medido em sandbox de dev, NAO e contrato):
* dispatcher, trabalho trivial: ordem de 500k eventos/s (custo puro do
  despacho, um evento a cada ~2 microssegundos)
* dispatcher, trabalho de 1ms (I/O): o tempo total cai quase linear com os
  workers (1 -> 8 workers acelerou ~7x: 909ms -> 125ms para 800 eventos),
  a prova do paralelismo por chave
* bus in-memory ponta a ponta: ordem de 50k eventos/s com 8 workers,
  latencia publish->handler mediana ~4ms / p95 ~8ms
"""

import asyncio
import statistics
import time

import pytest

from lumbra.adapters.eventbus.in_memory import InMemoryEventBus
from lumbra.domain.events import EventPayload, EventRegistry
from lumbra.ports.event_bus import ConsumerSpec
from lumbra.shared.partitioning import PartitionedDispatcher

pytestmark = pytest.mark.integration


def _registry() -> EventRegistry:
    reg = EventRegistry()

    @reg.event("doc.stage")
    class _Stage(EventPayload):
        document_id: str
        step: int

        def partition_key(self) -> str:
            return f"document:{self.document_id}"

    return reg


def _stage(reg: EventRegistry, document_id: str, step: int):
    cls = reg.payload_class("doc.stage")
    return reg.envelope(cls(document_id=document_id, step=step), producer="load")


class TestDispatcherThroughput:
    async def test_custo_de_despacho_trabalho_trivial(self):
        """Throughput bruto do despacho: trabalho mínimo, mede o overhead."""
        d = PartitionedDispatcher(workers=8)
        total, entidades = 50_000, 500

        async def trabalho() -> None: ...

        await d.start()
        inicio = time.perf_counter()
        for i in range(total):
            await d.submit(f"k{i % entidades}", trabalho)
        await d.join()
        elapsed = time.perf_counter() - inicio
        await d.stop()

        m = d.metrics()
        print(
            f"\ndispatcher (trivial, 8 workers): {total} eventos em {elapsed * 1000:.0f}ms "
            f"-> {total / elapsed:,.0f} ev/s | espera média {m.avg_wait_ms:.2f}ms"
        )
        assert m.total_processed == total
        assert total / elapsed > 5_000  # trava de sanidade larga

    @pytest.mark.parametrize("workers", [1, 2, 4, 8])
    async def test_paralelismo_reduz_wall_time_em_trabalho_io(self, workers):
        """Com trabalho de I/O (sleep), mais workers reduzem o tempo total —
        a prova de que chaves diferentes correm em paralelo."""
        d = PartitionedDispatcher(workers=workers)
        total, entidades = 800, 400  # 400 entidades: distribuem entre workers

        async def trabalho() -> None:
            await asyncio.sleep(0.001)  # simula I/O (banco, IA, rede)

        await d.start()
        inicio = time.perf_counter()
        for i in range(total):
            await d.submit(f"k{i % entidades}", trabalho)
        await d.join()
        elapsed = time.perf_counter() - inicio
        await d.stop()

        print(
            f"dispatcher (I/O 1ms, {workers} workers): {total} eventos em {elapsed * 1000:.0f}ms "
            f"-> {total / elapsed:,.0f} ev/s"
        )
        assert d.metrics().total_processed == total


class TestBusInMemoryThroughput:
    async def test_throughput_ponta_a_ponta(self):
        reg = _registry()
        bus = InMemoryEventBus(concurrency=8)
        processados = 0

        async def handler(_event) -> None:
            nonlocal processados
            processados += 1

        bus.register(ConsumerSpec("c", ("doc.*",), handler))
        await bus.start()
        total, entidades = 20_000, 500
        try:
            inicio = time.perf_counter()
            for i in range(total):
                await bus.publish(_stage(reg, f"d{i % entidades}", i))
            await bus.drain()
            elapsed = time.perf_counter() - inicio
            h = await bus.health()
            print(
                f"\nbus in-memory (8 workers): {total} eventos em {elapsed * 1000:.0f}ms "
                f"-> {total / elapsed:,.0f} ev/s | backlog final {h.consumers[0].backlog}"
            )
        finally:
            await bus.stop()
        assert processados == total
        assert total / elapsed > 2_000  # trava de sanidade larga

    async def test_latencia_de_entrega(self):
        """Latência publish->handler por evento (mediana e p95)."""
        reg = _registry()
        bus = InMemoryEventBus(concurrency=4)
        latencias: list[float] = []
        marcas: dict[str, float] = {}

        async def handler(event) -> None:
            mid = event.payload["document_id"]
            latencias.append((time.perf_counter() - marcas[mid]) * 1000)

        bus.register(ConsumerSpec("c", ("doc.*",), handler))
        await bus.start()
        try:
            for i in range(500):
                doc = f"d{i}"
                marcas[doc] = time.perf_counter()
                await bus.publish(_stage(reg, doc, i))
            await bus.drain()
        finally:
            await bus.stop()
        p95 = sorted(latencias)[int(len(latencias) * 0.95) - 1]
        print(
            f"\nbus in-memory latência publish->handler: "
            f"mediana {statistics.median(latencias):.2f}ms | p95 {p95:.2f}ms"
        )
        assert len(latencias) == 500


# canário anti-truncamento
