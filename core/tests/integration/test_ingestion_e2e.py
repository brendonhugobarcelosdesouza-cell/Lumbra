"""E2E do pipeline: pasta real → skills document.* → PG → busca → grafo → timeline."""

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
from lumbra.adapters.search.postgres import PostgresLexicalSearch
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

_provider = FastEmbedProvider()  # modelo local em cache — compartilhado no módulo


def _gateway(explain=None):
    return AIGateway(embedding_providers=[_provider], metrics=InMemoryMetrics(), explain=explain)


CONTRATO = (
    "# Contrato de Prestação\n\nFirmado com ana@acme.com.br em 12/03/2026.\n\n"
    "Valor mensal de R$ 2.500,00. CPF do contratante: 529.982.247-25.\n"
)


@pytest.fixture()
async def stack(db, tmp_path: Path):
    """Kernel + módulo de ingestão completos sobre PG real e bus in-memory."""
    user = await PostgresUserStore(db).create(
        email=f"e2e-{uuid.uuid4().hex[:8]}@lumbra.app", password_hash="h"
    )
    documents = PostgresDocumentStore(db)
    processing = PostgresProcessingStore(db)
    graph = PostgresKnowledgeGraph(db)

    async def read_raw(document):
        from urllib.parse import urlparse
        from urllib.request import url2pathname

        return Path(url2pathname(urlparse(document.uri).path)).read_bytes()

    gateway = _gateway()
    runner = PipelineRunner(
        stages=[
            ExtractStage(),
            MetadataStage(MetadataEngine(default_extractors())),
            ChunkStage(default_chunker_registry()),
            IndexStage(documents),
            EmbeddingStage(gateway, documents),
            KnowledgeGraphStage(graph),
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
            search=PostgresLexicalSearch(db),
            gateway=gateway,
        )
    )
    await kernel.start()
    yield kernel, user, documents, processing, graph, tmp_path
    await kernel.stop()


def _ctx(user) -> SkillContext:
    return SkillContext(subject=f"user:{user.id}", user_id=user.id)


async def _drain(kernel):
    await kernel.bus.drain()  # type: ignore[attr-defined]


class TestEndToEnd:
    async def test_index_search_graph_timeline(self, stack):
        kernel, user, documents, _processing, graph, tmp = stack
        (tmp / "contrato.md").write_text(CONTRATO, encoding="utf-8")
        (tmp / "notas.txt").write_text("Reunião sobre o projeto Lumbra amanhã.", encoding="utf-8")

        result = await kernel.skills.execute(
            "document.index", {"path": str(tmp)}, context=_ctx(user)
        )
        assert result.discovered == 2  # type: ignore[attr-defined]
        assert result.queued == 2  # type: ignore[attr-defined]
        await _drain(kernel)

        docs = await documents.list_by_user(user.id)
        assert {d.processing_state for d in docs} == {"indexed"}

        # busca com explicação
        found = await kernel.skills.execute(
            "document.find", {"query": "contrato prestação"}, context=_ctx(user)
        )
        hits = found.hits  # type: ignore[attr-defined]
        assert hits and "contrato" in hits[0]["uri"]
        assert "ts_rank" in hits[0]["explanation"]

        # grafo: documento menciona entidades extraídas
        emails = await graph.find(user_id=user.id, kind="email")
        assert [e.name for e in emails] == ["ana@acme.com.br"]
        neighbors = await graph.neighbors(emails[0].id)
        assert any(rel == "mentions" for rel, _ in neighbors)

        # timeline completa por estágio (req. 8)
        contrato = next(d for d in docs if "contrato" in d.uri)
        status = await kernel.skills.execute(
            "document.status", {"document_id": str(contrato.id)}, context=_ctx(user)
        )
        stages = [t["stage"] for t in status.timeline]  # type: ignore[attr-defined]
        assert stages == ["extract", "metadata", "chunk", "index", "embedding", "kg"]
        assert all(t["success"] for t in status.timeline)  # type: ignore[attr-defined]

    async def test_reindex_creates_version_and_unchanged_skips(self, stack):
        kernel, user, documents, _processing, _graph, tmp = stack
        target = tmp / "doc.md"
        target.write_text("# V1\nconteúdo original", encoding="utf-8")

        await kernel.skills.execute("document.index", {"path": str(tmp)}, context=_ctx(user))
        await _drain(kernel)

        # sem mudanças → UNCHANGED, nada re-enfileirado
        second = await kernel.skills.execute(
            "document.index", {"path": str(tmp)}, context=_ctx(user)
        )
        assert second.unchanged == 1  # type: ignore[attr-defined]
        assert second.queued == 0  # type: ignore[attr-defined]

        # conteúdo muda → nova versão com parent e motivo
        target.write_text("# V2\nconteúdo alterado", encoding="utf-8")
        third = await kernel.skills.execute(
            "document.index", {"path": str(tmp)}, context=_ctx(user)
        )
        assert third.new_versions == 1  # type: ignore[attr-defined]
        await _drain(kernel)

        doc = (await documents.list_by_user(user.id))[0]
        assert doc.version == 2
        history = await documents.versions(doc.id)
        assert history[0].parent_version == 1
        assert history[0].reason == "content_changed"
        chunks = await documents.chunks_of(doc.id)
        assert any("V2" in c or "alterado" in c for c in chunks)

    async def test_force_reprocessa_arquivo_inalterado(self, stack):
        """Quando a MÁQUINA muda (novo extrator/chunker/modelo), o arquivo
        é o mesmo mas precisa ser reprocessado. Sem ``force`` isso era
        impossível — o hash igual pulava o documento (issue #6 do
        dogfooding: reindexar não aplicava a extração corrigida)."""
        kernel, user, documents, _processing, _graph, tmp = stack
        (tmp / "doc.md").write_text("conteúdo estável", encoding="utf-8")

        await kernel.skills.execute("document.index", {"path": str(tmp)}, context=_ctx(user))
        await _drain(kernel)

        # sem force: conteúdo igual → pula
        normal = await kernel.skills.execute(
            "document.index", {"path": str(tmp)}, context=_ctx(user)
        )
        assert normal.unchanged == 1  # type: ignore[attr-defined]
        assert normal.queued == 0  # type: ignore[attr-defined]

        # com force: reprocessa mesmo sem mudança de conteúdo
        forcado = await kernel.skills.execute(
            "document.index", {"path": str(tmp), "force": True}, context=_ctx(user)
        )
        assert forcado.queued == 1  # type: ignore[attr-defined]
        assert forcado.unchanged == 0  # type: ignore[attr-defined]
        await _drain(kernel)

        # não cria versão nova: o conteúdo não mudou, só o processamento
        doc = (await documents.list_by_user(user.id))[0]
        assert doc.version == 1


