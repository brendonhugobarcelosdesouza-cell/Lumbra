"""E2-06 fim a fim: o que foi dito numa conversa volta na próxima.

O LLM é um dublê que devolve extrações controladas — o que se testa é a
PLATAFORMA: privacidade herdada, dedup, proveniência, e o fato voltando
pelo Context Engine numa conversa nova.
"""

import uuid
from pathlib import Path

import pytest

from lumbra.adapters.ai.fastembed_local import FastEmbedProvider
from lumbra.adapters.ai.gateway import AIGateway
from lumbra.adapters.conversations.postgres import PostgresConversationStore
from lumbra.adapters.eventbus.in_memory import InMemoryEventBus
from lumbra.adapters.eventstore.in_memory import InMemoryEventStore
from lumbra.adapters.memory.postgres import PostgresMemoryStore
from lumbra.adapters.metrics.in_memory import InMemoryMetrics
from lumbra.adapters.permissions.static import StaticPermissionAdapter
from lumbra.adapters.users.postgres import PostgresUserStore
from lumbra.context.providers import MemoryContextProvider
from lumbra.domain.events import EventRegistry
from lumbra.kernel.kernel import LumbraKernel
from lumbra.modules.chat import ChatModule
from lumbra.modules.memory import MemoryModule
from lumbra.modules.reflection import ReflectionModule
from lumbra.ports.ai import ChatProviderPort, ProviderCompletion
from lumbra.ports.skills import SkillContext

pytestmark = pytest.mark.integration

_embedder = FastEmbedProvider()


class RoteiroProvider(ChatProviderPort):
    """Devolve respostas de um roteiro; registra a privacidade recebida."""

    def __init__(self, *, local: bool = True, nome: str = "roteiro-local") -> None:
        self._nome = nome
        self._local = local
        self.roteiro: list[str] = []
        self.chamadas: list[tuple] = []

    @property
    def name(self) -> str:
        return self._nome

    @property
    def model(self) -> str:
        return "roteiro-1"

    @property
    def is_local(self) -> bool:
        return self._local

    def cost_usd(self, *, input_tokens: int, output_tokens: int) -> float:
        return 0.0

    async def complete(self, messages, *, max_tokens, temperature):
        self.chamadas.append((messages, temperature))
        texto = self.roteiro.pop(0) if self.roteiro else "ok"
        return ProviderCompletion(
            text=texto, input_tokens=10, output_tokens=5, finish_reason="stop"
        )


@pytest.fixture()
async def stack(db, tmp_path: Path):
    user = await PostgresUserStore(db).create(
        email=f"refl-{uuid.uuid4().hex[:8]}@lumbra.app", password_hash="h"
    )
    local = RoteiroProvider()
    nuvem = RoteiroProvider(local=False, nome="nuvem-teste")
    gateway = AIGateway(
        embedding_providers=[_embedder],
        chat_providers=[local, nuvem],
        metrics=InMemoryMetrics(),
    )
    kernel = LumbraKernel(
        events=EventRegistry(),
        bus=InMemoryEventBus(),
        event_store=InMemoryEventStore(),
        permissions=StaticPermissionAdapter(default_allow=True),
    )
    conversations = PostgresConversationStore(db)
    kernel.register_module(MemoryModule(store=PostgresMemoryStore(db), gateway=gateway))
    kernel.register_module(ChatModule(conversations=conversations, gateway=gateway))
    kernel.register_module(
        ReflectionModule(conversations=conversations, gateway=gateway, every_n_answers=2)
    )
    kernel.context.register(MemoryContextProvider(kernel.skills))
    await kernel.start()
    yield kernel, user, local, nuvem
    await kernel.stop()


def _ctx(user) -> SkillContext:
    return SkillContext(subject=f"user:{user.id}", user_id=user.id)


async def _conversar(kernel, ctx, cid, texto):
    return await kernel.skills.execute(
        "chat.send",
        {"conversation_id": cid, "content": texto, "use_context": False},
        context=ctx,
    )


