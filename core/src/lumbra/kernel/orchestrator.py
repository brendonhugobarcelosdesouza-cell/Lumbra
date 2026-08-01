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
from lumbra.kernel.learning import PlaybookProposer
from lumbra.kernel.planning import PlanResult, PlanRunner
from lumbra.kernel.sandbox import AgentSandbox, DelegationDeniedError
from lumbra.kernel.skill_registry import SkillRegistry
from lumbra.ports.capabilities import CapabilityError, ProviderKind
from lumbra.ports.permissions import PermissionPort
from lumbra.ports.planner import PlannerPort
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
        planner: PlannerPort | None = None,
        plan_runner: PlanRunner | None = None,
        llm_planner: PlannerPort | None = None,
        permissions: PermissionPort | None = None,
        user_scopes: frozenset[str] | None = None,
        proposer: PlaybookProposer | None = None,
    ) -> None:
        self._skills = skills
        self._capabilities = capabilities
        self._agents = agents
        self._decisions = decisions
        # sandbox por execução de agente (A6/A7.6). Sem permissions, o agente
        # roda sem isolamento (compatibilidade); com, escopo e orçamento valem.
        self._permissions = permissions
        # escopos do usuário; None = tudo que o agente declarar (dev)
        self._user_scopes = user_scopes
        # camada 3: planejamento multi-passo (opcional; sem planner, achieve falha
        # explicitamente em vez de improvisar)
        self._planner = planner
        self._plan_runner = plan_runner
        # camada 4 (A9): só entra quando a 3 não soube. None = desligada.
        self._llm_planner = llm_planner
        # camada 1: intenção conhecida → capability (atalho explícito)
        self._rules: dict[str, str] = dict(rules or {})
        # Learning Loop (L2): o que deu certo vira PROPOSTA de procedimento.
        # None = a plataforma executa sem aprender (comportamento anterior).
        self._proposer = proposer

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
            output = await self._executar_agente(provider.ref, payload, ctx)

        return OrchestrationResult(
            capability=capability_id,
            provider_ref=provider.ref,
            provider_kind=provider.kind,
            layer=camada,
            output=output,
        )

    async def _executar_agente(
        self, agent_id: str, payload: Mapping[str, Any], ctx: SkillContext
    ) -> dict[str, Any]:
        """Executa um agente DENTRO do seu sandbox (A6): escopo intersectado,
        orçamento próprio e estado temporário descartado ao final — sempre,
        inclusive em erro."""
        agente = self._agents.get(agent_id)
        manifesto = agente.manifest
        if self._permissions is None:  # sem isolamento configurado (compat)
            resultado = await agente.handle(payload, ctx)
            return resultado.output

        declarados = frozenset(manifesto.required_scopes)
        # escopo efetivo = min(usuário, agente). Sem escopos do usuário
        # declarados, vale o que o agente pede (o PermissionPort ainda decide).
        concedidos = declarados if self._user_scopes is None else declarados & self._user_scopes
        with AgentSandbox(
            agent_id=manifesto.id,
            permissions=self._permissions,
            scopes=concedidos,
            limits=manifesto.limits,
            cancellation=ctx.cancellation,
        ) as sandbox:
            # o agente executa skills pela VISTA escopada: não consegue mais do
            # que o manifesto declarou, mesmo que o port de origem permita
            resultado = await agente.handle(payload, ctx, sandbox=sandbox)
            gasto = sandbox.budget.snapshot()
            _log.info(
                "agent_executed",
                agent=manifesto.id,
                scopes=sorted(concedidos),
                steps=gasto.steps,
                tokens=gasto.tokens,
            )
            return resultado.output

    async def delegate(
        self,
        capability_id: str,
        payload: Mapping[str, Any],
        *,
        ctx: SkillContext,
        sandbox: AgentSandbox,
    ) -> dict[str, Any]:
        """Um agente delega uma CAPABILITY a outro (A8).

        Três barreiras, todas ANTES de executar: (1) o manifesto do agente atual
        precisa permitir delegar para aquela capability; (2) a cadeia não pode
        repetir um agente (anti-loop A→B→A); (3) escopo do filho = interseção, e
        o orçamento é o MESMO da árvore. Delegar nunca amplia poder nem zera
        contas — é sempre uma redução."""
        atual = self._agents.get(sandbox.agent_id).manifest
        politica = atual.delegation
        if not politica.can_delegate:
            raise DelegationDeniedError(
                f"{atual.id} não pode delegar (delegation.can_delegate=False)"
            )
        if politica.to_capabilities and capability_id not in politica.to_capabilities:
            raise DelegationDeniedError(
                f"{atual.id} não pode delegar para {capability_id!r} "
                f"(permitidas: {politica.to_capabilities})"
            )

        provider = self._capabilities.resolve(capability_id)
        self._decisions.record(
            DecisionRecord(
                kind=DecisionKind.PROVIDER_SELECTION,
                chosen=provider.ref,
                reason=f"delegação de {atual.id} para {capability_id}",
                algorithm="resolução determinística + interseção de escopo",
                correlation_id=ctx.correlation_id,
                inputs_used={"delegator": atual.id, "chain": list(sandbox.chain)},
            )
        )
        if provider.kind is ProviderKind.SKILL:
            # delegar a uma skill: roda no MESMO sandbox (sem nova profundidade)
            sandbox.budget.charge(steps=1)
            saida = await self._skills.scoped(sandbox.permissions).execute(
                provider.ref, payload, context=ctx
            )
            return dict(saida.model_dump(mode="json"))

        delegado = self._agents.get(provider.ref)
        filho = sandbox.child(  # levanta em ciclo, profundidade ou escopo
            agent_id=delegado.manifest.id,
            scopes=frozenset(delegado.manifest.required_scopes),
            limits=delegado.manifest.limits,
        )
        _log.info(
            "agent_delegated",
            de=atual.id,
            para=delegado.manifest.id,
            capability=capability_id,
            depth=filho.depth,
            chain=list(filho.chain),
        )
        with filho:
            resultado = await delegado.handle(payload, ctx, sandbox=filho)
            return resultado.output

    async def achieve(self, goal: str, *, ctx: SkillContext) -> PlanResult:
        """Camada 3: objetivo MULTI-PASSO via Planner + PlanRunner existentes.

        Acorda o que já estava construído: o planner decompõe o objetivo em um
        DAG de passos (dependências explícitas) e o PlanRunner executa com
        FALHA PARCIAL (passo falho não derruba o plano). Cada passo passa pelo
        SkillRegistry — escopo, risco, explain e cancelamento valem igual.

        Sem planner configurado, levanta em vez de improvisar: a camada 4 (LLM)
        é opt-in e chega depois."""
        if self._planner is None or self._plan_runner is None:
            raise OrchestrationError(
                "planejamento indisponível: nenhum PlannerPort/PlanRunner configurado"
            )
        manifestos = self._skills.manifests()
        plano = await self._planner.plan(goal, skills=manifestos)
        planner_usado = self._planner
        sem_ia = True

        # camada 4 (A9): a IA só entra se a camada 3 NÃO soube planejar.
        if not plano.steps and self._llm_planner is not None:
            self._decisions.record(
                DecisionRecord(
                    kind=DecisionKind.FALLBACK,
                    chosen=type(self._llm_planner).__name__,
                    candidates=(
                        Candidate(
                            ref=type(self._planner).__name__,
                            reason="não soube decompor o objetivo",
                        ),
                    ),
                    reason="camadas determinísticas esgotadas — recorrendo ao planner de IA",
                    algorithm="fallback da camada 3 para a 4",
                    deterministic=True,  # a DECISÃO de recorrer à IA é determinística
                    correlation_id=ctx.correlation_id,
                    inputs_used={"goal": goal},
                )
            )
            plano = await self._llm_planner.plan(goal, skills=manifestos)
            planner_usado = self._llm_planner
            sem_ia = False

        self._decisions.record(
            DecisionRecord(
                kind=DecisionKind.PLANNING,
                chosen=type(planner_usado).__name__,
                candidates=tuple(Candidate(ref=s.skill, reason=s.rationale) for s in plano.steps),
                reason=f"objetivo multi-passo: {len(plano.steps)} passo(s) planejado(s)",
                algorithm="PlannerPort + PlanRunner (DAG com falha parcial)",
                deterministic=sem_ia,
                correlation_id=ctx.correlation_id,
                inputs_used={"goal": goal},
            )
        )
        if not plano.steps:
            raise OrchestrationError(f"o planner não soube decompor o objetivo: {goal!r}")
        _log.info("orchestration_planned", goal=goal, steps=len(plano.steps), layer="planner")
        resultado = await self._plan_runner.run(plano, context=ctx)

        # Learning Loop (L2): o caminho que funcionou vira PROPOSTA de
        # procedimento — nunca escrita direta (ADR-064). Aprender é efeito
        # colateral: se falhar, o trabalho já feito não pode ser perdido.
        if self._proposer is not None:
            try:
                await self._proposer.propose(goal, resultado, ctx=ctx)
            except Exception as exc:
                _log.warning("playbook_proposal_failed", goal=goal, error=repr(exc)[:200])
        return resultado


# canário anti-truncamento
