"""AgentRegistry — registro de agentes, espelhando o SkillRegistry (ADR-057).

Para provedores COMPOSTOS (agentes), separado do SkillRegistry (unidades
executáveis). Registrar um agente publica AUTOMATICAMENTE um provedor por
capability declarada no CapabilityRegistry — uma fonte, dois índices. Descoberta
por capability/tag, versionamento com coexistência, enable/disable.

Agente externo = plugin (cliente com escopo, ADR-047): o mesmo registro serve;
não há segundo sistema de plugins.
"""

from __future__ import annotations

from lumbra.ports.agents import AgentManifest, AgentPort
from lumbra.ports.capabilities import (
    CapabilityProvider,
    CapabilityRegistryPort,
    ProviderKind,
)
from lumbra.shared.logging import get_logger

_log = get_logger("lumbra.kernel.agents")


class AgentError(Exception):
    pass


class DuplicateAgentError(AgentError):
    def __init__(self, agent_id: str, version: str) -> None:
        super().__init__(f"agente já registrado: {agent_id}@{version}")


class AgentNotFoundError(AgentError):
    def __init__(self, agent_id: str) -> None:
        super().__init__(f"agente não registrado: {agent_id}")


class AgentRegistry:
    def __init__(self, capabilities: CapabilityRegistryPort) -> None:
        self._capabilities = capabilities
        self._agents: dict[str, dict[str, AgentPort]] = {}  # id -> {versão -> agente}

    def register(self, agent: AgentPort) -> None:
        manifest = agent.manifest
        versoes = self._agents.setdefault(manifest.id, {})
        if manifest.version in versoes:
            raise DuplicateAgentError(manifest.id, manifest.version)
        # publica um provedor por capability declarada. register_provider levanta
        # CapabilityNotFoundError se a capability não tiver spec — fail fast:
        # a competência precisa existir antes de um agente prover.
        for capability in manifest.capabilities:
            self._capabilities.register_provider(
                CapabilityProvider(
                    capability_id=capability,
                    kind=ProviderKind.AGENT,
                    ref=manifest.id,
                )
            )
        versoes[manifest.version] = agent
        _log.info(
            "agent_registered",
            agent=manifest.id,
            version=manifest.version,
            capabilities=list(manifest.capabilities),
        )

    def get(self, agent_id: str, *, version: str | None = None) -> AgentPort:
        versoes = self._agents.get(agent_id)
        if not versoes:
            raise AgentNotFoundError(agent_id)
        chave = version if version is not None else max(versoes)  # None = mais recente
        try:
            return versoes[chave]
        except KeyError:
            raise AgentNotFoundError(f"{agent_id}@{version}") from None

    def versions(self, agent_id: str) -> list[str]:
        return sorted(self._agents.get(agent_id, {}))

    def manifests(self) -> list[AgentManifest]:
        return [self.get(aid).manifest for aid in self._agents]

    def find(self, *, capability: str | None = None, tag: str | None = None) -> list[AgentManifest]:
        resultado = self.manifests()
        if capability is not None:
            resultado = [m for m in resultado if capability in m.capabilities]
        if tag is not None:
            resultado = [m for m in resultado if tag in m.capabilities]
        return resultado

    def set_enabled(self, agent_id: str, enabled: bool) -> None:
        """Liga/desliga o agente: reflete nos provedores das suas capabilities."""
        manifest = self.get(agent_id).manifest
        for capability in manifest.capabilities:
            self._capabilities.set_enabled(capability, agent_id, enabled)


# canário anti-truncamento
