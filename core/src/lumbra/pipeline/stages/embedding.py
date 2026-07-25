"""Estágio embedding: chunks persistidos ganham vetores via AI Gateway.

Ordem no plano: chunk → index (persiste chunks) → embedding (atualiza
vetores) → kg. Idempotente: reexecução regrava os mesmos vetores.
Privacidade: propósito 'indexing' com política local_only — conteúdo do
usuário jamais sai da máquina neste estágio (princípio nº 14).
"""

from __future__ import annotations

from lumbra.domain.pipeline import PipelineError, ProcessingState, StageOutcome
from lumbra.ports.ai import AIGatewayPort, EmbedRequest, PrivacyMode
from lumbra.ports.document_store import DocumentStorePort
from lumbra.ports.pipeline import PipelineStagePort, StageInput

_BATCH = 64


class EmbeddingStage(PipelineStagePort):
    def __init__(self, gateway: AIGatewayPort, documents: DocumentStorePort) -> None:
        self._gateway = gateway
        self._documents = documents

    @property
    def name(self) -> str:
        return "embedding"

    @property
    def state(self) -> ProcessingState:
        return ProcessingState.EMBEDDING

    async def run(self, payload: StageInput) -> StageOutcome:
        chunks = payload.context.chunks
        if not chunks:
            raise PipelineError("embedding requer chunks (execute o estágio index antes)")
        vectors: list[tuple[float, ...]] = []
        provider = model = ""
        for start in range(0, len(chunks), _BATCH):
            batch = tuple(chunks[start : start + _BATCH])
            result = await self._gateway.embed(
                EmbedRequest(texts=batch, purpose="indexing", privacy=PrivacyMode.LOCAL_ONLY)
            )
            vectors.extend(result.vectors)
            provider, model = result.provider, result.model
        updated = await self._documents.set_chunk_embeddings(payload.document.id, vectors)
        return StageOutcome(
            context=payload.context,
            message=f"{updated} vetores ({model} via {provider})",
            metrics={"embeddings": float(updated)},
        )


# canário anti-truncamento
