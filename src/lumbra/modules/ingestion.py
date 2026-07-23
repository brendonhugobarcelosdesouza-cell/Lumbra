"""IngestionModule — o pipeline de ingestão como módulo do kernel.

Registra os eventos ``indexing.*``, o consumidor que processa documentos
via Event Bus e as skills do domínio ``document``:

* ``document.index``  — conecta uma pasta e enfileira itens novos/alterados
* ``document.find``   — busca híbrida (léxica + vetorial, fusão RRF) com
  explicação componente a componente; degrada para léxica sem IA disponível
* ``document.status`` — estado, timeline e versões de um documento
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any
from uuid import UUID

from lumbra.adapters.sources.filesystem import FilesystemSource
from lumbra.domain.events import EventPayload, EventRegistry
from lumbra.kernel.kernel import LumbraKernel, LumbraModule, ModuleManifest
from lumbra.pipeline.runner import PipelineRunner
from lumbra.ports.ai import AIGatewayPort, EmbedRequest, NoEligibleProviderError, PrivacyMode
from lumbra.ports.document_store import DocumentStorePort, IngestOutcome
from lumbra.ports.event_bus import ConsumerSpec
from lumbra.ports.explain import Explanation
from lumbra.ports.pipeline import ProcessingStorePort
from lumbra.ports.search import SearchPort
from lumbra.ports.skills import Skill, SkillContext, SkillInput, SkillManifest, SkillOutput
from lumbra.shared.logging import get_logger

_log = get_logger("lumbra.ingestion")


class FileDetected(EventPayload):
    document_id: str
    uri: str
    root: str  # raiz da fonte, para releitura do conteúdo


class DocumentIndexed(EventPayload):
    document_id: str
    chunks: int


class IndexingFailed(EventPayload):
    document_id: str
    stage_error: str


def register_indexing_events(registry: EventRegistry) -> None:
    for event_type, payload_cls in (
        ("indexing.file_detected", FileDetected),
        ("indexing.document_indexed", DocumentIndexed),
        ("indexing.failed", IndexingFailed),
    ):
        if (event_type, 1) not in registry.known_types():
            registry.event(event_type)(payload_cls)


# ------------------------------------------------------------------ skills I/O


class IndexFolderInput(SkillInput):
    path: str
    # reprocessa mesmo arquivos de conteúdo inalterado. Necessário quando
    # a MÁQUINA muda (novo extrator, novo chunker, novo modelo de
    # embedding): o arquivo é o mesmo, mas o que extraímos dele não é.
    force: bool = False


class IngestFileInput(SkillInput):
    """Ingestão de UM arquivo já armazenado (usado por anexos do chat e,
    futuramente, por conectores que entregam um blob por vez)."""

    uri: str
    mime_type: str | None = None
    title: str | None = None
    source: str = "upload"
    wait: bool = True  # processa agora (síncrono) em vez de enfileirar


class IngestFileOutput(SkillOutput):
    document_id: str
    outcome: str
    state: str
    chunks: int
    detail: str | None = None


class IndexFolderOutput(SkillOutput):
    discovered: int
    queued: int
    unchanged: int
    new_versions: int


class FindInput(SkillInput):
    query: str
    limit: int = 10


class FindOutput(SkillOutput):
    hits: tuple[dict[str, Any], ...]
    mode: str  # hybrid | lexical


class StatusInput(SkillInput):
    document_id: str


class StatusOutput(SkillOutput):
    state: str
    version: int
    timeline: tuple[dict[str, Any], ...]
    versions: tuple[dict[str, Any], ...]


class IngestionModule(LumbraModule):
    def __init__(
        self,
        *,
        documents: DocumentStorePort,
        processing: ProcessingStorePort,
        runner: PipelineRunner,
        search: SearchPort,
        gateway: AIGatewayPort | None = None,
    ) -> None:
        self._documents = documents
        self._processing = processing
        self._runner = runner
        self._search = search
        self._gateway = gateway
        self._kernel: LumbraKernel | None = None

    @property
    def manifest(self) -> ModuleManifest:
        return ModuleManifest(
            name="ingestion",
            version="0.1.0",
            description="Pipeline de ingestão: fontes → estágios → índice",
        )

    async def setup(self, kernel: LumbraKernel) -> None:
        self._kernel = kernel
        register_indexing_events(kernel.events)
        kernel.bus.register(
            ConsumerSpec(
                name="ingestion-worker",
                patterns=("indexing.file_detected",),
                handler=self._on_file_detected,
            )
        )
        await kernel.skills.register(
            Skill(
                manifest=SkillManifest(
                    name="document.index",
                    description="Indexa uma pasta local (novos e alterados)",
                    provider="ingestion",
                    capabilities=("document", "indexing"),
                    required_scopes=("read:files",),
                ),
                input_model=IndexFolderInput,
                output_model=IndexFolderOutput,
                handler=self._index_folder,
            )
        )
        await kernel.skills.register(
            Skill(
                manifest=SkillManifest(
                    name="document.ingest_file",
                    description="Ingere um único arquivo já armazenado (blob/upload)",
                    provider="ingestion",
                    capabilities=("documents", "write"),
                ),
                input_model=IngestFileInput,
                output_model=IngestFileOutput,
                handler=self._ingest_file,
            )
        )
        await kernel.skills.register(
            Skill(
                manifest=SkillManifest(
                    name="document.find",
                    description="Busca documentos indexados com explicação do ranking",
                    provider="ingestion",
                    capabilities=("document", "search"),
                ),
                input_model=FindInput,
                output_model=FindOutput,
                handler=self._find,
            )
        )
        await kernel.skills.register(
            Skill(
                manifest=SkillManifest(
                    name="document.status",
                    description="Estado, timeline e histórico de versões de um documento",
                    provider="ingestion",
                    capabilities=("document", "observability"),
                ),
                input_model=StatusInput,
                output_model=StatusOutput,
                handler=self._status,
            )
        )

    # ------------------------------------------------------------ handlers

    async def _index_folder(self, payload: SkillInput, ctx: SkillContext) -> IndexFolderOutput:
        assert isinstance(payload, IndexFolderInput)  # noqa: S101
        assert self._kernel is not None  # noqa: S101
        if ctx.user_id is None:
            raise ValueError("document.index exige usuário autenticado")
        source = FilesystemSource(Path(payload.path))
        discovered = queued = unchanged = new_versions = 0
        async for item in source.scan():
            discovered += 1
            raw = await source.read(item.uri)
            digest = hashlib.sha256(raw).digest()
            document, outcome = await self._documents.register(
                user_id=ctx.user_id,
                source=source.kind,
                uri=item.uri,
                content_hash=digest,
                mime_type=item.mime_type,
                title=Path(item.uri).name,
            )
            if outcome is IngestOutcome.UNCHANGED and not payload.force:
                unchanged += 1
                continue
            if outcome is IngestOutcome.NEW_VERSION:
                new_versions += 1
            await self._processing.reset_context(document.id)  # reprocessa do zero
            queued += 1
            await self._kernel.publish(
                FileDetected(document_id=str(document.id), uri=item.uri, root=str(payload.path)),
                user_id=ctx.user_id,
                correlation_id=ctx.correlation_id,
            )
        return IndexFolderOutput(
            discovered=discovered, queued=queued, unchanged=unchanged, new_versions=new_versions
        )

    async def _ingest_file(self, payload: SkillInput, ctx: SkillContext) -> IngestFileOutput:
        assert isinstance(payload, IngestFileInput)  # noqa: S101
        assert self._kernel is not None  # noqa: S101
        if ctx.user_id is None:
            raise ValueError("document.ingest_file exige usuário autenticado")
        raw = await self._read_uri(payload.uri)
        digest = hashlib.sha256(raw).digest()
        document, outcome = await self._documents.register(
            user_id=ctx.user_id,
            source=payload.source,
            uri=payload.uri,
            content_hash=digest,
            mime_type=payload.mime_type,
            title=payload.title or Path(payload.uri).name,
        )
        if outcome is IngestOutcome.UNCHANGED:
            # já processado antes: reaproveita o trabalho, não repete
            chunks = await self._documents.chunks_of(document.id)
            return IngestFileOutput(
                document_id=str(document.id),
                outcome=outcome.value,
                state=document.processing_state,
                chunks=len(chunks),
            )
        await self._processing.reset_context(document.id)
        if not payload.wait:
            await self._kernel.publish(
                FileDetected(document_id=str(document.id), uri=payload.uri, root="upload"),
                user_id=ctx.user_id,
                correlation_id=ctx.correlation_id,
            )
            return IngestFileOutput(
                document_id=str(document.id),
                outcome=outcome.value,
                state="queued",
                chunks=0,
            )
        # síncrono: quem anexou um arquivo quer perguntar sobre ele AGORA
        if ctx.cancellation:
            ctx.cancellation.step("documento registrado")
        state = await self._runner.process(document)
        chunks = await self._documents.chunks_of(document.id)
        refreshed = await self._documents.get(document.id)
        return IngestFileOutput(
            document_id=str(document.id),
            outcome=outcome.value,
            state=state.value,
            chunks=len(chunks),
            detail=refreshed.metadata.get("last_error"),
        )

    async def _read_uri(self, uri: str) -> bytes:
        from urllib.parse import urlparse
        from urllib.request import url2pathname

        parsed = urlparse(uri)
        if parsed.scheme not in ("file", ""):
            raise ValueError(f"esquema não suportado para ingestão direta: {parsed.scheme}")
        return await asyncio.to_thread(Path(url2pathname(parsed.path)).read_bytes)

    async def _on_file_detected(self, event: Any) -> None:  # DomainEvent
        assert self._kernel is not None  # noqa: S101
        payload = self._kernel.events.decode(event)
        assert isinstance(payload, FileDetected)  # noqa: S101
        document = await self._documents.get(UUID(payload.document_id))
        state = await self._runner.process(document)
        if state.value == "indexed":
            chunks = await self._documents.chunks_of(document.id)
            await self._kernel.publish(
                DocumentIndexed(document_id=payload.document_id, chunks=len(chunks)),
                user_id=event.user_id,
                correlation_id=event.correlation_id,
                causation_id=event.event_id,
            )
        else:
            refreshed = await self._documents.get(document.id)
            await self._kernel.publish(
                IndexingFailed(
                    document_id=payload.document_id,
                    stage_error=refreshed.processing_state,
                ),
                user_id=event.user_id,
                correlation_id=event.correlation_id,
                causation_id=event.event_id,
            )

    async def _find(self, payload: SkillInput, ctx: SkillContext) -> FindOutput:
        assert isinstance(payload, FindInput)  # noqa: S101
        assert self._kernel is not None  # noqa: S101
        if ctx.user_id is None:
            raise ValueError("document.find exige usuário autenticado")
        query_vector, mode, reason = await self._embed_query(payload.query)
        hits = await self._search.hybrid(
            user_id=ctx.user_id,
            query=payload.query,
            query_vector=query_vector,
            limit=payload.limit,
        )
        self._kernel.explain.record(
            Explanation(
                component="search:document.find",
                decision=f"busca {mode} com {len(hits)} resultados",
                reason=reason,
                inputs_used={"limit": payload.limit, "query_len": len(payload.query)},
                alternatives=("lexical",) if mode == "hybrid" else ("hybrid",),
                algorithm="RRF k=60 sobre ts_rank + cosseno" if mode == "hybrid" else "ts_rank",
                correlation_id=ctx.correlation_id,
            )
        )
        return FindOutput(hits=tuple(h.model_dump(mode="json") for h in hits), mode=mode)

    async def _embed_query(self, query: str) -> tuple[tuple[float, ...] | None, str, str]:
        """Vetor da consulta via AI Gateway; sem gateway/provedor, léxica pura."""
        if self._gateway is None:
            return None, "lexical", "AI Gateway não configurado — fallback léxico"
        try:
            result = await self._gateway.embed(
                EmbedRequest(texts=(query,), purpose="query", privacy=PrivacyMode.LOCAL_ONLY)
            )
        except NoEligibleProviderError:
            return None, "lexical", "nenhum provedor elegível na política local_only"
        return result.vectors[0], "hybrid", "léxico + vetorial fundidos por RRF"

    async def _status(self, payload: SkillInput, _ctx: SkillContext) -> StatusOutput:
        assert isinstance(payload, StatusInput)  # noqa: S101
        document_id = UUID(payload.document_id)
        document = await self._documents.get(document_id)
        timeline = await self._processing.get_timeline(document_id)
        versions = await self._documents.versions(document_id)
        return StatusOutput(
            state=document.processing_state,
            version=document.version,
            timeline=tuple(t.model_dump(mode="json") for t in timeline),
            versions=tuple(v.model_dump(mode="json") for v in versions),
        )


# canário anti-truncamento
