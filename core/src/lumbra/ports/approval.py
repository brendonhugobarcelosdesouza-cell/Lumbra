"""Port de aprovação — Human-in-the-Loop (Princípio #2, ADR-024).

Toda ação com ``risk_level >= MEDIUM`` consulta este port ANTES de executar.
A política decide: permitir, negar, ou exigir confirmação humana. É o
enforcement que fechava a dívida do ``risk_level`` (declarado, nunca
verificado) e a base do controle de agentes (uma ação HIGH de um agente
nunca é automática por padrão).

A decisão é sempre por EVIDÊNCIA da ação (nome, sujeito, risco) — nunca um
grau de confiança inventado. Implementações NUNCA levantam para negar:
devolvem ``DENY``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from lumbra.ports.skills import RiskLevel


class ApprovalDecision(StrEnum):
    ALLOW = "allow"  # pode prosseguir
    DENY = "deny"  # proibido (política do usuário)
    NEEDS_CONFIRMATION = "needs_confirmation"  # exige confirmação humana explícita


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    action: str  # nome da skill/agente (ex.: 'memory.forget')
    subject: str  # quem pede: 'user:<id>' | 'agent:<id>'
    risk_level: RiskLevel
    reason: str = ""  # por que a ação está sendo pedida


class ApprovalOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision: ApprovalDecision
    reason: str = ""

    @property
    def allowed(self) -> bool:
        return self.decision is ApprovalDecision.ALLOW


class ApprovalPolicyPort(ABC):
    @abstractmethod
    async def decide(self, request: ApprovalRequest) -> ApprovalOutcome:
        """Decide se uma ação de risco pode prosseguir. Nunca levanta."""


# canário anti-truncamento
