"""Skills — toda ação do sistema é uma Skill descobrível e executável.

Uma Skill é a unidade universal de capacidade do Lumbra (ADR-015):
``create_alarm``, ``search_memory``, ``scan_pdf``, ``register_medication``...
Agentes, módulos e plugins NÃO se chamam diretamente — publicam eventos ou
descobrem e executam Skills pelo registro (Capability Discovery).

Contrato:

* Manifesto declarativo: nome, versão, descrição, provedor, capacidades
  (tags de discovery) e escopos de permissão exigidos.
* Entrada e saída tipadas (Pydantic) — validação acontece no registro,
  nunca dentro do handler.
* Toda execução passa pelo Permission Manager e gera observabilidade
  (log estruturado + evento ``skill.executed``/``skill.failed``).
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from lumbra.shared.cancellation import CancellationToken

SKILL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")  # domínio.ação


class RiskLevel(StrEnum):
    """Nível de risco da ação (ADR-024): política Human-in-the-Loop.

    LOW: leitura/consulta. MEDIUM+: muta o mundo externo e passa pela
    política de aprovação do usuário quando o ApprovalPolicyPort chegar.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SkillError(Exception):
    """Erro-base de skills."""


class SkillNotFoundError(SkillError):
    def __init__(self, name: str) -> None:
        super().__init__(f"Skill não encontrada: {name}")
        self.name = name


class DuplicateSkillError(SkillError):
    def __init__(self, name: str) -> None:
        super().__init__(f"Skill já registrada: {name}")


class InvalidSkillError(SkillError):
    pass


class SkillPermissionDeniedError(SkillError):
    def __init__(self, name: str, subject: str, scope: str) -> None:
        super().__init__(f"Permissão negada: {subject!r} sem escopo {scope!r} para skill {name!r}")
        self.scope = scope


class SkillApprovalRequiredError(SkillError):
    """Ação de risco (>= MEDIUM) barrada pela política de aprovação (ADR-024).

    Distinta de permissão: o sujeito TEM o escopo, mas a ação precisa de
    confirmação humana (Human-in-the-Loop) que a política ainda não deu."""

    def __init__(self, name: str, subject: str, decision: str) -> None:
        super().__init__(f"Aprovação necessária para {name!r} (sujeito {subject!r}): {decision}")
        self.decision = decision


class SkillManifest(BaseModel):
    """Declaração pública de uma capacidade — o que o discovery enxerga."""

    model_config = ConfigDict(frozen=True)

    name: str  # 'domínio.ação' (ADR-018): document.search, memory.search
    version: str = "1.0.0"
    description: str
    provider: str  # "kernel", "health-agent", "plugin:acme"
    capabilities: tuple[str, ...] = ()  # tags de discovery: ("alarm", "scheduling")
    risk_level: RiskLevel = RiskLevel.LOW  # ADR-024: >= MEDIUM exige aprovação futura
    required_scopes: tuple[str, ...] = ()  # permissões 'verbo:recurso' exigidas

    def model_post_init(self, _ctx: Any) -> None:
        if not SKILL_NAME_RE.match(self.name):
            raise InvalidSkillError(
                f"nome de skill inválido: {self.name!r} "
                "(esperado 'domínio.ação', ex.: document.search)"
            )


class SkillInput(BaseModel):
    """Base para entradas de skill. ``extra='forbid'`` por segurança."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class SkillOutput(BaseModel):
    """Base para saídas de skill."""

    model_config = ConfigDict(frozen=True)


@dataclass(frozen=True, slots=True)
class SkillContext:
    """Contexto de execução propagado a todo handler."""

    subject: str  # quem pede: "user:<id>", "agent:task-agent"
    user_id: UUID | None = None
    correlation_id: UUID | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    # token de cancelamento da operação (ADR-032). Opcional: handlers que
    # não fazem trabalho longo simplesmente ignoram.
    cancellation: CancellationToken | None = None


SkillHandler = Callable[[SkillInput, SkillContext], Awaitable[SkillOutput]]

# Descreve o PEDIDO em linguagem de gente, para a confirmação humana.
#
# Existe porque uma tela de aprovação que mostra `playbook.forget` e um id
# opaco não deixa ninguém julgar nada — ela ensina a clicar em "Aprovar" sem
# ler, que é o hábito exato que o gate existe para evitar. Quem sabe traduzir
# o payload é a skill, não o cliente: assim toda ação de risco futura ganha
# uma frase honesta sem que app, CLI e plugins precisem conhecer cada uma.
#
# É async porque descrever costuma exigir uma consulta ("esquecer QUAL
# procedimento?"). Falhar aqui nunca impede a execução.
SkillDescriber = Callable[[SkillInput, SkillContext], Awaitable[str]]


@dataclass(frozen=True, slots=True)
class Skill:
    """Manifesto + esquemas + implementação."""

    manifest: SkillManifest
    input_model: type[SkillInput]
    output_model: type[SkillOutput]
    handler: SkillHandler
    describe: SkillDescriber | None = None
