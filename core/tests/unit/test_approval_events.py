"""A decisão humana entra na trilha de auditoria (L2.1).

A Lumbra publica evento para tudo que faz. Faltava o mais importante de um
sistema que age em nome de alguém: o que ela QUIS fazer e o que o dono
respondeu. Sem isso, um agente insistindo numa ação recusada sempre seria
invisível — cada tentativa some no 409.
"""

from uuid import uuid4

import pytest

from lumbra.adapters.approvals.in_memory import InMemoryApprovalStore
from lumbra.adapters.eventbus.in_memory import InMemoryEventBus
from lumbra.adapters.eventstore.in_memory import InMemoryEventStore
from lumbra.adapters.permissions.static import StaticPermissionAdapter
from lumbra.adapters.playbooks.in_memory import InMemoryPlaybookStore
from lumbra.domain.events import EventRegistry
from lumbra.kernel.approval import RecordingApprovalPolicy
from lumbra.kernel.approval_service import ApprovalService
from lumbra.kernel.kernel import LumbraKernel
from lumbra.kernel.learning import PlaybookProposer
from lumbra.kernel.planning import PlanResult, StepResult, StepStatus
from lumbra.modules.playbooks import PlaybookModule
from lumbra.ports.skills import RiskLevel, SkillApprovalRequiredError, SkillContext

_PROCEDIMENTO = {
    "title": "Reindexar apos mudar a extracao",
    "when_to_use": "quando o pipeline muda e os chunks ficam obsoletos",
    "steps": ("Reiniciar o No", "Rodar reindexar"),
}


def _ctx(user=None) -> SkillContext:
    uid = user or uuid4()
    return SkillContext(subject=f"user:{uid}", user_id=uid)


async def _monta():
    store = InMemoryApprovalStore()
    event_store = InMemoryEventStore()

    # a política publica pelo kernel, que só existe adiante: a closure resolve
    # o nome na hora da chamada (mesma montagem do composition root)
    async def publicar(payload, **kwargs):
        await kernel.publish(payload, **kwargs)

    kernel = LumbraKernel(
        events=EventRegistry(),
        bus=InMemoryEventBus(),
        event_store=event_store,
        permissions=StaticPermissionAdapter(default_allow=True),
        approval=RecordingApprovalPolicy(store, auto_ate=RiskLevel.LOW, publish=publicar),
    )
    kernel.register_module(PlaybookModule(InMemoryPlaybookStore()))
    await kernel.start()
    service = ApprovalService(kernel.skills, store, publish=kernel.publish)
    return kernel, event_store, service


async def _tipos(event_store: InMemoryEventStore) -> list[str]:
    return [e.type for e in await event_store.read()]


class TestTrilhaDeAuditoria:
    async def test_pedido_barrado_publica_approval_requested(self):
        kernel, eventos, _service = await _monta()
        ctx = _ctx()
        with pytest.raises(SkillApprovalRequiredError):
            await kernel.skills.execute("playbook.write", _PROCEDIMENTO, context=ctx)
        assert "approval.requested" in await _tipos(eventos)

    async def test_sim_publica_granted_e_nao_publica_rejected(self):
        kernel, eventos, service = await _monta()
        ctx = _ctx()
        with pytest.raises(SkillApprovalRequiredError):
            await kernel.skills.execute("playbook.write", _PROCEDIMENTO, context=ctx)
        ticket = (await service.pending(ctx.user_id))[0]
        await service.approve(ticket.id, user_id=ctx.user_id)

        tipos = await _tipos(eventos)
        assert "approval.granted" in tipos
        assert "approval.rejected" not in tipos

    async def test_o_nao_tambem_e_registrado(self):
        """O 'não' é o rastro que denuncia insistência — vale tanto quanto
        o 'sim'."""
        kernel, eventos, service = await _monta()
        ctx = _ctx()
        with pytest.raises(SkillApprovalRequiredError):
            await kernel.skills.execute("playbook.write", _PROCEDIMENTO, context=ctx)
        ticket = (await service.pending(ctx.user_id))[0]
        await service.reject(ticket.id, user_id=ctx.user_id)

        tipos = await _tipos(eventos)
        assert "approval.rejected" in tipos
        assert "approval.granted" not in tipos

    async def test_evento_carrega_o_ticket_e_a_acao(self):
        kernel, eventos, service = await _monta()
        ctx = _ctx()
        with pytest.raises(SkillApprovalRequiredError):
            await kernel.skills.execute("playbook.write", _PROCEDIMENTO, context=ctx)
        ticket = (await service.pending(ctx.user_id))[0]

        pedido = next(e for e in await eventos.read() if e.type == "approval.requested")
        assert pedido.payload["ticket"] == str(ticket.id)
        assert pedido.payload["action"] == "playbook.write"
        assert pedido.payload["risk_level"] == "medium"
        assert pedido.user_id == ctx.user_id


class TestPropostaTambemEntra:
    async def test_proposta_do_learning_loop_publica_requested(self):
        """Proposta e pedido barrado são a mesma coisa para a auditoria: a
        plataforma quis escrever e foi perguntar."""
        store = InMemoryApprovalStore()
        event_store = InMemoryEventStore()
        kernel = LumbraKernel(
            events=EventRegistry(),
            bus=InMemoryEventBus(),
            event_store=event_store,
            permissions=StaticPermissionAdapter(default_allow=True),
        )
        proposer = PlaybookProposer(InMemoryPlaybookStore(), store, publish=kernel.publish)
        ctx = _ctx()
        plano = PlanResult(
            goal="consolidar faturas do mes",
            results=(
                StepResult(step=0, skill="a.um", status=StepStatus.COMPLETED, output={}),
                StepResult(step=1, skill="a.dois", status=StepStatus.COMPLETED, output={}),
            ),
        )
        assert await proposer.propose("consolidar faturas do mes", plano, ctx=ctx)
        assert "approval.requested" in await _tipos(event_store)


# canário anti-truncamento
