"""Delegação agente→agente (A8, ADR-056/061).

Testes ADVERSARIAIS: a delegação é o caminho óbvio para tentar escapar das
regras — pedir a outro agente o que você não pode fazer, criar um ciclo para
gastar sem fim, ou reiniciar o orçamento delegando. Aqui se prova que nenhuma
dessas saídas existe.
"""

from collections.abc import Mapping
from typing import Any

import pytest

from lumbra.adapters.eventbus.in_memory import InMemoryEventBus
from lumbra.adapters.eventstore.in_memory import InMemoryEventStore
from lumbra.adapters.permissions.static import StaticPermissionAdapter
from lumbra.domain.events import EventRegistry
from lumbra.kernel.kernel import LumbraKernel
from lumbra.kernel.sandbox import (
    AgentSandbox,
    BudgetExceededError,
    DelegationDeniedError,
    DelegationLoopError,
)
from lumbra.ports.agents import (
    AgentLimits,
    AgentManifest,
    AgentPort,
    AgentResult,
    DelegationPolicy,
)
from lumbra.ports.capabilities import CapabilitySpec
from lumbra.ports.skills import (
    Skill,
    SkillContext,
    SkillInput,
    SkillManifest,
    SkillOutput,
    SkillPermissionDeniedError,
)


class _In(SkillInput):
    texto: str = "x"


class _Out(SkillOutput):
    feito: str


async def _handler(payload: SkillInput, _c: SkillContext) -> _Out:
    assert isinstance(payload, _In)
    return _Out(feito=payload.texto)


class _Agente(AgentPort):
    """Agente configurável para os cenários de delegação."""

    def __init__(
        self,
        kernel: LumbraKernel,
        *,
        agent_id: str,
        capability: str,
        scopes: tuple[str, ...] = ("read:a",),
        delega_para: str | None = None,
        politica: DelegationPolicy | None = None,
        limits: AgentLimits | None = None,
    ) -> None:
        self._kernel = kernel
        self._delega_para = delega_para
        self._manifest = AgentManifest(
            id=agent_id,
            name=agent_id,
            description=agent_id,
            provider="test",
            capabilities=(capability,),
            required_scopes=scopes,
            delegation=politica or DelegationPolicy(),
            limits=limits or AgentLimits(),
        )

    @property
    def manifest(self) -> AgentManifest:
        return self._manifest

    async def handle(
        self, request: Mapping[str, Any], ctx: SkillContext, *, sandbox: Any | None = None
    ) -> AgentResult:
        if self._delega_para is not None and sandbox is not None:
            saida = await self._kernel.orchestrator.delegate(
                self._delega_para, request, ctx=ctx, sandbox=sandbox
            )
            return AgentResult(output={"delegado": saida})
        return AgentResult(output={"direto": self._manifest.id})


@pytest.fixture()
async def kernel():
    k = LumbraKernel(
        events=EventRegistry(),
        bus=InMemoryEventBus(),
        event_store=InMemoryEventStore(),
        permissions=StaticPermissionAdapter(default_allow=True),
    )
    for nome, escopo in (("skill.a", "read:a"), ("skill.b", "write:b")):
        await k.skills.register(
            Skill(
                manifest=SkillManifest(
                    name=nome, description=nome, provider="t", required_scopes=(escopo,)
                ),
                input_model=_In,
                output_model=_Out,
                handler=_handler,
            )
        )
    for cap in ("demo.a", "demo.b", "demo.c"):
        k.capabilities.register_capability(CapabilitySpec(id=cap))
    yield k


def _ctx() -> SkillContext:
    return SkillContext(subject="user:test")


def _sandbox(kernel, agente: _Agente, *, limits: AgentLimits | None = None) -> AgentSandbox:
    m = agente.manifest
    return AgentSandbox(
        agent_id=m.id,
        permissions=kernel.permissions,
        scopes=frozenset(m.required_scopes),
        limits=limits or m.limits,
    )


