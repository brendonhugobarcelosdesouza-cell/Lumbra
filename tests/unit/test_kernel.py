"""Testes do LumbraKernel: ciclo de vida, módulos, publish auditado, readiness."""

import pytest

from lumbra.adapters.eventbus.in_memory import InMemoryEventBus
from lumbra.adapters.eventstore.in_memory import InMemoryEventStore
from lumbra.adapters.permissions.static import StaticPermissionAdapter
from lumbra.domain.events import EventRegistry
from lumbra.kernel.core_module import KernelCoreModule
from lumbra.kernel.kernel import (
    DuplicateModuleError,
    KernelAlreadyStartedError,
    LumbraKernel,
    LumbraModule,
    ModuleManifest,
)
from lumbra.ports.skills import SkillContext


class ProbeModule(LumbraModule):
    """Módulo de teste que grava a ordem das chamadas de ciclo de vida."""

    def __init__(self, name: str, journal: list[str]):
        self._name = name
        self._journal = journal

    @property
    def manifest(self) -> ModuleManifest:
        return ModuleManifest(name=self._name)

    async def setup(self, kernel: LumbraKernel) -> None:
        self._journal.append(f"setup:{self._name}")

    async def start(self) -> None:
        self._journal.append(f"start:{self._name}")

    async def stop(self) -> None:
        self._journal.append(f"stop:{self._name}")


@pytest.fixture()
def kernel() -> LumbraKernel:
    return LumbraKernel(
        events=EventRegistry(),
        bus=InMemoryEventBus(),
        event_store=InMemoryEventStore(),
        permissions=StaticPermissionAdapter(default_allow=True),
    )


class TestLifecycle:
    async def test_setup_start_stop_ordering(self, kernel):
        journal: list[str] = []
        kernel.register_module(ProbeModule("alpha", journal))
        kernel.register_module(ProbeModule("beta", journal))
        await kernel.start()
        await kernel.stop()
        assert journal == [
            "setup:alpha",
            "setup:beta",
            "start:alpha",
            "start:beta",
            "stop:beta",  # parada em ordem inversa
            "stop:alpha",
        ]

    async def test_register_after_start_rejected(self, kernel):
        await kernel.start()
        with pytest.raises(KernelAlreadyStartedError):
            kernel.register_module(ProbeModule("late", []))
        await kernel.stop()

    async def test_duplicate_module_rejected(self, kernel):
        kernel.register_module(ProbeModule("dup", []))
        with pytest.raises(DuplicateModuleError):
            kernel.register_module(ProbeModule("dup", []))


class TestPublishAuditing:
    async def test_publish_appends_to_event_store_and_bus(self, kernel):
        await kernel.start()
        stored = await kernel.event_store.read(event_types=("kernel.started",))
        assert len(stored) == 1  # kernel.started auditado no event store
        assert stored[0].producer.startswith("lumbra-kernel")
        await kernel.stop()
        stopped = await kernel.event_store.read(event_types=("kernel.stopped",))
        assert len(stopped) == 1


class TestReadiness:
    async def test_readiness_aggregates_checks(self, kernel):
        async def ok() -> bool:
            return True

        async def bad() -> bool:
            raise RuntimeError("indisponível")

        kernel.add_readiness_check("db", ok)
        kernel.add_readiness_check("redis", bad)
        assert await kernel.readiness() == {"db": True, "redis": False}


class TestCoreModule:
    async def test_core_skills_registered_and_discoverable(self, kernel):
        kernel.register_module(KernelCoreModule())
        await kernel.start()

        names = {m["name"] for m in kernel.capability_catalog()}
        assert {"system.list_capabilities", "context.gather"} <= names

        # Capability Discovery como skill: descobre a si mesma
        result = await kernel.skills.execute(
            "system.list_capabilities",
            {"capability": "discovery"},
            context=SkillContext(subject="agent:test"),
        )
        found = {s["name"] for s in result.skills}  # type: ignore[attr-defined]
        assert found == {"system.list_capabilities"}
        await kernel.stop()

    async def test_gather_context_via_skill(self, kernel):
        kernel.register_module(KernelCoreModule())
        await kernel.start()
        result = await kernel.skills.execute(
            "context.gather",
            {"query": "reunião de amanhã"},
            context=SkillContext(subject="agent:test"),
        )
        assert result.fragments == ()  # type: ignore[attr-defined] — sem provedores ainda
        await kernel.stop()
