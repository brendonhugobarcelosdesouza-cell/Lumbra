"""PartitionedDispatcher — paralelismo entre chaves, ordem por chave (L2-1).

Cobre os critérios pedidos: preservação de ordem da mesma entidade,
paralelismo entre entidades diferentes, ausência de starvation,
comportamento com milhares de eventos, isolamento de falha de worker, e as
seis métricas.
"""

import asyncio

import pytest

from lumbra.shared.partitioning import PartitionedDispatcher


async def _run_with(dispatcher: PartitionedDispatcher, corpo) -> None:
    await dispatcher.start()
    try:
        await corpo()
        await dispatcher.join()
    finally:
        await dispatcher.stop()


class TestRoteamento:
    def test_determinismo_mesma_chave_mesmo_worker(self):
        d = PartitionedDispatcher(workers=8)
        # a mesma chave sempre no mesmo worker, mesmo em instâncias distintas
        outra = PartitionedDispatcher(workers=8)
        for chave in ("document:abc", "memory:42", "user:xyz", "conversation:7"):
            assert d.worker_for(chave) == outra.worker_for(chave)

    def test_worker_dentro_do_intervalo(self):
        d = PartitionedDispatcher(workers=4)
        assert all(0 <= d.worker_for(f"k{i}") < 4 for i in range(100))

    def test_workers_invalido(self):
        with pytest.raises(ValueError, match="workers"):
            PartitionedDispatcher(workers=0)


class TestOrdemPorChave:
    async def test_mesma_entidade_processa_em_ordem(self):
        """O critério central: eventos da mesma chave nunca saem de ordem."""
        d = PartitionedDispatcher(workers=8)
        vistos: dict[str, list[int]] = {"doc:A": [], "doc:B": [], "doc:C": []}

        async def registrar(chave: str, n: int) -> None:
            # jitter para expor qualquer condição de corrida na ordem
            await asyncio.sleep(0.001 if n % 3 else 0.002)
            vistos[chave].append(n)

        async def corpo() -> None:
            for n in range(50):
                for chave in vistos:
                    await d.submit(chave, lambda c=chave, i=n: registrar(c, i))

        await _run_with(d, corpo)
        for chave, sequencia in vistos.items():
            assert sequencia == list(range(50)), f"ordem quebrada em {chave}"

    async def test_chaves_diferentes_correm_em_paralelo(self):
        """Entidades diferentes NÃO se bloqueiam: com workers suficientes,
        N tarefas lentas terminam em ~1 duração, não em N durações."""
        d = PartitionedDispatcher(workers=16)
        barreira = asyncio.Event()
        chegaram = 0

        async def espera() -> None:
            nonlocal chegaram
            chegaram += 1
            await asyncio.wait_for(barreira.wait(), timeout=2.0)

        async def corpo() -> None:
            # 10 chaves distintas: se rodam em paralelo, todas chegam à
            # barreira antes de qualquer uma liberar
            for i in range(10):
                await d.submit(f"chave-{i}", espera)
            await asyncio.sleep(0.1)
            assert chegaram == 10, "as chaves não rodaram em paralelo"
            barreira.set()

        await _run_with(d, corpo)


class TestStarvationEEscala:
    async def test_sem_starvation_todas_as_chaves_avancam(self):
        """Nenhuma chave fica sem ser servida: todas terminam."""
        d = PartitionedDispatcher(workers=4)
        contagem: dict[str, int] = {f"e{i}": 0 for i in range(20)}

        async def incrementar(chave: str) -> None:
            await asyncio.sleep(0.0005)
            contagem[chave] += 1

        async def corpo() -> None:
            for _ in range(25):
                for chave in contagem:
                    await d.submit(chave, lambda c=chave: incrementar(c))

        await _run_with(d, corpo)
        assert all(v == 25 for v in contagem.values()), "alguma chave foi negligenciada"

    async def test_milhares_de_eventos(self):
        d = PartitionedDispatcher(workers=8)
        total = 5000
        processados = 0

        async def trabalho() -> None:
            nonlocal processados
            processados += 1

        async def corpo() -> None:
            for i in range(total):
                await d.submit(f"chave-{i % 200}", trabalho)  # 200 entidades

        await _run_with(d, corpo)
        assert processados == total
        assert d.metrics().total_processed == total


class TestIsolamentoDeFalha:
    async def test_item_que_falha_nao_derruba_o_worker(self):
        """Um item que levanta exceção não impede os próximos DA MESMA fila."""
        d = PartitionedDispatcher(workers=1)  # tudo no mesmo worker de propósito
        ok: list[int] = []

        async def as_vezes_falha(n: int) -> None:
            if n == 2:
                raise RuntimeError("falha proposital")
            ok.append(n)

        async def corpo() -> None:
            for n in range(5):
                await d.submit("mesma-chave", lambda i=n: as_vezes_falha(i))

        await _run_with(d, corpo)
        # o item 2 falhou, mas 0,1,3,4 passaram — worker sobreviveu e seguiu
        assert ok == [0, 1, 3, 4]
        assert d.metrics().total_failed == 1
        assert d.metrics().total_processed == 4

    async def test_falha_em_um_worker_nao_afeta_os_demais(self):
        d = PartitionedDispatcher(workers=8)
        sucesso: list[str] = []
        # acha duas chaves que caem em workers diferentes
        chave_boa = next(k for k in (f"boa-{i}" for i in range(100)))
        chave_ruim = next(
            f"ruim-{i}" for i in range(100) if d.worker_for(f"ruim-{i}") != d.worker_for(chave_boa)
        )

        async def sempre_falha() -> None:
            raise RuntimeError("worker problemático")

        async def sempre_ok() -> None:
            sucesso.append("ok")

        async def corpo() -> None:
            for _ in range(10):
                await d.submit(chave_ruim, sempre_falha)
                await d.submit(chave_boa, sempre_ok)

        await _run_with(d, corpo)
        assert len(sucesso) == 10  # a chave boa completou apesar da ruim falhar
        assert d.metrics().total_failed == 10


class TestMetricas:
    async def test_seis_sinais_presentes(self):
        d = PartitionedDispatcher(workers=4, name="teste")

        async def trabalho() -> None:
            await asyncio.sleep(0.001)

        async def corpo() -> None:
            for i in range(40):
                await d.submit(f"k{i % 10}", trabalho)
            # uma reentrega marcada
            await d.submit("k0", trabalho, reprocess=True)

        await _run_with(d, corpo)
        m = d.metrics()
        assert m.name == "teste"
        assert m.workers == 4
        assert m.total_processed == 41  # eventos por worker (soma)
        assert len(m.per_worker) == 4  # tamanho das filas por worker
        assert all(w.queue_depth == 0 for w in m.per_worker)  # drenou
        assert m.avg_wait_ms >= 0.0  # tempo médio de espera
        assert m.avg_processing_ms > 0.0  # tempo médio de processamento
        assert m.throughput_per_s > 0.0  # throughput
        assert m.total_reprocessed == 1  # eventos reprocessados

    async def test_eventos_por_worker_somam_o_total(self):
        d = PartitionedDispatcher(workers=4)

        async def trabalho() -> None: ...

        async def corpo() -> None:
            for i in range(100):
                await d.submit(f"k{i}", trabalho)

        await _run_with(d, corpo)
        m = d.metrics()
        assert sum(w.processed for w in m.per_worker) == m.total_processed == 100


# canário anti-truncamento
