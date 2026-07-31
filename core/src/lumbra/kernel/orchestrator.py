"""Orchestrator em camadas — a IA nunca é a primeira decisão (ADR-062).

Camadas, acionadas em ordem e parando na primeira que resolve:

1. **Regras determinísticas** — atalhos explícitos (intenção → capability).
2. **Capability Router** — resolve a capability no CapabilityRegistry e executa
   o provedor (skill fina ou agente).
3. Planner existente (``PlannerPort`` + ``PlanRunner``) — multi-passo (A5.2).
4. LLM Planner — só quando o determinístico não sabe (A9, desligado por padrão).

Este arquivo cobre as camadas 1-2. Toda escolha vira DecisionRecord (ADR-060):
qual capability, qual provedor, e se foi determinístico. A execução em si
continua no SkillRegistry (escopo, risco/aprovação, explain, cancelamento) —
o Orchestrator é FINO, não reimplementa nada.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from lumbra.kernel.agent_registry import AgentRegistry
from lumbra.kernel.capability_registry import CapabilityRegistry
from lumbra.kernel.decisions import Candidate, DecisionEngine, DecisionKind, DecisionRecord
from lumbra.kernel.skill_registry import SkillRegistry
from lumbra.ports.capabilities import CapabilityError, ProviderKind
from lumbra.ports.skills import SkillContext
from lumbra.shared.logging import get_logger

_log = get_logger("lumbra.kernel.orchestrator")


class OrchestrationError(Exception):
    pass


class OrchestrationResult(BaseModel):
    """O que a orquestração produziu, e por qual caminho."""

    model_config = ConfigDict(frozen=True)

    capability: str
    provider_ref: str
    provider_kind: ProviderKind
    layer: str  # 'rules' | 'capability_router' | 'planner' | 'llm_planner'
    output: dict[str, Any] = Field(default_factory=dict)


class Orchestrator:
    def __init__(
        self,
        *,
        skills: SkillRegistry,
        capabilities: CapabilityRegistry,
        agents: AgentRegistry,
        decisions: DecisionEngine,
        rules: Mapping[str, str] | None = None,
    ) -> None:
        self._skills = skills
        self._capabilities = capabilities
        self._agents = agents
        self._decisions = decisions
        # camada 1: intenção conhecida → capability (atalho explícito)
        self._rules: dict[str, str] = dict(rules or {})

    def add_rule(self, intent: str, capability_id: str) -> None:
        self._rules[intent] = capability_id

    def route(self, intent: str, *, ctx: SkillContext | None = None) -> str:
        """Camadas 1-2: descobre QUAL capability atende a intenção.

        Regra determinística primeiro; senão, casa a intenção com o id de uma
        capability registrada. Registra a decisão (inclusive as determinísticas)."""
        correlation = ctx.correlation_id if ctx else None
        if intent in self._rules:
            escolhida = self._rules[intent]
            self._decisions.record(
                DecisionRecord(
                    kind=DecisionKind.CAPABILITY_ROUTING,
                    chosen=escolhida,
                    reason=f"regra determinística para a intenção {intent!r}",
                    algorithm="tabela de regras (camada 1)",
                    correlation_id=correlation,
                )
            )
            return escolhida

        candidatas = [c.id for c in self._capabilities.capabilities() if c.id == intent]
        if not candidatas:
            raise OrchestrationError(f"nenhuma capability atende a intenção {intent!r}")
        escolhida = candidatas[0]
        self._decisions.record(
            DecisionRecord(
                kind=DecisionKind.CAPABILITY_ROUTING,
                chosen=escolhida,
                candidates=tuple(Candidate(ref=c) for c in candidatas),
                reason="capability corresponde à intenção",
                algorithm="correspondência direta (camada 2)",
                correlation_id=correlation,
            )
        )
        return escolhida

    async def execute(
        self,
        intent: str,
        payload: Mapping[str, Any],
        *,
        ctx: SkillContext,
    ) -> OrchestrationResult:
        """Roteia e EXECUTA pelo provedor resolvido (skill fina ou agente)."""
        capability_id = self.route(intent, ctx=ctx)
        camada = "rules" if intent in self._rules else "capability_router"
        try:
            provider = self._capabilities.resolve(capability_id)
        except CapabilityError as exc:
            raise OrchestrationError(str(exc)) from exc

        self._decisions.record(
            DecisionRecord(
                kind=DecisionKind.PROVIDER_SELECTION,
                chosen=provider.ref,
                candidates=tuple(
                    Candidate(ref=p.ref, reason=f"prioridade {p.priority}, local={p.local}")
                    for p in self._capabilities.providers_of(capability_id)
                ),
                reason=f"provedor resolvido para {capability_id}",
                algorithm="prioridade desc, local antes de nuvem, ordem de registro",
                correlation_id=ctx.correlation_id,
            )
        )
        _log.info(
            "orchestration_routed",
            intent=intent,
            capability=capability_id,
            provider=provider.ref,
            kind=provider.kind.value,
            layer=camada,
        )

        if provider.kind is ProviderKind.SKILL:
            saida = await self._skills.execute(provider.ref, payload, context=ctx)
            output = saida.model_dump(mode="json")
        else:
            agente = self._agents.get(provider.ref)
            resultado = await agente.handle(payload, ctx)
            output = resultado.output

        return OrchestrationResult(
            capability=capability_id,
            provider_ref=provider.ref,
            provider_kind=provider.kind,
            layer=camada,
            output=output,
        )


# canário anti-truncamento
