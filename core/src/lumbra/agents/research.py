"""ResearchAgent — o primeiro agente que DELEGA (A11).

Implementa ``research.gather``: reúne evidência sobre uma pergunta consultando
DUAS competências por delegação — ``documents.search`` e ``memory.search`` — e
devolve o material consolidado, com a proveniência de cada fonte.

É aqui que a delegação do A8 deixa de ser mecanismo testado e vira uso real:

* o escopo efetivo do delegado é a INTERSEÇÃO com o deste agente (nunca amplia);
* o orçamento é COMPARTILHADO — as duas consultas debitam do mesmo teto;
* a cadeia impede ciclos, e cada delegação vira decisão auditável.

Deliberadamente SEM IA: a síntese aqui é agregação determinística (juntar e
rotular a evidência). Interpretar o material é papel do chat, que já tem o
guardrail de ambiguidade (ADR-052) — este agente não opina, só reúne.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from lumbra.ports.agents import (
    AgentLimits,
    AgentManifest,
    AgentPort,
    AgentResult,
    DelegationPolicy,
    MemoryAccess,
)
from lumbra.ports.skills import RiskLevel, SkillContext

CAPABILITY = "research.gather"
DOCUMENTS = "documents.search"
MEMORY = "memory.search"


class ResearchAgent(AgentPort):
    """Reúne evidência de documentos E memórias, por delegação."""

    def __init__(self, orchestrator: Any) -> None:
        # o orquestrador é quem sabe delegar (resolve capability + sandbox filho)
        self._orchestrator = orchestrator
        self._manifest = AgentManifest(
            id="research-agent",
            name="Pesquisa",
            description="Reúne evidência dos documentos e das memórias do usuário",
            provider="kernel",
            capabilities=(CAPABILITY,),
            tools=(),  # não chama skills direto: só delega
            required_scopes=("read:documents", "read:memory"),
            risk_level=RiskLevel.LOW,
            memory_access=MemoryAccess.NONE,  # não toca a memória; o delegado lê
            delegation=DelegationPolicy(
                can_delegate=True,
                to_capabilities=(DOCUMENTS, MEMORY),  # e NADA além disso
            ),
            # orçamento da ÁRVORE: cobre as duas delegações
            limits=AgentLimits(max_tokens=4000, max_steps=8, max_seconds=60.0, max_depth=2),
        )

    @property
    def manifest(self) -> AgentManifest:
        return self._manifest

    async def handle(
        self,
        request: Mapping[str, Any],
        ctx: SkillContext,
        *,
        sandbox: Any | None = None,
    ) -> AgentResult:
        if sandbox is None:
            raise ValueError("research-agent exige sandbox: ele delega, e delegação precisa dele")
        if ctx.cancellation is not None:
            ctx.cancellation.raise_if_cancelled()

        fontes: dict[str, Any] = {}
        falhas: dict[str, str] = {}
        # resultado PARCIAL é melhor que falha total (doc 07): se uma fonte cai,
        # a outra ainda responde, e a falha fica explícita no resultado.
        for capability in (DOCUMENTS, MEMORY):
            try:
                fontes[capability] = await self._orchestrator.delegate(
                    capability, request, ctx=ctx, sandbox=sandbox
                )
            except Exception as exc:
                falhas[capability] = repr(exc)[:200]

        total = sum(len(v.get("hits", [])) for v in fontes.values() if isinstance(v, dict))
        return AgentResult(
            output={"sources": fontes, "failures": falhas, "total_hits": total},
            summary=f"{total} evidência(s) de {len(fontes)} fonte(s)",
        )


# canário anti-truncamento
