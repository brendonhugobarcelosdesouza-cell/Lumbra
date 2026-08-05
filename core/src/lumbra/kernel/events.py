"""Eventos do próprio kernel (contextos ``kernel.*`` e ``skill.*``).

Registrados de forma idempotente contra o EventRegistry fornecido ao
kernel — testes usam registries isolados sem conflito.
"""

from __future__ import annotations

from lumbra.domain.events import EventPayload, EventRegistry


class KernelStarted(EventPayload):
    modules: tuple[str, ...]
    skills: tuple[str, ...]


class KernelStopped(EventPayload):
    pass


class ModuleStarted(EventPayload):
    module: str
    version: str


class SkillRegistered(EventPayload):
    """Capability Discovery: anuncia uma nova capacidade ao sistema."""

    skill: str
    provider: str
    capabilities: tuple[str, ...]


class SkillExecuted(EventPayload):
    skill: str
    subject: str
    duration_ms: float
    success: bool


class SkillFailed(EventPayload):
    skill: str
    subject: str
    duration_ms: float
    error: str


class ApprovalRequested(EventPayload):
    """Uma ação de risco ficou esperando o humano (ADR-063).

    Está na trilha de auditoria porque o que a plataforma QUIS fazer importa
    tanto quanto o que fez: é assim que se descobre um agente insistindo numa
    ação que o usuário recusa sempre.
    """

    ticket: str
    action: str
    subject: str
    risk_level: str


class ApprovalGranted(EventPayload):
    ticket: str
    action: str
    subject: str


class ApprovalRejected(EventPayload):
    ticket: str
    action: str
    subject: str


_KERNEL_EVENTS: tuple[tuple[str, type[EventPayload]], ...] = (
    ("kernel.started", KernelStarted),
    ("kernel.stopped", KernelStopped),
    ("kernel.module_started", ModuleStarted),
    ("kernel.skill_registered", SkillRegistered),
    ("skill.executed", SkillExecuted),
    ("skill.failed", SkillFailed),
    ("approval.requested", ApprovalRequested),
    ("approval.granted", ApprovalGranted),
    ("approval.rejected", ApprovalRejected),
)


def register_kernel_events(registry: EventRegistry) -> None:
    """Registra os eventos do kernel. Idempotente."""
    for event_type, payload_cls in _KERNEL_EVENTS:
        if (event_type, 1) not in registry.known_types():
            registry.event(event_type)(payload_cls)