class TestPoliticaDeDelegacao:
    async def test_agente_sem_permissao_nao_delega(self, kernel):
        a = _Agente(kernel, agent_id="agente-a", capability="demo.a", delega_para="demo.b")
        b = _Agente(kernel, agent_id="agente-b", capability="demo.b")
        kernel.agents.register(a)
        kernel.agents.register(b)
        with pytest.raises(DelegationDeniedError):
            await a.handle({}, _ctx(), sandbox=_sandbox(kernel, a))

    async def test_delega_apenas_para_capabilities_permitidas(self, kernel):
        politica = DelegationPolicy(can_delegate=True, to_capabilities=("demo.c",))
        a = _Agente(
            kernel,
            agent_id="agente-a",
            capability="demo.a",
            delega_para="demo.b",
            politica=politica,
        )
        b = _Agente(kernel, agent_id="agente-b", capability="demo.b")
        kernel.agents.register(a)
        kernel.agents.register(b)
        with pytest.raises(DelegationDeniedError):  # pediu demo.b, só pode demo.c
            await a.handle({}, _ctx(), sandbox=_sandbox(kernel, a))

    async def test_delegacao_permitida_funciona(self, kernel):
        politica = DelegationPolicy(can_delegate=True, to_capabilities=("demo.b",))
        a = _Agente(
            kernel,
            agent_id="agente-a",
            capability="demo.a",
            delega_para="demo.b",
            politica=politica,
        )
        b = _Agente(kernel, agent_id="agente-b", capability="demo.b")
        kernel.agents.register(a)
        kernel.agents.register(b)
        r = await a.handle({}, _ctx(), sandbox=_sandbox(kernel, a))
        assert r.output == {"delegado": {"direto": "agente-b"}}


class TestAntiEscalada:
    async def test_filho_nao_ganha_escopo_que_o_pai_nao_tem(self, kernel):
        """O cenário clássico: A (read:a) delega para B (write:b) tentando
        alcançar uma skill proibida. A interseção deixa B sem nada."""
        politica = DelegationPolicy(can_delegate=True)
        a = _Agente(
            kernel, agent_id="agente-a", capability="demo.a", scopes=("read:a",), politica=politica
        )
        b = _Agente(kernel, agent_id="agente-b", capability="demo.b", scopes=("write:b",))
        kernel.agents.register(a)
        kernel.agents.register(b)
        pai = _sandbox(kernel, a)
        filho = pai.child(agent_id="agente-b", scopes=frozenset({"write:b"}), limits=AgentLimits())
        assert filho.scopes == frozenset()  # interseção vazia
        escopado = kernel.skills.scoped(filho.permissions)
        with pytest.raises(SkillPermissionDeniedError):
            await escopado.execute("skill.b", {}, context=_ctx())


class TestAntiLoop:
    async def test_ciclo_direto_e_barrado(self, kernel):
        a = _Agente(kernel, agent_id="agente-a", capability="demo.a")
        kernel.agents.register(a)
        pai = _sandbox(kernel, a)
        with pytest.raises(DelegationLoopError):
            pai.child(agent_id="agente-a", scopes=frozenset(), limits=AgentLimits())

    async def test_ciclo_indireto_e_barrado(self, kernel):
        """A → B → A: o terceiro salto vê 'agente-a' já na cadeia."""
        a = _Agente(kernel, agent_id="agente-a", capability="demo.a")
        kernel.agents.register(a)
        pai = _sandbox(kernel, a, limits=AgentLimits(max_depth=5))
        filho = pai.child(agent_id="agente-b", scopes=frozenset(), limits=AgentLimits(max_depth=5))
        assert filho.chain == ("agente-a", "agente-b")
        with pytest.raises(DelegationLoopError):
            filho.child(agent_id="agente-a", scopes=frozenset(), limits=AgentLimits())


class TestOrcamentoCompartilhado:
    async def test_delegar_nao_zera_o_orcamento(self, kernel):
        """Delegar não pode ser escapatória do budget: o filho debita do MESMO
        contador da árvore."""
        a = _Agente(
            kernel, agent_id="agente-a", capability="demo.a", limits=AgentLimits(max_steps=3)
        )
        kernel.agents.register(a)
        pai = _sandbox(kernel, a)
        pai.budget.charge(steps=2)
        filho = pai.child(agent_id="agente-b", scopes=frozenset(), limits=AgentLimits(max_steps=3))
        assert filho.budget is pai.budget  # o mesmo objeto
        filho.budget.charge(steps=1)  # total 3 — no limite
        with pytest.raises(BudgetExceededError):
            filho.budget.charge(steps=1)  # 4 > 3

    async def test_profundidade_maxima_limita_a_cadeia(self, kernel):
        a = _Agente(
            kernel, agent_id="agente-a", capability="demo.a", limits=AgentLimits(max_depth=1)
        )
        kernel.agents.register(a)
        pai = _sandbox(kernel, a)
        filho = pai.child(agent_id="b", scopes=frozenset(), limits=AgentLimits(max_depth=1))
        with pytest.raises(BudgetExceededError):
            filho.child(agent_id="c", scopes=frozenset(), limits=AgentLimits(max_depth=1))


# canário anti-truncamento
