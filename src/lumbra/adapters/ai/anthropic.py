"""Provedor de chat cloud via API da Anthropic (Claude).

Só é elegível sob ``PrivacyMode.ALLOW_CLOUD`` — o Gateway garante isso
(princípio nº 14: nada sai da máquina sem autorização explícita por
chamada). Cliente HTTP direto (sem SDK extra) contra a Messages API;
preço por token configurável, pois tabelas de preço mudam com o tempo
(conferir sempre https://platform.claude.com/docs/en/about-claude/pricing).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx
from pydantic import SecretStr

from lumbra.ports.ai import ChatChunk, ChatMessage, ChatProviderPort, ProviderCompletion

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
ANTHROPIC_VERSION = "2023-06-01"

# USD por milhão de tokens — padrão = Claude Haiku 4.5 (platform.claude.com,
# verificado em jul/2026). Atualize se o modelo ou o preço mudar.
DEFAULT_INPUT_PRICE_PER_MTOK = 1.0
DEFAULT_OUTPUT_PRICE_PER_MTOK = 5.0


class AnthropicAPIError(Exception):
    """A API da Anthropic respondeu com erro (chave inválida, limite, etc.)."""


class AnthropicChatProvider(ChatProviderPort):
    def __init__(
        self,
        *,
        api_key: SecretStr,
        model: str = DEFAULT_MODEL,
        base_url: str = "https://api.anthropic.com",
        input_price_per_mtok: float = DEFAULT_INPUT_PRICE_PER_MTOK,
        output_price_per_mtok: float = DEFAULT_OUTPUT_PRICE_PER_MTOK,
        timeout_s: float = 60.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._input_price = input_price_per_mtok
        self._output_price = output_price_per_mtok
        self._timeout_s = timeout_s

    @property
    def name(self) -> str:
        return "anthropic"

    @property
    def model(self) -> str:
        return self._model

    @property
    def is_local(self) -> bool:
        return False

    def cost_usd(self, *, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * self._input_price + output_tokens * self._output_price) / 1_000_000

    async def complete(
        self, messages: tuple[ChatMessage, ...], *, max_tokens: int, temperature: float
    ) -> ProviderCompletion:
        system = "\n\n".join(m.content for m in messages if m.role == "system") or None
        turns = [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]
        body: dict[str, object] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": turns,
        }
        if system:
            body["system"] = system
        headers = {
            "x-api-key": self._api_key.get_secret_value(),
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                response = await client.post(
                    f"{self._base_url}/v1/messages", json=body, headers=headers
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise AnthropicAPIError(
                f"Anthropic respondeu {exc.response.status_code}: {exc.response.text[:300]}"
            ) from exc
        except httpx.ConnectError as exc:
            raise AnthropicAPIError(f"sem conexão com {self._base_url}") from exc
        data = response.json()
        text = "".join(
            block.get("text", "")
            for block in data.get("content", [])
            if block.get("type") == "text"
        )
        usage = data.get("usage", {})
        return ProviderCompletion(
            text=text,
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
            finish_reason=str(data.get("stop_reason", "end_turn")),
        )

    async def stream(
        self, messages: tuple[ChatMessage, ...], *, max_tokens: int, temperature: float
    ) -> AsyncIterator[ChatChunk]:
        """Messages API transmite SSE: eventos message_start /
        content_block_delta / message_delta com o uso final."""
        system = "\n\n".join(m.content for m in messages if m.role == "system") or None
        body: dict[str, object] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [
                {"role": m.role, "content": m.content} for m in messages if m.role != "system"
            ],
            "stream": True,
        }
        if system:
            body["system"] = system
        headers = {
            "x-api-key": self._api_key.get_secret_value(),
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        input_tokens = 0
        output_tokens = 0
        finish_reason = "end_turn"
        try:
            url = f"{self._base_url}/v1/messages"
            async with (
                httpx.AsyncClient(timeout=self._timeout_s) as client,
                client.stream("POST", url, json=body, headers=headers) as response,
            ):
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if not payload or payload == "[DONE]":
                        continue
                    event = json.loads(payload)
                    kind = event.get("type")
                    if kind == "message_start":
                        usage = event.get("message", {}).get("usage", {})
                        input_tokens = int(usage.get("input_tokens", 0))
                    elif kind == "content_block_delta":
                        delta = event.get("delta", {}).get("text", "")
                        if delta:
                            yield ChatChunk(delta=delta)
                    elif kind == "message_delta":
                        output_tokens = int(event.get("usage", {}).get("output_tokens", 0))
                        finish_reason = str(
                            event.get("delta", {}).get("stop_reason") or finish_reason
                        )
        except httpx.HTTPStatusError as exc:
            raise AnthropicAPIError(
                f"Anthropic respondeu {exc.response.status_code} ao transmitir"
            ) from exc
        except httpx.ConnectError as exc:
            raise AnthropicAPIError(f"sem conexão com {self._base_url}") from exc
        yield ChatChunk(
            done=True,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            finish_reason=finish_reason,
        )


# canário anti-truncamento
