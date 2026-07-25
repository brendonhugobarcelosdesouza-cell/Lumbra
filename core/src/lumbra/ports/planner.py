"""Port do Planner — decomposição de objetivos em passos de skills.

O Planner recebe um objetivo, o catálogo de skills disponíveis
(Capability Discovery) e contexto, e devolve um ``Plan``: passos que
referenciam skills por nome, com dependências explícitas. A execução é
responsabilidade do ``PlanRunner`` do kernel — o Planner só planeja.

Implementações: ``KeywordPlanner`` (determinística, fallback) hoje;
planner com IA na fase do AI Layer, atrás do MESMO port.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from lumbra.ports.context import ContextFragment
from lumbra.ports.skills import SkillManifest


class PlanStep(BaseModel):
    model_config = ConfigDict(frozen=True)

    skill: str  # nome da skill a executar
    input: dict[str, Any] = Field(default_factory=dict)
    depends_on: tuple[int, ...] = ()  # índices de passos anteriores
    rationale: str = ""  # por que este passo existe


class Plan(BaseModel):
    model_config = ConfigDict(frozen=True)

    goal: str
    steps: tuple[PlanStep, ...] = ()

    def model_post_init(self, _ctx: Any) -> None:
        for index, step in enumerate(self.steps):
            for dep in step.depends_on:
                if dep >= index:
                    raise ValueError(
                        f"passo {index} depende de {dep}: dependências devem apontar para trás"
                    )


class PlannerPort(ABC):
    @abstractmethod
    async def plan(
        self,
        goal: str,
        *,
        skills: Sequence[SkillManifest],
        context: Sequence[ContextFragment] = (),
    ) -> Plan:
        """Decompõe o objetivo em passos executáveis. Plano vazio = não sei planejar."""
