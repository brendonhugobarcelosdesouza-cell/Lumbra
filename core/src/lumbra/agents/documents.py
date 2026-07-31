"""DocumentsAgent — o primeiro agente especialista (A7).

Implementa a capability ``documents.search`` compondo a skill ``document.find``
(busca híbrida existente). É deliberadamente simples: o valor deste incremento
é provar o CAMINHO COMPLETO — manifesto, registro, resolução por capability,
execução dentro do sandbox (escopo intersectado + orçamento + descarte) — com
uma composição real, e não com um agente de brinquedo.

Não usa IA: o resultado é determinístico e testável no CI. Agentes que precisem
de modelo continuam obrigados a passar pelo AI Gateway.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from lumbra.kernel.sandbox import AgentSandbox
from lumbra.kernel.skill_registry import SkillRegistry
from lumbra.ports.agents import AgentLimits, AgentManifest, AgentPort, AgentResult, MemoryAccess
from lumbra.ports.skills import RiskLevel, SkillContext

CAPABILITY = "documents.search"
SKILL = "document.find"


class DocumentsAgent(AgentPort):
    """Busca nos documentos do usuário, respeitando o sandbox da execução."""

    def __init__(self, skills: SkillRegistry) -> None:
        self._skills = skills
        self._manifest = AgentManifest(
            id="documents-agent",
            name="Documentos",
            description="Busca trechos relevantes nos documentos indexados do usuário",
            provider="kernel",
            capabilities=(CAPABILITY,),
            tools=(SKILL,),  # 'tools' é o campo do manifesto (A0); as skills que pode chamar
            required_scopes=("read:documents",),
            risk_level=RiskLevel.LOW,  # leitura
            memory_access=MemoryAccess.NONE,  # não toca a memória do usuário
            limits=AgentLimits(max_tokens=2000, max_steps=4, max_seconds=30.0),
        )

    @property
    def manifest(self) -> AgentManifest:
        return self._manifest

    async def handle(
        self,
        request: Mapping[str, Any],
        ctx: SkillContext,
        *,
        sandbox: AgentSandbox | None = None,
    ) -> AgentResult:
        """Executa a busca. Com sandbox, cada passo debita orçamento e o
        cancelamento é observado; sem sandbox, roda direto (compatibilidade)."""
        if sandbox is not None:
            sandbox.budget.charge(steps=1)
        if ctx.cancellation is not None:
            ctx.cancellation.raise_if_cancelled()

        saida = await self._skills.execute(SKILL, dict(request), context=ctx)
        hits: tuple[dict[str, Any], ...] = saida.hits  # type: ignore[attr-defined]
        return AgentResult(
            output={"hits": list(hits), "mode": saida.mode},  # type: ignore[attr-defined]
            summary=f"{len(hits)} trecho(s) encontrado(s)",
        )


# canário anti-truncamento
