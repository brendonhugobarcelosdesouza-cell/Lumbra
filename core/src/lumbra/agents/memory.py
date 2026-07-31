"""MemoryAgent — competência de recall sobre a memória do usuário (A11).

Implementa ``memory.search`` compondo a skill homônima (recall híbrido com
explicação). Segue o mesmo desenho do DocumentsAgent: sem IA, determinístico,
e com ``memory_access=READ`` — lê a memória do usuário, NUNCA escreve. Escrita
de memória continua sendo uma skill explícita, sujeita à aprovação (ADR-061).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from lumbra.kernel.skill_registry import SkillRegistry
from lumbra.ports.agents import AgentLimits, AgentManifest, AgentPort, AgentResult, MemoryAccess
from lumbra.ports.skills import RiskLevel, SkillContext

CAPABILITY = "memory.search"
SKILL = "memory.search"


class MemoryAgent(AgentPort):
    """Recall na memória pessoal, dentro do sandbox da execução."""

    def __init__(self, skills: SkillRegistry) -> None:
        self._skills = skills
        self._manifest = AgentManifest(
            id="memory-agent",
            name="Memória",
            description="Recupera memórias relevantes do usuário",
            provider="kernel",
            capabilities=(CAPABILITY,),
            tools=(SKILL,),
            required_scopes=("read:memory",),
            risk_level=RiskLevel.LOW,
            memory_access=MemoryAccess.READ,  # lê; escrever exige skill + aprovação
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
        sandbox: Any | None = None,
    ) -> AgentResult:
        skills = self._skills
        if sandbox is not None:
            sandbox.budget.charge(steps=1)
            skills = self._skills.scoped(sandbox.permissions)
        if ctx.cancellation is not None:
            ctx.cancellation.raise_if_cancelled()

        saida = await skills.execute(SKILL, dict(request), context=ctx)
        hits: tuple[dict[str, Any], ...] = saida.hits  # type: ignore[attr-defined]
        return AgentResult(
            output={"hits": list(hits), "mode": saida.mode},  # type: ignore[attr-defined]
            summary=f"{len(hits)} memória(s) encontrada(s)",
        )


# canário anti-truncamento
