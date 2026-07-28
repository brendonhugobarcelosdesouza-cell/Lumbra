"""Golden set de RAG (E1-07, doc 14): qualidade de busca medida a cada commit.

Indexa o corpus fixo pelo MESMO caminho do produto (document.index →
pipeline com embeddings → document.find híbrido) e mede duas coisas:

* nível de DOCUMENTO (``queries``): recall@1/@3 e MRR — o doc certo aparece?
* nível de CHUNK (``answer_cases``, issue #10): sobre documentos densos com
  vários valores parecidos (fatura, relatório), o trecho com o VALOR certo
  é recuperado ACIMA dos valores concorrentes e chega ao contexto? É a prova
  numérica de que o chunking ciente de estrutura corrige o #10.

Regressão abaixo dos thresholds ou das garantias por caso QUEBRA o CI —
qualidade de busca vira contrato, não impressão.
"""

import json
import re
import shutil
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

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
from lumbra.adapters.persistence.models import ChunkModel
from lumbra.adapters.search.postgres import PostgresSearch
from lumbra.adapters.users.postgres import PostgresUserStore
from lumbra.context.providers import _diversify
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


def _texto_hit(hit: dict) -> str:
    """Texto do trecho recuperado, sem os marcadores ** do ts_headline."""
    return re.sub(r"\*\*", "", hit.get("snippet") or "")


def _diag_hits(caso: dict, hits: list[dict], textos: dict[str, str]) -> str:
    """Relatório do top-8 recuperado, para o log do CI quando um caso falha."""
    topo = "\n".join(
        f"      #{i} {h['uri'].rsplit('/', 1)[-1]}: "
        f"{textos.get(str(h['chunk_id']), _texto_hit(h))[:90]!r}"
        for i, h in enumerate(hits[:8], 1)
    )
    return f"    query={caso['query']!r} answer={caso['answer']!r}\n{topo}"


async def _indexar_corpus(kernel, user, tmp_path: Path) -> SkillContext:
    """Indexa o corpus pelo caminho do produto e devolve o contexto do usuário."""
    corpus_dir = tmp_path / "corpus"
    shutil.copytree(CORPUS, corpus_dir)
    ctx = SkillContext(subject=f"user:{user.id}", user_id=user.id)
    result = await kernel.skills.execute("document.index", {"path": str(corpus_dir)}, context=ctx)
    assert result.discovered == len(list(CORPUS.iterdir()))  # type: ignore[attr-defined]
    await kernel.bus.drain()  # type: ignore[attr-defined]
    return ctx


class TestRAGGoldenSet:
    async def test_golden_set_meets_thresholds(self, stack, tmp_path: Path):
        kernel, user = stack
        golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        ctx = await _indexar_corpus(kernel, user, tmp_path)

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

    async def test_answer_cases_recuperam_o_valor_certo(self, stack, tmp_path: Path, db):
        """Nível de chunk (issue #10): sobre documentos densos com vários
        valores parecidos, o trecho com o valor CERTO precisa ser recuperado
        acima dos concorrentes e sobreviver à montagem do contexto.

        As garantias por caso são o contrato — não um threshold ajustável:
        (1) o valor certo é recuperado; (2) NÃO fica abaixo de um valor
        concorrente (o bug do #10); (3) chega ao contexto que o modelo veria
        (após o mesmo _diversify do produto: 8 vagas, teto 3 por documento).

        O casamento usa o TEXTO REAL do chunk (não o snippet do ts_headline),
        para separar 'chunk não recuperado' de 'snippet não mostrou o valor'.
        """
        kernel, user = stack
        golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        ctx = await _indexar_corpus(kernel, user, tmp_path)

        # mapa chunk_id -> texto indexado (a fonte de verdade do que foi recuperado)
        async with db.session() as session:
            textos = {
                str(cid): txt
                for cid, txt in (
                    await session.execute(select(ChunkModel.id, ChunkModel.text))
                ).all()
            }

        def _rank(hits: list[dict], valor: str) -> int | None:
            for i, hit in enumerate(hits, 1):
                if valor in textos.get(str(hit["chunk_id"]), _texto_hit(hit)):
                    return i
            return None

        linhas: list[str] = []
        problemas: list[str] = []
        ranks: list[int | None] = []
        for caso in golden["answer_cases"]:
            found = await kernel.skills.execute(
                "document.find", {"query": caso["query"], "limit": 20}, context=ctx
            )
            hits = list(found.hits)  # type: ignore[attr-defined]
            rank_ok = _rank(hits, caso["answer"])
            ranks.append(rank_ok)
            linhas.append(f"  rank={rank_ok} {caso['query']!r} -> {caso['answer']}")

            # (1) o valor certo foi recuperado
            if rank_ok is None:
                problemas.append(
                    f"[não recuperado] {caso['answer']}\n{_diag_hits(caso, hits, textos)}"
                )
                continue
            # (2) o bug do #10: o valor certo não pode ficar ABAIXO de um concorrente
            for distrator in caso["distractors"]:
                rank_dist = _rank(hits, distrator)
                if rank_dist is not None and rank_ok > rank_dist:
                    problemas.append(
                        f"[#10 ordem] {distrator} (rank {rank_dist}) acima de "
                        f"{caso['answer']} (rank {rank_ok})\n{_diag_hits(caso, hits, textos)}"
                    )
            # (3) o valor certo chega ao contexto (mesma diversificação do produto)
            contexto = _diversify(hits, limite=8, por_documento=3)
            if not any(caso["answer"] in textos.get(str(h["chunk_id"]), "") for h in contexto):
                problemas.append(
                    f"[fora do contexto] {caso['answer']}\n{_diag_hits(caso, hits, textos)}"
                )

        total = len(ranks)
        recall_at_1 = sum(1 for r in ranks if r == 1) / total
        recall_at_3 = sum(1 for r in ranks if r is not None and r <= 3) / total
        mrr = sum(1.0 / r for r in ranks if r is not None) / total
        assert not problemas, "casos de resposta falharam:\n" + "\n".join(problemas)
        print(  # noqa: T201 — relatório do CI
            f"\nRAG answer cases (#10): recall@1={recall_at_1:.2f} "
            f"recall@3={recall_at_3:.2f} mrr={mrr:.3f} (n={total})\n" + "\n".join(linhas)
        )


# canário anti-truncamento
