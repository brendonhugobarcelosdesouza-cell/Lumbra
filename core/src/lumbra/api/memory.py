"""Rotas /api/v1/memory (doc 11) — camada FINA sobre as skills memory.*.

Toda operação passa pelo SkillRegistry (permissões, eventos, Explanation
automática): a API não tem lógica própria — mesmo caminho de agentes e
console (Capability Driven).
"""

from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from lumbra.adapters.security.tokens import Claims
from lumbra.kernel.kernel import LumbraKernel
from lumbra.ports.memory import MemoryNotFoundError, MemoryStorePort
from lumbra.ports.skills import SkillContext, SkillError


class RememberBody(BaseModel):
    content: str = Field(min_length=1, max_length=10_000)
    kind: str = "episodic"
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    source_ref: dict[str, Any] = Field(default_factory=dict)
    expires_in_hours: float | None = None


class MemoryItemOut(BaseModel):
    """Uma memória listada — espelha o MemoryItem do domínio em tipos JSON."""

    id: str
    user_id: str
    kind: str
    content: str
    importance: float
    source_ref: dict[str, Any] = Field(default_factory=dict)
    access_count: int
    expires_at: str | None = None
    last_accessed_at: str
    created_at: str
    archived_at: str | None = None


class MemoryHitOut(BaseModel):
    """Um resultado de recall (memory.search) com explicação."""

    memory_id: str
    kind: str
    content: str
    score: float
    similarity: float
    source_ref: dict[str, Any] = Field(default_factory=dict)
    explanation: str


class MemoryQueryOut(BaseModel):
    """GET /memory: lista (sem query) OU recall (com query). Envelope único
    com campos opcionais — o cliente tipado não lida com união de esquemas."""

    items: tuple[MemoryItemOut, ...] = ()
    mode: str | None = None
    hits: tuple[MemoryHitOut, ...] = ()


class RememberOut(BaseModel):
    memory_id: str
    kind: str
    embedded: bool


class ForgetOut(BaseModel):
    forgotten: bool


class ConsolidateOut(BaseModel):
    expired: int
    archived: int
    kept: int


def build_memory_router(
    kernel: LumbraKernel,
    store: MemoryStorePort,
    require_subject: Callable[..., Awaitable[Claims]],
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/memory", tags=["memory"])
    authed = Annotated[Claims, Depends(require_subject)]

    def _ctx(claims: Claims) -> SkillContext:
        return SkillContext(subject=f"user:{claims.subject}", user_id=claims.subject)

    async def _run(name: str, payload: dict[str, Any], claims: Claims) -> Any:
        try:
            return await kernel.skills.execute(name, payload, context=_ctx(claims))
        except MemoryNotFoundError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "memória não encontrada") from None
        except PermissionError:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "memória de outro usuário") from None
        except (SkillError, ValueError) as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None

    @router.get("", response_model=MemoryQueryOut)
    async def list_memories(
        claims: authed, kind: str | None = None, query: str | None = None, limit: int = 20
    ) -> dict[str, Any]:
        """Sem query: lista (auditável). Com query: recall via memory.search."""
        if query:
            result = await _run("memory.search", {"query": query, "limit": limit}, claims)
            return {"mode": result.mode, "hits": list(result.hits)}
        items = await store.list_by_user(claims.subject, kind=kind)
        return {"items": [i.model_dump(mode="json") for i in items[:limit]]}

    @router.post("", status_code=status.HTTP_201_CREATED, response_model=RememberOut)
    async def remember(body: RememberBody, claims: authed) -> dict[str, Any]:
        result = await _run("memory.remember", body.model_dump(), claims)
        return dict(result.model_dump(mode="json"))

    @router.delete("/{memory_id}", response_model=ForgetOut)
    async def forget(memory_id: str, claims: authed) -> dict[str, Any]:
        result = await _run("memory.forget", {"memory_id": memory_id}, claims)
        return dict(result.model_dump(mode="json"))

    @router.post("/consolidate", response_model=ConsolidateOut)
    async def consolidate(claims: authed) -> dict[str, Any]:
        result = await _run("memory.consolidate", {}, claims)
        return dict(result.model_dump(mode="json"))

    return router


# canário anti-truncamento
