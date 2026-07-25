"""Calibração do limiar de recall vetorial da memória.

Este teste existe para travar uma decisão numérica que, errada, degrada o
produto silenciosamente: se o corte for alto demais, o assistente "esquece"
o que o usuário contou; se for baixo demais, entope o contexto com ruído.

Os valores vêm de medição real com o modelo de embedding em uso. Trocar o
modelo provavelmente quebra estes testes — e é exatamente o ponto: a troca
tem que ser uma decisão consciente, não um efeito colateral.
"""

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

MEMORIAS = [
    "O usuário mora em Curitiba",
    "O usuário é alérgico a dipirona",
    "O usuário tem um cachorro chamado Rex",
    "O usuário prefere reuniões pela manhã",
]


@pytest.fixture()
async def memoria(db):
    user = await PostgresUserStore(db).create(
        email=f"recall-{uuid.uuid4().hex[:8]}@lumbra.app", password_hash="h"
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
    for conteudo in MEMORIAS:
        await kernel.skills.execute("memory.remember", {"content": conteudo}, context=ctx)
    yield kernel, ctx
    await kernel.stop()


class TestRecall:
    @pytest.mark.parametrize(
        ("pergunta", "esperado"),
        [
            ("Onde eu moro mesmo?", "Curitiba"),
            ("Qual minha cidade?", "Curitiba"),
            ("sou alérgico a quê?", "dipirona"),
            ("qual meu cachorro", "Rex"),
            ("quando prefiro reunião", "manhã"),
        ],
    )
    async def test_pergunta_natural_recupera_a_memoria(self, memoria, pergunta, esperado):
        """Perguntas em linguagem natural — não paráfrases exatas — precisam
        alcançar a memória, senão o usuário se repete."""
        kernel, ctx = memoria
        resultado = await kernel.skills.execute(
            "memory.search", {"query": pergunta, "limit": 5}, context=ctx
        )
        conteudos = " | ".join(h["content"] for h in resultado.hits)
        assert esperado in conteudos, f"{pergunta!r} não recuperou {esperado!r}"

    @pytest.mark.parametrize(
        "pergunta",
        [
            "Qual a capital da França?",
            "como funciona um motor a combustão",
        ],
    )
    async def test_pergunta_sem_relacao_nao_traz_ruido(self, memoria, pergunta):
        """O outro lado do limiar: contexto poluído piora a resposta."""
        kernel, ctx = memoria
        resultado = await kernel.skills.execute(
            "memory.search", {"query": pergunta, "limit": 5}, context=ctx
        )
        vetoriais = [h for h in resultado.hits if h.get("similarity", 0) > 0]
        assert vetoriais == [], f"{pergunta!r} trouxe memórias irrelevantes"

    async def test_relevante_vence_ruido_no_topo(self, memoria):
        """Regressão real: com RRF puro (só posição), uma memória fraca
        podia superar a resposta certa pela força acumulada. O lado
        vetorial passou a ser pesado pela similaridade."""
        kernel, ctx = memoria
        await kernel.skills.execute(
            "memory.remember",
            {"content": "O usuário guardou os documentos na gaveta", "importance": 1.0},
            context=ctx,
        )
        resultado = await kernel.skills.execute(
            "memory.search", {"query": "Onde eu moro mesmo?", "limit": 5}, context=ctx
        )
        assert "Curitiba" in resultado.hits[0]["content"]

    async def test_similaridade_exposta_para_deduplicacao(self, memoria):
        kernel, ctx = memoria
        resultado = await kernel.skills.execute(
            "memory.search", {"query": "O usuário mora em Curitiba", "limit": 1}, context=ctx
        )
        assert resultado.hits[0]["similarity"] > 0.9  # praticamente idêntico


# canário anti-truncamento
