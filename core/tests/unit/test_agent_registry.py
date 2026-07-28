"""Agent Registry (A2, ADR-057): registro, descoberta, versões, enable, e a
publicação automática de provedores no CapabilityRegistry. Inclui um agente
trivial (POC) que implementa 1 capability compondo 1 skill.
"""

from collections.abc import Mapping
from typing import Any

import pytest

from lumbra.adapters.eventbus.in_memory import InMemoryEventBus
from lumbra.adapters.eventstore.in_memory import InMemoryEventStore
from lumbra.adapters.permissions.static import StaticPermissionAdapter
from lumbra.domain.events import EventRegistry
from lumbra.kernel.agent_registry import AgentNotFoundError, DuplicateAgentError
from lumbra.kernel.kernel import LumbraKernel
from lumbra.ports.agents import AgentManifest, AgentPort, AgentResult
from lumbra.ports.capabilities import (
    CapabilityNotFoundError,
    CapabilitySpec,
    NoProviderError,
    ProviderKind,
)
from lumbra.ports.skills import (
    Skill,
    SkillContext,
    SkillInput,
    SkillManifest,
    SkillOutput,
)


class _EchoIn(SkillInput):
    text: str = "oi"


class _EchoOut(SkillOutput):
    echoed: str


async def _echo(payload: SkillInput, _c: SkillContext) -> _EchoOut:
    assert isinstance(payload, _EchoIn)
    return _EchoOut(echoed=payload.text.upper())


class _EchoAgent(AgentPort):
    """POC: implementa a capability 'demo.echo' chamando a skill 'test.echo'.
    Prova que um agente COMPÕE skills pelo SkillRegistry, sem importar módulos."""

    def __init__(self, kernel: LumbraKernel, *, version: str = "1.0.0") -> None:
        self._kernel = kernel
        self._manifest = AgentManifest(
            id="echo-agent",
            version=version,
            name="Echo",
            description="ecoa em maiúsculas",
            provider="test",
            capabilities=("demo.echo",),
            skills=("test.echo",),
        )

    @property
    def manifest(self) -> AgentManifest:
        return self._manifest

    async def handle(self, request: Mapping[str, Any], ctx: SkillContext) -> AgentResult:
        out = await self._kernel.skills.execute("test.echo", request, context=ctx)
        return AgentResult(output=out.model_dump(mode="json"), summary="ecoado")


@pytest.fixture()
async def kernel():
    k = LumbraKernel(
        events=EventRegistry(),
        bus=InMemoryEventBus(),
        event_store=InMemoryEventStore(),
        permissions=StaticPermissionAdapter(default_allow=True),
    )
    await k.skills.register(
        Skill(
            manifest=SkillManifest(name="test.echo", description="echo", provider="test"),
            input_model=_EchoIn,
            output_model=_EchoOut,
            handler=_echo,
        )
    )
    k.capabilities.register_capability(CapabilitySpec(id="demo.echo", description="eco"))
    yield k


class TestRegistroEPublicacao:
    async def test_registrar_publica_provider_no_capability_registry(self, kernel):
        kernel.agents.register(_EchoAgent(kernel))
        prov = kernel.capabilities.resolve("demo.echo")
        assert prov.kind is ProviderKind.AGENT
        assert prov.ref == "echo-agent"

    async def test_capability_sem_spec_falha_rapido(self, kernel):
        class _SemSpec(_EchoAgent):
            def __init__(self, k):
                super().__init__(k)
                self._manifest = self._manifest.model_copy(update={"capabilities": ("nao.existe",)})

        with pytest.raises(CapabilityNotFoundError):
            kernel.agents.register(_SemSpec(kernel))

    async def test_duplicado_mesma_versao_levanta(self, kernel):
        kernel.agents.register(_EchoAgent(kernel))
        with pytest.raises(DuplicateAgentError):
            kernel.agents.register(_EchoAgent(kernel))


class TestDescobertaEVersoes:
    async def test_find_por_capability(self, kernel):
        kernel.agents.register(_EchoAgent(kernel))
        achados = kernel.agents.find(capability="demo.echo")
        assert [m.id for m in achados] == ["echo-agent"]

    async def test_get_versao_mais_recente(self, kernel):
        kernel.agents.register(_EchoAgent(kernel, version="1.0.0"))
        kernel.agents.register(_EchoAgent(kernel, version="1.2.0"))
        assert kernel.agents.versions("echo-agent") == ["1.0.0", "1.2.0"]
        assert kernel.agents.get("echo-agent").manifest.version == "1.2.0"

    async def test_get_inexistente_levanta(self, kernel):
        with pytest.raises(AgentNotFoundError):
            kernel.agents.get("nao-existe")


class TestEnableEExecucao:
    async def test_desabilitar_agente_tira_o_provider(self, kernel):
        kernel.agents.register(_EchoAgent(kernel))
        kernel.agents.set_enabled("echo-agent", False)
        with pytest.raises(NoProviderError):
            kernel.capabilities.resolve("demo.echo")

    async def test_agente_compoe_a_skill(self, kernel):
        agent = _EchoAgent(kernel)
        kernel.agents.register(agent)
        resultado = await agent.handle({"text": "olá"}, SkillContext(subject="user:t"))
        assert resultado.output == {"echoed": "OLÁ"}


# canário anti-truncamento
