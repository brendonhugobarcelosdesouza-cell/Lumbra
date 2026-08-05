"""A skill descreve o próprio pedido (L2.3).

Encontrado testando a interface: o cartão de aprovação mostrava
"playbook.forget" e um id opaco. Pedir para alguém autorizar uma EXCLUSÃO
sem dizer o que será excluído não é confirmação — é treinar o hábito de
clicar em "Aprovar" sem ler, que é o oposto do que o gate existe para fazer.
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
from lumbra.kernel.kernel import LumbraKernel
from lumbra.modules.playbooks import PlaybookModule
from lumbra.ports.playbooks import PlaybookOrigin
from lumbra.ports.skills import (
    RiskLevel,
    Skill,
    SkillApprovalRequiredError,
    SkillContext,
    SkillInput,
    SkillManifest,
    SkillOutput,
)

_PROCEDIMENTO = {
    "title": "Reindexar após mudar a extração",
    "when_to_use": "quando o pipeline muda",
    "steps": ("Reiniciar o Nó", "Rodar reindexar"),
}


def _ctx(user=None) -> SkillContext:
    uid = user or uuid4()
    return SkillContext(subject=f"user:{uid}", user_id=uid)


async def _monta(*, teto: RiskLevel = RiskLevel.LOW):
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
    return kernel, store, playbooks


class TestDescricaoNoPedido:
    async def test_guardar_diz_o_titulo_e_o_tamanho(self):
        kernel, store, _pb = await _monta()
        ctx = _ctx()
        with pytest.raises(SkillApprovalRequiredError):
            await kernel.skills.execute("playbook.write", _PROCEDIMENTO, context=ctx)

        (ticket,) = await store.list_pending(ctx.user_id)
        assert "Reindexar após mudar a extração" in ticket.reason
        assert "2 passos" in ticket.reason

    async def test_proposta_da_plataforma_se_identifica(self):
        """Quem pede muda o peso da decisão: o usuário precisa saber que a
        sugestão partiu da Lumbra, não dele."""
        kernel, store, _pb = await _monta()
        ctx = _ctx()
        with pytest.raises(SkillApprovalRequiredError):
            await kernel.skills.execute(
                "playbook.write",
                {**_PROCEDIMENTO, "origin": PlaybookOrigin.AGENT},
                context=ctx,
            )
        (ticket,) = await store.list_pending(ctx.user_id)
        assert "a Lumbra quer guardar" in ticket.reason

    async def test_esquecer_diz_qual_procedimento(self):
        """O caso que motivou tudo: antes, o cartao mostrava so o id."""
        kernel, store, _pb = await _monta(teto=RiskLevel.CRITICAL)
        ctx = _ctx()
        escrito = await kernel.skills.execute("playbook.write", _PROCEDIMENTO, context=ctx)

        # agora com o gate mordendo, o pedido de exclusao precisa se explicar
        kernel.approval = RecordingApprovalPolicy(store, auto_ate=RiskLevel.LOW)
        kernel.skills._approval = kernel.approval
        with pytest.raises(SkillApprovalRequiredError):
            await kernel.skills.execute(
                "playbook.forget", {"playbook_id": escrito.playbook_id}, context=ctx
            )

        (ticket,) = await store.list_pending(ctx.user_id)
        assert "Reindexar após mudar a extração" in ticket.reason
        assert escrito.playbook_id not in ticket.reason  # id nao ajuda ninguem


class TestRobustez:
    async def test_skill_sem_describe_cai_no_generico(self):
        kernel, store, _pb = await _monta()

        class _In(SkillInput):
            x: int = 1

        class _Out(SkillOutput):
            ok: bool = True

        async def _handler(_p: SkillInput, _c: SkillContext) -> _Out:
            return _Out()

        await kernel.skills.register(
            Skill(
                manifest=SkillManifest(
                    name="teste.arriscada",
                    description="sem describe",
                    provider="teste",
                    risk_level=RiskLevel.HIGH,
                ),
                input_model=_In,
                output_model=_Out,
                handler=_handler,
            )
        )
        ctx = _ctx()
        with pytest.raises(SkillApprovalRequiredError):
            await kernel.skills.execute("teste.arriscada", {}, context=ctx)
        (ticket,) = await store.list_pending(ctx.user_id)
        assert "teste.arriscada" in ticket.reason

    async def test_describe_que_falha_nao_impede_a_decisao(self):
        """Descrever é enfeite: se a consulta cair, o pedido continua sendo
        feito — só que sem a frase bonita."""
        kernel, store, _pb = await _monta()

        class _In(SkillInput):
            x: int = 1

        class _Out(SkillOutput):
            ok: bool = True

        async def _handler(_p: SkillInput, _c: SkillContext) -> _Out:
            return _Out()

        async def _describe_quebrado(_p: SkillInput, _c: SkillContext) -> str:
            raise RuntimeError("banco fora do ar")

        await kernel.skills.register(
            Skill(
                manifest=SkillManifest(
                    name="teste.quebrada",
                    description="describe quebrado",
                    provider="teste",
                    risk_level=RiskLevel.HIGH,
                ),
                input_model=_In,
                output_model=_Out,
                handler=_handler,
                describe=_describe_quebrado,
            )
        )
        ctx = _ctx()
        with pytest.raises(SkillApprovalRequiredError):
            await kernel.skills.execute("teste.quebrada", {}, context=ctx)
        assert len(await store.list_pending(ctx.user_id)) == 1


class TestValidacaoAntesDoGate:
    async def test_pedido_malformado_nao_vira_decisao_humana(self):
        """Perguntar sobre algo que nem seria executável gasta a atenção do
        usuário à toa — e enche a fila de lixo."""
        kernel, store, _pb = await _monta()
        ctx = _ctx()
        with pytest.raises(Exception):  # noqa: B017  (ValidationError)
            await kernel.skills.execute("playbook.write", {"title": "x"}, context=ctx)
        assert await store.list_pending(ctx.user_id) == []


# canário anti-truncamento
