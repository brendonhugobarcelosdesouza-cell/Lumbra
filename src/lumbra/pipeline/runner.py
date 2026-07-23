"""PipelineResolver + PipelineRunner (ADR-020).

Resolver: plano de estágios por tipo de documento, com override por
DataSource — pipelines diferentes compartilham a MESMA infraestrutura
(multimodal por construção, req. 10).

Runner: executa o plano com estado persistido, contexto de retomada,
timeline por estágio e métricas. Reexecutar um documento FAILED continua
do estágio que falhou; estágios concluídos nunca re-executam.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from lumbra.domain.pipeline import ProcessingState
from lumbra.ports.document_store import DocumentRecord
from lumbra.ports.metrics import MetricsPort
from lumbra.ports.pipeline import (
    PipelineStagePort,
    ProcessingStorePort,
    StageInput,
    TimelineEntry,
)
from lumbra.shared.logging import get_logger

_log = get_logger("lumbra.pipeline")

RawReader = Callable[[DocumentRecord], Awaitable[bytes | None]]


class PipelineResolver:
    """Seleciona o plano de estágios. Ordem de precedência:
    plano explícito do DataSource > mapeamento por mime > padrão."""

    def __init__(self, default_plan: list[str]) -> None:
        self._default = default_plan
        self._by_mime: list[tuple[str, list[str]]] = []

    def map_mime(self, mime_prefix: str, plan: list[str]) -> None:
        self._by_mime.append((mime_prefix, plan))

    def resolve(self, *, mime_type: str | None, source_plan: list[str] | None = None) -> list[str]:
        if source_plan is not None:
            return source_plan
        if mime_type:
            for prefix, plan in self._by_mime:
                if mime_type.startswith(prefix):
                    return plan
        return self._default


def default_resolver() -> PipelineResolver:
    text_plan = ["extract", "metadata", "chunk", "index", "embedding", "kg"]
    resolver = PipelineResolver(default_plan=text_plan)
    resolver.map_mime("image/", ["ocr", "metadata", "chunk", "index", "embedding", "kg"])
    # áudio/vídeo entram com os estágios speech_to_text/audio_extract (mesma infra)
    return resolver


class PipelineRunner:
    def __init__(
        self,
        *,
        stages: list[PipelineStagePort],
        resolver: PipelineResolver,
        processing: ProcessingStorePort,
        metrics: MetricsPort,
        read_raw: RawReader,
    ) -> None:
        self._stages = {stage.name: stage for stage in stages}
        self._resolver = resolver
        self._processing = processing
        self._metrics = metrics
        self._read_raw = read_raw

    async def process(
        self, document: DocumentRecord, *, source_plan: list[str] | None = None
    ) -> ProcessingState:
        plan = self._resolver.resolve(mime_type=document.mime_type, source_plan=source_plan)
        context = await self._processing.load_context(document.id)
        raw: bytes | None = None
        raw_loaded = False
        total_start = time.perf_counter()

        for stage_name in plan:
            if stage_name in context.stages_done:
                continue  # retomada: estágio já concluído nunca re-executa
            stage = self._stages.get(stage_name)
            started_at = datetime.now(tz=UTC)
            stage_start = time.perf_counter()

            if stage is None:
                await self._fail(
                    document,
                    stage_name,
                    started_at,
                    stage_start,
                    f"estágio não registrado: {stage_name}",
                )
                return ProcessingState.FAILED

            await self._processing.set_state(document.id, stage.state)
            if not raw_loaded:
                raw = await self._read_raw(document)
                raw_loaded = True
            try:
                outcome = await stage.run(StageInput(document=document, raw=raw, context=context))
            except Exception as exc:
                await self._fail(document, stage_name, started_at, stage_start, repr(exc)[:500])
                return ProcessingState.FAILED

            duration_ms = round((time.perf_counter() - stage_start) * 1000, 2)
            context = outcome.context.model_copy(
                update={"stages_done": [*outcome.context.stages_done, stage_name]}
            )
            await self._processing.save_context(document.id, context)
            await self._processing.add_timeline(
                document.id,
                TimelineEntry(
                    stage=stage_name,
                    started_at=started_at,
                    duration_ms=duration_ms,
                    success=True,
                    message=outcome.message,
                    metrics=outcome.metrics,
                ),
            )
            self._metrics.observe("pipeline_stage_ms", duration_ms, stage=stage_name)
            for key, value in outcome.metrics.items():
                self._metrics.increment(f"pipeline_{key}", value)

        await self._processing.set_state(document.id, ProcessingState.INDEXED)
        await self._processing.mark_indexed(document.id)
        total_ms = round((time.perf_counter() - total_start) * 1000, 2)
        self._metrics.observe("pipeline_total_ms", total_ms)
        self._metrics.increment("documents_processed")
        _log.info("document_indexed", document_id=str(document.id), plan=plan, total_ms=total_ms)
        return ProcessingState.INDEXED

    async def _fail(
        self,
        document: DocumentRecord,
        stage_name: str,
        started_at: datetime,
        stage_start: float,
        error: str,
    ) -> None:
        duration_ms = round((time.perf_counter() - stage_start) * 1000, 2)
        await self._processing.add_timeline(
            document.id,
            TimelineEntry(
                stage=stage_name,
                started_at=started_at,
                duration_ms=duration_ms,
                success=False,
                message=error,
            ),
        )
        await self._processing.set_state(document.id, ProcessingState.FAILED, error=error)
        self._metrics.increment("documents_failed", stage=stage_name)
        _log.error(
            "pipeline_stage_failed",
            document_id=str(document.id),
            stage=stage_name,
            error=error,
        )


# canário anti-truncamento