class TestReflexao:
    async def test_fato_de_uma_conversa_volta_na_seguinte(self, stack):
        kernel, user, local, _nuvem = stack
        ctx = _ctx(user)
        primeira = await kernel.skills.execute("chat.start", {}, context=ctx)

        local.roteiro = [
            "Legal saber disso!",
            '{"fatos": [{"fato": "O usuário mora em Curitiba", "importancia": 0.9}]}',
        ]
        await _conversar(kernel, ctx, primeira.conversation_id, "Eu moro em Curitiba")

        resultado = await kernel.skills.execute(
            "reflection.from_conversation",
            {"conversation_id": primeira.conversation_id},
            context=ctx,
        )
        assert resultado.stored == 1

        # conversa NOVA: o fato volta pelo Context Engine
        segunda = await kernel.skills.execute("chat.start", {}, context=ctx)
        local.roteiro = ["Sim, você mora em Curitiba."]
        await kernel.skills.execute(
            "chat.send",
            {"conversation_id": segunda.conversation_id, "content": "Onde eu moro mesmo?"},
            context=ctx,
        )
        prompt = local.chamadas[-1][0]
        contexto = " ".join(m.content for m in prompt if m.role == "system")
        assert "Curitiba" in contexto, "a memória não voltou na nova conversa"

    async def test_nao_duplica_o_que_ja_sabe(self, stack):
        kernel, user, local, _nuvem = stack
        ctx = _ctx(user)
        conversa = await kernel.skills.execute("chat.start", {}, context=ctx)
        fato = '{"fatos": [{"fato": "O usuário é alérgico a dipirona"}]}'

        local.roteiro = ["ok", fato]
        await _conversar(kernel, ctx, conversa.conversation_id, "sou alérgico a dipirona")
        primeira = await kernel.skills.execute(
            "reflection.from_conversation",
            {"conversation_id": conversa.conversation_id},
            context=ctx,
        )
        assert primeira.stored == 1

        local.roteiro = [fato]  # o modelo extrai o MESMO fato de novo
        segunda = await kernel.skills.execute(
            "reflection.from_conversation",
            {"conversation_id": conversa.conversation_id},
            context=ctx,
        )
        assert segunda.stored == 0
        assert segunda.skipped_duplicates == 1

    async def test_credencial_nunca_vira_memoria(self, stack):
        kernel, user, local, _nuvem = stack
        ctx = _ctx(user)
        conversa = await kernel.skills.execute("chat.start", {}, context=ctx)
        local.roteiro = [
            "ok",
            '{"fatos": [{"fato": "A senha do wifi dele e 12345"},'
            ' {"fato": "O usuario prefere cafe sem acucar"}]}',
        ]
        await _conversar(kernel, ctx, conversa.conversation_id, "anota ai")
        resultado = await kernel.skills.execute(
            "reflection.from_conversation",
            {"conversation_id": conversa.conversation_id},
            context=ctx,
        )
        assert resultado.candidates == 2
        assert resultado.stored == 1  # a credencial foi descartada

        memorias = await kernel.skills.execute(
            "memory.search", {"query": "senha wifi", "limit": 5}, context=ctx
        )
        assert all("12345" not in h["content"] for h in memorias.hits)

    async def test_privacidade_da_conversa_e_herdada(self, stack):
        """Refletir não pode ser porta dos fundos para a nuvem."""
        kernel, user, local, nuvem = stack
        ctx = _ctx(user)
        conversa = await kernel.skills.execute("chat.start", {}, context=ctx)  # local_only
        local.roteiro = ["ok", '{"fatos": []}']
        await _conversar(kernel, ctx, conversa.conversation_id, "oi")
        await kernel.skills.execute(
            "reflection.from_conversation",
            {"conversation_id": conversa.conversation_id},
            context=ctx,
        )
        assert nuvem.chamadas == [], "conversa privada foi para a nuvem na reflexão"
        # e a extração roda determinística
        assert local.chamadas[-1][1] == 0.0

    async def test_extracao_ilegivel_nao_quebra_nada(self, stack):
        kernel, user, local, _nuvem = stack
        ctx = _ctx(user)
        conversa = await kernel.skills.execute("chat.start", {}, context=ctx)
        local.roteiro = ["ok", "desculpe, nao consegui analisar"]
        await _conversar(kernel, ctx, conversa.conversation_id, "oi")
        resultado = await kernel.skills.execute(
            "reflection.from_conversation",
            {"conversation_id": conversa.conversation_id},
            context=ctx,
        )
        assert resultado.stored == 0
        assert resultado.candidates == 0

    async def test_memoria_registra_de_qual_conversa_veio(self, stack):
        kernel, user, local, _nuvem = stack
        ctx = _ctx(user)
        conversa = await kernel.skills.execute("chat.start", {}, context=ctx)
        local.roteiro = ["ok", '{"fatos": [{"fato": "O usuario tem um cachorro chamado Rex"}]}']
        await _conversar(kernel, ctx, conversa.conversation_id, "tenho um cachorro")
        await kernel.skills.execute(
            "reflection.from_conversation",
            {"conversation_id": conversa.conversation_id},
            context=ctx,
        )
        hits = await kernel.skills.execute(
            "memory.search", {"query": "cachorro Rex", "limit": 1}, context=ctx
        )
        assert hits.hits
        origem = hits.hits[0].get("source_ref") or {}
        assert origem.get("origin") == "chat-reflection"
        assert origem.get("conversation_id") == conversa.conversation_id

    async def test_gatilho_automatico_em_lote(self, stack):
        """every_n_answers=2: reflete na 2ª resposta, não na 1ª."""
        kernel, user, local, _nuvem = stack
        ctx = _ctx(user)
        conversa = await kernel.skills.execute("chat.start", {}, context=ctx)

        local.roteiro = ["resposta 1"]
        await _conversar(kernel, ctx, conversa.conversation_id, "primeira")
        await kernel.bus.drain()  # type: ignore[attr-defined]
        eventos = await kernel.event_store.read(event_types=("reflection.completed",))
        assert eventos == [], "refletiu cedo demais (deveria ser em lote)"

        local.roteiro = ["resposta 2", '{"fatos": [{"fato": "O usuario gosta de xadrez"}]}']
        await _conversar(kernel, ctx, conversa.conversation_id, "segunda")
        await kernel.bus.drain()  # type: ignore[attr-defined]
        eventos = await kernel.event_store.read(event_types=("reflection.completed",))
        assert len(eventos) == 1, "gatilho automático não disparou na 2ª resposta"

    async def test_reflexao_de_conversa_alheia_e_negada(self, stack):
        kernel, user, _local, _nuvem = stack
        conversa = await kernel.skills.execute("chat.start", {}, context=_ctx(user))
        intruso = SkillContext(subject="user:intruso", user_id=uuid.uuid4())
        with pytest.raises(PermissionError):
            await kernel.skills.execute(
                "reflection.from_conversation",
                {"conversation_id": conversa.conversation_id},
                context=intruso,
            )


# canário anti-truncamento
