"""Composição de runtime da API — ponto de entrada do uvicorn/Docker.

Monta o LumbraKernel com adaptadores selecionados por configuração:
``LUMBRA_EVENTBUS=memory|redis`` e ``LUMBRA_PERSISTENCE=memory|postgres``
selecionam os adaptadores. Perfil compose/cloud: redis + postgres, com
readiness checks reais; dev sem infraestrutura: tudo in-memory.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from redis.asyncio import Redis

from lumbra.adapters.ai.anthropic import AnthropicChatProvider
from lumbra.adapters.ai.fastembed_local import FastEmbedProvider
from lumbra.adapters.ai.gateway import AIGateway
from lumbra.adapters.ai.ollama import OllamaChatProvider
from lumbra.adapters.attachments.filesystem import FilesystemBlobStore
from lumbra.adapters.attachments.in_memory import InMemoryAttachmentStore
from lumbra.adapters.attachments.postgres import PostgresAttachmentStore
from lumbra.adapters.chunking.basic import default_chunker_registry
from lumbra.adapters.conversations.in_memory import InMemoryConversationStore
from lumbra.adapters.conversations.postgres import PostgresConversationStore
from lumbra.adapters.devices.in_memory import InMemoryDeviceStore
from lumbra.adapters.devices.postgres import PostgresDeviceStore
from lumbra.adapters.documents.postgres import PostgresDocumentStore
from lumbra.adapters.documents.processing_pg import PostgresProcessingStore
from lumbra.adapters.eventbus.in_memory import InMemoryEventBus
from lumbra.adapters.eventbus.redis_streams import RedisStreamsEventBus
from lumbra.adapters.eventstore.in_memory import InMemoryEventStore
from lumbra.adapters.eventstore.postgres import PostgresEventStore
from lumbra.adapters.knowledge.postgres import PostgresKnowledgeGraph
from lumbra.adapters.memory.in_memory import InMemoryMemoryStore
from lumbra.adapters.memory.postgres import PostgresMemoryStore
from lumbra.adapters.metadata.regex_extractors import default_extractors
from lumbra.adapters.metrics.in_memory import InMemoryMetrics
from lumbra.adapters.permissions.static import StaticPermissionAdapter
from lumbra.adapters.persistence.database import Database
from lumbra.adapters.search.postgres import PostgresSearch
from lumbra.adapters.security.passwords import PasswordHasher
from lumbra.adapters.security.tokens import TokenService
from lumbra.adapters.users.in_memory import InMemoryUserStore
from lumbra.adapters.users.postgres import PostgresUserStore
from lumbra.agents.documents import CAPABILITY as DOCUMENTS_SEARCH
from lumbra.agents.documents import DocumentsAgent
from lumbra.api.agents import build_agents_router
from lumbra.api.app import create_app
from lumbra.api.auth import AuthServices
from lumbra.api.chat import build_chat_router
from lumbra.api.devices import build_devices_router
from lumbra.api.memory import build_memory_router
from lumbra.api.system import build_system_router
from lumbra.context.providers import (
    AttachmentContextProvider,
    DocumentContextProvider,
    MemoryContextProvider,
)
from lumbra.domain.events import EventRegistry
from lumbra.kernel.core_module import KernelCoreModule
from lumbra.kernel.executions import ExecutionTracker
from lumbra.kernel.kernel import LumbraKernel
from lumbra.modules.ai import AIModule
from lumbra.modules.chat import ChatModule
from lumbra.modules.ingestion import IngestionModule
from lumbra.modules.memory import MemoryModule
from lumbra.modules.reflection import ReflectionModule
from lumbra.pipeline.metadata_engine import MetadataEngine
from lumbra.pipeline.runner import PipelineRunner, default_resolver
from lumbra.pipeline.stages.chunk import ChunkStage
from lumbra.pipeline.stages.embedding import EmbeddingStage
from lumbra.pipeline.stages.extract import ExtractStage
from lumbra.pipeline.stages.index import IndexStage
from lumbra.pipeline.stages.kg import KnowledgeGraphStage
from lumbra.pipeline.stages.metadata import MetadataStage
from lumbra.pipeline.stages.ocr import OCRStage
from lumbra.ports.attachments import AttachmentStorePort
from lumbra.ports.capabilities import CapabilitySpec
from lumbra.ports.conversations import ConversationStorePort
from lumbra.ports.devices import DeviceStorePort
from lumbra.ports.document_store import DocumentRecord
from lumbra.ports.event_bus import EventBusPort
from lumbra.ports.event_store import EventStorePort
from lumbra.ports.memory import MemoryStorePort
from lumbra.ports.users import UserStorePort
from lumbra.shared.config import Settings, get_settings


def _build_bus(settings: Settings, events: EventRegistry) -> tuple[EventBusPort, Redis | None]:
    if settings.eventbus == "redis":
        redis = Redis.from_url(settings.redis.url.get_secret_value())
        return RedisStreamsEventBus(redis, events, settings.redis), redis
    return InMemoryEventBus(), None


def create_default_app() -> FastAPI:
    """Fábrica usada por ``uvicorn lumbra.api.main:create_default_app --factory``."""
    settings = get_settings()
    events = EventRegistry()
    bus, redis = _build_bus(settings, events)

    db: Database | None = None
    event_store: EventStorePort
    users: UserStorePort
    if settings.persistence == "postgres":
        db = Database(settings.database)
        event_store = PostgresEventStore(db)
        users = PostgresUserStore(db)
    else:
        event_store = InMemoryEventStore()
        users = InMemoryUserStore()

    kernel = LumbraKernel(
        events=events,
        bus=bus,
        event_store=event_store,
        # dev: permite tudo EXPLICITAMENTE; produção usará consents (doc 18)
        permissions=StaticPermissionAdapter(default_allow=not settings.is_production),
    )
    kernel.register_module(KernelCoreModule())

    metrics_global = InMemoryMetrics()
    # ordem = prioridade sob ALLOW_CLOUD: local primeiro, cloud é opt-in explícito
    chat_providers: list[Any] = [
        OllamaChatProvider(
            base_url=settings.ai.ollama_base_url, model=settings.ai.ollama_chat_model
        )
    ]
    if settings.ai.anthropic_api_key is not None:
        chat_providers.append(
            AnthropicChatProvider(
                api_key=settings.ai.anthropic_api_key, model=settings.ai.anthropic_chat_model
            )
        )
    gateway = AIGateway(
        embedding_providers=[
            FastEmbedProvider(settings.ai.embedding_model, dim=settings.ai.embedding_dim)
        ],
        chat_providers=chat_providers,
        metrics=metrics_global,
        explain=kernel.explain,
    )
    kernel.register_module(AIModule(gateway))

    # Stack de chat/memória: presente nos DOIS modos de persistência, para que
    # a superfície da Platform API seja idêntica independente do adaptador
    # (docs/24, Regra 1). Em modo memória, stores in-memory tornam o Nó um
    # ambiente leve de desenvolvimento; em postgres, os stores persistentes.
    memory_store: MemoryStorePort
    conversation_store: ConversationStorePort
    attachment_store: AttachmentStorePort
    device_store: DeviceStorePort
    blobs = FilesystemBlobStore(Path(settings.storage.attachments_dir))
    if db is not None:
        memory_store = PostgresMemoryStore(db)
        conversation_store = PostgresConversationStore(db)
        attachment_store = PostgresAttachmentStore(db)
        device_store = PostgresDeviceStore(db)
    else:
        memory_store = InMemoryMemoryStore()
        conversation_store = InMemoryConversationStore()
        attachment_store = InMemoryAttachmentStore()
        device_store = InMemoryDeviceStore()

    kernel.register_module(MemoryModule(store=memory_store, gateway=gateway))
    chat_module = ChatModule(
        conversations=conversation_store, gateway=gateway, attachments=attachment_store
    )
    kernel.register_module(chat_module)
    kernel.register_module(ReflectionModule(conversations=conversation_store, gateway=gateway))
    # Context First (princípio nº 5): memória sempre; documentos/anexos só há
    # o que consultar quando existe acervo indexado (modo postgres).
    kernel.context.register(MemoryContextProvider(kernel.skills))

    dev_router = None
    if db is not None:
        documents = PostgresDocumentStore(db)
        processing = PostgresProcessingStore(db)
        graph = PostgresKnowledgeGraph(db)
        search = PostgresSearch(db)
        metrics = metrics_global

        async def _read_raw(document: DocumentRecord) -> bytes:
            from pathlib import Path
            from urllib.parse import urlparse
            from urllib.request import url2pathname

            return Path(url2pathname(urlparse(document.uri).path)).read_bytes()

        runner = PipelineRunner(
            stages=[
                ExtractStage(),
                OCRStage(provider=None),  # provider concreto: próxima sub-etapa
                MetadataStage(MetadataEngine(default_extractors())),
                ChunkStage(default_chunker_registry()),
                IndexStage(documents),
                EmbeddingStage(gateway, documents),
                KnowledgeGraphStage(graph),
            ],
            resolver=default_resolver(),
            processing=processing,
            metrics=metrics,
            read_raw=_read_raw,
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
        kernel.context.register(DocumentContextProvider(kernel.skills))
        kernel.context.register(AttachmentContextProvider(attachment_store, documents))
        # camada de agentes (A7.5): a competência e quem a implementa. O cliente
        # pede a CAPABILITY; o Orchestrator resolve o provedor.
        kernel.capabilities.register_capability(
            CapabilitySpec(
                id=DOCUMENTS_SEARCH,
                description="Busca trechos relevantes nos documentos do usuário",
                required_scopes=("read:documents",),
            )
        )
        kernel.agents.register(DocumentsAgent(kernel.skills))
        if not settings.is_production:
            from lumbra.api.auth import make_require_subject
            from lumbra.api.dev import build_dev_router
            from lumbra.ports.event_bus import ConsumerSpec
            from lumbra.shared.logging import install_log_tap

            tracker = ExecutionTracker(kernel)
            kernel.bus.register(
                ConsumerSpec(name="devconsole-observer", patterns=("*",), handler=tracker.on_event)
            )
            install_log_tap(tracker.on_log)
            dev_router = build_dev_router(
                kernel=kernel,
                tracker=tracker,
                documents=documents,
                processing=processing,
                search=search,
                metrics=metrics,
                graph=graph,
                runner=runner,
                gateway=gateway,
                require_subject=make_require_subject(TokenService(settings.security)),
            )

    if redis is not None:

        async def redis_ready() -> bool:
            return bool(await redis.ping())

        kernel.add_readiness_check("redis", redis_ready)
    if db is not None:
        kernel.add_readiness_check("database", db.ping)

    auth = AuthServices(
        users=users,
        passwords=PasswordHasher(),
        tokens=TokenService(settings.security),
    )
    from lumbra.api.auth import make_require_subject as _mrs

    extra_routers = [
        build_system_router(settings, kernel),
        build_memory_router(kernel, memory_store, _mrs(auth.tokens)),
        build_chat_router(
            kernel, conversation_store, _mrs(auth.tokens), chat_module, gateway, blobs
        ),
        build_devices_router(kernel, device_store, auth.tokens),
        build_agents_router(kernel, _mrs(auth.tokens)),
    ]
    return create_app(
        settings, kernel=kernel, auth=auth, dev_router=dev_router, extra_routers=extra_routers
    )


# canário anti-truncamento
