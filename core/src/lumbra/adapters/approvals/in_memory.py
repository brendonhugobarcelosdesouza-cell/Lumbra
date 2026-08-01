"""Fila de aprovações em memória (L2.0).

In-memory de propósito: um pedido de confirmação é uma interação VIVA — o
usuário está ali, decidindo agora. Ticket que sobrevive a um restart do Nó
seria um pedido órfão, sem quem o esperasse. Se o uso mostrar que aprovações
assíncronas (agente propõe hoje, usuário decide amanhã) importam, o port
permite trocar por Postgres sem tocar em nada.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from lumbra.ports.approval import (
    ApprovalAlreadyDecidedError,
    ApprovalNotFoundError,
    ApprovalState,
    ApprovalStorePort,
    ApprovalTicket,
)


class InMemoryApprovalStore(ApprovalStorePort):
    def __init__(self) -> None:
        self._tickets: dict[UUID, ApprovalTicket] = {}

    async def add(self, ticket: ApprovalTicket) -> ApprovalTicket:
        self._tickets[ticket.id] = ticket
        return ticket

    async def list_pending(self, user_id: UUID, *, limit: int = 50) -> list[ApprovalTicket]:
        pendentes = [
            t
            for t in self._tickets.values()
            if t.user_id == user_id and t.state is ApprovalState.PENDING
        ]
        pendentes.sort(key=lambda t: t.created_at, reverse=True)
        return pendentes[:limit]

    async def get(self, ticket_id: UUID, *, user_id: UUID) -> ApprovalTicket:
        ticket = self._tickets.get(ticket_id)
        # ticket de outro usuário responde igual a inexistente: não vaza
        if ticket is None or ticket.user_id != user_id:
            raise ApprovalNotFoundError(str(ticket_id))
        return ticket

    async def resolve(
        self, ticket_id: UUID, *, user_id: UUID, state: ApprovalState
    ) -> ApprovalTicket:
        ticket = await self.get(ticket_id, user_id=user_id)
        if ticket.state is not ApprovalState.PENDING:
            raise ApprovalAlreadyDecidedError(f"{ticket_id} já está {ticket.state.value}")
        decidido = ticket.model_copy(update={"state": state, "decided_at": datetime.now(tz=UTC)})
        self._tickets[ticket_id] = decidido
        return decidido


# canário anti-truncamento
