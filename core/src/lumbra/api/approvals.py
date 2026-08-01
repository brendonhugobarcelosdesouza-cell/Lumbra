"""Rotas /api/v1/approvals (L2.0) — o Human-in-the-Loop com para onde ir.

Antes disto, ação de risco barrada devolvia 409 e morria ali: o usuário não
via o que ficou por fazer, nem tinha como dizer sim. Aqui os pendentes viram
uma fila que qualquer cliente lê, e aprovar EXECUTA o pedido original.

O 409 do resto da API passa a ser acionável: quem o recebe consulta esta
fila, mostra o pedido ao usuário e volta com a decisão.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from lumbra.adapters.security.tokens import Claims
from lumbra.kernel.approval_service import ApprovalService
from lumbra.ports.approval import (
    ApprovalAlreadyDecidedError,
    ApprovalNotFoundError,
)
from lumbra.ports.skills import (
    SkillError,
    SkillNotFoundError,
    SkillPermissionDeniedError,
)


class ApprovalOut(BaseModel):
    """Um pedido aguardando decisão — com o suficiente para o usuário julgar
    sem precisar confiar: o que é, quem pediu, qual o risco, e o pedido cru."""

    id: str
    action: str
    subject: str
    risk_level: str
    reason: str = ""
    payload: dict[str, Any] = {}
    created_at: str


class ApprovalsOut(BaseModel):
    approvals: tuple[ApprovalOut, ...] = ()


class ApproveOut(BaseModel):
    """O resultado da ação que estava pendente — aprovar é executar."""

    approved: bool
    action: str
    result: dict[str, Any] = {}


class RejectOut(BaseModel):
    rejected: bool
    action: str


def build_approvals_router(
    approvals: ApprovalService,
    require_subject: Callable[..., Awaitable[Claims]],
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/approvals", tags=["approvals"])
    authed = Annotated[Claims, Depends(require_subject)]

    def _nao_encontrado(exc: Exception) -> HTTPException:
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))

    @router.get("", response_model=ApprovalsOut)
    async def list_pending(claims: authed, limit: int = 50) -> dict[str, Any]:
        tickets = await approvals.pending(claims.subject, limit=limit)
        return {
            "approvals": [
                {
                    "id": str(t.id),
                    "action": t.action,
                    "subject": t.subject,
                    "risk_level": t.risk_level.value,
                    "reason": t.reason,
                    "payload": t.payload,
                    "created_at": t.created_at.isoformat(),
                }
                for t in tickets
            ]
        }

    @router.post("/{approval_id}/approve", response_model=ApproveOut)
    async def approve(approval_id: UUID, claims: authed) -> dict[str, Any]:
        """Confirma e EXECUTA o pedido. 409 se já houver decisão: o sim
        humano é único e não se repete."""
        try:
            ticket = await approvals.get(approval_id, user_id=claims.subject)
            resultado = await approvals.approve(approval_id, user_id=claims.subject)
        except ApprovalNotFoundError as exc:
            raise _nao_encontrado(exc) from None
        except ApprovalAlreadyDecidedError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
        except SkillPermissionDeniedError as exc:
            # aprovar libera a AÇÃO, não o escopo
            raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
        except (SkillNotFoundError, SkillError, ValueError) as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
        return {
            "approved": True,
            "action": ticket.action,
            "result": resultado.model_dump(mode="json"),
        }

    @router.post("/{approval_id}/reject", response_model=RejectOut)
    async def reject(approval_id: UUID, claims: authed) -> dict[str, Any]:
        try:
            ticket = await approvals.reject(approval_id, user_id=claims.subject)
        except ApprovalNotFoundError as exc:
            raise _nao_encontrado(exc) from None
        except ApprovalAlreadyDecidedError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
        return {"rejected": True, "action": ticket.action}

    return router


# canário anti-truncamento
