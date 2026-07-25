"""Planejamento e execução de planos.

``KeywordPlanner``: planner determinístico (fallback e testes) — casa
capacidades das skills com palavras do objetivo. O planner com IA chegará
atrás do mesmo ``PlannerPort`` na fase do AI Layer, sem tocar em nada aqui.

``PlanRunner``: executa um ``Plan`` respeitando dependências, tolerando
falhas parciais — passo falho marca dependentes como ``skipped`` e o
restante do plano segue (resultado parcial > falha total, doc 07).
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from lumbra.kernel.skill_registry import SkillRegistry
from lumbra.ports.context import ContextFragment
from lumbra.ports.planner import Plan, PlannerPort, PlanStep
from lumbra.ports.skills import SkillContext, SkillManifest
from lumbra.shared.logging import get_logger

_log = get_logger("lumbra.kernel.planning")


class KeywordPlanner(PlannerPort):
    """Seleciona skills cujas capacidades aparecem no objetivo (normalizado)."""

    async def plan(
        self,
        goal: str,
        *,
        skills: Sequence[SkillManifest],
        context: Sequence[ContextFragment] = (),
    ) -> Plan:
        words = set(goal.lower().split())
        steps = tuple(
            PlanStep(skill=m.name, rationale=f"capacidade '{cap}' presente no objetivo")
            for m in skills
            for cap in m.capabilities
            if cap in words
        )
        return Plan(goal=goal, steps=steps)


class StepStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class StepResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    step: int
    skill: str
    status: StepStatus
    output: dict[str, Any] | None = None
    error: str | None = None


class PlanResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    goal: str
    results: tuple[StepResult, ...]

    @property
    def succeeded(self) -> bool:
        return all(r.status is StepStatus.COMPLETED for r in self.results)


class PlanRunner:
    """Executa planos contra o SkillRegistry — cooperação multi-agente concreta."""

    def __init__(self, skills: SkillRegistry) -> None:
        self._skills = skills

    async def run(self, plan: Plan, *, context: SkillContext) -> PlanResult:
        results: list[StepResult] = []
        for index, step in enumerate(plan.steps):
            failed_deps = [
                d for d in step.depends_on if results[d].status is not StepStatus.COMPLETED
            ]
            if failed_deps:
                _log.warning(
                    "plan_step_skipped", step=index, skill=step.skill, failed_deps=failed_deps
                )
                results.append(
                    StepResult(
                        step=index,
                        skill=step.skill,
                        status=StepStatus.SKIPPED,
                        error=f"dependências falharam: {failed_deps}",
                    )
                )
                continue
            try:
                output = await self._skills.execute(step.skill, step.input, context=context)
                results.append(
                    StepResult(
                        step=index,
                        skill=step.skill,
                        status=StepStatus.COMPLETED,
                        output=output.model_dump(mode="json"),
                    )
                )
            except Exception as exc:
                results.append(
                    StepResult(
                        step=index,
                        skill=step.skill,
                        status=StepStatus.FAILED,
                        error=repr(exc)[:500],
                    )
                )
        return PlanResult(goal=plan.goal, results=tuple(results))


# canário anti-truncamento
