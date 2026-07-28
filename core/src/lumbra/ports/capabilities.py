"""Capability Model — competências roteáveis, distintas de Skills (ADR-055).

Uma ``Capability`` é uma COMPETÊNCIA funcional (``documents.summarize``), com
contrato tipado — uma interface, não uma implementação. É cumprida por um
provedor: uma Skill (fina, 1:1) ou um Agente (composta). O ``CapabilityRegistry``
(ADR-056) resolve capability → provedor de forma DETERMINÍSTICA, nunca por IA.

Este módulo é só o contrato (portos e modelos). A implementação in-memory vive
em ``kernel/capability_registry.py``. Skills e o SkillRegistry NÃO mudam.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from lumbra.ports.skills import RiskLevel

# capacidade nomeada 'domínio.ação' — mesmo formato de skill (Capability Driven)
CAPABILITY_ID_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")


class CapabilityMode(StrEnum):
    READ = "read"  # consulta, sem efeito no mundo
    WRITE = "write"  # muta algo — herda a lógica de risco/aprovação


class ProviderKind(StrEnum):
    SKILL = "skill"  # cumprida direto por uma skill (fina)
    AGENT = "agent"  # cumprida por um agente (composta)


class CapabilityError(Exception):
    pass


class InvalidCapabilityError(CapabilityError):
    pass


class DuplicateCapabilityError(CapabilityError):
    pass


class CapabilityNotFoundError(CapabilityError):
    def __init__(self, capability_id: str) -> None:
        super().__init__(f"capability não registrada: {capability_id}")


class NoProviderError(CapabilityError):
    def __init__(self, capability_id: str) -> None:
        super().__init__(f"nenhum provedor habilitado para {capability_id}")


class CapabilitySpec(BaseModel):
    """Declaração de uma competência — o contrato que os provedores cumprem."""

    model_config = ConfigDict(frozen=True)

    id: str  # 'documents.summarize' (domínio.ação)
    version: str = "1.0.0"
    description: str = ""
    risk_level: RiskLevel = RiskLevel.LOW  # risco MÍNIMO da competência
    required_scopes: tuple[str, ...] = ()  # escopos MÍNIMOS exigidos
    mode: CapabilityMode = CapabilityMode.READ

    def model_post_init(self, _ctx: Any) -> None:
        if not CAPABILITY_ID_RE.match(self.id):
            raise InvalidCapabilityError(
                f"id de capability inválido: {self.id!r} (esperado 'domínio.ação')"
            )


class CapabilityProvider(BaseModel):
    """Quem cumpre uma capability: uma skill (por nome) ou um agente (por id)."""

    model_config = ConfigDict(frozen=True)

    capability_id: str
    kind: ProviderKind
    ref: str  # nome da skill OU id do agente
    priority: int = 0  # maior vence no desempate (determinístico)
    local: bool = True  # roda 100% local (preferido sob privacidade)
    enabled: bool = True


class CapabilityRegistryPort(ABC):
    """Registro de competências → provedores, separado do SkillRegistry."""

    @abstractmethod
    def register_capability(self, spec: CapabilitySpec) -> None: ...

    @abstractmethod
    def register_provider(self, provider: CapabilityProvider) -> None: ...

    @abstractmethod
    def resolve(self, capability_id: str) -> CapabilityProvider:
        """Escolhe o provedor de forma DETERMINÍSTICA. Levanta se não houver."""

    @abstractmethod
    def providers_of(self, capability_id: str) -> list[CapabilityProvider]: ...

    @abstractmethod
    def capabilities(self) -> list[CapabilitySpec]: ...

    @abstractmethod
    def set_enabled(self, capability_id: str, ref: str, enabled: bool) -> None: ...


# canário anti-truncamento
