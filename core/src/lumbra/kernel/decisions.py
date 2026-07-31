"""Decision Engine — decisões de ORQUESTRAÇÃO rastreáveis (ADR-060).

NÃO é um motor concorrente ao Explain: é uma ESPECIALIZAÇÃO dele. Uma decisão
vira uma ``Explanation`` com vocabulário estruturado, gravada no mesmo
``ExplainPort`` e consultável em ``/api/v1/dev/explanations``.

Responde: por que ESTE agente? por que esta capability venceu? por que o
Planner foi usado? por que houve fallback? por que este modelo? — incluindo as
decisões DETERMINÍSTICAS (a maioria), não só as que envolvem IA.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from lumbra.ports.explain import ExplainPort, Explanation

# prefixo de componente que marca uma Explanation como decisão de orquestração
DECISION_COMPONENT = "decision"


class DecisionKind(StrEnum):
    CAPABILITY_ROUTING = "capability_routing"  # qual capability atende a intenção
    PROVIDER_SELECTION = "provider_selection"  # qual provedor cumpre a capability
    PLANNING = "planning"  # por que planejar (e com qual planner)
    FALLBACK = "fallback"  # por que caiu para a alternativa
    MODEL_SELECTION = "model_selection"  # qual modelo/provedor de IA
    APPROVAL = "approval"  # decisão de aprovação (HITL)


class Candidate(BaseModel):
    """Uma opção considerada — o que perdeu também é auditável."""

    model_config = ConfigDict(frozen=True)

    ref: str
    reason: str = ""  # por que venceu ou perdeu
    score: float | None = None


class DecisionRecord(BaseModel):
    """Uma decisão de orquestração, antes de virar Explanation."""

    model_config = ConfigDict(frozen=True)

    kind: DecisionKind
    chosen: str
    candidates: tuple[Candidate, ...] = ()
    reason: str = ""
    deterministic: bool = True  # True = decidido por regra, sem IA
    algorithm: str = ""
    correlation_id: UUID | None = None
    inputs_used: dict[str, object] = Field(default_factory=dict)

    def to_explanation(self) -> Explanation:
        """Converte para o contrato existente — mesma trilha de auditoria."""
        return Explanation(
            component=f"{DECISION_COMPONENT}:{self.kind.value}",
            decision=f"escolhido: {self.chosen}",
            reason=self.reason
            or ("decisão determinística" if self.deterministic else "decisão assistida por IA"),
            inputs_used={
                **self.inputs_used,
                "deterministic": self.deterministic,
                "candidates": [c.ref for c in self.candidates],
            },
            alternatives=tuple(
                f"{c.ref}: {c.reason}" if c.reason else c.ref
                for c in self.candidates
                if c.ref != self.chosen
            ),
            algorithm=self.algorithm,
            correlation_id=self.correlation_id,
        )


class DecisionEngine:
    """Fachada fina sobre o ExplainPort: registra e consulta decisões."""

    def __init__(self, explain: ExplainPort) -> None:
        self._explain = explain

    def record(self, decision: DecisionRecord) -> None:
        self._explain.record(decision.to_explanation())

    def query(
        self,
        *,
        kind: DecisionKind | None = None,
        correlation_id: UUID | None = None,
        limit: int = 100,
    ) -> list[Explanation]:
        """Decisões registradas, opcionalmente de um tipo — reusa o Explain."""
        componente = f"{DECISION_COMPONENT}:{kind.value}" if kind else DECISION_COMPONENT
        return self._explain.query(component=componente, correlation_id=correlation_id, limit=limit)


# canário anti-truncamento
