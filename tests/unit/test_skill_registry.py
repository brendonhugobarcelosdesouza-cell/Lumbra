"""Testes do SkillRegistry: registro, discovery, execução, permissões, observabilidade."""

import pytest
from pydantic import ValidationError

from lumbra.adapters.permissions.static import StaticPermissionAdapter
from lumbra.kernel.skill_registry import SkillRegistry
from lumbra.ports.skills import (
    DuplicateSkillError,
    InvalidSkillError,
    Skill,
    SkillContext,
    SkillInput,
    SkillManifest,
    SkillNotFoundError,
    SkillOutput,
    SkillPermissionDeniedError,
)


class CreateAlarmInput(SkillInput):
    when: str
    label: str = "alarme"


class CreateAlarmOutput(SkillOutput):
    alarm_id: str


async def _create_alarm(payload: SkillInput, _ctx: SkillContext) -> CreateAlarmOutput:
    assert isinstance(payload, CreateAlarmInput)
    return CreateAlarmOutput(alarm_id=f"alarm-{payload.when}")


def _skill(name="alarm.create", scopes=(), capabilities=("alarm", "scheduling")) -> Skill:
    return Skill(
        manifest=SkillManifest(
            name=name,
            description="Cria um alarme inteligente",
            provider="test-module",
            capabilities=capabilities,
            required_scopes=scopes,
        ),
        input_model=CreateAlarmInput,
        output_model=CreateAlarmOutput,
        handler=_create_alarm,
    )


@pytest.fixture()
def registry() -> SkillRegistry:
    return SkillRegistry(StaticPermissionAdapter(default_allow=True))


_CTX = SkillContext(subject="user:test")


class TestRegistration:
    async def test_register_and_get(self, registry):
        await registry.register(_skill())
        assert registry.get("alarm.create").manifest.provider == "test-module"

    async def test_duplicate_rejected(self, registry):
        await registry.register(_skill())
        with pytest.raises(DuplicateSkillError):
            await registry.register(_skill())

    def test_invalid_name_rejected(self):
        with pytest.raises(InvalidSkillError):
            SkillManifest(
                name="create_alarm", description="x", provider="t"
            )  # sem domínio → inválido

    async def test_registration_announces_capability(self):
        published = []

        async def capture(payload, **kwargs):
            published.append(payload)

        registry = SkillRegistry(StaticPermissionAdapter(default_allow=True), publish=capture)
        await registry.register(_skill())
        assert published[0].skill == "alarm.create"
        assert "alarm" in published[0].capabilities


class TestDiscovery:
    async def test_find_by_capability(self, registry):
        await registry.register(_skill())
        await registry.register(_skill(name="email.send", capabilities=("email",)))
        found = registry.find(capability="alarm")
        assert [m.name for m in found] == ["alarm.create"]

    async def test_find_by_free_text(self, registry):
        await registry.register(_skill())
        assert registry.find(query="alarme")[0].name == "alarm.create"
        assert registry.find(query="inexistente") == []


class TestExecution:
    async def test_execute_returns_typed_output(self, registry):
        await registry.register(_skill())
        result = await registry.execute("alarm.create", {"when": "08:00"}, context=_CTX)
        assert isinstance(result, CreateAlarmOutput)
        assert result.alarm_id == "alarm-08:00"

    async def test_unknown_skill(self, registry):
        with pytest.raises(SkillNotFoundError):
            await registry.execute("ghost", {}, context=_CTX)

    async def test_invalid_input_rejected_before_handler(self, registry):
        await registry.register(_skill())
        with pytest.raises(ValidationError):
            await registry.execute("alarm.create", {"unknown_field": 1}, context=_CTX)

    async def test_permission_denied(self):
        registry = SkillRegistry(
            StaticPermissionAdapter(default_allow=True, denied_scopes=frozenset({"write:alarms"}))
        )
        await registry.register(_skill(scopes=("write:alarms",)))
        with pytest.raises(SkillPermissionDeniedError):
            await registry.execute("alarm.create", {"when": "08:00"}, context=_CTX)

    async def test_execution_emits_observability_event(self):
        published = []

        async def capture(payload, **kwargs):
            published.append(payload)

        registry = SkillRegistry(StaticPermissionAdapter(default_allow=True), publish=capture)
        await registry.register(_skill())
        await registry.execute("alarm.create", {"when": "08:00"}, context=_CTX)
        executed = [p for p in published if type(p).__name__ == "SkillExecuted"]
        assert len(executed) == 1
        assert executed[0].skill == "alarm.create"
        assert executed[0].duration_ms >= 0

    async def test_handler_failure_emits_skill_failed(self):
        published = []

        async def capture(payload, **kwargs):
            published.append(payload)

        async def broken(payload, ctx):
            raise RuntimeError("boom")

        registry = SkillRegistry(StaticPermissionAdapter(default_allow=True), publish=capture)
        skill = _skill()
        await registry.register(
            Skill(
                manifest=skill.manifest,
                input_model=skill.input_model,
                output_model=skill.output_model,
                handler=broken,
            )
        )
        with pytest.raises(RuntimeError):
            await registry.execute("alarm.create", {"when": "08:00"}, context=_CTX)
        failed = [p for p in published if type(p).__name__ == "SkillFailed"]
        assert len(failed) == 1
        assert "boom" in failed[0].error
