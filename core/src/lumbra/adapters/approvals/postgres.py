"""ApprovalStorePort sobre PostgreSQL (L2.2) — o mesmo contrato do in-memory.

A decisão é única, e aqui isso vira uma garantia do BANCO: o UPDATE que
resolve o ticket só casa enquanto o estado é 'pending'. Duas abas clicando
"Aprovar" ao mesmo tempo não executam a ação duas vezes — a segunda não
encontra linha para atualizar e recebe o erro de já-decidido.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update

from lumbra.adapters.persistence.database import Database
from lumbra.adapters.persistence.models import ApprovalModel
from lumbra.ports.approval import (
    ApprovalAlreadyDecidedError,
    ApprovalNotFoundError,
    ApprovalState,
    ApprovalStorePort,
    ApprovalTicket,
)
from lumbra.ports.skills import RiskLevel


def _to_domain(row: ApprovalModel) -> ApprovalTicket:
    return ApprovalTicket(
        id=row.id,
        user_id=row.user_id,
        action=row.action,
        subject=row.subject,
        risk_level=RiskLevel(row.risk_level),
        reason=row.reason,
        payload=dict(row.payload or {}),
        state=ApprovalState(row.state),
        created_at=row.created_at,
        decided_at=row.decided_at,
    )


class PostgresApprovalStore(ApprovalStorePort):
    def __init__(self, db: Database) -> None:
        self._db = db

    async def add(self, ticket: ApprovalTicket) -> ApprovalTicket:
        row = ApprovalModel(
            id=ticket.id,
            user_id=ticket.user_id,
            action=ticket.action,
            subject=ticket.subject,
            risk_level=ticket.risk_level.value,
            reason=ticket.reason,
            payload=ticket.payload,
            state=ticket.state.value,
            created_at=ticket.created_at,
            decided_at=ticket.decided_at,
        )
        async with self._db.session() as session:
            session.add(row)
            await session.flush()
            return _to_domain(row)

    async def list_pending(self, user_id: UUID, *, limit: int = 50) -> list[ApprovalTicket]:
        stmt = (
            select(ApprovalModel)
            .where(
                ApprovalModel.user_id == user_id,
                ApprovalModel.state == ApprovalState.PENDING.value,
            )
            .order_by(ApprovalModel.created_at.desc())
            .limit(limit)
        )
        async with self._db.session() as session:
            return [_to_domain(r) for r in (await session.execute(stmt)).scalars().all()]

    async def get(self, ticket_id: UUID, *, user_id: UUID) -> ApprovalTicket:
        async with self._db.session() as session:
            row = await session.get(ApprovalModel, ticket_id)
            # ticket de outro usuário responde igual a inexistente: não vaza
            if row is None or row.user_id != user_id:
                raise ApprovalNotFoundError(str(ticket_id))
            return _to_domain(row)

    async def resolve(
        self, ticket_id: UUID, *, user_id: UUID, state: ApprovalState
    ) -> ApprovalTicket:
        agora = datetime.now(tz=UTC)
        # o filtro por 'pending' faz do UPDATE a trava: quem chegar depois não
        # casa nenhuma linha, e a acao nao roda duas vezes
        stmt = (
            update(ApprovalModel)
            .where(
                ApprovalModel.id == ticket_id,
                ApprovalModel.user_id == user_id,
                ApprovalModel.state == ApprovalState.PENDING.value,
            )
            .values(state=state.value, decided_at=agora)
            .returning(ApprovalModel)
        )
        async with self._db.session() as session:
            row = (await session.execute(stmt)).scalars().first()
            if row is not None:
                return _to_domain(row)
            # não atualizou: ou não existe/não é dele, ou já foi decidido —
            # a diferença importa para o cliente (404 vs 409)
            atual = await session.get(ApprovalModel, ticket_id)
            if atual is None or atual.user_id != user_id:
                raise ApprovalNotFoundError(str(ticket_id))
            raise ApprovalAlreadyDecidedError(f"{ticket_id} já está {atual.state}")


# canário anti-truncamento
