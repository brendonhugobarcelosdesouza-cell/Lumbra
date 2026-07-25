"""AI Gateway (ADR-005/ADR-025/ADR-028, princípio permanente nº 6).

NENHUM componente fala com provedores de IA diretamente: toda chamada
passa pelo Gateway, que roteia por política (privacidade/custo), registra
o trace completo (modelo, provider, latência, unidades, custo) e explica
cada decisão de roteamento (ADR-023).

Etapa 3a: embeddings. Etapa E2-1: chat/completions — extensão aditiva,
mesmo contrato de roteamento/trace/explicação dos embeddings.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from lumbra.shared.cancellation import CancellationToken
from lumbra.shared.ids import uuid7


class PrivacyMode(StrEnum):
    """Política de privacidade da chamada (princípio nº 14)."""

    LOCAL_ONLY = "local_only"  # jamais sai da máquina
    ALLOW_CLOUD = "allow_cloud"  # pode usar provedor externo autorizado


class EmbedRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    texts: tuple[str, ...]
    purpose: str = "indexing"  # indexing | query | similarity...
    privacy: PrivacyMode = PrivacyMode.LOCAL_ONLY
    correlation_id: UUID | None = None


class EmbedResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    vectors: tuple[tuple[float, ...], ...]
    dim: int
    provider: str
    model: str


class AICallRecord(BaseModel):
    """Trace de UMA chamada de IA — visível no Developer Console (AI Trace)."""

    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid7)
    kind: str  # embedding | completion
    provider: str
    model: str
    purpose: str
    privacy: PrivacyMode
    input_units: int  # nº de textos (embeddings) / tokens de entrada (chat)
    input_chars: int
    duration_ms: float
    cost_usd: float  # 0.0 para local
    success: bool
    # desfecho detalhado (ADR-032): completed | cancelled | timeout | failed.
    # ``success`` continua existindo para métricas simples, mas cancelamento
    # NÃO é falha — o console e os alertas usam ``outcome``.
    outcome: str = "completed"
    error: str | None = None
    correlation_id: UUID | None = None
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))


# ------------------------------------------------------------------ chat/completions


ChatRole = Literal["system", "user", "assistant"]


class ChatMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: ChatRole
    content: str


class ChatRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    messages: tuple[ChatMessage, ...]
    purpose: str = "chat"  # chat | summarization | extraction...
    privacy: PrivacyMode = PrivacyMode.LOCAL_ONLY
    provider: str | None = None  # força um provedor elegível específico (E2-04)
    max_tokens: int = 1024
    temperature: float = 0.7
    correlation_id: UUID | None = None


class ChatResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    finish_reason: str


class ProviderCompletion(BaseModel):
    """Retorno cru do provedor — o Gateway agrega provider/model (mesmo
    desenho de ``EmbeddingProviderPort.embed``: o provedor não conhece o
    próprio papel no roteamento, só executa)."""

    model_config = ConfigDict(frozen=True)

    text: str
    input_tokens: int
    output_tokens: int
    finish_reason: str


class ChatChunk(BaseModel):
    """Pedaço de uma resposta em streaming.

    O último pedaço (``done=True``) carrega a contabilidade de tokens —
    é onde o Gateway fecha o trace e calcula o custo.
    """

    model_config = ConfigDict(frozen=True)

    delta: str = ""
    done: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    finish_reason: str | None = None


class ChatStreamEvent(BaseModel):
    """O que o Gateway emite: deltas e, ao final, o resultado completo."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["delta", "final"]
    delta: str = ""
    result: ChatResult | None = None  # preenchido apenas em kind="final"


class ChatProviderPort(ABC):
    """Um provedor concreto de chat/completions (local ou cloud)."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def model(self) -> str: ...

    @property
    @abstractmethod
    def is_local(self) -> bool: ...

    @abstractmethod
    def cost_usd(self, *, input_tokens: int, output_tokens: int) -> float:
        """0.0 para provedores locais; preço real por token para cloud."""

    @abstractmethod
    async def complete(
        self, messages: tuple[ChatMessage, ...], *, max_tokens: int, temperature: float
    ) -> ProviderCompletion: ...

    async def stream(
        self, messages: tuple[ChatMessage, ...], *, max_tokens: int, temperature: float
    ) -> AsyncIterator[ChatChunk]:
        """Resposta incremental.

        Implementação padrão: quem não sabe transmitir cai automaticamente
        no ``complete()`` e entrega tudo num único pedaço. Assim o chat em
        streaming funciona com QUALQUER provedor — só fica menos fluido.
        """
        completion = await self.complete(messages, max_tokens=max_tokens, temperature=temperature)
        yield ChatChunk(delta=completion.text)
        yield ChatChunk(
            done=True,
            input_tokens=completion.input_tokens,
            output_tokens=completion.output_tokens,
            finish_reason=completion.finish_reason,
        )


class EmbeddingProviderPort(ABC):
    """Um provedor concreto de embeddings (local ou cloud)."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def model(self) -> str: ...

    @property
    @abstractmethod
    def dim(self) -> int: ...

    @property
    @abstractmethod
    def is_local(self) -> bool: ...

    @abstractmethod
    async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]: ...


class ChatProviderInfo(BaseModel):
    """Descrição de um provedor de chat registrado — o cardápio que a
    interface mostra quando o usuário escolhe o modelo da conversa (E2-04)."""

    model_config = ConfigDict(frozen=True)

    name: str
    model: str
    is_local: bool
    # preço por 1M de tokens; 0.0/0.0 para locais
    input_price_per_mtok: float
    output_price_per_mtok: float


class AIGatewayPort(ABC):
    @abstractmethod
    async def embed(
        self, request: EmbedRequest, *, cancellation: CancellationToken | None = None
    ) -> EmbedResult: ...

    @abstractmethod
    async def chat(
        self, request: ChatRequest, *, cancellation: CancellationToken | None = None
    ) -> ChatResult: ...

    @abstractmethod
    def chat_stream(
        self, request: ChatRequest, *, cancellation: CancellationToken | None = None
    ) -> AsyncIterator[ChatStreamEvent]:
        """Mesma política/trace do ``chat``, entregue incrementalmente.

        Cancelar fecha a conexão com o provedor: o Ollama para de gerar e
        libera a GPU na hora, em vez de continuar produzindo texto que
        ninguém vai ler."""

    @abstractmethod
    def trace(self, *, limit: int = 100) -> list[AICallRecord]:
        """Chamadas recentes, mais novas primeiro (AI Trace do console)."""

    @abstractmethod
    def chat_providers(self) -> list[ChatProviderInfo]:
        """Provedores de chat registrados, na ordem de prioridade."""


class NoEligibleProviderError(Exception):
    """Nenhum provedor satisfaz a política (ex.: local_only sem provedor local)."""


# canário anti-truncamento
