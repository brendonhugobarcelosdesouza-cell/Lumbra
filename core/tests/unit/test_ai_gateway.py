"""Testes do AI Gateway: roteamento por privacidade, trace, explicações, erros."""

import pytest

from lumbra.adapters.ai.gateway import AIGateway
from lumbra.adapters.metrics.in_memory import InMemoryMetrics
from lumbra.kernel.explain import ExplainEngine
from lumbra.ports.ai import (
    ChatChunk,
    ChatMessage,
    ChatProviderPort,
    ChatRequest,
    EmbeddingProviderPort,
    EmbedRequest,
    NoEligibleProviderError,
    PrivacyMode,
    ProviderCompletion,
)
from lumbra.shared.ids import uuid7


class StubProvider(EmbeddingProviderPort):
    """Dublê de teste do PORT (contrato real, implementação de laboratório)."""

    def __init__(self, name: str, *, local: bool, dim: int = 4, fail: bool = False):
        self._name, self._local, self._dim, self.fail = name, local, dim, fail
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def model(self) -> str:
        return f"{self._name}-model"

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def is_local(self) -> bool:
        return self._local

    async def embed(self, texts):
        self.calls += 1
        if self.fail:
            raise RuntimeError("provedor caiu")
        return tuple((float(len(t)),) * self._dim for t in texts)


def _gateway(*providers, explain=None):
    return AIGateway(
        embedding_providers=list(providers),
        metrics=InMemoryMetrics(),
        explain=explain,
    )


class TestRouting:
    async def test_local_only_uses_local_provider(self):
        local = StubProvider("local", local=True)
        cloud = StubProvider("cloud", local=False)
        gw = _gateway(local, cloud)
        result = await gw.embed(EmbedRequest(texts=("oi",), privacy=PrivacyMode.LOCAL_ONLY))
        assert result.provider == "local"
        assert cloud.calls == 0  # dado nunca saiu (princípio nº 14)

    async def test_local_only_without_local_provider_fails_loudly(self):
        cloud = StubProvider("cloud", local=False)
        gw = _gateway(cloud)
        with pytest.raises(NoEligibleProviderError):
            await gw.embed(EmbedRequest(texts=("oi",), privacy=PrivacyMode.LOCAL_ONLY))

    async def test_allow_cloud_prefers_registration_order(self):
        local = StubProvider("local", local=True)
        cloud = StubProvider("cloud", local=False)
        gw = _gateway(local, cloud)
        result = await gw.embed(EmbedRequest(texts=("oi",), privacy=PrivacyMode.ALLOW_CLOUD))
        assert result.provider == "local"  # local primeiro mesmo com cloud liberado


class TestTraceAndExplain:
    async def test_every_call_is_traced(self):
        gw = _gateway(StubProvider("local", local=True))
        await gw.embed(EmbedRequest(texts=("um", "dois"), purpose="indexing"))
        trace = gw.trace()
        assert len(trace) == 1
        record = trace[0]
        assert record.kind == "embedding"
        assert record.provider == "local"
        assert record.input_units == 2
        assert record.input_chars == 6
        assert record.cost_usd == 0.0
        assert record.success is True
        assert record.duration_ms >= 0

    async def test_failure_is_traced_and_reraised(self):
        gw = _gateway(StubProvider("local", local=True, fail=True))
        with pytest.raises(RuntimeError):
            await gw.embed(EmbedRequest(texts=("x",)))
        record = gw.trace()[0]
        assert record.success is False
        assert "provedor caiu" in (record.error or "")

    async def test_explanation_recorded_with_alternatives(self):
        explain = ExplainEngine()
        corr = uuid7()
        gw = _gateway(
            StubProvider("local", local=True),
            StubProvider("cloud", local=False),
            explain=explain,
        )
        await gw.embed(EmbedRequest(texts=("x",), correlation_id=corr))
        records = explain.query(correlation_id=corr)
        assert len(records) == 1
        assert records[0].component == "ai_gateway"
        assert records[0].alternatives == ("cloud",)
        assert "local_only" in records[0].reason


class TestResult:
    async def test_result_shape(self):
        gw = _gateway(StubProvider("local", local=True, dim=3))
        result = await gw.embed(EmbedRequest(texts=("abc", "de")))
        assert result.dim == 3
        assert len(result.vectors) == 2
        assert all(len(v) == 3 for v in result.vectors)


