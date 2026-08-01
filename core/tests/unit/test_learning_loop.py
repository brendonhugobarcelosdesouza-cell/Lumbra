"""Learning Loop (L2): o que deu certo vira PROPOSTA de procedimento.

O teste mais importante deste arquivo é o que garante que propor não é
escrever — nem com o teto de aprovação em 'aprova tudo'. A reflexão
automática já guardou uma resposta errada como fato e contaminou o RAG;
memória procedural errada é pior, porque se repete a cada uso.
"""

from uuid import uuid4

from lumbra.adapters.approvals.in_memory import InMemoryApprovalStore
from lumbra.adapters.eventbus.in_memory import InMemoryEventBus
from lumbra.adapters.eventstore.in_memory import InMemoryEventStore
from lumbra.adapters.permissions.static import StaticPermissionAdapter
from lumbra.adapters.playbooks.in_memory import InMemoryPlaybookStore
from lumbra.domain.events import EventRegistry
from lumbra.kernel.kernel import LumbraKernel
from lumbra.kernel.learning import PlaybookProposer
from lumbra.kernel.planning import PlanResult, StepResult, StepStatus
from lumbra.ports.playbooks import Playbook, PlaybookOrigin
from lumbra.ports.skills import (
    Skill,
    SkillContext,
    SkillInput,
    SkillManifest,
    SkillOutput,
)
from lumbra.shared.ids import uuid7

_OBJETIVO = "consolidar as faturas do mes e conferir o total"


class _Vazio(SkillOutput):
    ok: bool = True


async def _nada(_payload: SkillInput, _ctx: SkillContext) -> _Vazio:
    return _Vazio()


def _ctx(user=None) -> SkillContext:
    uid = user or uuid4()
    return SkillContext(subject=f"user:{uid}", user_id=uid)


def _plano_ok(*skills: str) -> PlanResult:
    return PlanResult(
        goal=_OBJETIVO,
        results=tuple(
            StepResult(step=i, skill=s, status=StepStatus.COMPLETED, output={})
            for i, s in enumerate(skills)
        ),
    )


def _proposer() -> tuple[PlaybookProposer, InMemoryPlaybookStore, InMemoryApprovalStore]:
    playbooks, approvals = InMemoryPlaybookStore(), InMemoryApprovalStore()
    return PlaybookProposer(playbooks, approvals), playbooks, approvals


class TestPropoeSoOqueValeAPena:
    async def test_execucao_multi_passo_bem_sucedida_vira_pedido(self):
        proposer, playbooks, approvals = _proposer()
        ctx = _ctx()
        ticket = await proposer.propose(_OBJETIVO, _plano_ok("a.um", "a.dois"), ctx=ctx)

        assert ticket is not None
        assert ticket.action == "playbook.write"
        assert ticket.payload["origin"] == PlaybookOrigin.AGENT.value
        assert ticket.payload["steps"] == ["Executar a.um", "Executar a.dois"]
        # PROPOR NÃO É ESCREVER: nada foi para a memória procedural
        assert await playbooks.list_by_user(ctx.user_id) == []
        assert len(await approvals.list_pending(ctx.user_id)) == 1

    async def test_um_passo_so_nao_e_procedimento(self):
        proposer, _pb, approvals = _proposer()
        ctx = _ctx()
        assert await proposer.propose(_OBJETIVO, _plano_ok("a.um"), ctx=ctx) is None
        assert await approvals.list_pending(ctx.user_id) == []

    async def test_plano_com_falha_nao_ensina(self):
        """Guardar um caminho parcial ensinaria a repetir o erro."""
        proposer, _pb, approvals = _proposer()
        ctx = _ctx()
        parcial = PlanResult(
            goal=_OBJETIVO,
            results=(
                StepResult(step=0, skill="a.um", status=StepStatus.COMPLETED, output={}),
                StepResult(step=1, skill="a.dois", status=StepStatus.FAILED, error="boom"),
            ),
        )
        assert await proposer.propose(_OBJETIVO, parcial, ctx=ctx) is None
        assert await approvals.list_pending(ctx.user_id) == []

    async def test_sem_usuario_nao_propoe(self):
        proposer, _pb, _ap = _proposer()
        ctx = SkillContext(subject="agent:x")
        assert await proposer.propose(_OBJETIVO, _plano_ok("a.um", "a.dois"), ctx=ctx) is None


