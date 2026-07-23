"""Golden set de RAG (E1-07, doc 14): qualidade de busca medida a cada commit.

Indexa o corpus fixo pelo MESMO caminho do produto (document.index →
pipeline com embeddings → document.find híbrido) e mede recall@1,
recall@3 e MRR sobre consultas com resposta esperada. Regressão abaixo
dos thresholds do golden.json QUEBRA o CI — qualidade de busca vira
contrato, não impressão.
"""

import json
import shutil
import uuid
from pathlib import Path

import pytest

from lumbra.adapters.ai.fastembed_local import FastEmbedProvider
from lumbra.adapters.ai.gateway import AIGateway
from lumbra.adapters.chunking.basic import default_chunker_registry
from lumbra.adapters.documents.postgres import PostgresDocumentStore
from lumbra.adapters.documents.processing_pg import PostgresProcessingStore
from lumbra.adapters.eventbus.in_memory import InMemoryEventBus
from lumbra.adapters.eventstore.in_memory import InMemoryEventStore
from lumbra.adapters.knowledge.postgres import PostgresKnowledgeGraph
from lumbra.adapters.metadata.regex_extractors import default_extractors
from lumbra.adapters.metrics.in_memory import InMemoryMetrics
from lumbra.adapters.permissions.static import StaticPermissionAdapter
from lumbra.adapters.search.postgres import PostgresSearch
from lumbra.adapters.users.postgres import PostgresUserStore
from lumbra.domain.events import EventRegistry
from lumbra.kernel.kernel import LumbraKernel
from lumbra.modules.ingestion import IngestionModule
from lumbra.pipeline.metadata_engine import MetadataEngine
from lumbra.pipeline.runner import PipelineRunner, default_resolver
from lumbra.pipeline.stages.chunk import ChunkStage
from lumbra.pipeline.stages.embedding import EmbeddingStage
from lumbra.pipeline.stages.extract import ExtractStage
from lumbra.pipeline.stages.index import IndexStage
from lumbra.pipeline.stages.kg import KnowledgeGraphStage
from lumbra.pipeline.stages.metadata import MetadataStage
from lumbra.ports.skills import SkillContext

pytestmark = pytest.mark.integration

GOLDEN = Path(__file__).parent.parent / "rag" / "golden.json"
CORPUS = Path(__file__).parent.parent / "rag" / "corpus"


@pytest.fixture()
async def stack(db, tmp_path: Path):
    user = await PostgresUserStore(db).create(
        email=f"rag-{uuid.uuid4().hex[:8]}@lumbra.app", password_hash="h"
    )
    documents = PostgresDocumentStore(db)
    processing = PostgresProcessingStore(db)
    gateway = AIGateway(
        embedding_providers=[FastEmbedProvider()], metrics=InMemoryMetrics(), explain=None
    )

    async def read_raw(document):
        from urllib.parse import urlparse
        from urllib.request import url2pathname

        return Path(url2pathname(urlparse(document.uri).path)).read_bytes()

    runner = PipelineRunner(
        stages=[
            ExtractStage(),
            MetadataStage(MetadataEngine(default_extractors())),
            ChunkStage(default_chunker_registry()),
            IndexStage(documents),
            EmbeddingStage(gateway, documents),
            KnowledgeGraphStage(PostgresKnowledgeGraph(db)),
        ],
        resolver=default_resolver(),
        processing=processing,
        metrics=InMemoryMetrics(),
        read_raw=read_raw,
    )
    kernel = LumbraKernel(
        events=EventRegistry(),
        bus=InMemoryEventBus(),
        event_store=InMemoryEventStore(),
        permissions=StaticPermissionAdapter(default_allow=True),
    )
    kernel.register_module(
        IngestionModule(
            documents=documents,
            processing=processing,
            runner=runner,
            search=PostgresSearch(db),
            gateway=gateway,
        )
    )
    await kernel.start()
    yield kernel, user
    await kernel.stop()


def _doc_rank(hits: tuple[dict, ...], expected: str) -> int | None:
    """Posição (1-based) do documento esperado entre DOCUMENTOS únicos."""
    seen: list[str] = []
    for hit in hits:
        name = hit["uri"].rsplit("/", 1)[-1]
        if name not in seen:
            seen.append(name)
        if name == expected:
            return seen.index(name) + 1
    return None


class TestRAGGoldenSet:
    async def test_golden_set_meets_thresholds(self, stack, tmp_path: Path):
        kernel, user = stack
        golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        corpus_dir = tmp_path / "corpus"
        shutil.copytree(CORPUS, corpus_dir)
        ctx = SkillContext(subject=f"user:{user.id}", user_id=user.id)

        result = await kernel.skills.execute(
            "document.index", {"path": str(corpus_dir)}, context=ctx
        )
        assert result.discovered == len(list(CORPUS.iterdir()))  # type: ignore[attr-defined]
        await kernel.bus.drain()  # type: ignore[attr-defined]

        rows: list[tuple[str, str, str, int | None]] = []
        for item in golden["queries"]:
            found = await kernel.skills.execute(
                "document.find", {"query": item["query"], "limit": 10}, context=ctx
            )
            assert found.mode == "hybrid"  # type: ignore[attr-defined]
            rank = _doc_rank(found.hits, item["expected"])  # type: ignore[attr-defined]
            rows.append((item["kind"], item["query"], item["expected"], rank))

        total = len(rows)
        recall_at_1 = sum(1 for *_, r in rows if r == 1) / total
        recall_at_3 = sum(1 for *_, r in rows if r is not None and r <= 3) / total
        mrr = sum(1.0 / r for *_, r in rows if r is not None) / total

        report = "\n".join(
            f"  [{kind:8s}] rank={rank if rank else 'MISS'}: {query!r} -> {expected}"
            for kind, query, expected, rank in rows
        )
        summary = f"recall@1={recall_at_1:.2f} recall@3={recall_at_3:.2f} mrr={mrr:.3f} (n={total})"
        print(f"\nRAG golden set: {summary}\n{report}")  # noqa: T201 — relatório do CI

        thresholds = golden["thresholds"]
        assert recall_at_1 >= thresholds["recall_at_1"], f"recall@1 regrediu: {summary}\n{report}"
        assert recall_at_3 >= thresholds["recall_at_3"], f"recall@3 regrediu: {summary}\n{report}"
        assert mrr >= thresholds["mrr"], f"MRR regrediu: {summary}\n{report}"


# canário anti-truncamento
