"""Context Engine — agregação de contexto antes de qualquer chamada de IA.

Consulta todos os provedores registrados em paralelo, com timeout por
provedor e isolamento de falhas (um provedor quebrado nunca derruba a
resposta). Resultado: fragmentos ordenados por relevância, limitados ao
orçamento do pedido, cada um com proveniência (vira citação).
"""

from __future__ import annotations

import asyncio

from lumbra.ports.context import ContextFragment, ContextProviderPort, ContextRequest
from lumbra.shared.logging import get_logger

_log = get_logger("lumbra.kernel.context")


class DuplicateProviderError(Exception):
    def __init__(self, name: str) -> None:
        super().__init__(f"Provedor de contexto já registrado: {name}")


class ContextEngine:
    def __init__(self, *, provider_timeout_seconds: float = 2.0) -> None:
        self._providers: dict[str, ContextProviderPort] = {}
        self._timeout = provider_timeout_seconds

    def register(self, provider: ContextProviderPort) -> None:
        if provider.name in self._providers:
            raise DuplicateProviderError(provider.name)
        self._providers[provider.name] = provider
        _log.info("context_provider_registered", provider=provider.name)

    def providers(self) -> list[str]:
        return sorted(self._providers)

    async def gather(self, request: ContextRequest) -> list[ContextFragment]:
        if not self._providers:
            return []
        results = await asyncio.gather(
            *(self._collect(p, request) for p in self._providers.values())
        )
        fragments = [fragment for sublist in results for fragment in sublist]
        fragments.sort(key=lambda f: f.relevance, reverse=True)
        selected = fragments[: request.max_fragments]
        _log.info(
            "context_gathered",
            purpose=request.purpose,
            providers=len(self._providers),
            fragments=len(selected),
        )
        return selected

    async def _collect(
        self, provider: ContextProviderPort, request: ContextRequest
    ) -> list[ContextFragment]:
        try:
            async with asyncio.timeout(self._timeout):
                return await provider.provide(request)
        except TimeoutError:
            _log.warning("context_provider_timeout", provider=provider.name)
            return []
        except Exception as exc:
            _log.error("context_provider_error", provider=provider.name, error=repr(exc))
            return []


# canário anti-truncamento
