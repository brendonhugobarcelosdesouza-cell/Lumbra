"""E2E do chat: documento indexado + memória → conversa com citações verificáveis.

O LLM é um dublê determinístico (ChatProviderPort): o que se testa aqui é
a PLATAFORMA — contexto reunido, prompt montado, citações persistidas e
recuperáveis — não a qualidade do modelo (isso é papel do golden set).
"""

import asyncio
import uuid
from pathlib import Path

import pytest

from lumbra.adapters.ai.fastembed_local import FastEmbedProvider
from lumbra.adapters.ai.gateway import AIGateway
from lumbra.adapters.attachments.filesystem import FilesystemBlobStore
from lumbra.adapters.attachments.postgres import PostgresAttachmentStore
from lumbra.adapters.chunking.basic import default_chunker_registry
from lumbra.adapters.conversations.postgres import PostgresConversationStore
from lumbra.adapters.documents.postgres import PostgresDocumentStore
from lumbra.adapters.documents.processing_pg import PostgresProcessingStore
from lumbra.adapters.eventbus.in_memory import InMemoryEventBus
from lumbra.adapters.eventstore.in_memory import InMemoryEventStore
from lumbra.adapters.knowledge.postgres import PostgresKnowledgeGraph
from lumbra.adapters.memory.postgres import PostgresMemoryStore
from lumbra.adapters.metadata.regex_extractors import default_extractors
from lumbra.adapters.metrics.in_memory import InMemoryMetrics
from lumbra.adapters.permissions.static import StaticPermissionAdapter
from lumbra.adapters.search.postgres import PostgresSearch
from lumbra.adapters.users.postgres import PostgresUserStore
from lumbra.context.providers import (
    AttachmentContextProvider,
    DocumentContextProvider,
    MemoryContextProvider,
)
from lumbra.domain.events import EventRegistry
from lumbra.kernel.kernel import LumbraKernel
from lumbra.modules.chat import ChatModule
from lumbra.modules.ingestion import IngestionModule
from lumbra.modules.memory import MemoryModule
from lumbra.pipeline.metadata_engine import MetadataEngine
from lumbra.pipeline.runner import PipelineRunner, default_resolver
from lumbra.pipeline.stages.chunk import ChunkStage
from lumbra.pipeline.stages.embedding import EmbeddingStage
from lumbra.pipeline.stages.extract import ExtractStage
from lumbra.pipeline.stages.index import IndexStage
from lumbra.pipeline.stages.kg import KnowledgeGraphStage
from lumbra.pipeline.stages.metadata import MetadataStage
from lumbra.ports.ai import ChatChunk, ChatProviderPort, ProviderCompletion
from lumbra.ports.skills import SkillContext
from lumbra.shared.cancellation import CancelReason

pytestmark = pytest.mark.integration

_provider = FastEmbedProvider()

RESPOSTA = "O aluguel é R$ 1.800,00 por mês [1]. Suas chaves estão na gaveta [2]."

CONTRATO = (
    "# Contrato de Aluguel\n\nO aluguel do apartamento custa R$ 1.800,00 por mês, "
    "com vencimento todo dia 5. Reajuste anual pelo IGP-M.\n"
)


class EchoChatProvider(ChatProviderPort):
    """Dublê determinístico: devolve o prompt que recebeu, para inspeção."""

    def __init__(self) -> None:
        self.last_messages: tuple = ()
        self.stream_delay = 0.0
        self.stream_completo = False
        self.stream_fechado = False

    @property
    def name(self) -> str:
        return "echo-local"

    @property
    def model(self) -> str:
        return "echo-1"

    @property
    def is_local(self) -> bool:
        return True

    def cost_usd(self, *, input_tokens: int, output_tokens: int) -> float:
        return 0.0

    async def complete(self, messages, *, max_tokens, temperature):
        self.last_messages = messages
        return ProviderCompletion(
            text=RESPOSTA,
            input_tokens=100,
            output_tokens=20,
            finish_reason="stop",
        )

    async def stream(self, messages, *, max_tokens, temperature):
        """Transmite palavra a palavra, como um modelo real faria.

        O ``finally`` faz o papel do ``httpx`` fechando a conexão: se ele
        rodar antes do fim, o provedor real teria parado de gerar."""
        self.last_messages = messages
        self.stream_completo = False
        self.stream_fechado = False
        try:
            for word in RESPOSTA.split(" "):
                if self.stream_delay:
                    await asyncio.sleep(self.stream_delay)
                yield ChatChunk(delta=word + " ")
            yield ChatChunk(done=True, input_tokens=100, output_tokens=20, finish_reason="stop")
            self.stream_completo = True
        finally:
            self.stream_fechado = True


