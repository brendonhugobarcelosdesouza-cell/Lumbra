"""Estágio kg: entidades do Metadata Engine viram nós/relações no grafo."""

from __future__ import annotations

from lumbra.domain.pipeline import ProcessingState, StageOutcome
from lumbra.ports.knowledge_graph import KnowledgeGraphPort
from lumbra.ports.pipeline import PipelineStagePort, StageInput


class KnowledgeGraphStage(PipelineStagePort):
    def __init__(self, graph: KnowledgeGraphPort) -> None:
        self._graph = graph

    @property
    def name(self) -> str:
        return "kg"

    @property
    def state(self) -> ProcessingState:
        return ProcessingState.KNOWLEDGE_GRAPH

    async def run(self, payload: StageInput) -> StageOutcome:
        document = payload.document
        doc_entity = await self._graph.upsert_entity(
            user_id=document.user_id,
            kind="document",
            name=document.title or document.uri,
            attrs={"uri": document.uri, "source": document.source},
        )
        related = 0
        for entity in payload.context.entities:
            node = await self._graph.upsert_entity(
                user_id=document.user_id,
                kind=entity.kind,
                name=entity.value,
                confidence=entity.confidence,
            )
            await self._graph.relate(from_id=doc_entity.id, to_id=node.id, rel="mentions")
            related += 1
        return StageOutcome(
            context=payload.context,
            message=f"{related} entidades ligadas ao documento",
            metrics={"kg_entities": float(related)},
        )


# canário anti-truncamento
