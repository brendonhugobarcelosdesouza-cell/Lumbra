"""Estágio chunk: ciente de estrutura quando há tabela, legado caso contrário.

A decisão é deliberadamente conservadora (issue #10): só desviamos do
chunker legado quando o documento TEM tabela — o caso em que o chunking
por tamanho destrói o par rótulo-valor. Documentos de prosa pura seguem
byte a byte pelo caminho de antes, então nada muda para eles (o golden
set é o guarda dessa promessa)."""

from __future__ import annotations

from lumbra.adapters.chunking.basic import ChunkerRegistry
from lumbra.adapters.chunking.structural import chunk_blocks
from lumbra.domain.document_structure import BlockType
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
        blocks = payload.context.blocks
        tem_tabela = any(b.type is BlockType.TABLE for b in blocks)

        if blocks and tem_tabela:
            chunks, metas = chunk_blocks(blocks)
            estrategia = "structural"
        else:
            chunks, metas = [], []

        # legado como padrão E como rede: se a via estrutural não render
        # nada, cai para o chunker por texto (nunca deixa o doc sem chunks)
        if not chunks:
            chunker = self._registry.for_mime(payload.document.mime_type)
            chunks = chunker.chunk(payload.context.text)
            metas = []
            estrategia = chunker.name

        if not chunks:
            raise PipelineError("chunking não produziu chunks")

        atualizacao: dict[str, object] = {"chunks": chunks, "chunk_meta": metas}
        context = payload.context.model_copy(update=atualizacao)
        tabelas = sum(1 for m in metas if m.block_type is BlockType.TABLE)
        return StageOutcome(
            context=context,
            message=f"{len(chunks)} chunks via {estrategia}"
            + (f" ({tabelas} de tabela)" if tabelas else ""),
            metrics={"chunks": float(len(chunks)), "chunks_tabela": float(tabelas)},
        )


# canário anti-truncamento
