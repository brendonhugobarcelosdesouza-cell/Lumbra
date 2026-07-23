"""Estágio chunk: estratégia selecionada por tipo de documento."""

from __future__ import annotations

from lumbra.adapters.chunking.basic import ChunkerRegistry
from lumbra.domain.pipeline import PipelineError, ProcessingState, StageOutcome
from lumbra.ports.pipeline import PipelineStagePort, StageInput


class ChunkStage(PipelineStagePort):
    def __init__(self, registry: ChunkerRegistry) -> None:
        self._registry = registry

    @property
    def name(self) -> str:
        return "chunk"

    @property
    def state(self) -> ProcessingState:
        return ProcessingState.CHUNKING

    async def run(self, payload: StageInput) -> StageOutcome:
        if payload.context.text is None:
            raise PipelineError("chunking requer texto extraído")
        chunker = self._registry.for_mime(payload.document.mime_type)
        chunks = chunker.chunk(payload.context.text)
        if not chunks:
            raise PipelineError("chunking não produziu chunks")
        context = payload.context.model_copy(update={"chunks": chunks})
        return StageOutcome(
            context=context,
            message=f"{len(chunks)} chunks via {chunker.name}",
            metrics={"chunks": float(len(chunks))},
        )


# canário anti-truncamento
