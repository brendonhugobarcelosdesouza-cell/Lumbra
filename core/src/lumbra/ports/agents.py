"""Agente de primeira classe — o CONTRATO (A0.3, análise em docs/25).

Um agente é um consumidor da plataforma, não a plataforma. Este manifesto
espelha o ``SkillManifest``: declarativo, validado na construção, descobrível.
NÃO há runtime aqui — só o contrato. O Agent Registry/Runtime (A1/A2) virão
depois, reusando SkillRegistry, ExecutionTracker e a política de aprovação.

Invariantes que o manifesto carrega (segurança, docs/25 seção I):
* ``tools``: as ÚNICAS skills que o agente pode chamar (subconjunto do
  SkillRegistry). Fora disso, o registry nega por escopo.
* ``required_scopes``: o TETO de permissão do agente. O escopo efetivo em
  execução é sempre ``min(usuário, agente, cadeia de delegação)``.
* ``memory_access``: leitura ou nada — agentes NUNCA criam "memória oculta"
  (a memória é do usuário; regra dura da análise).
* ``limits``: budgets (tokens, tempo, passos, profundidade) — a base para um
  sistema multiagente não multiplicar chamadas sem teto.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from lumbra.ports.skills import SKILL_NAME_RE, RiskLevel, SkillContext

AGENT_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")  # slug: 'finance-agent'


class InvalidAgentError(Exception):
    pass


class MemoryAccess(StrEnum):
    """Acesso à memória do usuário. Sem 'WRITE oculto': agentes não criam
    memórias invisíveis. Escrita de memória, quando houver, é uma skill
    explícita, auditável e sujeita à privacidade — não um efeito colateral."""

    NONE = "none"
    READ = "read"


class DelegationPolicy(BaseModel):
    """Se e como o agente pode chamar OUTROS agentes (A5)."""

    model_config = ConfigDict(frozen=True)

    can_delegate: bool = False
    # capacidades (tags) às quais pode delegar; vazio = nenhuma
    to_capabilities: tuple[str, ...] = ()


class AgentLimits(BaseModel):
    """Budgets de uma execução de agente — teto para não multiplicar custo."""

    model_config = ConfigDict(frozen=True)

    max_tokens: int = Field(default=8000, gt=0)
    max_seconds: float = Field(default=60.0, gt=0)
    max_steps: int = Field(default=16, gt=0)  # passos de skill/plano
    max_depth: int = Field(default=3, ge=0)  # profundidade de delegação


class AgentManifest(BaseModel):
    """Declaração pública de um agente — o que o discovery e a segurança veem."""

    # extra='forbid' como no SkillInput: um campo desconhecido é ERRO, não é
    # ignorado em silêncio. Sem isto, um manifesto com 'skills=' (campo que só
    # existe na proposta de docs/26) passaria batido e o agente rodaria sem
    # declarar suas tools — a segurança depende do manifesto estar correto.
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str  # slug único: 'finance-agent'
    name: str
    version: str = "1.0.0"
    description: str
    provider: str  # 'kernel' | 'plugin:acme'
    capabilities: tuple[str, ...] = ()  # tags de discovery
    tools: tuple[str, ...] = ()  # skills chamáveis ('domínio.ação')
    required_scopes: tuple[str, ...] = ()  # teto de permissão do agente
    risk_level: RiskLevel = RiskLevel.LOW
    memory_access: MemoryAccess = MemoryAccess.NONE
    delegation: DelegationPolicy = DelegationPolicy()
    limits: AgentLimits = AgentLimits()

    def model_post_init(self, _ctx: Any) -> None:
        if not AGENT_ID_RE.match(self.id):
            raise InvalidAgentError(
                f"id de agente inválido: {self.id!r} (esperado slug, ex.: 'finance-agent')"
            )
        for tool in self.tools:
            if not SKILL_NAME_RE.match(tool):
                raise InvalidAgentError(
                    f"tool inválida no agente {self.id!r}: {tool!r} (esperado 'domínio.ação')"
                )


class AgentResult(BaseModel):
    """Saída de uma execução de agente. Runtime completo (sandbox, budgets,
    árvore) vem depois; aqui é o contrato mínimo."""

    model_config = ConfigDict(frozen=True)

    output: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""


class AgentPort(ABC):
    """Um agente executável: um manifesto + um handler que COMPÕE skills.

    O agente descobre e executa skills pelo SkillRegistry (nunca importa
    módulos), como qualquer consumidor da plataforma. O runtime que aplica
    sandbox/budget/árvore ao redor deste handle chega nos incrementos A3/A6."""

    @property
    @abstractmethod
    def manifest(self) -> AgentManifest: ...

    @abstractmethod
    async def handle(self, request: Mapping[str, Any], ctx: SkillContext) -> AgentResult:
        """Executa a competência do agente e devolve o resultado."""


# canário anti-truncamento