class TestHybridSearch:
    async def test_semantic_query_finds_paraphrase_and_explains(self, stack):
        """'locação de imóvel' deve achar o doc de ALUGUEL sem casar termos —
        só o componente vetorial explica o acerto (léxica pura falharia)."""
        kernel, user, documents, processing, _graph, tmp = stack
        (tmp / "aluguel.md").write_text(
            "O aluguel do apartamento no centro custa R$ 1.800,00 por mês, "
            "com reajuste anual pelo IGP-M e caução de dois meses.",
            encoding="utf-8",
        )
        (tmp / "bolo.md").write_text(
            "Receita de bolo de cenoura: misture farinha, ovos e cenoura ralada. "
            "Asse por quarenta minutos e cubra com calda de chocolate.",
            encoding="utf-8",
        )
        await kernel.skills.execute("document.index", {"path": str(tmp)}, context=_ctx(user))
        await _drain(kernel)

        docs = await documents.list_by_user(user.id)
        aluguel = next(d for d in docs if "aluguel" in d.uri)

        # timeline registra o estágio embedding com métrica de vetores gravados
        timeline = await processing.get_timeline(aluguel.id)
        embed_entries = [t for t in timeline if t.stage == "embedding"]
        assert embed_entries and embed_entries[-1].success
        assert embed_entries[-1].metrics.get("embeddings", 0) >= 1

        found = await kernel.skills.execute(
            "document.find", {"query": "locação de imóvel"}, context=_ctx(user)
        )
        assert found.mode == "hybrid"  # type: ignore[attr-defined]
        hits = found.hits  # type: ignore[attr-defined]
        assert hits, "busca híbrida não retornou resultados"
        assert "aluguel" in hits[0]["uri"], f"top hit errado: {hits[0]['uri']}"
        assert "vetorial: #" in hits[0]["explanation"]
        assert "RRF" in hits[0]["explanation"]

        # Explain Engine registra a decisão de modo de busca
        explanations = kernel.explain.query(component="search:document.find")
        assert explanations and "hybrid" in explanations[-1].decision