class TestNaoRepete:
    async def test_nao_propoe_o_que_ja_esta_na_fila(self):
        proposer, _pb, approvals = _proposer()
        ctx = _ctx()
        await proposer.propose(_OBJETIVO, _plano_ok("a.um", "a.dois"), ctx=ctx)
        assert await proposer.propose(_OBJETIVO, _plano_ok("a.um", "a.dois"), ctx=ctx) is None
        assert len(await approvals.list_pending(ctx.user_id)) == 1

    async def test_nao_propoe_o_que_o_usuario_ja_sabe(self):
        proposer, playbooks, approvals = _proposer()
        ctx = _ctx()
        await playbooks.add(
            Playbook(
                id=uuid7(),
                user_id=ctx.user_id,  # type: ignore[arg-type]
                title="Consolidar faturas",
                when_to_use="consolidar as faturas do mes e conferir o total",
                steps=("Abrir a pasta", "Somar"),
            )
        )
        assert await proposer.propose(_OBJETIVO, _plano_ok("a.um", "a.dois"), ctx=ctx) is None
        assert await approvals.list_pending(ctx.user_id) == []

    async def test_proposta_de_um_usuario_nao_bloqueia_outro(self):
        proposer, _pb, approvals = _proposer()
        primeiro, segundo = _ctx(), _ctx()
        await proposer.propose(_OBJETIVO, _plano_ok("a.um", "a.dois"), ctx=primeiro)
        assert await proposer.propose(_OBJETIVO, _plano_ok("a.um", "a.dois"), ctx=segundo)
        assert len(await approvals.list_pending(segundo.user_id)) == 1


class TestNoOrchestrator:
    """O gancho real: achieve() bem-sucedido propõe, e aprender nunca quebra
    o trabalho que já foi feito."""

    async def _kernel(self, proposer: PlaybookProposer | None):
        k = LumbraKernel(
            events=EventRegistry(),
            bus=InMemoryEventBus(),
            event_store=InMemoryEventStore(),
            permissions=StaticPermissionAdapter(default_allow=True),
            proposer=proposer,
        )
        # duas skills triviais cujas capacidades aparecem no objetivo — é
        # assim que o KeywordPlanner monta um plano de 2 passos
        for capacidade in ("alfa", "beta"):
            await k.skills.register(
                Skill(
                    manifest=SkillManifest(
                        name=f"teste.{capacidade}",
                        description="passo trivial",
                        provider="teste",
                        capabilities=(capacidade,),
                    ),
                    input_model=SkillInput,
                    output_model=_Vazio,
                    handler=_nada,
                )
            )
        await k.start()
        return k

    async def test_achieve_multi_passo_deixa_proposta_pendente(self):
        proposer, _pb, approvals = _proposer()
        kernel = await self._kernel(proposer)
        ctx = _ctx()
        objetivo = "alfa beta"
        resultado = await kernel.orchestrator.achieve(objetivo, ctx=ctx)

        assert resultado.succeeded
        pendentes = await approvals.list_pending(ctx.user_id)
        assert [t.payload["title"] for t in pendentes] == [objetivo]
        assert pendentes[0].payload["steps"] == ["Executar teste.alfa", "Executar teste.beta"]

    async def test_sem_proposer_nada_muda(self):
        kernel = await self._kernel(None)
        assert (await kernel.orchestrator.achieve("alfa beta", ctx=_ctx())).succeeded

    async def test_falha_ao_propor_nao_derruba_a_execucao(self):
        class _Quebrado(PlaybookProposer):
            async def propose(self, goal, result, *, ctx):  # type: ignore[override]
                raise RuntimeError("store fora do ar")

        kernel = await self._kernel(_Quebrado(InMemoryPlaybookStore(), InMemoryApprovalStore()))
        resultado = await kernel.orchestrator.achieve("alfa beta", ctx=_ctx())
        assert resultado.succeeded  # o trabalho principal sobreviveu


# canário anti-truncamento
