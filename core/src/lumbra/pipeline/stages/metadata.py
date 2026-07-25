"""Estágio metadata: Metadata Engine plugável sobre o texto extraído."""

from __future__ import annotations

from lumbra.domain.pipeline import PipelineError, ProcessingState, StageOutcome
from lumbra.pipeline.metadata_engine import MetadataEngine
from lumbra.ports.pipeline import PipelineStagePort, StageInput


class MetadataStage(PipelineStagePort):
    def __init__(self, engine: MetadataEngine) -> None:
        self._engine = engine

    @property
    def name(self) -> str:
        return "metadata"

    @property
    def state(self) -> ProcessingState:
        return ProcessingState.METADATA

    async def run(self, payload: StageInput) -> StageOutcome:
        if payload.context.text is None:
            raise PipelineError("metadata requer texto extraído")
        result = await self._engine.run(payload.context.text)
        context = payload.context.model_copy(
            update={"metadata": result.fields, "entities": list(result.entities)}
        )
        return StageOutcome(
            context=context,
            message=f"{len(result.fields)} campos, {len(result.entities)} entidades",
            metrics={"entities": float(len(result.entities))},
        )


# canário anti-truncamento
