"""Medição de latência dos caminhos quentes (consolidação).

Não é teste de regressão com limite rígido — a máquina do CI varia. É
instrumento: roda com -s e imprime números comparáveis antes/depois de
uma otimização.
"""

import statistics
import time
import uuid

import pytest

from lumbra.adapters.ai.fastembed_local import FastEmbedProvider
from lumbra.adapters.ai.gateway import AIGateway
from lumbra.adapters.eventbus.in_memory import InMemoryEventBus
from lumbra.adapters.eventstore.in_memory import InMemoryEventStore
from lumbra.adapters.memory.postgres import PostgresMemoryStore
from lumbra.adapters.metrics.in_memory import InMemoryMetrics
from lumbra.adapters.permissions.static import StaticPermissionAdapter
from lumbra.adapters.users.postgres import PostgresUserStore
from lumbra.domain.events import EventRegistry
from lumbra.kernel.kernel import LumbraKernel
from lumbra.modules.memory import MemoryModule
from lumbra.ports.skills import SkillContext

pytestmark = pytest.mark.integration

_embedder = FastEmbedProvider()
_N_MEMORIAS = 120


@pytest.fixture()
async def memoria_populada(db):
    user = await PostgresUserStore(db).create(
        email=f"perf-{uuid.uuid4().hex[:8]}@lumbra.app", password_hash="h"
    )
    kernel = LumbraKernel(
        events=EventRegistry(),
        bus=InMemoryEventBus(),
        event_store=InMemoryEventStore(),
        permissions=StaticPermissionAdapter(default_allow=True),
    )
    gateway = AIGateway(embedding_providers=[_embedder], metrics=InMemoryMetrics())
    kernel.register_module(MemoryModule(store=PostgresMemoryStore(db), gateway=gateway))
    await kernel.start()
    ctx = SkillContext(subject=f"user:{user.id}", user_id=user.id)
    assuntos = ["trabalho", "saúde", "família", "finanças", "viagem", "estudo"]
    for i in range(_N_MEMORIAS):
        await kernel.skills.execute(
            "memory.remember",
            {"content": f"Nota {i} sobre {assuntos[i % len(assuntos)]} do usuário"},
            context=ctx,
        )
    yield kernel, ctx
    await kernel.stop()


async def test_latencia_busca_de_memoria(memoria_populada):
    kernel, ctx = memoria_populada
    consultas = [
        "o que anotei sobre trabalho",
        "alguma coisa de saúde",
        "minhas finanças",
        "notas de viagem",
    ]
    tempos = []
    for consulta in consultas * 3:
        inicio = time.perf_counter()
        await kernel.skills.execute("memory.search", {"query": consulta, "limit": 5}, context=ctx)
        tempos.append((time.perf_counter() - inicio) * 1000)
    print(
        f"\nmemory.search sobre {_N_MEMORIAS} memórias: "
        f"mediana {statistics.median(tempos):.1f} ms | "
        f"p95 {sorted(tempos)[int(len(tempos) * 0.95) - 1]:.1f} ms | "
        f"máx {max(tempos):.1f} ms"
    )
    assert statistics.median(tempos) < 2000  # trava de sanidade, não de meta
