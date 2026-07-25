"""Contrato HTTP dos adapters de chat (Ollama e Anthropic) — sem serviço real:
valida que Lumbra monta a requisição certa e interpreta a resposta certa,
com um transporte HTTP falso (não é o Ollama/Anthropic sendo testado, é o
NOSSO código de integração com eles)."""

import json

import httpx
import pytest
from pydantic import SecretStr

from lumbra.adapters.ai.anthropic import AnthropicAPIError, AnthropicChatProvider
from lumbra.adapters.ai.ollama import OllamaChatProvider, OllamaUnavailableError
from lumbra.ports.ai import ChatMessage

_RealAsyncClient = httpx.AsyncClient


def _client_factory(handler):
    def _patched(*args, **kwargs):
        kwargs.pop("timeout", None)
        return _RealAsyncClient(transport=httpx.MockTransport(handler))

    return _patched


class TestOllamaChatProvider:
    async def test_builds_request_and_parses_response(self, monkeypatch):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["body"] = request.read()
            return httpx.Response(
                200,
                json={
                    "message": {"role": "assistant", "content": "Olá! Como posso ajudar?"},
                    "done": True,
                    "done_reason": "stop",
                    "prompt_eval_count": 12,
                    "eval_count": 7,
                },
            )

        monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
        provider = OllamaChatProvider(model="qwen2.5:7b")
        assert provider.name == "ollama-local"
        assert provider.is_local is True
        assert provider.cost_usd(input_tokens=1000, output_tokens=1000) == 0.0

        result = await provider.complete(
            (ChatMessage(role="user", content="Oi"),), max_tokens=256, temperature=0.7
        )
        assert result.text == "Olá! Como posso ajudar?"
        assert result.input_tokens == 12
        assert result.output_tokens == 7
        assert result.finish_reason == "stop"
        assert captured["url"].endswith("/api/chat")

    async def test_connection_error_is_explained(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("recusado", request=request)

        monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
        provider = OllamaChatProvider()
        with pytest.raises(OllamaUnavailableError, match="ollama serve"):
            await provider.complete(
                (ChatMessage(role="user", content="oi"),), max_tokens=10, temperature=0.5
            )

    async def test_http_error_is_wrapped(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": "model not found"})

        monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
        provider = OllamaChatProvider(model="modelo-que-nao-existe")
        with pytest.raises(OllamaUnavailableError, match="404"):
            await provider.complete(
                (ChatMessage(role="user", content="oi"),), max_tokens=10, temperature=0.5
            )


class TestAnthropicChatProvider:
    async def test_builds_request_and_parses_response(self, monkeypatch):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["headers"] = dict(request.headers)
            captured["body"] = request.read()
            return httpx.Response(
                200,
                json={
                    "content": [{"type": "text", "text": "Claro, posso ajudar."}],
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 20, "output_tokens": 8},
                },
            )

        monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
        provider = AnthropicChatProvider(api_key=SecretStr("sk-ant-teste"))
        assert provider.name == "anthropic"
        assert provider.is_local is False

        result = await provider.complete(
            (
                ChatMessage(role="system", content="Seja conciso."),
                ChatMessage(role="user", content="Oi"),
            ),
            max_tokens=512,
            temperature=0.3,
        )
        assert result.text == "Claro, posso ajudar."
        assert result.input_tokens == 20
        assert result.output_tokens == 8
        assert captured["headers"]["x-api-key"] == "sk-ant-teste"
        body = json.loads(captured["body"])
        assert body["system"] == "Seja conciso."
        assert body["messages"] == [{"role": "user", "content": "Oi"}]

    def test_cost_matches_haiku_pricing(self):
        provider = AnthropicChatProvider(api_key=SecretStr("x"))
        # 1M tokens de entrada + 1M de saída, preço padrão do Haiku 4.5: $1 + $5
        cost = provider.cost_usd(input_tokens=1_000_000, output_tokens=1_000_000)
        assert cost == pytest.approx(6.0)

    async def test_api_error_is_wrapped(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": {"message": "invalid api key"}})

        monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
        provider = AnthropicChatProvider(api_key=SecretStr("chave-invalida"))
        with pytest.raises(AnthropicAPIError, match="401"):
            await provider.complete(
                (ChatMessage(role="user", content="oi"),), max_tokens=10, temperature=0.5
            )


class TestOllamaStreaming:
    async def test_ndjson_becomes_chunks(self, monkeypatch):
        lines = [
            '{"message":{"content":"Olá"},"done":false}',
            '{"message":{"content":", tudo"},"done":false}',
            '{"message":{"content":" bem?"},"done":false}',
            '{"done":true,"done_reason":"stop","prompt_eval_count":9,"eval_count":4}',
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            assert json.loads(request.read())["stream"] is True
            return httpx.Response(200, text="\n".join(lines))

        monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
        chunks = [
            c
            async for c in OllamaChatProvider().stream(
                (ChatMessage(role="user", content="oi"),), max_tokens=64, temperature=0.5
            )
        ]
        assert "".join(c.delta for c in chunks) == "Olá, tudo bem?"
        assert chunks[-1].done is True
        assert chunks[-1].input_tokens == 9
        assert chunks[-1].output_tokens == 4

    async def test_connection_error_during_stream(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("caiu", request=request)

        monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
        with pytest.raises(OllamaUnavailableError):
            async for _ in OllamaChatProvider().stream(
                (ChatMessage(role="user", content="oi"),), max_tokens=10, temperature=0.5
            ):
                pass


class TestAnthropicStreaming:
    async def test_sse_becomes_chunks(self, monkeypatch):
        def sse(payload: dict) -> str:
            return f"event: {payload['type']}\ndata: {json.dumps(payload)}"

        events = [
            sse({"type": "message_start", "message": {"usage": {"input_tokens": 30}}}),
            sse({"type": "content_block_delta", "delta": {"text": "Claro"}}),
            sse({"type": "content_block_delta", "delta": {"text": ", vamos lá."}}),
            sse(
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn"},
                    "usage": {"output_tokens": 6},
                }
            ),
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            assert json.loads(request.read())["stream"] is True
            return httpx.Response(200, text="\n\n".join(events) + "\n\n")

        monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
        chunks = [
            c
            async for c in AnthropicChatProvider(api_key=SecretStr("k")).stream(
                (ChatMessage(role="user", content="oi"),), max_tokens=64, temperature=0.5
            )
        ]
        assert "".join(c.delta for c in chunks) == "Claro, vamos lá."
        assert chunks[-1].done is True
        assert chunks[-1].input_tokens == 30
        assert chunks[-1].output_tokens == 6
        assert chunks[-1].finish_reason == "end_turn"


class TestStreamFallback:
    async def test_provider_without_streaming_still_streams(self):
        """A implementação padrão do port entrega tudo num pedaço só —
        streaming funciona com QUALQUER provedor."""
        from lumbra.ports.ai import ChatProviderPort, ProviderCompletion

        class NoStreamProvider(ChatProviderPort):
            name = "sem-stream"  # type: ignore[assignment]
            model = "x"  # type: ignore[assignment]
            is_local = True  # type: ignore[assignment]

            def cost_usd(self, *, input_tokens: int, output_tokens: int) -> float:
                return 0.0

            async def complete(self, messages, *, max_tokens, temperature):
                return ProviderCompletion(
                    text="resposta inteira", input_tokens=5, output_tokens=3, finish_reason="stop"
                )

        chunks = [
            c
            async for c in NoStreamProvider().stream(
                (ChatMessage(role="user", content="oi"),), max_tokens=10, temperature=0.5
            )
        ]
        assert "".join(c.delta for c in chunks) == "resposta inteira"
        assert chunks[-1].done is True
        assert chunks[-1].output_tokens == 3


# canário anti-truncamento
