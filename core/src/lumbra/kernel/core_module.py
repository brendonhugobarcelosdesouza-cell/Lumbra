"""Módulo core do kernel — primeiras skills reais do sistema.

Demonstra o padrão completo que TODOS os agentes seguirão: um módulo que,
no ``setup()``, registra skills tipadas no SkillRegistry. As duas skills
aqui são de infraestrutura (meta-capacidades do próprio kernel):

* ``system.list_capabilities`` — Capability Discovery como skill: agentes e o
  Planner descobrem o que o sistema sabe fazer executando uma skill.
* ``context.gather``   — o Context Engine exposto como skill: qualquer
  agente pode pedir contexto agregado sem conhecer provedores.

Skills de negócio (``document.search``, ``memory.search``, ``pdf.scan``...)
chegam com seus módulos nos épicos E1+, seguindo exatamente este molde.
"""

from __future__ import annotations

from typing import Any

from lumbra.kernel.kernel import LumbraKernel, LumbraModule, ModuleManifest
from lumbra.ports.context import ContextRequest
from lumbra.ports.skills import Skill, SkillContext, SkillInput, SkillManifest, SkillOutput


class ListCapabilitiesInput(SkillInput):
    capability: str | None = None
    query: str | None = None


class ListCapabilitiesOutput(SkillOutput):
    skills: tuple[dict[str, Any], ...]


class GatherContextInput(SkillInput):
    query: str
    purpose: str = "chat"
    max_fragments: int = 20


class GatherContextOutput(SkillOutput):
    fragments: tuple[dict[str, Any], ...]


class KernelCoreModule(LumbraModule):
    def __init__(self) -> None:
        self._kernel: LumbraKernel | None = None

    @property
    def manifest(self) -> ModuleManifest:
        return ModuleManifest(
            name="kernel-core",
            version="0.1.0",
            description="Meta-capacidades do Core Intelligence Engine",
        )

    async def setup(self, kernel: LumbraKernel) -> None:
        self._kernel = kernel
        await kernel.skills.register(
            Skill(
                manifest=SkillManifest(
                    name="system.list_capabilities",
                    description="Descobre skills disponíveis por capacidade ou texto livre",
                    provider="kernel-core",
                    capabilities=("discovery", "introspection"),
                ),
                input_model=ListCapabilitiesInput,
                output_model=ListCapabilitiesOutput,
                handler=self._list_capabilities,
            )
        )
        await kernel.skills.register(
            Skill(
                manifest=SkillManifest(
                    name="context.gather",
                    description="Agrega contexto relevante dos provedores registrados",
                    provider="kernel-core",
                    capabilities=("context",),
                ),
                input_model=GatherContextInput,
                output_model=GatherContextOutput,
                handler=self._gather_context,
            )
        )

    async def _list_capabilities(
        self, payload: SkillInput, _ctx: SkillContext
    ) -> ListCapabilitiesOutput:
        assert isinstance(payload, ListCapabilitiesInput)  # noqa: S101 — invariante interna
        assert self._kernel is not None  # noqa: S101
        manifests = self._kernel.skills.find(capability=payload.capability, query=payload.query)
        return ListCapabilitiesOutput(skills=tuple(m.model_dump() for m in manifests))

    async def _gather_context(self, payload: SkillInput, ctx: SkillContext) -> GatherContextOutput:
        assert isinstance(payload, GatherContextInput)  # noqa: S101
        assert self._kernel is not None  # noqa: S101
        fragments = await self._kernel.context.gather(
            ContextRequest(
                query=payload.query,
                user_id=ctx.user_id,
                purpose=payload.purpose,
                max_fragments=payload.max_fragments,
            )
        )
        return GatherContextOutput(fragments=tuple(f.model_dump() for f in fragments))


# canário anti-truncamento
