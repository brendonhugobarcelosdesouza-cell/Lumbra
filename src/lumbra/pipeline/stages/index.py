"""Estágio index: persiste chunks (busca léxica ativa; vetores na Etapa 3)."""

from __future__ import annotations

from lumbra.domain.pipeline import PipelineError, ProcessingState, StageOutcome
from lumbra.ports.document_store import DocumentStorePort
from lumbra.ports.pipeline import PipelineStagePort, StageInput


class IndexStage(PipelineStagePort):
    def __init__(self, documents: DocumentStorePort) -> None:
        self._documents = documents

    @property
    def name(self) -> str:
        return "index"

    @property
    def state(self) -> ProcessingState:
        return ProcessingState.INDEXED

    async def run(self, payload: StageInput) -> StageOutcome:
        if not payload.context.chunks:
            raise PipelineError("index requer chunks")
        # replace é idempotente: reexecução produz o mesmo resultado
        total = await self._documents.replace_chunks(payload.document.id, payload.context.chunks)
        return StageOutcome(
            context=payload.context,
            message=f"{total} chunks indexados",
            metrics={"chunks_indexed": float(total)},
        )


# canário anti-truncamento
