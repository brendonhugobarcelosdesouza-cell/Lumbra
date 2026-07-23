"""Domínio do pipeline de ingestão: estados, planos e contexto (ADR-020).

O pipeline é uma máquina de estados persistida por documento. Cada
estágio é idempotente e declara o estado que representa; uma queda no
meio do processamento retoma do último estágio concluído usando o
contexto persistido — nunca reprocessa do zero.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProcessingState(StrEnum):
    PENDING = "pending"
    EXTRACTING = "extracting"
    OCR = "ocr"
    METADATA = "metadata"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    KNOWLEDGE_GRAPH = "knowledge_graph"
    INDEXED = "indexed"
    FAILED = "failed"


class ExtractedEntity(BaseModel):
    """Entidade estruturada produzida pelo Metadata Engine."""

    model_config = ConfigDict(frozen=True)

    kind: str  # date, email, phone, cpf, cnpj, money, person, company...
    value: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class PipelineContext(BaseModel):
    """Estado intermediário entre estágios — persistido para retomada.

    Serializável em JSONB; o conteúdo bruto (bytes) NÃO vive aqui: cada
    estágio que precisa dele relê da fonte (idempotência sem inflar o
    contexto persistido).
    """

    text: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    entities: list[ExtractedEntity] = Field(default_factory=list)
    chunks: list[str] = Field(default_factory=list)
    stages_done: list[str] = Field(default_factory=list)


class StageOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    context: PipelineContext
    message: str = ""
    metrics: dict[str, float] = Field(default_factory=dict)


class PipelineError(Exception):
    """Falha de estágio — registrada na timeline; documento fica FAILED."""


# canário anti-truncamento
