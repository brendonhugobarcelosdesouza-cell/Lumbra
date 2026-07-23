"""Estágio ocr: imagens → texto via OCRProviderPort (desacoplado, req. 4)."""

from __future__ import annotations

from lumbra.domain.pipeline import PipelineError, ProcessingState, StageOutcome
from lumbra.ports.ocr import OCRProviderPort
from lumbra.ports.pipeline import PipelineStagePort, StageInput


class OCRStage(PipelineStagePort):
    def __init__(self, provider: OCRProviderPort | None) -> None:
        self._provider = provider

    @property
    def name(self) -> str:
        return "ocr"

    @property
    def state(self) -> ProcessingState:
        return ProcessingState.OCR

    async def run(self, payload: StageInput) -> StageOutcome:
        if self._provider is None:
            # falha explícita e retomável: quando um provider for configurado,
            # o resume continua deste exato estágio
            raise PipelineError("nenhum OCRProvider configurado")
        if payload.raw is None:
            raise PipelineError("conteúdo bruto indisponível para OCR")
        result = await self._provider.recognize(
            payload.raw, mime_type=payload.document.mime_type or "image/*"
        )
        if not result.text.strip():
            raise PipelineError("OCR não reconheceu texto")
        context = payload.context.model_copy(update={"text": result.text})
        return StageOutcome(
            context=context,
            message=f"OCR via {self._provider.name} (conf. {result.confidence:.2f})",
            metrics={"chars": float(len(result.text)), "confidence": result.confidence},
        )


# canário anti-truncamento
