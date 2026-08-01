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
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

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
    # dono da decisão e o que exatamente foi pedido — sem isso a confirmação
    # humana não teria como ser REEXECUTADA depois do "sim"
    user_id: UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


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


class ApprovalState(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ApprovalTicket(BaseModel):
    """Um pedido de confirmação humana que ficou PENDENTE.

    Guarda ``action`` + ``payload`` porque aprovar não é registrar um sim: é
    executar o que foi pedido. Sem o payload, o "sim" do usuário não teria o
    que reexecutar e a confirmação viraria teatro.
    """

    model_config = ConfigDict(frozen=True)

    id: UUID
    user_id: UUID
    action: str
    subject: str
    risk_level: RiskLevel
    reason: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    state: ApprovalState = ApprovalState.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    decided_at: datetime | None = None


class ApprovalNotFoundError(LookupError):
    """Ticket inexistente ou de outro usuário (não se distingue: não vaza)."""


class ApprovalAlreadyDecidedError(RuntimeError):
    """Ticket já aprovado ou rejeitado — decisão humana não se repete."""


class ApprovalStorePort(ABC):
    """Fila de pedidos aguardando o humano. Pequena e viva por natureza."""

    @abstractmethod
    async def add(self, ticket: ApprovalTicket) -> ApprovalTicket: ...

    @abstractmethod
    async def list_pending(self, user_id: UUID, *, limit: int = 50) -> list[ApprovalTicket]: ...

    @abstractmethod
    async def get(self, ticket_id: UUID, *, user_id: UUID) -> ApprovalTicket:
        """Levanta ``ApprovalNotFoundError`` se não existir ou não for do dono."""

    @abstractmethod
    async def resolve(
        self, ticket_id: UUID, *, user_id: UUID, state: ApprovalState
    ) -> ApprovalTicket:
        """Marca a decisão. Levanta se já houver uma — o sim/não é único."""


# canário anti-truncamento
