"""Rotas /api/v1/agents (A7.5) — a camada de agentes na Platform API.

Regra da arquitetura (docs/26, seção 10): **o cliente pede uma CAPABILITY,
nunca um agente por nome**. Quem decide o provedor é o Orchestrator, de forma
determinística; trocar o provedor de uma competência não quebra cliente algum.

Camada FINA sobre o kernel, como as demais rotas: nenhuma lógica própria.
Tudo tipado (response_model) — o cliente Dart é gerado do contrato.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from lumbra.adapters.security.tokens import Claims
from lumbra.kernel.kernel import LumbraKernel
from lumbra.kernel.orchestrator import OrchestrationError
from lumbra.kernel.sandbox import BudgetExceededError
from lumbra.ports.skills import SkillContext, SkillError, SkillPermissionDeniedError


class CapabilityOut(BaseModel):
    """Uma competência disponível — o vocabulário que o cliente usa."""

    id: str
    version: str
    description: str = ""
    risk_level: str
    mode: str
    provider_kind: str | None = None  # skill | agent (quem atende hoje)
    provider_ref: str | None = None


class CapabilitiesOut(BaseModel):
    capabilities: tuple[CapabilityOut, ...] = ()


class AgentOut(BaseModel):
    """Um agente registrado — informativo (o cliente não o invoca por nome)."""

    id: str
    name: str
    version: str
    description: str = ""
    capabilities: tuple[str, ...] = ()
    risk_level: str
    enabled: bool = True


class AgentsOut(BaseModel):
    agents: tuple[AgentOut, ...] = ()


class ExecuteBody(BaseModel):
    capability: str = Field(min_length=3, max_length=120)
    payload: dict[str, Any] = Field(default_factory=dict)


class ExecuteOut(BaseModel):
    """Resultado da orquestração, com a proveniência da decisão."""

    capability: str
    provider_kind: str
    provider_ref: str
    layer: str  # rules | capability_router | planner | llm_planner
    output: dict[str, Any] = Field(default_factory=dict)


def build_agents_router(
    kernel: LumbraKernel,
    require_subject: Callable[..., Awaitable[Claims]],
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/agents", tags=["agents"])
    authed = Annotated[Claims, Depends(require_subject)]

    @router.get("/capabilities", response_model=CapabilitiesOut)
    async def list_capabilities(claims: authed) -> dict[str, Any]:
        """O vocabulário de competências e quem as atende hoje."""
        del claims  # exige apenas autenticação
        itens: list[dict[str, Any]] = []
        for spec in kernel.capabilities.capabilities():
            provedores = [p for p in kernel.capabilities.providers_of(spec.id) if p.enabled]
            escolhido = provedores[0] if provedores else None
            itens.append(
                {
                    "id": spec.id,
                    "version": spec.version,
                    "description": spec.description,
                    "risk_level": spec.risk_level.value,
                    "mode": spec.mode.value,
                    "provider_kind": escolhido.kind.value if escolhido else None,
                    "provider_ref": escolhido.ref if escolhido else None,
                }
            )
        return {"capabilities": itens}

    @router.get("", response_model=AgentsOut)
    async def list_agents(claims: authed) -> dict[str, Any]:
        del claims
        return {
            "agents": [
                {
                    "id": m.id,
                    "name": m.name,
                    "version": m.version,
                    "description": m.description,
                    "capabilities": list(m.capabilities),
                    "risk_level": m.risk_level.value,
                }
                for m in kernel.agents.manifests()
            ]
        }

    @router.post("/execute", response_model=ExecuteOut)
    async def execute(body: ExecuteBody, claims: authed) -> dict[str, Any]:
        """Executa uma CAPABILITY — o Orchestrator escolhe o provedor.

        O cliente não sabe (nem precisa saber) se quem atendeu foi uma skill
        ou um agente: é o desacoplamento que o Capability Model garante."""
        ctx = SkillContext(subject=f"user:{claims.subject}", user_id=claims.subject)
        try:
            resultado = await kernel.orchestrator.execute(body.capability, body.payload, ctx=ctx)
        except OrchestrationError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
        except SkillPermissionDeniedError as exc:
            raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
        except BudgetExceededError as exc:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from None
        except (SkillError, ValueError) as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
        return {
            "capability": resultado.capability,
            "provider_kind": resultado.provider_kind.value,
            "provider_ref": resultado.provider_ref,
            "layer": resultado.layer,
            "output": resultado.output,
        }

    return router


# canário anti-truncamento
