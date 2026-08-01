"""Rotas /api/v1/playbooks (L1.5) — a memória procedural na Platform API.

Existe porque memória procedural sem interface não é usada: o dev console é
ferramenta de engenharia (fora do contrato), não caminho de usuário. Aqui os
procedimentos ficam onde qualquer cliente alcança — app, CLI, plugin.

Camada FINA sobre as skills ``playbook.*``: nenhuma lógica própria, tudo
tipado (o cliente Dart é gerado do contrato). Escrever e apagar continuam
passando pelo gate de aprovação, porque a rota não contorna o SkillRegistry.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from lumbra.adapters.security.tokens import Claims
from lumbra.kernel.kernel import LumbraKernel
from lumbra.ports.playbooks import PlaybookOrigin, PlaybookStorePort
from lumbra.ports.skills import (
    SkillApprovalRequiredError,
    SkillContext,
    SkillError,
    SkillPermissionDeniedError,
)


class PlaybookOut(BaseModel):
    """Um procedimento — espelha o Playbook do domínio em tipos JSON."""

    id: str
    title: str
    when_to_use: str
    steps: tuple[str, ...] = ()
    pitfalls: tuple[str, ...] = ()
    verification: str = ""
    origin: str
    uses: int = 0
    created_at: str


class PlaybooksOut(BaseModel):
    playbooks: tuple[PlaybookOut, ...] = ()


class PlaybookHitOut(BaseModel):
    """Resultado de busca — traz o texto renderizado, pronto para contexto."""

    playbook_id: str
    title: str
    when_to_use: str
    content: str
    origin: str
    uses: int = 0


class PlaybookSearchOut(BaseModel):
    hits: tuple[PlaybookHitOut, ...] = ()


class WriteBody(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    when_to_use: str = Field(min_length=3, max_length=500)
    steps: tuple[str, ...] = Field(min_length=1)
    pitfalls: tuple[str, ...] = ()
    verification: str = ""
    origin: PlaybookOrigin = PlaybookOrigin.USER


class WriteOut(BaseModel):
    playbook_id: str
    title: str


class ForgetOut(BaseModel):
    forgotten: bool


def build_playbooks_router(
    kernel: LumbraKernel,
    store: PlaybookStorePort,
    require_subject: Callable[..., Awaitable[Claims]],
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/playbooks", tags=["playbooks"])
    authed = Annotated[Claims, Depends(require_subject)]

    async def _run(name: str, payload: dict[str, Any], claims: Claims) -> Any:
        ctx = SkillContext(subject=f"user:{claims.subject}", user_id=claims.subject)
        try:
            return await kernel.skills.execute(name, payload, context=ctx)
        except SkillApprovalRequiredError as exc:
            # 409: o pedido é válido, mas falta a confirmação humana (HITL)
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
        except SkillPermissionDeniedError as exc:
            raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
        except (SkillError, ValueError) as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None

    @router.get("", response_model=PlaybooksOut)
    async def list_playbooks(claims: authed, limit: int = 50) -> dict[str, Any]:
        """Todos os procedimentos do usuário — auditável: ele é dono do que a
        plataforma aprendeu."""
        itens = await store.list_by_user(claims.subject, limit=limit)
        return {
            "playbooks": [
                {
                    "id": str(p.id),
                    "title": p.title,
                    "when_to_use": p.when_to_use,
                    "steps": list(p.steps),
                    "pitfalls": list(p.pitfalls),
                    "verification": p.verification,
                    "origin": p.origin.value,
                    "uses": p.uses,
                    "created_at": p.created_at.isoformat(),
                }
                for p in itens
            ]
        }

    @router.get("/search", response_model=PlaybookSearchOut)
    async def search(claims: authed, query: str, limit: int = 3) -> dict[str, Any]:
        result = await _run("playbook.search", {"query": query, "limit": limit}, claims)
        return {"hits": list(result.hits)}

    @router.post("", status_code=status.HTTP_201_CREATED, response_model=WriteOut)
    async def write(body: WriteBody, claims: authed) -> dict[str, Any]:
        """Grava um procedimento. Risco MEDIUM: passa pela política de
        aprovação — 409 quando exige confirmação humana."""
        result = await _run("playbook.write", body.model_dump(mode="json"), claims)
        return dict(result.model_dump(mode="json"))

    @router.delete("/{playbook_id}", response_model=ForgetOut)
    async def forget(playbook_id: str, claims: authed) -> dict[str, Any]:
        result = await _run("playbook.forget", {"playbook_id": playbook_id}, claims)
        return dict(result.model_dump(mode="json"))

    return router


# canário anti-truncamento
