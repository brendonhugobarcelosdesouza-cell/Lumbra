"""Ports do pipeline de ingestão (ADR-020).

``PipelineStagePort``: unidade de processamento idempotente registrada
dinamicamente. ``ProcessingStorePort``: persistência de estado, contexto
de retomada e timeline de observabilidade por documento.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from lumbra.domain.pipeline import PipelineContext, ProcessingState, StageOutcome
from lumbra.ports.document_store import DocumentRecord


class StageInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    document: DocumentRecord
    raw: bytes | None  # conteúdo bruto (relido da fonte a cada execução)
    context: PipelineContext


class PipelineStagePort(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Nome do estágio: extract, ocr, metadata, chunk, embedding, kg, index."""

    @property
    @abstractmethod
    def state(self) -> ProcessingState:
        """Estado exibido enquanto o estágio executa."""

    @abstractmethod
    async def run(self, payload: StageInput) -> StageOutcome:
        """Executa o estágio. DEVE ser idempotente (reexecução segura)."""


class TimelineEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    stage: str
    started_at: datetime
    duration_ms: float
    success: bool
    message: str = ""
    metrics: dict[str, float] = Field(default_factory=dict)


class ProcessingStorePort(ABC):
    @abstractmethod
    async def set_state(
        self, document_id: UUID, state: ProcessingState, *, error: str | None = None
    ) -> None: ...

    @abstractmethod
    async def get_state(self, document_id: UUID) -> ProcessingState: ...

    @abstractmethod
    async def save_context(self, document_id: UUID, context: PipelineContext) -> None: ...

    @abstractmethod
    async def load_context(self, document_id: UUID) -> PipelineContext:
        """Contexto persistido, ou vazio se nunca processado."""

    @abstractmethod
    async def add_timeline(self, document_id: UUID, entry: TimelineEntry) -> None: ...

    @abstractmethod
    async def get_timeline(self, document_id: UUID) -> list[TimelineEntry]: ...

    @abstractmethod
    async def reset_context(self, document_id: UUID) -> None:
        """Descarta o contexto de retomada (nova versão reprocessa do zero;
        a timeline histórica é preservada)."""

    @abstractmethod
    async def mark_indexed(self, document_id: UUID) -> None:
        """Registra a conclusão (indexed_at no documento e na versão atual)."""


# canário anti-truncamento
