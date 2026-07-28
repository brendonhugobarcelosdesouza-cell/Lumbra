"""LumbraKernel — composição e ciclo de vida do Core Intelligence Engine.

O kernel é o ÚNICO lugar que conhece implementações concretas (composition
root). Módulos e agentes recebem apenas ports e os serviços do kernel:

* ``skills``  — SkillRegistry (Tool Registry unificado, ADR-015)
* ``context`` — Context Engine
* ``planner`` + ``plan_runner`` — planejamento cooperativo
* ``publish`` — publicação de eventos (envelopa, audita no event store
  e entrega ao bus — ponto único de observabilidade)

Módulos implementam ``LumbraModule`` e declaram tudo em ``setup()``;
o kernel inicia na ordem de registro e para na ordem inversa.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from lumbra.domain.events import EventPayload, EventRegistry
from lumbra.kernel.agent_registry import AgentRegistry
from lumbra.kernel.approval import AutoApprovePolicy
from lumbra.kernel.capability_registry import CapabilityRegistry
from lumbra.kernel.context_engine import ContextEngine
from lumbra.kernel.events import KernelStarted, KernelStopped, ModuleStarted, register_kernel_events
from lumbra.kernel.explain import ExplainEngine
from lumbra.kernel.planning import KeywordPlanner, PlanRunner
from lumbra.kernel.skill_registry import SkillRegistry
from lumbra.ports.approval import ApprovalPolicyPort
from lumbra.ports.event_bus import EventBusPort
from lumbra.ports.event_store import EventStorePort
from lumbra.ports.permissions import PermissionPort
from lumbra.ports.planner import PlannerPort
from lumbra.shared.cancellation import CancellationToken, CancelReason
from lumbra.shared.logging import get_logger

_log = get_logger("lumbra.kernel")

ReadinessCheck = Callable[[], Awaitable[bool]]


class KernelError(Exception):
    pass


class KernelAlreadyStartedError(KernelError):
    def __init__(self) -> None:
        super().__init__("Operação exige kernel parado")


class ModuleNotRegisteredError(Exception):
    def __init__(self, name: str) -> None:
        super().__init__(f"Módulo não registrado: {name}")


class DuplicateModuleError(KernelError):
    def __init__(self, name: str) -> None:
        super().__init__(f"Módulo já registrado: {name}")


class ModuleManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    version: str = "0.1.0"
    description: str = ""


class LumbraModule(ABC):
    """Contrato de extensão do kernel (agentes, módulos de vida, plugins)."""

    @property
    @abstractmethod
    def manifest(self) -> ModuleManifest: ...

    @abstractmethod
    async def setup(self, kernel: LumbraKernel) -> None:
        """Registra skills, consumidores de eventos e provedores de contexto."""

    async def start(self) -> None:  # opcional
        return None

    async def stop(self) -> None:  # opcional
        return None


class LumbraKernel:
    def __init__(
        self,
        *,
        events: EventRegistry,
        bus: EventBusPort,
        event_store: EventStorePort,
        permissions: PermissionPort,
        planner: PlannerPort | None = None,
        approval: ApprovalPolicyPort | None = None,
        producer: str = "lumbra-kernel@0.1.0",
    ) -> None:
        self.events = events
        self.bus = bus
        self.event_store = event_store
        self.permissions = permissions
        self.planner: PlannerPort = planner or KeywordPlanner()
        # HITL (ADR-024): default 'aprova tudo' — liga o gate sem quebrar nada
        # enquanto não há tela de confirmação. Trocar a política é injeção.
        self.approval: ApprovalPolicyPort = approval or AutoApprovePolicy()
        self.context = ContextEngine()
        self.explain = ExplainEngine()
        self.skills = SkillRegistry(
            permissions, publish=self.publish, explain=self.explain, approval=self.approval
        )
        # registro de competências (ADR-056), separado do SkillRegistry. Vazio
        # e fora da execução por ora — o Orchestrator (A5) passa a resolvê-lo.
        self.capabilities = CapabilityRegistry()
        # registro de agentes (ADR-057); registrar um agente publica seus
        # provedores no CapabilityRegistry. Dormente até o Orchestrator (A5).
        self.agents = AgentRegistry(self.capabilities)
        self.plan_runner = PlanRunner(self.skills)
        self._producer = producer
        self._modules: dict[str, LumbraModule] = {}
        self._cancellation = CancellationToken(name="kernel")
        self._started_modules: list[LumbraModule] = []
        self._readiness: dict[str, ReadinessCheck] = {}
        self._started = False
        register_kernel_events(events)

    # ------------------------------------------------------------ registro

    @property
    def started(self) -> bool:
        return self._started

    def register_module(self, module: LumbraModule) -> None:
        if self._started:
            raise KernelAlreadyStartedError
        name = module.manifest.name
        if name in self._modules:
            raise DuplicateModuleError(name)
        self._modules[name] = module

    def module(self, name: str) -> LumbraModule:
        """Módulo registrado, pelo nome do manifesto."""
        try:
            return self._modules[name]
        except KeyError:
            raise ModuleNotRegisteredError(name) from None

    def modules(self) -> tuple[LumbraModule, ...]:
        return tuple(self._modules.values())

    def add_readiness_check(self, name: str, check: ReadinessCheck) -> None:
        self._readiness[name] = check

    async def readiness(self) -> dict[str, bool]:
        results: dict[str, bool] = {}
        for name, check in self._readiness.items():
            try:
                results[name] = await check()
            except Exception:
                results[name] = False
        return results

    # ------------------------------------------------------------ eventos

    async def publish(
        self,
        payload: EventPayload,
        *,
        user_id: UUID | None = None,
        correlation_id: UUID | None = None,
        causation_id: UUID | None = None,
    ) -> None:
        """Ponto único de publicação: envelopa → audita (event store) → bus."""
        envelope = self.events.envelope(
            payload,
            producer=self._producer,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )
        await self.event_store.append(envelope)
        await self.bus.publish(envelope)

    # ------------------------------------------------------------ ciclo de vida

    async def start(self) -> None:
        if self._started:
            return
        # setup de todos os módulos ANTES do bus.start: consumidores curinga
        # dependem do catálogo completo de eventos (ADR-014)
        for module in self._modules.values():
            await module.setup(self)
        await self.bus.start()
        self._started = True
        for module in self._modules.values():
            await module.start()
            self._started_modules.append(module)
            _log.info("module_started", module=module.manifest.name)
            await self.publish(
                ModuleStarted(module=module.manifest.name, version=module.manifest.version)
            )
        await self.publish(
            KernelStarted(
                modules=tuple(self._modules),
                skills=tuple(m.name for m in self.skills.manifests()),
            )
        )
        _log.info("kernel_started", modules=len(self._modules))

    @property
    def cancellation(self) -> CancellationToken:
        """Token RAIZ do processo (ADR-032): cancelado no desligamento,
        então nenhuma operação longa sobrevive ao ciclo de vida do kernel.
        Operações criam filhos dele com ``kernel.cancellation.child(nome)``."""
        return self._cancellation

    async def stop(self) -> None:
        if not self._started:
            return
        # antes de parar módulos: avisa todo trabalho em voo para encerrar
        self._cancellation.cancel(CancelReason.SHUTDOWN, requested_by="kernel")
        for module in reversed(self._started_modules):
            try:
                await module.stop()
            except Exception as exc:
                _log.error("module_stop_error", module=module.manifest.name, error=repr(exc))
        self._started_modules.clear()
        await self.publish(KernelStopped())
        await self.bus.stop()
        self._started = False
        _log.info("kernel_stopped")

    # ------------------------------------------------------------ conveniências

    def capability_catalog(self) -> list[dict[str, Any]]:
        """Visão de Capability Discovery para API/agentes/planner."""
        return [m.model_dump() for m in self.skills.manifests()]


# canário anti-truncamento
