"""Provedor de chat 100% local via Ollama (privacidade por padrão).

Fala com o daemon Ollama já instalado pelo usuário via HTTP local
(``/api/chat``), com e sem streaming. Nenhum dado sai da máquina:
``is_local`` é sempre True e o custo é sempre zero.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from lumbra.ports.ai import ChatChunk, ChatMessage, ChatProviderPort, ProviderCompletion
from lumbra.shared.logging import get_logger

_log = get_logger("lumbra.ai.ollama")

DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5:7b"


class OllamaUnavailableError(Exception):
    """Ollama não está rodando ou o modelo não está disponível localmente."""


class OllamaChatProvider(ChatProviderPort):
    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout_s: float = 120.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_s = timeout_s

    @property
    def name(self) -> str:
        return "ollama-local"

    @property
    def model(self) -> str:
        return self._model

    @property
    def is_local(self) -> bool:
        return True

    def cost_usd(self, *, input_tokens: int, output_tokens: int) -> float:
        return 0.0  # roda na máquina do usuário — sem custo por token

    async def complete(
        self, messages: tuple[ChatMessage, ...], *, max_tokens: int, temperature: float
    ) -> ProviderCompletion:
        body = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                response = await client.post(f"{self._base_url}/api/chat", json=body)
                response.raise_for_status()
        except httpx.ConnectError as exc:
            raise OllamaUnavailableError(
                f"Ollama não respondeu em {self._base_url} — ele está rodando? "
                "(`ollama serve`, e o modelo baixado com `ollama pull "
                f"{self._model}`)"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise OllamaUnavailableError(
                f"Ollama respondeu {exc.response.status_code}: {exc.response.text[:300]}"
            ) from exc
        data = response.json()
        return ProviderCompletion(
            text=data["message"]["content"],
            input_tokens=int(data.get("prompt_eval_count", 0)),
            output_tokens=int(data.get("eval_count", 0)),
            finish_reason=str(data.get("done_reason", "stop")),
        )

    async def stream(
        self, messages: tuple[ChatMessage, ...], *, max_tokens: int, temperature: float
    ) -> AsyncIterator[ChatChunk]:
        """Ollama transmite NDJSON: uma linha JSON por token gerado."""
        body = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": True,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        try:
            url = f"{self._base_url}/api/chat"
            async with (
                httpx.AsyncClient(timeout=self._timeout_s) as client,
                client.stream("POST", url, json=body) as response,
            ):
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    if data.get("done"):
                        yield ChatChunk(
                            done=True,
                            input_tokens=int(data.get("prompt_eval_count", 0)),
                            output_tokens=int(data.get("eval_count", 0)),
                            finish_reason=str(data.get("done_reason", "stop")),
                        )
                        return
                    delta = data.get("message", {}).get("content", "")
                    if delta:
                        yield ChatChunk(delta=delta)
        except httpx.ConnectError as exc:
            raise OllamaUnavailableError(
                f"Ollama não respondeu em {self._base_url} — ele está rodando? "
                f"(`ollama serve`, e o modelo baixado com `ollama pull {self._model}`)"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise OllamaUnavailableError(
                f"Ollama respondeu {exc.response.status_code} ao transmitir"
            ) from exc


# canário anti-truncamento
