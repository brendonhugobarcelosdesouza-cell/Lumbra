"""LLM Planner — camada 4 (A9, ADR-062).

O único ponto não-determinístico da orquestração, e por isso o mais cercado:
a IA só entra quando o determinístico falha, o plano é VALIDADO contra as
skills reais (o modelo não inventa passos), e a decisão fica marcada como
assistida por IA. Gateway mockado — testes determinísticos no CI.
"""

from typing import Any

import pytest

from lumbra.adapters.eventbus.in_memory import InMemoryEventBus
from lumbra.adapters.eventstore.in_memory import InMemoryEventStore
from lumbra.adapters.permissions.static import StaticPermissionAdapter
from lumbra.domain.events import EventRegistry
from lumbra.kernel.decisions import DecisionKind
from lumbra.kernel.kernel import LumbraKernel
from lumbra.kernel.llm_planner import LLMPlanner
from lumbra.kernel.orchestrator import OrchestrationError, Orchestrator
from lumbra.ports.ai import ChatResult
from lumbra.ports.skills import (
    Skill,
    SkillContext,
    SkillInput,
    SkillManifest,
    SkillOutput,
)


class _In(SkillInput):
    texto: str = "x"


class _Out(SkillOutput):
    ok: bool = True


async def _handler(_p: SkillInput, _c: SkillContext) -> _Out:
    return _Out()


class _GatewayFake:
    """AI Gateway mockado: devolve o texto combinado, sem rede nem modelo."""

    def __init__(self, resposta: str = "[]", *, falha: bool = False) -> None:
        self.resposta = resposta
        self.falha = falha
        self.chamadas = 0

    async def chat(self, request: Any, *, cancellation: Any = None) -> ChatResult:
        self.chamadas += 1
        if self.falha:
            raise RuntimeError("provedor fora do ar")
        return ChatResult(
            text=self.resposta,
            provider="fake",
            model="fake-1",
            input_tokens=10,
            output_tokens=5,
            finish_reason="stop",
        )

    async def embed(self, *a: Any, **k: Any) -> Any:  # não usado aqui
        raise NotImplementedError


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
            manifest=SkillManifest(name="doc.buscar", description="busca", provider="t"),
            input_model=_In,
            output_model=_Out,
            handler=_handler,
        )
    )
    yield k


def _ctx() -> SkillContext:
    return SkillContext(subject="user:test")


class TestValidacaoDoPlano:
    async def test_plano_valido_vira_passos(self, kernel):
        gw = _GatewayFake('[{"skill": "doc.buscar", "rationale": "preciso buscar"}]')
        plano = await LLMPlanner(gw).plan("objetivo", skills=kernel.skills.manifests())
        assert [p.skill for p in plano.steps] == ["doc.buscar"]
        assert plano.steps[0].rationale == "preciso buscar"

    async def test_skill_inventada_e_descartada(self, kernel):
        """A trava central: o modelo não executa o que imaginou."""
        gw = _GatewayFake('[{"skill": "skill.que.nao.existe", "rationale": "inventei"}]')
        plano = await LLMPlanner(gw).plan("objetivo", skills=kernel.skills.manifests())
        assert plano.steps == ()

    async def test_json_invalido_vira_plano_vazio(self, kernel):
        gw = _GatewayFake("desculpe, não consigo ajudar com isso")
        plano = await LLMPlanner(gw).plan("objetivo", skills=kernel.skills.manifests())
        assert plano.steps == ()

    async def test_extrai_json_com_texto_ao_redor(self, kernel):
        gw = _GatewayFake('Claro! Aqui:\n[{"skill": "doc.buscar"}]\nEspero ter ajudado.')
        plano = await LLMPlanner(gw).plan("objetivo", skills=kernel.skills.manifests())
        assert [p.skill for p in plano.steps] == ["doc.buscar"]

    async def test_provedor_indisponivel_nao_derruba(self, kernel):
        gw = _GatewayFake(falha=True)
        plano = await LLMPlanner(gw).plan("objetivo", skills=kernel.skills.manifests())
        assert plano.steps == ()  # degrada, não explode

    async def test_sem_skills_nem_chama_o_modelo(self, kernel):
        gw = _GatewayFake('[{"skill": "x"}]')
        plano = await LLMPlanner(gw).plan("objetivo", skills=[])
        assert plano.steps == ()
        assert gw.chamadas == 0  # não gasta token à toa


class TestFallbackNaOrquestracao:
    def _orquestrador(self, kernel, gw: _GatewayFake) -> Orchestrator:
        return Orchestrator(
            skills=kernel.skills,
            capabilities=kernel.capabilities,
            agents=kernel.agents,
            decisions=kernel.decisions,
            planner=kernel.planner,  # KeywordPlanner (camada 3)
            plan_runner=kernel.plan_runner,
            llm_planner=LLMPlanner(gw),
        )

    async def test_ia_nao_e_chamada_quando_o_deterministico_resolve(self, kernel):
        """A regra de ouro: IA por último. Se a camada 3 planeja, a 4 nem roda."""
        await kernel.skills.register(
            Skill(
                manifest=SkillManifest(
                    name="doc.resumir",
                    description="resume",
                    provider="t",
                    capabilities=("resumir",),
                ),
                input_model=_In,
                output_model=_Out,
                handler=_handler,
            )
        )
        gw = _GatewayFake('[{"skill": "doc.buscar"}]')
        orq = self._orquestrador(kernel, gw)
        await orq.achieve("resumir tudo", ctx=_ctx())  # KeywordPlanner casa 'resumir'
        assert gw.chamadas == 0  # a IA não foi acionada

    async def test_ia_entra_quando_o_deterministico_falha(self, kernel):
        gw = _GatewayFake('[{"skill": "doc.buscar", "rationale": "única opção"}]')
        orq = self._orquestrador(kernel, gw)
        resultado = await orq.achieve("algo que nenhuma palavra-chave casa", ctx=_ctx())
        assert gw.chamadas == 1
        assert [r.skill for r in resultado.results] == ["doc.buscar"]

    async def test_decisao_marca_que_houve_ia_e_fallback(self, kernel):
        gw = _GatewayFake('[{"skill": "doc.buscar"}]')
        orq = self._orquestrador(kernel, gw)
        await orq.achieve("objetivo obscuro", ctx=_ctx())
        (fallback,) = kernel.decisions.query(kind=DecisionKind.FALLBACK)
        (planejamento,) = kernel.decisions.query(kind=DecisionKind.PLANNING)
        assert "LLMPlanner" in fallback.decision
        assert fallback.inputs_used["deterministic"] is True  # decidir recorrer é regra
        assert planejamento.inputs_used["deterministic"] is False  # o plano veio de IA

    async def test_sem_llm_planner_falha_explicitamente(self, kernel):
        orq = Orchestrator(
            skills=kernel.skills,
            capabilities=kernel.capabilities,
            agents=kernel.agents,
            decisions=kernel.decisions,
            planner=kernel.planner,
            plan_runner=kernel.plan_runner,
        )
        with pytest.raises(OrchestrationError):
            await orq.achieve("objetivo obscuro", ctx=_ctx())


# canário anti-truncamento