class TestDeveloperConsoleEndToEnd:
    """Valida document.index e o pipeline COMPLETO através do Developer Console."""

    async def test_console_executes_document_index(self, db, tmp_path):
        import asyncio

        import httpx

        from lumbra.adapters.metrics.in_memory import InMemoryMetrics
        from lumbra.adapters.security.passwords import PasswordHasher
        from lumbra.adapters.security.tokens import TokenService
        from lumbra.adapters.users.postgres import PostgresUserStore
        from lumbra.api.app import create_app
        from lumbra.api.auth import AuthServices, make_require_subject
        from lumbra.api.dev import build_dev_router
        from lumbra.kernel.executions import ExecutionTracker
        from lumbra.ports.event_bus import ConsumerSpec
        from lumbra.shared.config import Settings

        # stack completa (mesmas peças do runtime)
        documents = PostgresDocumentStore(db)
        processing = PostgresProcessingStore(db)
        graph = PostgresKnowledgeGraph(db)
        search = PostgresLexicalSearch(db)

        async def read_raw(document):
            from pathlib import Path as LocalPath
            from urllib.parse import urlparse
            from urllib.request import url2pathname

            return LocalPath(url2pathname(urlparse(document.uri).path)).read_bytes()

        gateway = _gateway()
        runner = PipelineRunner(
            stages=[
                ExtractStage(),
                MetadataStage(MetadataEngine(default_extractors())),
                ChunkStage(default_chunker_registry()),
                IndexStage(documents),
                EmbeddingStage(gateway, documents),
                KnowledgeGraphStage(graph),
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
                search=search,
                gateway=gateway,
            )
        )
        settings = Settings(_env_file=None, environment="test")
        tracker = ExecutionTracker(kernel)
        kernel.bus.register(
            ConsumerSpec(name="devconsole-observer", patterns=("*",), handler=tracker.on_event)
        )
        auth = AuthServices(
            users=PostgresUserStore(db),
            passwords=PasswordHasher(),
            tokens=TokenService(settings.security),
        )
        dev_router = build_dev_router(
            kernel=kernel,
            tracker=tracker,
            documents=documents,
            processing=processing,
            search=search,
            metrics=InMemoryMetrics(),
            graph=graph,
            runner=runner,
            require_subject=make_require_subject(auth.tokens),
        )
        app = create_app(settings, kernel=kernel, auth=auth, dev_router=dev_router)

        (tmp_path / "nota.md").write_text(
            "# Nota\nPagar boleto de R$ 150,00 até 10/08/2026. Contato: x@y.com",
            encoding="utf-8",
        )

        transport = httpx.ASGITransport(app=app)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=transport, base_url="http://t") as client,
        ):
            # a página do console é pública; dados exigem token
            assert (await client.get("/api/v1/dev/console")).status_code == 200
            assert (await client.get("/api/v1/dev/skills")).status_code == 401

            await client.post(
                "/api/v1/auth/register",
                json={"email": "console@lumbra.app", "password": "senha-console-1"},
            )
            token = (
                await client.post(
                    "/api/v1/auth/token",
                    data={"username": "console@lumbra.app", "password": "senha-console-1"},
                )
            ).json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}

            # catálogo visível
            skills = (await client.get("/api/v1/dev/skills", headers=headers)).json()
            assert any(s["name"] == "document.index" for s in skills)

            # executa document.index PELO CONSOLE
            execution_id = (
                await client.post(
                    "/api/v1/dev/executions",
                    headers=headers,
                    json={
                        "kind": "skill",
                        "name": "document.index",
                        "payload": {"path": str(tmp_path)},
                    },
                )
            ).json()["execution_id"]

            for _ in range(50):
                detail = (
                    await client.get(f"/api/v1/dev/executions/{execution_id}", headers=headers)
                ).json()
                if detail["execution"]["status"] != "running":
                    break
                await asyncio.sleep(0.1)
            assert detail["execution"]["status"] == "completed"
            assert detail["execution"]["output"]["queued"] == 1
            await kernel.bus.drain()  # type: ignore[attr-defined]

            # pipeline concluiu; documento inspecionável pelo console
            docs = (await client.get("/api/v1/dev/documents", headers=headers)).json()
            assert docs and docs[0]["processing_state"] == "indexed"

            # busca HÍBRIDA com explicação pelo console (mesmo caminho do produto)
            result = (
                await client.get("/api/v1/dev/search", headers=headers, params={"q": "boleto"})
            ).json()
            assert result["mode"] == "hybrid"
            hits = result["hits"]
            assert hits and "ts_rank" in hits[0]["explanation"]
            assert "RRF" in hits[0]["explanation"]

            # eventos correlacionados + export
            export = (
                await client.get(f"/api/v1/dev/executions/{execution_id}/export", headers=headers)
            ).json()
            event_types = {e["type"] for e in export["events"]}
            assert "indexing.file_detected" in event_types
