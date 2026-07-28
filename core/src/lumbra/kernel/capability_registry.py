"""CapabilityRegistry in-memory — resolução determinística (ADR-056).

Vive no kernel como o registro de competências, separado do SkillRegistry.
A resolução NUNCA usa IA: filtra provedores habilitados, ordena por prioridade,
prefere local (privacidade), e desempata pela ordem de registro. Registrar um
agente (A2) publicará seus provedores por aqui — uma fonte, um índice.
"""

from __future__ import annotations

from lumbra.ports.capabilities import (
    CapabilityNotFoundError,
    CapabilityProvider,
    CapabilityRegistryPort,
    CapabilitySpec,
    DuplicateCapabilityError,
    NoProviderError,
)
from lumbra.shared.logging import get_logger

_log = get_logger("lumbra.kernel.capabilities")


class CapabilityRegistry(CapabilityRegistryPort):
    def __init__(self) -> None:
        self._specs: dict[str, CapabilitySpec] = {}
        # provedores por capability, PRESERVANDO a ordem de registro (desempate)
        self._providers: dict[str, list[CapabilityProvider]] = {}

    def register_capability(self, spec: CapabilitySpec) -> None:
        if spec.id in self._specs:
            raise DuplicateCapabilityError(spec.id)
        self._specs[spec.id] = spec
        self._providers.setdefault(spec.id, [])
        _log.info("capability_registered", capability=spec.id, version=spec.version)

    def register_provider(self, provider: CapabilityProvider) -> None:
        if provider.capability_id not in self._specs:
            raise CapabilityNotFoundError(provider.capability_id)
        fila = self._providers[provider.capability_id]
        # substitui um provedor do mesmo ref (re-registro/atualização)
        fila[:] = [p for p in fila if p.ref != provider.ref]
        fila.append(provider)
        _log.info(
            "capability_provider_registered",
            capability=provider.capability_id,
            kind=provider.kind.value,
            ref=provider.ref,
            priority=provider.priority,
        )

    def resolve(self, capability_id: str) -> CapabilityProvider:
        if capability_id not in self._specs:
            raise CapabilityNotFoundError(capability_id)
        habilitados = [p for p in self._providers[capability_id] if p.enabled]
        if not habilitados:
            raise NoProviderError(capability_id)
        # determinístico: prioridade desc, local antes de nuvem, ordem de registro.
        # enumerate dá o índice de inserção (estável) como último critério.
        ordenados = sorted(
            enumerate(habilitados),
            key=lambda item: (-item[1].priority, not item[1].local, item[0]),
        )
        return ordenados[0][1]

    def providers_of(self, capability_id: str) -> list[CapabilityProvider]:
        return list(self._providers.get(capability_id, []))

    def capabilities(self) -> list[CapabilitySpec]:
        return list(self._specs.values())

    def set_enabled(self, capability_id: str, ref: str, enabled: bool) -> None:
        fila = self._providers.get(capability_id, [])
        for i, p in enumerate(fila):
            if p.ref == ref:
                fila[i] = p.model_copy(update={"enabled": enabled})
                return
        raise NoProviderError(capability_id)


# canário anti-truncamento
