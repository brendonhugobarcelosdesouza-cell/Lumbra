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
)
from lumbra.ports.skills import RiskLevel

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


# canário anti-truncamento
