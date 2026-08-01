"""Serviço de aprovações (L2.0) — o que acontece depois do "sim".

Aprovar não é registrar um consentimento: é EXECUTAR o que ficou pendente.
Este serviço fecha o ciclo que faltava — a ação barrada pelo gate vira
ticket, o usuário decide, e o sim reexecuta exatamente o pedido original.

Duas invariantes que o desenho garante:

* **A decisão é única.** Resolver um ticket já decidido levanta; um "sim"
  não pode ser reaproveitado para rodar a ação duas vezes.
* **Aprovar libera a AÇÃO, não o escopo.** A reexecução usa uma vista do
  registro com a política trocada, mas as MESMAS permissões — confirmar
  nunca amplia o que o sujeito podia fazer.
"""

from __future__ import annotations

from uuid import UUID

from lumbra.kernel.approval import AutoApprovePolicy
from lumbra.kernel.skill_registry import SkillRegistry
from lumbra.ports.approval import (
    ApprovalState,
    ApprovalStorePort,
    ApprovalTicket,
)
from lumbra.ports.skills import RiskLevel, SkillContext, SkillOutput
from lumbra.shared.logging import get_logger

_log = get_logger("lumbra.kernel.approval_service")


class ApprovalService:
    def __init__(self, skills: SkillRegistry, store: ApprovalStorePort) -> None:
        self._store = store
        # vista com o gate aberto: só é usada DEPOIS do sim humano, e só
        # para o pedido exato que ele confirmou
        self._aprovado = skills.with_approval(AutoApprovePolicy(auto_ate=RiskLevel.CRITICAL))

    async def pending(self, user_id: UUID, *, limit: int = 50) -> list[ApprovalTicket]:
        return await self._store.list_pending(user_id, limit=limit)

    async def get(self, ticket_id: UUID, *, user_id: UUID) -> ApprovalTicket:
        """Qualquer estado, não só pendente — quem já decidiu precisa poder
        distinguir 'não existe' de 'já foi decidido'."""
        return await self._store.get(ticket_id, user_id=user_id)

    async def approve(self, ticket_id: UUID, *, user_id: UUID) -> SkillOutput:
        """Confirma e executa. A resolução vem ANTES da execução: se a ação
        falhar, o ticket não volta a pendente — decisão tomada é histórico, e
        repetir automaticamente seria decidir pelo usuário."""
        ticket = await self._store.resolve(ticket_id, user_id=user_id, state=ApprovalState.APPROVED)
        _log.info("approval_granted", ticket=str(ticket.id), action=ticket.action)
        return await self._aprovado.execute(
            ticket.action,
            ticket.payload,
            context=SkillContext(subject=ticket.subject, user_id=ticket.user_id),
        )

    async def reject(self, ticket_id: UUID, *, user_id: UUID) -> ApprovalTicket:
        ticket = await self._store.resolve(ticket_id, user_id=user_id, state=ApprovalState.REJECTED)
        _log.info("approval_rejected", ticket=str(ticket.id), action=ticket.action)
        return ticket


# canário anti-truncamento