class StubChatProvider(ChatProviderPort):
    def __init__(
        self,
        name: str,
        *,
        local: bool,
        fail: bool = False,
        cost_per_token: float = 0.0,
        stream_parts: list[str] | None = None,
        fail_after: int | None = None,
    ):
        self._name, self._local, self.fail, self._cost = name, local, fail, cost_per_token
        self._stream_parts = stream_parts or ["resposta ", "em partes"]
        self._fail_after = fail_after  # quebra no meio da transmissão
        self.calls: list[tuple] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def model(self) -> str:
        return f"{self._name}-model"

    @property
    def is_local(self) -> bool:
        return self._local

    def cost_usd(self, *, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens + output_tokens) * self._cost

    async def complete(self, messages, *, max_tokens, temperature):
        self.calls.append((messages, max_tokens, temperature))
        if self.fail:
            raise RuntimeError("provedor caiu")
        return ProviderCompletion(
            text=f"resposta de {self._name}",
            input_tokens=10,
            output_tokens=5,
            finish_reason="stop",
        )

    async def stream(self, messages, *, max_tokens, temperature):
        self.calls.append((messages, max_tokens, temperature))
        if self.fail:
            raise RuntimeError("provedor caiu")
        for position, part in enumerate(self._stream_parts):
            if self._fail_after is not None and position >= self._fail_after:
                raise RuntimeError("conexão caiu no meio da geração")
            yield ChatChunk(delta=part)
        yield ChatChunk(done=True, input_tokens=10, output_tokens=5, finish_reason="stop")


class TestChatRouting:
    async def test_local_only_uses_ollama(self):
        ollama = StubChatProvider("ollama-local", local=True)
        claude = StubChatProvider("anthropic", local=False)
        gw = AIGateway(
            embedding_providers=[StubProvider("emb", local=True)],
            chat_providers=[ollama, claude],
            metrics=InMemoryMetrics(),
        )
        result = await gw.chat(ChatRequest(messages=(ChatMessage(role="user", content="oi"),)))
        assert result.provider == "ollama-local"
        assert claude.calls == []  # dado nunca saiu (princípio nº 14)

    async def test_local_only_without_local_chatter_fails_loudly(self):
        claude = StubChatProvider("anthropic", local=False)
        gw = AIGateway(
            embedding_providers=[StubProvider("emb", local=True)],
            chat_providers=[claude],
            metrics=InMemoryMetrics(),
        )
        with pytest.raises(NoEligibleProviderError):
            await gw.chat(ChatRequest(messages=(ChatMessage(role="user", content="oi"),)))

    async def test_no_chat_providers_registered_fails_loudly(self):
        gw = AIGateway(
            embedding_providers=[StubProvider("emb", local=True)], metrics=InMemoryMetrics()
        )
        with pytest.raises(NoEligibleProviderError):
            await gw.chat(ChatRequest(messages=(ChatMessage(role="user", content="oi"),)))

    async def test_explicit_provider_forces_choice_under_allow_cloud(self):
        ollama = StubChatProvider("ollama-local", local=True)
        claude = StubChatProvider("anthropic", local=False)
        gw = AIGateway(
            embedding_providers=[StubProvider("emb", local=True)],
            chat_providers=[ollama, claude],
            metrics=InMemoryMetrics(),
        )
        result = await gw.chat(
            ChatRequest(
                messages=(ChatMessage(role="user", content="oi"),),
                privacy=PrivacyMode.ALLOW_CLOUD,
                provider="anthropic",
            )
        )
        assert result.provider == "anthropic"

    async def test_explicit_provider_not_eligible_under_local_only_fails(self):
        ollama = StubChatProvider("ollama-local", local=True)
        claude = StubChatProvider("anthropic", local=False)
        gw = AIGateway(
            embedding_providers=[StubProvider("emb", local=True)],
            chat_providers=[ollama, claude],
            metrics=InMemoryMetrics(),
        )
        with pytest.raises(NoEligibleProviderError):
            await gw.chat(
                ChatRequest(
                    messages=(ChatMessage(role="user", content="oi"),),
                    privacy=PrivacyMode.LOCAL_ONLY,
                    provider="anthropic",
                )
            )

    async def test_cloud_cost_is_recorded_local_is_free(self):
        ollama = StubChatProvider("ollama-local", local=True, cost_per_token=0.0)
        claude = StubChatProvider("anthropic", local=False, cost_per_token=0.001)
        gw = AIGateway(
            embedding_providers=[StubProvider("emb", local=True)],
            chat_providers=[ollama, claude],
            metrics=InMemoryMetrics(),
        )
        await gw.chat(
            ChatRequest(
                messages=(ChatMessage(role="user", content="oi"),),
                privacy=PrivacyMode.ALLOW_CLOUD,
                provider="anthropic",
            )
        )
        record = gw.trace()[0]
        assert record.kind == "completion"
        assert record.cost_usd == pytest.approx(0.015)  # (10+5) tokens x 0.001

    async def test_failed_chat_is_traced_with_zero_cost(self):
        claude = StubChatProvider("anthropic", local=False, fail=True, cost_per_token=0.01)
        gw = AIGateway(
            embedding_providers=[StubProvider("emb", local=True)],
            chat_providers=[claude],
            metrics=InMemoryMetrics(),
        )
        with pytest.raises(RuntimeError):
            await gw.chat(
                ChatRequest(
                    messages=(ChatMessage(role="user", content="oi"),),
                    privacy=PrivacyMode.ALLOW_CLOUD,
                )
            )
        record = gw.trace()[0]
        assert record.success is False
        assert record.cost_usd == 0.0

    async def test_chat_explained(self):
        explain = ExplainEngine()
        ollama = StubChatProvider("ollama-local", local=True)
        gw = AIGateway(
            embedding_providers=[StubProvider("emb", local=True)],
            chat_providers=[ollama],
            metrics=InMemoryMetrics(),
            explain=explain,
        )
        await gw.chat(ChatRequest(messages=(ChatMessage(role="user", content="oi"),)))
        records = explain.query(component="ai_gateway")
        assert any("chat via ollama-local" in r.decision for r in records)


