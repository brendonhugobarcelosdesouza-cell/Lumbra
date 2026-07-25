"""Testes das sementes dos princípios 1 e 2: Explain Engine e níveis de risco."""

from lumbra.adapters.eventbus.in_memory import InMemoryEventBus
from lumbra.adapters.eventstore.in_memory import InMemoryEventStore
from lumbra.adapters.permissions.static import StaticPermissionAdapter
from lumbra.domain.events import EventRegistry
from lumbra.kernel.explain import ExplainEngine
from lumbra.kernel.kernel import LumbraKernel
from lumbra.ports.explain import Explanation
from lumbra.ports.skills import (
    RiskLevel,
    Skill,
    SkillContext,
    SkillInput,
    SkillManifest,
    SkillOutput,
)
from lumbra.shared.ids import uuid7


class TestExplainEngine:
    def test_record_and_query_by_component_and_correlation(self):
        engine = ExplainEngine()
        corr = uuid7()
        engine.record(
            Explanation(
                component="search",
                decision="retornou 3 documentos",
                reason="consulta do usuário",
                algorithm="ts_rank",
                correlation_id=corr,
            )
        )
        engine.record(Explanation(component="planner", decision="plano vazio", reason="sem skills"))

        assert len(engine.query()) == 2
        assert [e.component for e in engine.query(component="search")] == ["search"]
        assert [e.decision for e in engine.query(correlation_id=corr)] == ["retornou 3 documentos"]
        assert engine.query(correlation_id=uuid7()) == []


class TestRiskLevel:
    def test_default_is_low(self):
        manifest = SkillManifest(name="document.search", description="x", provider="t")
        assert manifest.risk_level is RiskLevel.LOW

    def test_declaring_higher_risk(self):
        manifest = SkillManifest(
            name="document.delete",
            description="apaga documento",
            provider="t",
            risk_level=RiskLevel.HIGH,
        )
        assert manifest.risk_level is RiskLevel.HIGH


class TestSkillExecutionIsExplained:
    async def test_every_execution_records_explanation(self):
        kernel = LumbraKernel(
            events=EventRegistry(),
            bus=InMemoryEventBus(),
            event_store=InMemoryEventStore(),
            permissions=StaticPermissionAdapter(default_allow=True),
        )

        class In(SkillInput):
            q: str = "x"

        class Out(SkillOutput):
            ok: bool = True

        async def handler(payload: SkillInput, _ctx: SkillContext) -> Out:
            return Out()

        await kernel.skills.register(
            Skill(
                manifest=SkillManifest(name="test.echo", description="t", provider="t"),
                input_model=In,
                output_model=Out,
                handler=handler,
            )
        )
        await kernel.start()
        corr = uuid7()
        await kernel.skills.execute(
            "test.echo", {"q": "oi"}, context=SkillContext(subject="user:t", correlation_id=corr)
        )
        explanations = kernel.explain.query(correlation_id=corr)
        assert len(explanations) == 1
        assert explanations[0].component == "skill:test.echo"
        assert "user:t" in explanations[0].reason
        assert explanations[0].inputs_used == {"payload_fields": ["q"]}
        await kernel.stop()
