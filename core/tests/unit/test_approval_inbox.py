"""Caixa de aprovações (L2.0) — o Human-in-the-Loop com para onde ir.

Antes disto o gate era decorativo: a ação de risco era barrada e a intenção
morria ali. Aqui o "precisa confirmar" vira ticket, e o sim REEXECUTA o
pedido original — é isso que separa confirmação real de teatro.
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
from lumbra.modules.playbooks import PlaybookModule
from lumbra.ports.approval import (
    ApprovalAlreadyDecidedError,
    ApprovalNotFoundError,
    ApprovalState,
)
from lumbra.ports.skills import RiskLevel, SkillApprovalRequiredError, SkillContext

_PROCEDIMENTO = {
    "title": "Reindexar após mudança de extração",
    "when_to_use": "quando o pipeline muda e os chunks ficam obsoletos",
    "steps": ("Reiniciar o Nó", "Rodar reindexar com force"),
}


async def _monta(*, teto: RiskLevel = RiskLevel.LOW):
    """Teto LOW: escrever playbook (MEDIUM) passa a exigir confirmação."""
    store = InMemoryApprovalStore()
    playbooks = InMemoryPlaybookStore()
    kernel = LumbraKernel(
        events=EventRegistry(),
        bus=InMemoryEventBus(),
        event_store=InMemoryEventStore(),
        permissions=StaticPermissionAdapter(default_allow=True),
        approval=RecordingApprovalPolicy(store, auto_ate=teto),
    )
    kernel.register_module(PlaybookModule(playbooks))
    await kernel.start()
    return kernel, store, playbooks, ApprovalService(kernel.skills, store)


def _ctx(user=None) -> SkillContext:
    uid = user or uuid4()
    return SkillContext(subject=f"user:{uid}", user_id=uid)


class TestPedidoVirapendente:
    async def test_acao_barrada_deixa_ticket_com_o_pedido_inteiro(self):
        kernel, _store, _pb, service = await _monta()
        ctx = _ctx()
        with pytest.raises(SkillApprovalRequiredError):
            await kernel.skills.execute("playbook.write", _PROCEDIMENTO, context=ctx)

        pendentes = await service.pending(ctx.user_id)
        assert len(pendentes) == 1
        t = pendentes[0]
        assert t.action == "playbook.write"
        assert t.risk_level is RiskLevel.MEDIUM
        assert t.state is ApprovalState.PENDING
        # sem o payload, o "sim" não teria o que reexecutar
        assert t.payload["title"] == _PROCEDIMENTO["title"]

    async def test_acao_dentro_do_teto_nao_gera_ticket(self):
        kernel, _s, _pb, service = await _monta(teto=RiskLevel.CRITICAL)
        ctx = _ctx()
        await kernel.skills.execute("playbook.write", _PROCEDIMENTO, context=ctx)
        assert await service.pending(ctx.user_id) == []

    async def test_leitura_nunca_gera_ticket(self):
        """Skill LOW não passa pelo gate — senão o contexto do chat pediria
        confirmação a cada mensagem."""
        kernel, _s, _pb, service = await _monta()
        ctx = _ctx()
        await kernel.skills.execute("playbook.search", {"query": "x"}, context=ctx)
        assert await service.pending(ctx.user_id) == []


class TestSimExecuta:
    async def test_aprovar_executa_o_pedido_original(self):
        kernel, _s, playbooks, service = await _monta()
        ctx = _ctx()
        with pytest.raises(SkillApprovalRequiredError):
            await kernel.skills.execute("playbook.write", _PROCEDIMENTO, context=ctx)

        ticket = (await service.pending(ctx.user_id))[0]
        resultado = await service.approve(ticket.id, user_id=ctx.user_id)

        assert resultado.title == _PROCEDIMENTO["title"]
        # o efeito é REAL: o playbook existe depois do sim
        gravados = await playbooks.list_by_user(ctx.user_id)
        assert [p.title for p in gravados] == [_PROCEDIMENTO["title"]]
        assert await service.pending(ctx.user_id) == []

    async def test_rejeitar_nao_executa(self):
        kernel, _s, playbooks, service = await _monta()
        ctx = _ctx()
        with pytest.raises(SkillApprovalRequiredError):
            await kernel.skills.execute("playbook.write", _PROCEDIMENTO, context=ctx)

        ticket = (await service.pending(ctx.user_id))[0]
        recusado = await service.reject(ticket.id, user_id=ctx.user_id)
        assert recusado.state is ApprovalState.REJECTED
        assert await playbooks.list_by_user(ctx.user_id) == []

    async def test_decisao_nao_se_repete(self):
        """Um sim não pode ser reaproveitado para rodar a ação duas vezes."""
        kernel, _s, playbooks, service = await _monta()
        ctx = _ctx()
        with pytest.raises(SkillApprovalRequiredError):
            await kernel.skills.execute("playbook.write", _PROCEDIMENTO, context=ctx)

        ticket = (await service.pending(ctx.user_id))[0]
        await service.approve(ticket.id, user_id=ctx.user_id)
        with pytest.raises(ApprovalAlreadyDecidedError):
            await service.approve(ticket.id, user_id=ctx.user_id)
        assert len(await playbooks.list_by_user(ctx.user_id)) == 1

    async def test_rejeitado_nao_pode_ser_aprovado_depois(self):
        kernel, _s, _pb, service = await _monta()
        ctx = _ctx()
        with pytest.raises(SkillApprovalRequiredError):
            await kernel.skills.execute("playbook.write", _PROCEDIMENTO, context=ctx)
        ticket = (await service.pending(ctx.user_id))[0]
        await service.reject(ticket.id, user_id=ctx.user_id)
        with pytest.raises(ApprovalAlreadyDecidedError):
            await service.approve(ticket.id, user_id=ctx.user_id)


class TestIsolamento:
    async def test_ticket_de_outro_usuario_nao_aparece_nem_decide(self):
        kernel, _s, _pb, service = await _monta()
        dono, outro = _ctx(), _ctx()
        with pytest.raises(SkillApprovalRequiredError):
            await kernel.skills.execute("playbook.write", _PROCEDIMENTO, context=dono)

        ticket = (await service.pending(dono.user_id))[0]
        assert await service.pending(outro.user_id) == []
        # inexistente e alheio respondem igual: não vaza a existência
        with pytest.raises(ApprovalNotFoundError):
            await service.approve(ticket.id, user_id=outro.user_id)

    async def test_pedido_sem_usuario_continua_apenas_barrado(self):
        """Sem dono não há a quem perguntar: nada de ticket órfão."""
        kernel, store, _pb, _service = await _monta()
        with pytest.raises(SkillApprovalRequiredError):
            await kernel.skills.execute(
                "playbook.write", _PROCEDIMENTO, context=SkillContext(subject="agent:x")
            )
        assert store._tickets == {}


# canário anti-truncamento