# canário anti-truncamento


class TestChatStreaming:
    """Streaming mantém a MESMA política, trace e explicação do chat comum."""

    async def _drain(self, gateway, **kwargs):
        events = []
        async for event in gateway.chat_stream(
            ChatRequest(messages=(ChatMessage(role="user", content="oi"),), **kwargs)
        ):
            events.append(event)
        return events

    async def test_deltas_then_final_result(self):
        local = StubChatProvider("ollama-local", local=True, stream_parts=["Olá", " mundo"])
        gateway = AIGateway(
            embedding_providers=[StubProvider("local", local=True)],
            chat_providers=[local],
            metrics=InMemoryMetrics(),
        )
        events = await self._drain(gateway)
        assert [e.delta for e in events if e.kind == "delta"] == ["Olá", " mundo"]
        final = events[-1]
        assert final.kind == "final"
        assert final.result.text == "Olá mundo"
        assert final.result.provider == "ollama-local"

    async def test_privacy_is_enforced_in_streaming_too(self):
        cloud = StubChatProvider("cloud", local=False)
        gateway = AIGateway(
            embedding_providers=[StubProvider("local", local=True)],
            chat_providers=[cloud],
            metrics=InMemoryMetrics(),
        )
        with pytest.raises(NoEligibleProviderError):
            await self._drain(gateway, privacy=PrivacyMode.LOCAL_ONLY)

    async def test_stream_is_traced_with_tokens_and_cost(self):
        cloud = StubChatProvider(
            "cloud", local=False, stream_parts=["a", "b"], cost_per_token=0.001
        )
        gateway = AIGateway(
            embedding_providers=[StubProvider("local", local=True)],
            chat_providers=[cloud],
            metrics=InMemoryMetrics(),
        )
        await self._drain(gateway, privacy=PrivacyMode.ALLOW_CLOUD)
        record = gateway.trace()[0]
        assert record.kind == "completion"
        assert record.success is True
        assert record.cost_usd > 0

    async def test_failure_midstream_is_traced(self):
        broken = StubChatProvider("ollama-local", local=True, fail_after=1)
        gateway = AIGateway(
            embedding_providers=[StubProvider("local", local=True)],
            chat_providers=[broken],
            metrics=InMemoryMetrics(),
        )
        with pytest.raises(RuntimeError):
            await self._drain(gateway)
        record = gateway.trace()[0]
        assert record.success is False
        assert record.error is not None
