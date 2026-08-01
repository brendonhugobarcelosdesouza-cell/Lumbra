"""Política de aprovação padrão do kernel (A0) — Human-in-the-Loop.

Vive no kernel como o ``KeywordPlanner``: é o DEFAULT trivial de um port, não
uma infraestrutura. A política real (backed nas configurações do usuário)
chegará como adaptador, atrás do mesmo ``ApprovalPolicyPort``.

Default explícito: aprova tudo até ``CRITICAL`` — ou seja, TUDO — para que
ligar o gate no SkillRegistry não quebre nada enquanto ainda não há tela de
confirmação. Quando a interface chegar, baixa-se o teto (ex.: ``LOW``) e
``MEDIUM+`` passa a exigir confirmação, sem tocar no Core.
"""

from __future__ import annotations

from lumbra.ports.approval import (
    ApprovalDecision,
    ApprovalOutcome,
    ApprovalPolicyPort,
    ApprovalRequest,
    ApprovalStorePort,
    ApprovalTicket,
)
from lumbra.ports.skills import RiskLevel
from lumbra.shared.ids import uuid7
from lumbra.shared.logging import get_logger

_log = get_logger("lumbra.kernel.approval")

# ordem explícita dos níveis (StrEnum não é ordenável por padrão)
_ORDEM: dict[RiskLevel, int] = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
    RiskLevel.CRITICAL: 3,
}


class AutoApprovePolicy(ApprovalPolicyPort):
    """Aprova ações com risco até ``auto_ate`` (inclusive); acima, pede
    confirmação. Default ``CRITICAL`` = aprova tudo (o 'default permitir')."""

    def __init__(self, *, auto_ate: RiskLevel = RiskLevel.CRITICAL) -> None:
        self._teto = _ORDEM[auto_ate]

    async def decide(self, request: ApprovalRequest) -> ApprovalOutcome:
        if _ORDEM[request.risk_level] <= self._teto:
            return ApprovalOutcome(decision=ApprovalDecision.ALLOW)
        return ApprovalOutcome(
            decision=ApprovalDecision.NEEDS_CONFIRMATION,
            reason=f"risco {request.risk_level.value} acima do teto de aprovação automática",
        )


class RecordingApprovalPolicy(ApprovalPolicyPort):
    """Mesma decisão da ``AutoApprovePolicy``, mas o "precisa confirmar" vira
    um TICKET pendente em vez de um beco sem saída.

    Sem isso o gate era decorativo: a ação era barrada e a intenção do usuário
    se perdia — ele nem ficava sabendo o que ficou por fazer. Aqui o pedido
    sobrevive à recusa e pode ser executado quando o humano disser sim.

    Pedido sem ``user_id`` não vira ticket (não há a quem perguntar): a ação
    continua barrada, como antes.
    """

    def __init__(
        self, store: ApprovalStorePort, *, auto_ate: RiskLevel = RiskLevel.CRITICAL
    ) -> None:
        self._store = store
        self._base = AutoApprovePolicy(auto_ate=auto_ate)

    async def decide(self, request: ApprovalRequest) -> ApprovalOutcome:
        outcome = await self._base.decide(request)
        if outcome.decision is not ApprovalDecision.NEEDS_CONFIRMATION:
            return outcome
        if request.user_id is None:
            return outcome
        ticket = await self._store.add(
            ApprovalTicket(
                id=uuid7(),
                user_id=request.user_id,
                action=request.action,
                subject=request.subject,
                risk_level=request.risk_level,
                reason=request.reason,
                payload=request.payload,
            )
        )
        _log.info(
            "approval_pending",
            ticket=str(ticket.id),
            action=request.action,
            subject=request.subject,
            risk=request.risk_level.value,
        )
        # o id vai na razão: é o que o cliente mostra ao usuário para decidir
        return ApprovalOutcome(
            decision=ApprovalDecision.NEEDS_CONFIRMATION,
            reason=f"{outcome.reason} (aprovação pendente: {ticket.id})",
        )


# canário anti-truncamento
