"""ResearchAgent (A11): a delegação real, com dois agentes de verdade.

Até aqui a delegação era mecanismo testado em cenários sintéticos. Aqui ela
vira uso: um agente que DELEGA a documentos e a memória, com escopo
intersectado e orçamento compartilhado — o desenho do A8 exercitado ponta a
ponta, sem IA (determinístico no CI).
"""

from typing import Any

import pytest

from lumbra.adapters.eventbus.in_memory import InMemoryEventBus
from lumbra.adapters.eventstore.in_memory import InMemoryEventStore
from lumbra.adapters.permissions.static import StaticPermissionAdapter
from lumbra.agents.documents import CAPABILITY as DOCUMENTS
from lumbra.agents.documents import SKILL as SKILL_DOCS
from lumbra.agents.documents import DocumentsAgent
from lumbra.agents.memory import CAPABILITY as MEMORIA
from lumbra.agents.memory import SKILL as SKILL_MEM
from lumbra.agents.memory import MemoryAgent
from lumbra.agents.research import CAPABILITY as PESQUISA
from lumbra.agents.research import ResearchAgent
from lumbra.domain.events import EventRegistry
from lumbra.kernel.decisions import DecisionKind
from lumbra.kernel.kernel import LumbraKernel
from lumbra.kernel.sandbox import AgentSandbox, DelegationDeniedError
from lumbra.ports.capabilities import CapabilityProvider, CapabilitySpec, ProviderKind
from lumbra.ports.skills import (
    Skill,
    SkillContext,
    SkillInput,
    SkillManifest,
    SkillOutput,
)


class _In(SkillInput):
    query: str
    limit: int = 10


class _Out(SkillOutput):
    hits: tuple[dict[str, Any], ...] = ()
    mode: str = "hybrid"


def _busca(prefixo: str):
    async def handler(payload: SkillInput, _c: SkillContext) -> _Out:
        assert isinstance(payload, _In)
        return _Out(hits=({"snippet": f"{prefixo}: {payload.query}"},))

    return handler


async def _kernel(*, default_allow: bool = True) -> LumbraKernel:
    k = LumbraKernel(
        events=EventRegistry(),
        bus=InMemoryEventBus(),
        event_store=InMemoryEventStore(),
        permissions=StaticPermissionAdapter(default_allow=default_allow),
    )
    for nome, escopo, prefixo in (
        (SKILL_DOCS, "read:documents", "doc"),
        (SKILL_MEM, "read:memory", "mem"),
    ):
        await k.skills.register(
            Skill(
                manifest=SkillManifest(
                    name=nome, description=nome, provider="kernel", required_scopes=(escopo,)
                ),
                input_model=_In,
                output_model=_Out,
                handler=_busca(prefixo),
            )
        )
    for cap in (DOCUMENTS, MEMORIA, PESQUISA):
        k.capabilities.register_capability(CapabilitySpec(id=cap))
    k.agents.register(DocumentsAgent(k.skills))
    k.agents.register(MemoryAgent(k.skills))
    k.agents.register(ResearchAgent(k.orchestrator))
    return k


def _ctx() -> SkillContext:
    return SkillContext(subject="user:test")


class TestDelegacaoReal:
    async def test_reune_evidencia_das_duas_fontes(self):
        k = await _kernel()
        r = await k.orchestrator.execute(PESQUISA, {"query": "fatura"}, ctx=_ctx())
        fontes = r.output["sources"]
        assert set(fontes) == {DOCUMENTS, MEMORIA}
        assert fontes[DOCUMENTS]["hits"][0]["snippet"] == "doc: fatura"
        assert fontes[MEMORIA]["hits"][0]["snippet"] == "mem: fatura"
        assert r.output["total_hits"] == 2
        assert r.output["failures"] == {}

    async def test_cada_delegacao_vira_decisao_auditavel(self):
        k = await _kernel()
        await k.orchestrator.execute(PESQUISA, {"query": "x"}, ctx=_ctx())
        decisoes = k.decisions.query(kind=DecisionKind.PROVIDER_SELECTION)
        escolhidos = {d.decision for d in decisoes}
        assert any("documents-agent" in e for e in escolhidos)
        assert any("memory-agent" in e for e in escolhidos)

    async def test_falha_de_uma_fonte_nao_derruba_a_outra(self):
        """Resultado parcial > falha total: a fonte que caiu vira dado."""
        k = await _kernel()
        k.agents.set_enabled("memory-agent", False)  # memória indisponível
        r = await k.orchestrator.execute(PESQUISA, {"query": "y"}, ctx=_ctx())
        assert DOCUMENTS in r.output["sources"]  # documentos respondeu
        assert MEMORIA in r.output["failures"]  # memória registrou a falha
        assert r.output["total_hits"] == 1


class TestLimitesDaDelegacao:
    async def test_so_delega_para_as_capabilities_declaradas(self):
        """O manifesto do research-agent lista documents/memory. Qualquer outra
        capability é negada, mesmo existindo e mesmo o agente tendo escopo."""
        k = await _kernel()
        k.capabilities.register_capability(CapabilitySpec(id="outra.coisa"))
        k.capabilities.register_provider(
            CapabilityProvider(capability_id="outra.coisa", kind=ProviderKind.SKILL, ref=SKILL_DOCS)
        )
        agente = k.agents.get("research-agent")
        with (
            AgentSandbox(
                agent_id="research-agent",
                permissions=k.permissions,
                scopes=frozenset(agente.manifest.required_scopes),
                limits=agente.manifest.limits,
            ) as sb,
            pytest.raises(DelegationDeniedError),
        ):
            await k.orchestrator.delegate("outra.coisa", {}, ctx=_ctx(), sandbox=sb)

    async def test_orcamento_e_compartilhado_entre_as_delegacoes(self):
        """As duas consultas debitam do MESMO teto — delegar não multiplica
        orçamento."""
        k = await _kernel()
        agente = k.agents.get("research-agent")
        with AgentSandbox(
            agent_id="research-agent",
            permissions=k.permissions,
            scopes=frozenset(agente.manifest.required_scopes),
            limits=agente.manifest.limits,
        ) as sb:
            await agente.handle({"query": "z"}, _ctx(), sandbox=sb)
            # 2 delegações, cada delegado debitou 1 passo do orçamento comum
            assert sb.budget.snapshot().steps >= 2

    async def test_escopo_do_delegado_e_intersecao(self):
        """documents-agent pede read:documents; o research tem os dois escopos.
        A interseção mantém só o necessário — nunca amplia."""
        k = await _kernel()
        research = k.agents.get("research-agent").manifest
        docs = k.agents.get("documents-agent").manifest
        pai = AgentSandbox(
            agent_id=research.id,
            permissions=k.permissions,
            scopes=frozenset(research.required_scopes),
            limits=research.limits,
        )
        filho = pai.child(
            agent_id=docs.id,
            scopes=frozenset(docs.required_scopes),
            limits=docs.limits,
        )
        assert filho.scopes == frozenset({"read:documents"})
        assert filho.budget is pai.budget
        assert filho.chain == (research.id, docs.id)


# canário anti-truncamento
