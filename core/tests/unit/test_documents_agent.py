"""DocumentsAgent (A7): o primeiro agente especialista, ponta a ponta.

Prova o caminho completo — manifesto → registro → resolução por capability →
execução dentro do sandbox — com uma composição REAL (a skill document.find),
sem IA, de forma determinística. Cobre também os modos de falha que importam:
escopo negado, orçamento estourado e cancelamento.
"""

from typing import Any

import pytest

from lumbra.adapters.eventbus.in_memory import InMemoryEventBus
from lumbra.adapters.eventstore.in_memory import InMemoryEventStore
from lumbra.adapters.permissions.static import StaticPermissionAdapter
from lumbra.agents.documents import CAPABILITY, SKILL, DocumentsAgent
from lumbra.domain.events import EventRegistry
from lumbra.kernel.kernel import LumbraKernel
from lumbra.kernel.sandbox import BudgetExceededError, SandboxFactory
from lumbra.ports.agents import AgentLimits
from lumbra.ports.capabilities import CapabilitySpec, ProviderKind
from lumbra.ports.skills import (
    Skill,
    SkillContext,
    SkillInput,
    SkillManifest,
    SkillOutput,
    SkillPermissionDeniedError,
)
from lumbra.shared.cancellation import CancellationToken, CancelReason, OperationCancelledError


class _FindIn(SkillInput):
    query: str
    limit: int = 10


class _FindOut(SkillOutput):
    hits: tuple[dict[str, Any], ...]
    mode: str


async def _find(payload: SkillInput, _c: SkillContext) -> _FindOut:
    assert isinstance(payload, _FindIn)
    return _FindOut(
        hits=({"snippet": f"trecho sobre {payload.query}", "score": 0.9},),
        mode="hybrid",
    )


async def _kernel(*, default_allow: bool = True) -> LumbraKernel:
    k = LumbraKernel(
        events=EventRegistry(),
        bus=InMemoryEventBus(),
        event_store=InMemoryEventStore(),
        permissions=StaticPermissionAdapter(default_allow=default_allow),
    )
    await k.skills.register(
        Skill(
            manifest=SkillManifest(
                name=SKILL,
                description="busca híbrida",
                provider="kernel",
                required_scopes=("read:documents",),
            ),
            input_model=_FindIn,
            output_model=_FindOut,
            handler=_find,
        )
    )
    k.capabilities.register_capability(CapabilitySpec(id=CAPABILITY, description="busca"))
    k.agents.register(DocumentsAgent(k.skills))
    return k


def _ctx(**over: Any) -> SkillContext:
    return SkillContext(subject="agent:documents-agent", **over)


class TestCaminhoCompleto:
    async def test_capability_resolve_para_o_agente(self):
        k = await _kernel()
        provedor = k.capabilities.resolve(CAPABILITY)
        assert provedor.kind is ProviderKind.AGENT
        assert provedor.ref == "documents-agent"

    async def test_orquestrador_executa_o_agente(self):
        k = await _kernel()
        r = await k.orchestrator.execute(CAPABILITY, {"query": "fatura"}, ctx=_ctx())
        assert r.provider_ref == "documents-agent"
        assert r.output["mode"] == "hybrid"
        assert "fatura" in r.output["hits"][0]["snippet"]

    async def test_manifesto_declara_o_que_usa(self):
        k = await _kernel()
        m = k.agents.get("documents-agent").manifest
        assert m.capabilities == (CAPABILITY,)
        assert m.tools == (SKILL,)
        assert m.memory_access.value == "none"  # não escreve memória do usuário


class TestSandbox:
    async def test_debita_orcamento_por_passo(self):
        k = await _kernel()
        agente = k.agents.get("documents-agent")
        fabrica = SandboxFactory(permissions=k.permissions)
        with fabrica.create(
            agent_id="documents-agent",
            agent_scopes=frozenset({"read:documents"}),
            user_scopes=frozenset({"read:documents"}),
            limits=agente.manifest.limits,
        ) as sandbox:
            await agente.handle({"query": "x"}, _ctx(), sandbox=sandbox)
            assert sandbox.budget.snapshot().steps == 1

    async def test_orcamento_estourado_interrompe(self):
        k = await _kernel()
        agente = k.agents.get("documents-agent")
        fabrica = SandboxFactory(permissions=k.permissions)
        with fabrica.create(
            agent_id="documents-agent",
            agent_scopes=frozenset({"read:documents"}),
            user_scopes=frozenset({"read:documents"}),
            limits=AgentLimits(max_steps=1),
        ) as sandbox:
            await agente.handle({"query": "1"}, _ctx(), sandbox=sandbox)
            with pytest.raises(BudgetExceededError):
                await agente.handle({"query": "2"}, _ctx(), sandbox=sandbox)


class TestModosDeFalha:
    async def test_escopo_negado_barra_a_skill(self):
        """O usuário não concedeu read:documents: a skill é negada mesmo com o
        agente declarando a tool."""
        k = await _kernel(default_allow=False)
        agente = k.agents.get("documents-agent")
        with pytest.raises(SkillPermissionDeniedError):
            await agente.handle({"query": "x"}, _ctx())

    async def test_cancelamento_e_observado(self):
        k = await _kernel()
        agente = k.agents.get("documents-agent")
        token = CancellationToken(name="execucao")
        token.cancel(CancelReason.USER, requested_by="teste")
        with pytest.raises(OperationCancelledError):
            await agente.handle({"query": "x"}, _ctx(cancellation=token))

    async def test_entrada_invalida_propaga(self):
        k = await _kernel()
        agente = k.agents.get("documents-agent")
        with pytest.raises(Exception):  # noqa: B017 — validação do Pydantic
            await agente.handle({"sem_query": True}, _ctx())


# canário anti-truncamento
