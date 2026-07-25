"""Testes de planejamento: KeywordPlanner, validação de Plan e PlanRunner."""

import pytest

from lumbra.adapters.permissions.static import StaticPermissionAdapter
from lumbra.kernel.planning import KeywordPlanner, PlanRunner, StepStatus
from lumbra.kernel.skill_registry import SkillRegistry
from lumbra.ports.planner import Plan, PlanStep
from lumbra.ports.skills import Skill, SkillContext, SkillInput, SkillManifest, SkillOutput

_CTX = SkillContext(subject="user:test")


class EmptyInput(SkillInput):
    pass


class TextOutput(SkillOutput):
    text: str


def _skill(name: str, capabilities: tuple[str, ...], *, fail: bool = False) -> Skill:
    async def handler(payload: SkillInput, ctx: SkillContext) -> TextOutput:
        if fail:
            raise RuntimeError(f"{name} falhou")
        return TextOutput(text=f"{name} ok")

    return Skill(
        manifest=SkillManifest(
            name=name, description=name, provider="test", capabilities=capabilities
        ),
        input_model=EmptyInput,
        output_model=TextOutput,
        handler=handler,
    )


class TestPlanModel:
    def test_forward_dependency_rejected(self):
        with pytest.raises(ValueError, match="dependências"):
            Plan(goal="g", steps=(PlanStep(skill="a", depends_on=(0,)),))

    def test_backward_dependency_accepted(self):
        plan = Plan(goal="g", steps=(PlanStep(skill="a"), PlanStep(skill="b", depends_on=(0,))))
        assert len(plan.steps) == 2


class TestKeywordPlanner:
    async def test_matches_capabilities_in_goal(self):
        skills = [
            _skill("alarm.create", ("alarme",)).manifest,
            _skill("email.send", ("email",)).manifest,
        ]
        plan = await KeywordPlanner().plan("criar um alarme para amanhã", skills=skills)
        assert [s.skill for s in plan.steps] == ["alarm.create"]

    async def test_no_match_returns_empty_plan(self):
        plan = await KeywordPlanner().plan("objetivo sem skills", skills=[])
        assert plan.steps == ()


@pytest.fixture()
def registry() -> SkillRegistry:
    return SkillRegistry(StaticPermissionAdapter(default_allow=True))


class TestPlanRunner:
    async def test_runs_all_steps(self, registry):
        await registry.register(_skill("document.find", ("document",)))
        await registry.register(_skill("pdf.scan", ("pdf",)))
        plan = Plan(
            goal="g",
            steps=(PlanStep(skill="document.find"), PlanStep(skill="pdf.scan", depends_on=(0,))),
        )
        result = await PlanRunner(registry).run(plan, context=_CTX)
        assert result.succeeded
        assert [r.status for r in result.results] == [StepStatus.COMPLETED, StepStatus.COMPLETED]
        assert result.results[0].output == {"text": "document.find ok"}

    async def test_failed_step_skips_dependents_but_not_others(self, registry):
        await registry.register(_skill("test.a_fails", ("a",), fail=True))
        await registry.register(_skill("test.b_dependent", ("b",)))
        await registry.register(_skill("test.c_independent", ("c",)))
        plan = Plan(
            goal="g",
            steps=(
                PlanStep(skill="test.a_fails"),
                PlanStep(skill="test.b_dependent", depends_on=(0,)),
                PlanStep(skill="test.c_independent"),
            ),
        )
        result = await PlanRunner(registry).run(plan, context=_CTX)
        assert not result.succeeded
        assert result.results[0].status is StepStatus.FAILED
        assert result.results[1].status is StepStatus.SKIPPED
        assert result.results[2].status is StepStatus.COMPLETED
