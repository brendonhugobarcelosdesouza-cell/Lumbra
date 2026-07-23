"""AIModule — o AI Gateway como módulo do kernel, com a skill ``ai.embed``.

A skill existe para validação/diagnóstico via Developer Console e para
uso por agentes (Capability Driven): qualquer componente pode gerar
embeddings sem conhecer provedores.
"""

from __future__ import annotations

from typing import Any

from lumbra.kernel.kernel import LumbraKernel, LumbraModule, ModuleManifest
from lumbra.ports.ai import AIGatewayPort, EmbedRequest, PrivacyMode
from lumbra.ports.skills import Skill, SkillContext, SkillInput, SkillManifest, SkillOutput


class EmbedInput(SkillInput):
    texts: list[str]
    purpose: str = "query"
    privacy: PrivacyMode = PrivacyMode.LOCAL_ONLY


class EmbedOutput(SkillOutput):
    dim: int
    provider: str
    model: str
    count: int
    preview: list[float]  # primeiras dimensões do 1º vetor (diagnóstico)


class AIModule(LumbraModule):
    def __init__(self, gateway: AIGatewayPort) -> None:
        self._gateway = gateway

    @property
    def manifest(self) -> ModuleManifest:
        return ModuleManifest(
            name="ai",
            version="0.1.0",
            description="AI Gateway: embeddings (chat na fase do assistente)",
        )

    async def setup(self, kernel: LumbraKernel) -> None:
        await kernel.skills.register(
            Skill(
                manifest=SkillManifest(
                    name="ai.embed",
                    description="Gera embeddings via AI Gateway (roteado por privacidade)",
                    provider="ai",
                    capabilities=("ai", "embedding"),
                ),
                input_model=EmbedInput,
                output_model=EmbedOutput,
                handler=self._embed,
            )
        )

    async def _embed(self, payload: SkillInput, ctx: SkillContext) -> EmbedOutput:
        assert isinstance(payload, EmbedInput)  # noqa: S101
        result = await self._gateway.embed(
            EmbedRequest(
                texts=tuple(payload.texts),
                purpose=payload.purpose,
                privacy=payload.privacy,
                correlation_id=ctx.correlation_id,
            )
        )
        return EmbedOutput(
            dim=result.dim,
            provider=result.provider,
            model=result.model,
            count=len(result.vectors),
            preview=list(result.vectors[0][:8]) if result.vectors else [],
        )

    def gateway(self) -> AIGatewayPort:
        return self._gateway


def _unused() -> None:  # pragma: no cover
    _ = Any


# canário anti-truncamento
