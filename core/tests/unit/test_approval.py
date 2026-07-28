"""Gate de aprovação por risco no SkillRegistry (A0.2, ADR-024).

O risk_level era declarado e nunca verificado (dívida). Agora skills >= MEDIUM
passam pela política ANTES de executar. O default 'aprova tudo' garante zero
regressão; baixar o teto faz o gate morder de fato.
"""

import pytest

from lumbra.adapters.eventbus.in_memory import InMemoryEventBus
from lumbra.adapters.eventstore.in_memory import InMemoryEventStore
from lumbra.adapters.permissions.static import StaticPermissionAdapter
from lumbra.domain.events import EventRegistry
from lumbra.kernel.approval import AutoApprovePolicy
from lumbra.kernel.kernel import LumbraKernel
from lumbra.ports.approval import (
    ApprovalDecision,
    ApprovalOutcome,
    ApprovalPolicyPort,
    ApprovalRequest,
)
from lumbra.ports.skills import (
    RiskLevel,
    Skill,
    SkillApprovalRequiredError,
    SkillContext,
    SkillInput,
    SkillManifest,
    SkillOutput,
)


class _In(SkillInput):
    pass


class _Out(SkillOutput):
    ok: bool = True


async def _handler(_p: SkillInput, _c: SkillContext) -> _Out:
    return _Out()


def _skill(name: str, risk: RiskLevel) -> Skill:
    return Skill(
        manifest=SkillManifest(name=name, description=name, provider="test", risk_level=risk),
        input_model=_In,
        output_model=_Out,
        handler=_handler,
    )


def _kernel(approval: ApprovalPolicyPort | None = None) -> LumbraKernel:
    return LumbraKernel(
        events=EventRegistry(),
        bus=InMemoryEventBus(),
        event_store=InMemoryEventStore(),
        permissions=StaticPermissionAdapter(default_allow=True),
        approval=approval,
    )


class TestAutoApprovePolicy:
    async def test_default_aprova_tudo(self):
        pol = AutoApprovePolicy()
        for risco in RiskLevel:
            out = await pol.decide(ApprovalRequest(action="x", subject="s", risk_level=risco))
            assert out.allowed

    async def test_teto_baixo_pede_confirmacao_acima(self):
        pol = AutoApprovePolicy(auto_ate=RiskLevel.LOW)
        baixo = await pol.decide(ApprovalRequest(action="x", subject="s", risk_level=RiskLevel.LOW))
        alto = await pol.decide(
            ApprovalRequest(action="x", subject="s", risk_level=RiskLevel.MEDIUM)
        )
        assert baixo.allowed
        assert alto.decision is ApprovalDecision.NEEDS_CONFIRMATION


class TestGateNoRegistry:
    async def test_skill_low_nao_passa_pelo_gate(self):
        # LOW nunca consulta a política — nem precisa de aprovação
        kernel = _kernel(approval=_NegaTudo())
        await kernel.skills.register(_skill("test.leitura", RiskLevel.LOW))
        out = await kernel.skills.execute("test.leitura", {}, context=_ctx())
        assert out.ok  # executou apesar da política negar tudo

    async def test_skill_medium_barrada_quando_politica_nega(self):
        kernel = _kernel(approval=_NegaTudo())
        await kernel.skills.register(_skill("test.escrita", RiskLevel.MEDIUM))
        with pytest.raises(SkillApprovalRequiredError):
            await kernel.skills.execute("test.escrita", {}, context=_ctx())

    async def test_default_do_kernel_nao_quebra_medium(self):
        # sem passar approval: default AutoApprovePolicy aprova tudo
        kernel = _kernel()
        await kernel.skills.register(_skill("test.escrita", RiskLevel.MEDIUM))
        out = await kernel.skills.execute("test.escrita", {}, context=_ctx())
        assert out.ok


class _NegaTudo(ApprovalPolicyPort):
    async def decide(self, request: ApprovalRequest) -> ApprovalOutcome:
        return ApprovalOutcome(decision=ApprovalDecision.DENY, reason="teste")


def _ctx() -> SkillContext:
    return SkillContext(subject="user:test")


# canário anti-truncamento
