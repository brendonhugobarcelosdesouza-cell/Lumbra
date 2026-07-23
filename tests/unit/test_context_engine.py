"""Testes do Context Engine: agregação, isolamento de falhas, timeout, orçamento."""

import asyncio

import pytest

from lumbra.kernel.context_engine import ContextEngine, DuplicateProviderError
from lumbra.ports.context import ContextFragment, ContextProviderPort, ContextRequest


class FakeProvider(ContextProviderPort):
    def __init__(self, name: str, fragments: list[ContextFragment], delay: float = 0.0):
        self._name = name
        self._fragments = fragments
        self._delay = delay

    @property
    def name(self) -> str:
        return self._name

    async def provide(self, request: ContextRequest) -> list[ContextFragment]:
        if self._delay:
            await asyncio.sleep(self._delay)
        return self._fragments


class BrokenProvider(ContextProviderPort):
    @property
    def name(self) -> str:
        return "broken"

    async def provide(self, request: ContextRequest) -> list[ContextFragment]:
        raise RuntimeError("provider quebrado")


def _frag(source: str, relevance: float) -> ContextFragment:
    return ContextFragment(source=source, content=f"conteúdo de {source}", relevance=relevance)


async def test_gathers_and_sorts_by_relevance():
    engine = ContextEngine()
    engine.register(FakeProvider("memory", [_frag("memory", 0.9), _frag("memory", 0.3)]))
    engine.register(FakeProvider("calendar", [_frag("calendar", 0.7)]))

    fragments = await engine.gather(ContextRequest(query="reunião amanhã"))
    assert [f.relevance for f in fragments] == [0.9, 0.7, 0.3]


async def test_broken_provider_is_isolated():
    engine = ContextEngine()
    engine.register(BrokenProvider())
    engine.register(FakeProvider("memory", [_frag("memory", 0.5)]))

    fragments = await engine.gather(ContextRequest(query="q"))
    assert len(fragments) == 1
    assert fragments[0].source == "memory"


async def test_slow_provider_times_out():
    engine = ContextEngine(provider_timeout_seconds=0.05)
    engine.register(FakeProvider("slow", [_frag("slow", 1.0)], delay=1.0))
    engine.register(FakeProvider("fast", [_frag("fast", 0.5)]))

    fragments = await engine.gather(ContextRequest(query="q"))
    assert [f.source for f in fragments] == ["fast"]


async def test_budget_is_enforced():
    engine = ContextEngine()
    engine.register(FakeProvider("m", [_frag("m", i / 100) for i in range(50)]))
    fragments = await engine.gather(ContextRequest(query="q", max_fragments=5))
    assert len(fragments) == 5


async def test_no_providers_returns_empty():
    assert await ContextEngine().gather(ContextRequest(query="q")) == []


def test_duplicate_provider_rejected():
    engine = ContextEngine()
    engine.register(FakeProvider("memory", []))
    with pytest.raises(DuplicateProviderError):
        engine.register(FakeProvider("memory", []))