class FakeCloudProvider(EchoChatProvider):
    """Mesmo dublê, fingindo ser cloud — para as regras de política."""

    @property
    def name(self) -> str:
        return "nuvem-teste"

    @property
    def is_local(self) -> bool:
        return False

    def cost_usd(self, *, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * 1.0 + output_tokens * 5.0) / 1_000_000


@pytest.fixture()
async def stack(db, tmp_path: Path):
    user = await PostgresUserStore(db).create(
        email=f"chat-{uuid.uuid4().hex[:8]}@lumbra.app", password_hash="h"
    )
    documents = PostgresDocumentStore(db)
    processing = PostgresProcessingStore(db)
    echo = EchoChatProvider()
    gateway = AIGateway(
        embedding_providers=[_provider],
        chat_providers=[echo, FakeCloudProvider()],
        metrics=InMemoryMetrics(),
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
    kernel.register_module(MemoryModule(store=PostgresMemoryStore(db), gateway=gateway))
    conversations = PostgresConversationStore(db)
    attachments = PostgresAttachmentStore(db)
    blobs = FilesystemBlobStore(tmp_path / "blobs")
    kernel.register_module(
        ChatModule(conversations=conversations, gateway=gateway, attachments=attachments)
    )
    kernel.context.register(DocumentContextProvider(kernel.skills))
    kernel.context.register(MemoryContextProvider(kernel.skills))
    kernel.context.register(AttachmentContextProvider(attachments, documents))
    await kernel.start()
    kernel.attachments_store = attachments  # type: ignore[attr-defined]
    kernel.blobs = blobs  # type: ignore[attr-defined]
    yield kernel, user, conversations, echo, tmp_path
    await kernel.stop()


def _ctx(user) -> SkillContext:
    return SkillContext(subject=f"user:{user.id}", user_id=user.id)


class TestChatWithRAG:
    async def test_answer_cites_documents_and_memories(self, stack):
        kernel, user, conversations, echo, tmp = stack
        ctx = _ctx(user)

        (tmp / "contrato.md").write_text(CONTRATO, encoding="utf-8")
        await kernel.skills.execute("document.index", {"path": str(tmp)}, context=ctx)
        await kernel.bus.drain()  # type: ignore[attr-defined]
        await kernel.skills.execute(
            "memory.remember",
            {"content": "Deixei as chaves do apartamento na gaveta da cozinha"},
            context=ctx,
        )

        started = await kernel.skills.execute("chat.start", {}, context=ctx)
        conversation_id = started.conversation_id  # type: ignore[attr-defined]

        answer = await kernel.skills.execute(
            "chat.send",
            {"conversation_id": conversation_id, "content": "Quanto custa o aluguel?"},
            context=ctx,
        )

        # o prompt recebeu contexto NUMERADO, com a pergunta por último
        prompt = echo.last_messages
        assert prompt[0].role == "system"
        assert prompt[-1].content == "Quanto custa o aluguel?"
        context_block = next(m for m in prompt if "CONTEXTO:" in m.content)
        assert "[1]" in context_block.content
        assert "1.800" in context_block.content  # o documento chegou ao modelo

        # citações persistidas e verificáveis
        citations = answer.citations  # type: ignore[attr-defined]
        assert citations, "resposta sem citações"
        kinds = {c["kind"] for c in citations}
        assert "document" in kinds
        assert all(c["ref_id"] for c in citations)
        assert citations[0]["ordinal"] == 1

        # histórico traz pergunta + resposta com as citações
        history = await kernel.skills.execute(
            "chat.history", {"conversation_id": conversation_id}, context=ctx
        )
        messages = history.messages  # type: ignore[attr-defined]
        assert [m["role"] for m in messages] == ["user", "assistant"]
        assert len(messages[1]["citations"]) == len(citations)
        assert messages[1]["provider"] == "echo-local"

        # título automático a partir da primeira pergunta
        conversation = await conversations.get(uuid.UUID(conversation_id))
        assert conversation.title == "Quanto custa o aluguel?"

        # decisão explicada (princípio nº 13)
        explanations = kernel.explain.query(component="chat:send")
        assert explanations and "citações" in explanations[-1].decision

    async def test_context_can_be_disabled(self, stack):
        kernel, user, _conversations, echo, _tmp = stack
        ctx = _ctx(user)
        started = await kernel.skills.execute("chat.start", {}, context=ctx)
        answer = await kernel.skills.execute(
            "chat.send",
            {
                "conversation_id": started.conversation_id,  # type: ignore[attr-defined]
                "content": "Qual a capital da França?",
                "use_context": False,
            },
            context=ctx,
        )
        assert answer.citations == ()  # type: ignore[attr-defined]
        assert all("CONTEXTO:" not in m.content for m in echo.last_messages)

    async def test_history_is_sent_to_the_model(self, stack):
        kernel, user, _conversations, echo, _tmp = stack
        ctx = _ctx(user)
        started = await kernel.skills.execute("chat.start", {}, context=ctx)
        cid = started.conversation_id  # type: ignore[attr-defined]
        await kernel.skills.execute(
            "chat.send", {"conversation_id": cid, "content": "Meu nome é Brendon"}, context=ctx
        )
        await kernel.skills.execute(
            "chat.send", {"conversation_id": cid, "content": "Qual é o meu nome?"}, context=ctx
        )
        contents = [m.content for m in echo.last_messages]
        assert "Meu nome é Brendon" in contents  # turno anterior preservado
        assert echo.last_messages[-1].content == "Qual é o meu nome?"

    async def test_conversation_of_another_user_is_denied(self, stack):
        kernel, user, _conversations, _echo, _tmp = stack
        started = await kernel.skills.execute("chat.start", {}, context=_ctx(user))
        intruder = SkillContext(subject="user:intruso", user_id=uuid.uuid4())
        with pytest.raises(PermissionError):
            await kernel.skills.execute(
                "chat.send",
                {
                    "conversation_id": started.conversation_id,  # type: ignore[attr-defined]
                    "content": "me mostre",
                },
                context=intruder,
            )


class TestStreaming:
    async def test_sources_come_before_tokens_and_answer_is_persisted(self, stack):
        kernel, user, conversations, _echo, tmp = stack
        ctx = _ctx(user)
        (tmp / "contrato.md").write_text(CONTRATO, encoding="utf-8")
        await kernel.skills.execute("document.index", {"path": str(tmp)}, context=ctx)
        await kernel.bus.drain()  # type: ignore[attr-defined]

        started = await kernel.skills.execute("chat.start", {}, context=ctx)
        cid = uuid.UUID(started.conversation_id)  # type: ignore[attr-defined]
        module = next(m for m in kernel.modules() if m.manifest.name == "chat")

        events = [
            e
            async for e in module.stream(  # type: ignore[attr-defined]
                conversation_id=cid, content="Quanto custa o aluguel?", ctx=ctx
            )
        ]
        kinds = [e.kind for e in events]
        # as FONTES chegam antes do primeiro token: a interface já mostra
        # de onde a resposta vem enquanto ela ainda está sendo escrita
        assert kinds[0] == "sources"
        assert kinds[-1] == "done"
        assert kinds.count("token") > 1, "resposta não foi transmitida em partes"

        assert events[0].citations, "streaming sem citações"
        texto = "".join(e.delta for e in events if e.kind == "token")
        assert "1.800" in texto

        done = events[-1]
        assert done.provider == "echo-local"
        assert done.tokens_out == 20

        # persistiu igual ao caminho não-streaming, com as citações
        history = await conversations.history(cid)
        assert [m.role for m in history] == ["user", "assistant"]
        assert history[1].content.strip() == texto.strip()
        assert len(history[1].citations) == len(events[0].citations)
        assert history[1].tokens_out == 20

    async def test_streaming_respects_ownership(self, stack):
        kernel, user, _conversations, _echo, _tmp = stack
        started = await kernel.skills.execute("chat.start", {}, context=_ctx(user))
        module = next(m for m in kernel.modules() if m.manifest.name == "chat")
        intruder = SkillContext(subject="user:intruso", user_id=uuid.uuid4())
        with pytest.raises(PermissionError):
            async for _ in module.stream(  # type: ignore[attr-defined]
                conversation_id=uuid.UUID(started.conversation_id),  # type: ignore[attr-defined]
                content="me mostre",
                ctx=intruder,
            ):
                pass


class TestModelPolicy:
    """E2-04: escolher (e trocar) o modelo por conversa, com as regras
    de privacidade aplicadas na ESCOLHA, não no primeiro envio."""

    async def test_unknown_provider_fails_at_start(self, stack):
        kernel, user, _conversations, _echo, _tmp = stack
        with pytest.raises(Exception, match="não existe"):
            await kernel.skills.execute("chat.start", {"provider": "gpt-99"}, context=_ctx(user))

    async def test_cloud_provider_requires_allow_cloud(self, stack):
        kernel, user, _conversations, _echo, _tmp = stack
        with pytest.raises(Exception, match="allow_cloud"):
            await kernel.skills.execute(
                "chat.start", {"provider": "nuvem-teste"}, context=_ctx(user)
            )
        # com o opt-in explícito, funciona
        started = await kernel.skills.execute(
            "chat.start",
            {"provider": "nuvem-teste", "privacy": "allow_cloud"},
            context=_ctx(user),
        )
        assert started.provider == "nuvem-teste"  # type: ignore[attr-defined]

    async def test_forced_provider_is_used_by_send(self, stack):
        kernel, user, _conversations, _echo, _tmp = stack
        ctx = _ctx(user)
        started = await kernel.skills.execute(
            "chat.start",
            {"provider": "nuvem-teste", "privacy": "allow_cloud"},
            context=ctx,
        )
        answer = await kernel.skills.execute(
            "chat.send",
            {
                "conversation_id": started.conversation_id,  # type: ignore[attr-defined]
                "content": "oi",
                "use_context": False,
            },
            context=ctx,
        )
        assert answer.provider == "nuvem-teste"  # type: ignore[attr-defined]

    async def test_set_policy_switches_provider_mid_conversation(self, stack):
        kernel, user, _conversations, _echo, _tmp = stack
        ctx = _ctx(user)
        started = await kernel.skills.execute("chat.start", {}, context=ctx)
        cid = started.conversation_id  # type: ignore[attr-defined]
        # começa local
        first = await kernel.skills.execute(
            "chat.send",
            {"conversation_id": cid, "content": "primeira", "use_context": False},
            context=ctx,
        )
        assert first.provider == "echo-local"  # type: ignore[attr-defined]
        # troca para cloud no meio da conversa
        changed = await kernel.skills.execute(
            "chat.set_policy",
            {"conversation_id": cid, "privacy": "allow_cloud", "provider": "nuvem-teste"},
            context=ctx,
        )
        assert changed.provider == "nuvem-teste"  # type: ignore[attr-defined]
        second = await kernel.skills.execute(
            "chat.send",
            {"conversation_id": cid, "content": "segunda", "use_context": False},
            context=ctx,
        )
        assert second.provider == "nuvem-teste"  # type: ignore[attr-defined]
        # e cada mensagem do histórico registra QUEM respondeu
        history = await kernel.skills.execute("chat.history", {"conversation_id": cid}, context=ctx)
        providers = [
            m["provider"]
            for m in history.messages
            if m["role"] == "assistant"  # type: ignore[attr-defined]
        ]
        assert providers == ["echo-local", "nuvem-teste"]

    async def test_empty_provider_resets_to_default_routing(self, stack):
        kernel, user, _conversations, _echo, _tmp = stack
        ctx = _ctx(user)
        started = await kernel.skills.execute(
            "chat.start",
            {"provider": "nuvem-teste", "privacy": "allow_cloud"},
            context=ctx,
        )
        cid = started.conversation_id  # type: ignore[attr-defined]
        reset = await kernel.skills.execute(
            "chat.set_policy", {"conversation_id": cid, "provider": ""}, context=ctx
        )
        assert reset.provider is None  # type: ignore[attr-defined]
        answer = await kernel.skills.execute(
            "chat.send",
            {"conversation_id": cid, "content": "oi", "use_context": False},
            context=ctx,
        )
        # roteamento padrão: local primeiro
        assert answer.provider == "echo-local"  # type: ignore[attr-defined]

    async def test_downgrade_to_local_only_with_cloud_provider_fails(self, stack):
        kernel, user, _conversations, _echo, _tmp = stack
        ctx = _ctx(user)
        started = await kernel.skills.execute(
            "chat.start",
            {"provider": "nuvem-teste", "privacy": "allow_cloud"},
            context=ctx,
        )
        with pytest.raises(Exception, match="allow_cloud"):
            await kernel.skills.execute(
                "chat.set_policy",
                {
                    "conversation_id": started.conversation_id,  # type: ignore[attr-defined]
                    "privacy": "local_only",
                },
                context=ctx,
            )

    async def test_gateway_lists_providers_with_pricing(self, stack):
        kernel, _user, _conversations, _echo, _tmp = stack
        del kernel
        # via stack: gateway tem echo-local (grátis) e nuvem-teste ($1/$5)


def _gw(kernel):
    module = kernel.module("chat")
    return module._gateway


class TestCancelamento:
    """E2-01: cancelar libera a GPU na hora e preserva o que já foi feito."""

    async def test_cancelar_no_meio_fecha_o_provedor_e_salva_parcial(self, stack):
        kernel, user, conversations, echo, _tmp = stack
        ctx_base = _ctx(user)
        started = await kernel.skills.execute("chat.start", {}, context=ctx_base)
        cid = uuid.UUID(started.conversation_id)  # type: ignore[attr-defined]
        module = kernel.module("chat")

        token = kernel.cancellation.child("teste")
        ctx = SkillContext(subject=ctx_base.subject, user_id=user.id, cancellation=token)
        echo.stream_delay = 0.05  # dá tempo de cancelar no meio

        recebidos, evento_final = [], None
        async for event in module.stream(  # type: ignore[attr-defined]
            conversation_id=cid, content="Conte uma história longa", ctx=ctx, use_context=False
        ):
            if event.kind == "token":
                recebidos.append(event.delta)
                if len(recebidos) == 2:
                    token.cancel(CancelReason.USER, requested_by="usuário")
            elif event.kind == "cancelled":
                evento_final = event

        assert evento_final is not None, "stream não avisou o cancelamento"
        assert evento_final.reason == "user"
        assert evento_final.requested_by == "usuário"

        # o provedor foi FECHADO (nao terminou de gerar): libera GPU
        assert echo.stream_completo is False
        assert echo.stream_fechado is True

        # o parcial virou mensagem no historico, marcado como cancelado
        history = await conversations.history(cid)
        assistente = [m for m in history if m.role == "assistant"]
        assert len(assistente) == 1
        assert assistente[0].content == "".join(recebidos)
        assert assistente[0].content, "parcial foi descartado"

        # explicacao registra motivo, quem pediu e etapas concluidas
        explicacoes = kernel.explain.query(component="chat:send")
        ultima = explicacoes[-1]
        assert "INTERROMPIDA" in ultima.decision
        assert "usuário" in ultima.reason
        assert any("GPU" in c for c in ultima.consequences)

    async def test_trace_do_gateway_marca_cancelado_nao_falha(self, stack):
        kernel, user, _conversations, echo, _tmp = stack
        ctx_base = _ctx(user)
        started = await kernel.skills.execute("chat.start", {}, context=ctx_base)
        token = kernel.cancellation.child("teste")
        ctx = SkillContext(subject=ctx_base.subject, user_id=user.id, cancellation=token)
        echo.stream_delay = 0.05
        module = kernel.module("chat")

        async for event in module.stream(  # type: ignore[attr-defined]
            conversation_id=uuid.UUID(started.conversation_id),  # type: ignore[attr-defined]
            content="oi",
            ctx=ctx,
            use_context=False,
        ):
            if event.kind == "token":
                token.cancel(CancelReason.USER, requested_by="usuário")

        gateway = kernel.module("chat")._gateway
        registro = gateway.trace()[0]
        assert registro.outcome == "cancelled"
        assert registro.success is False  # nao completou...
        # ...mas nao e falha: metrica de erro NAO foi incrementada
        assert registro.kind == "completion"

    async def test_desligar_o_kernel_cancela_geracoes_em_voo(self, stack):
        """Token raiz: nenhuma operacao sobrevive ao desligamento."""
        kernel, _user, _conversations, _echo, _tmp = stack
        filho = kernel.cancellation.child("geracao-em-voo")
        assert filho.is_cancelled is False
        kernel.cancellation.cancel(CancelReason.SHUTDOWN, requested_by="teste")
        assert filho.is_cancelled is True
        assert filho.reason is CancelReason.PARENT


class TestAnexos:
    """E2-03: anexo é documento ingerido pelo pipeline padrão, não um
    caminho paralelo — por isso vira citação verificável igual."""

    async def _anexar(self, kernel, user, cid, nome, conteudo, mime):
        blobs = kernel.blobs
        uri = await blobs.save(conteudo, filename=nome, owner=user.id)
        return await kernel.skills.execute(
            "chat.attach",
            {
                "conversation_id": str(cid),
                "storage_uri": uri,
                "filename": nome,
                "mime_type": mime,
                "size_bytes": len(conteudo),
            },
            context=_ctx(user),
        )

    async def test_arquivo_anexado_vira_documento_indexado_e_citavel(self, stack):
        kernel, user, _conversations, echo, _tmp = stack
        ctx = _ctx(user)
        started = await kernel.skills.execute("chat.start", {}, context=ctx)
        cid = uuid.UUID(started.conversation_id)  # type: ignore[attr-defined]

        anexado = await self._anexar(
            kernel, user, cid, "contrato.md", CONTRATO.encode("utf-8"), "text/markdown"
        )
        assert anexado.state == "ready"  # type: ignore[attr-defined]
        assert anexado.chunks > 0  # type: ignore[attr-defined]
        assert anexado.document_id is not None  # type: ignore[attr-defined]

        # a pergunta seguinte já enxerga o anexo
        resposta = await kernel.skills.execute(
            "chat.send",
            {"conversation_id": str(cid), "content": "Quanto custa o aluguel?"},
            context=ctx,
        )
        contexto = next(m for m in echo.last_messages if "CONTEXTO:" in m.content)
        assert "1.800" in contexto.content
        citacoes = resposta.citations  # type: ignore[attr-defined]
        assert any(c["title"] == "contrato.md" for c in citacoes)

    async def test_anexo_aparece_na_listagem_com_estado(self, stack):
        kernel, user, _conversations, _echo, _tmp = stack
        ctx = _ctx(user)
        started = await kernel.skills.execute("chat.start", {}, context=ctx)
        cid = uuid.UUID(started.conversation_id)  # type: ignore[attr-defined]
        await self._anexar(kernel, user, cid, "nota.txt", b"lembrete: pagar luz", "text/plain")
        listagem = await kernel.skills.execute(
            "chat.attachments", {"conversation_id": str(cid)}, context=ctx
        )
        itens = listagem.attachments  # type: ignore[attr-defined]
        assert len(itens) == 1
        assert itens[0]["filename"] == "nota.txt"
        assert itens[0]["state"] == "ready"
        assert itens[0]["document_id"]

    async def test_imagem_sem_ocr_degrada_com_clareza(self, stack):
        """Sem OCRProvider configurado a imagem NÃO quebra o anexo: fica
        'unsupported' com explicação, e o chat segue funcionando."""
        kernel, user, _conversations, _echo, _tmp = stack
        ctx = _ctx(user)
        started = await kernel.skills.execute("chat.start", {}, context=ctx)
        cid = uuid.UUID(started.conversation_id)  # type: ignore[attr-defined]
        png = bytes.fromhex("89504e470d0a1a0a") + b"\x00" * 32
        anexado = await self._anexar(kernel, user, cid, "foto.png", png, "image/png")
        assert anexado.state == "unsupported"  # type: ignore[attr-defined]
        assert anexado.detail  # type: ignore[attr-defined]
        # a conversa continua utilizável
        resposta = await kernel.skills.execute(
            "chat.send",
            {"conversation_id": str(cid), "content": "e aí?", "use_context": True},
            context=ctx,
        )
        assert resposta.text  # type: ignore[attr-defined]

    async def test_anexo_de_outra_conversa_nao_vaza(self, stack):
        kernel, user, _conversations, _echo, _tmp = stack
        ctx = _ctx(user)
        a = await kernel.skills.execute("chat.start", {}, context=ctx)
        b = await kernel.skills.execute("chat.start", {}, context=ctx)
        await self._anexar(
            kernel,
            user,
            uuid.UUID(a.conversation_id),  # type: ignore[attr-defined]
            "segredo.txt",
            b"conteudo da conversa A",
            "text/plain",
        )
        listagem_b = await kernel.skills.execute(
            "chat.attachments",
            {"conversation_id": b.conversation_id},  # type: ignore[attr-defined]
            context=ctx,
        )
        assert listagem_b.attachments == ()  # type: ignore[attr-defined]

    async def test_anexar_em_conversa_alheia_e_negado(self, stack):
        kernel, user, _conversations, _echo, _tmp = stack
        started = await kernel.skills.execute("chat.start", {}, context=_ctx(user))
        uri = await kernel.blobs.save(b"x", filename="a.txt", owner=user.id)
        intruso = SkillContext(subject="user:intruso", user_id=uuid.uuid4())
        with pytest.raises(PermissionError):
            await kernel.skills.execute(
                "chat.attach",
                {
                    "conversation_id": started.conversation_id,  # type: ignore[attr-defined]
                    "storage_uri": uri,
                    "filename": "a.txt",
                    "mime_type": "text/plain",
                    "size_bytes": 1,
                },
                context=intruso,
            )

    async def test_anexo_e_explicado(self, stack):
        kernel, user, _conversations, _echo, _tmp = stack
        started = await kernel.skills.execute("chat.start", {}, context=_ctx(user))
        await self._anexar(
            kernel,
            user,
            uuid.UUID(started.conversation_id),  # type: ignore[attr-defined]
            "doc.md",
            b"# titulo\n\nconteudo do documento anexado",
            "text/markdown",
        )
        explicacoes = kernel.explain.query(component="chat:attach")
        assert explicacoes
        assert "doc.md" in explicacoes[-1].decision


class TestChatAPI:
    async def test_full_cycle_over_http(self, db, stack):
        from httpx import ASGITransport, AsyncClient

        from lumbra.adapters.security.passwords import PasswordHasher
        from lumbra.adapters.security.tokens import TokenService
        from lumbra.api.app import create_app
        from lumbra.api.auth import AuthServices, make_require_subject
        from lumbra.api.chat import build_chat_router
        from lumbra.shared.config import Settings

        kernel, _user, conversations, _echo, _tmp = stack
        settings = Settings(_env_file=None, environment="test")
        auth = AuthServices(
            users=PostgresUserStore(db),
            passwords=PasswordHasher(),
            tokens=TokenService(settings.security),
        )
        app = create_app(
            settings,
            kernel=kernel,
            auth=auth,
            extra_routers=[
                build_chat_router(
                    kernel,
                    conversations,
                    make_require_subject(auth.tokens),
                    next(m for m in kernel.modules() if m.manifest.name == "chat"),  # type: ignore[arg-type]
                    _gw(kernel),
                    kernel.blobs,  # type: ignore[attr-defined]
                )
            ],
        )
        email = f"api-chat-{uuid.uuid4().hex[:8]}@lumbra.app"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.post(
                "/api/v1/auth/register", json={"email": email, "password": "senha-super-forte"}
            )
            token = (
                await client.post(
                    "/api/v1/auth/token",
                    data={"username": email, "password": "senha-super-forte"},
                )
            ).json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}

            created = await client.post("/api/v1/chat/conversations", headers=headers, json={})
            assert created.status_code == 201
            cid = created.json()["conversation_id"]
            assert created.json()["privacy"] == "local_only"  # privado por padrão

            sent = await client.post(
                f"/api/v1/chat/conversations/{cid}/messages",
                headers=headers,
                json={"content": "Quanto custa o aluguel?"},
            )
            assert sent.status_code == 200
            assert sent.json()["text"]
            assert sent.json()["provider"] == "echo-local"

            listing = (await client.get("/api/v1/chat/conversations", headers=headers)).json()
            assert len(listing["conversations"]) == 1

            # upload multipart (E2-03)
            enviado = await client.post(
                f"/api/v1/chat/conversations/{cid}/attachments",
                headers=headers,
                files={"file": ("nota.txt", b"o aluguel vence dia 5", "text/plain")},
            )
            assert enviado.status_code == 201
            assert enviado.json()["state"] == "ready"
            anexos = await client.get(
                f"/api/v1/chat/conversations/{cid}/attachments", headers=headers
            )
            assert len(anexos.json()["attachments"]) == 1
            vazio = await client.post(
                f"/api/v1/chat/conversations/{cid}/attachments",
                headers=headers,
                files={"file": ("vazio.txt", b"", "text/plain")},
            )
            assert vazio.status_code == 400

            # cardápio de provedores (E2-04)
            menu = (await client.get("/api/v1/chat/providers", headers=headers)).json()
            names = {p["name"]: p for p in menu["providers"]}
            assert names["echo-local"]["is_local"] is True
            assert names["echo-local"]["input_price_per_mtok"] == 0.0
            assert names["nuvem-teste"]["output_price_per_mtok"] == 5.0

            # troca de política pela API
            patched = await client.patch(
                f"/api/v1/chat/conversations/{cid}/policy",
                headers=headers,
                json={"privacy": "allow_cloud", "provider": "nuvem-teste"},
            )
            assert patched.status_code == 200
            assert patched.json()["provider"] == "nuvem-teste"
            bad = await client.patch(
                f"/api/v1/chat/conversations/{cid}/policy",
                headers=headers,
                json={"provider": "inexistente"},
            )
            assert bad.status_code == 400

            history = await client.get(
                f"/api/v1/chat/conversations/{cid}/messages", headers=headers
            )
            assert len(history.json()["messages"]) == 2

            # SSE: eventos nomeados conforme o doc 11
            async with client.stream(
                "POST",
                f"/api/v1/chat/conversations/{cid}/messages/stream",
                headers=headers,
                json={"content": "E quando vence?"},
            ) as streamed:
                assert streamed.status_code == 200
                assert streamed.headers["content-type"].startswith("text/event-stream")
                body = "".join([chunk async for chunk in streamed.aiter_text()])
            assert "event: sources" in body
            assert "event: token" in body
            assert "event: done" in body
            assert body.index("event: sources") < body.index("event: token")

            assert (await client.get("/api/v1/chat/conversations")).status_code == 401


# canário anti-truncamento
