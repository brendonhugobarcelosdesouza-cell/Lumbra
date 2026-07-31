"""Orchestrator camadas 1-2 (A5.1, ADR-062).

Regras determinísticas e Capability Router: descobre a capability, resolve o
provedor e executa — skill fina OU agente — registrando cada decisão. A IA não
participa de nada aqui (é a 4ª camada, ainda desligada).
"""

from collections.abc import Mapping
from typing import Any

import pytest

from lumbra.adapters.eventbus.in_memory import InMemoryEventBus
from lumbra.adapters.eventstore.in_memory import InMemoryEventStore
from lumbra.adapters.permissions.static import StaticPermissionAdapter
from lumbra.domain.events import EventRegistry
from lumbra.kernel.decisions import DecisionKind
from lumbra.kernel.kernel import LumbraKernel
from lumbra.kernel.orchestrator import OrchestrationError
from lumbra.ports.agents import AgentManifest, AgentPort, AgentResult
from lumbra.ports.capabilities import CapabilityProvider, CapabilitySpec, ProviderKind
from lumbra.ports.skills import (
    Skill,
    SkillContext,
    SkillInput,
    SkillManifest,
    SkillOutput,
)


class _In(SkillInput):
    text: str = "oi"


class _Out(SkillOutput):
    echoed: str


async def _echo(payload: SkillInput, _c: SkillContext) -> _Out:
    assert isinstance(payload, _In)
    return _Out(echoed=payload.text.upper())


class _Agente(AgentPort):
    def __init__(self, kernel: LumbraKernel) -> None:
        self._kernel = kernel
        self._manifest = AgentManifest(
            id="eco-agent",
            name="Eco",
            description="agente que compõe a skill",
            provider="test",
            capabilities=("demo.composta",),
            tools=("test.echo",),
        )

    @property
    def manifest(self) -> AgentManifest:
        return self._manifest

    async def handle(self, request: Mapping[str, Any], ctx: SkillContext) -> AgentResult:
        out = await self._kernel.skills.execute("test.echo", request, context=ctx)
        return AgentResult(output={"via_agente": out.model_dump(mode="json")})


@pytest.fixture()
async def kernel():
    k = LumbraKernel(
        events=EventRegistry(),
        bus=InMemoryEventBus(),
        event_store=InMemoryEventStore(),
        permissions=StaticPermissionAdapter(default_allow=True),
    )
    await k.skills.register(
        Skill(
            manifest=SkillManifest(name="test.echo", description="echo", provider="test"),
            input_model=_In,
            output_model=_Out,
            handler=_echo,
        )
    )
    # capability fina (cumprida direto pela skill)
    k.capabilities.register_capability(CapabilitySpec(id="demo.fina"))
    k.capabilities.register_provider(
        CapabilityProvider(capability_id="demo.fina", kind=ProviderKind.SKILL, ref="test.echo")
    )
    # capability composta (cumprida por um agente)
    k.capabilities.register_capability(CapabilitySpec(id="demo.composta"))
    k.agents.register(_Agente(k))
    yield k


def _ctx() -> SkillContext:
    return SkillContext(subject="user:test")


class TestRoteamento:
    async def test_intencao_igual_a_capability(self, kernel):
        assert kernel.orchestrator.route("demo.fina") == "demo.fina"

    async def test_regra_deterministica_tem_precedencia(self, kernel):
        kernel.orchestrator.add_rule("resumir_documento", "demo.fina")
        assert kernel.orchestrator.route("resumir_documento") == "demo.fina"

    async def test_intencao_desconhecida_levanta(self, kernel):
        with pytest.raises(OrchestrationError):
            kernel.orchestrator.route("nao.existe")


class TestExecucao:
    async def test_executa_skill_fina(self, kernel):
        r = await kernel.orchestrator.execute("demo.fina", {"text": "olá"}, ctx=_ctx())
        assert r.provider_kind is ProviderKind.SKILL
        assert r.output == {"echoed": "OLÁ"}
        assert r.layer == "capability_router"

    async def test_executa_agente(self, kernel):
        r = await kernel.orchestrator.execute("demo.composta", {"text": "oi"}, ctx=_ctx())
        assert r.provider_kind is ProviderKind.AGENT
        assert r.provider_ref == "eco-agent"
        assert r.output == {"via_agente": {"echoed": "OI"}}

    async def test_camada_de_regra_e_reportada(self, kernel):
        kernel.orchestrator.add_rule("eco", "demo.fina")
        r = await kernel.orchestrator.execute("eco", {"text": "x"}, ctx=_ctx())
        assert r.layer == "rules"

    async def test_capability_sem_provedor_levanta(self, kernel):
        kernel.capabilities.register_capability(CapabilitySpec(id="demo.orfa"))
        with pytest.raises(OrchestrationError):
            await kernel.orchestrator.execute("demo.orfa", {}, ctx=_ctx())


class TestCamadaPlanner:
    """A5.2: camada 3 — objetivos multi-passo pelo Planner/PlanRunner que
    estavam dormentes desde que foram construídos."""

    async def test_objetivo_multipasso_executa_o_plano(self, kernel):
        # o KeywordPlanner casa capacidades da skill com palavras do objetivo
        await kernel.skills.register(
            Skill(
                manifest=SkillManifest(
                    name="test.resumir",
                    description="resume",
                    provider="test",
                    capabilities=("resumir",),
                ),
                input_model=_In,
                output_model=_Out,
                handler=_echo,
            )
        )
        resultado = await kernel.orchestrator.achieve("resumir tudo", ctx=_ctx())
        assert resultado.succeeded
        assert [r.skill for r in resultado.results] == ["test.resumir"]

    async def test_registra_a_decisao_de_planejar(self, kernel):
        await kernel.skills.register(
            Skill(
                manifest=SkillManifest(
                    name="test.listar",
                    description="lista",
                    provider="test",
                    capabilities=("listar",),
                ),
                input_model=_In,
                output_model=_Out,
                handler=_echo,
            )
        )
        await kernel.orchestrator.achieve("listar coisas", ctx=_ctx())
        (decisao,) = kernel.decisions.query(kind=DecisionKind.PLANNING)
        assert "KeywordPlanner" in decisao.decision
        assert decisao.inputs_used["deterministic"] is True  # planner sem IA

    async def test_objetivo_indecomponivel_levanta(self, kernel):
        with pytest.raises(OrchestrationError):
            await kernel.orchestrator.achieve("objetivo que ninguem sabe fazer", ctx=_ctx())


class TestDecisoesRegistradas:
    async def test_registra_roteamento_e_selecao_de_provedor(self, kernel):
        await kernel.orchestrator.execute("demo.fina", {"text": "a"}, ctx=_ctx())
        roteamento = kernel.decisions.query(kind=DecisionKind.CAPABILITY_ROUTING)
        provedor = kernel.decisions.query(kind=DecisionKind.PROVIDER_SELECTION)
        assert roteamento and provedor
        assert "demo.fina" in roteamento[0].decision
        assert "test.echo" in provedor[0].decision

    async def test_decisoes_sao_deterministicas(self, kernel):
        await kernel.orchestrator.execute("demo.fina", {"text": "a"}, ctx=_ctx())
        for registro in kernel.decisions.query():
            assert registro.inputs_used["deterministic"] is True  # sem IA nas camadas 1-2


# canário anti-truncamento
