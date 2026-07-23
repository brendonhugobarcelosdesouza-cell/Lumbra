"""Provedor de embeddings 100% local (fastembed/ONNX) — privacidade por padrão.

Modelo multilíngue pequeno (384 dims): bom para PT-BR + EN, roda em CPU
comum. O modelo é baixado uma única vez para o cache do usuário; depois
disso o provedor opera totalmente offline.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from lumbra.ports.ai import EmbeddingProviderPort
from lumbra.shared.logging import get_logger

_log = get_logger("lumbra.ai.fastembed")

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_DIM = 384


class FastEmbedProvider(EmbeddingProviderPort):
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        dim: int = DEFAULT_DIM,
        cache_dir: Path | None = None,
    ) -> None:
        self._model_name = model
        self._dim = dim
        self._cache_dir = cache_dir
        self._engine: Any = None  # carregamento preguiçoso (download só no 1º uso)
        self._lock = asyncio.Lock()

    @property
    def name(self) -> str:
        return "fastembed-local"

    @property
    def model(self) -> str:
        return self._model_name

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def is_local(self) -> bool:
        return True

    async def _ensure_loaded(self) -> Any:
        if self._engine is None:
            async with self._lock:
                if self._engine is None:
                    _log.info("embedding_model_loading", model=self._model_name)
                    self._engine = await asyncio.to_thread(self._load)
                    _log.info("embedding_model_ready", model=self._model_name)
        return self._engine

    def _load(self) -> Any:
        from fastembed import TextEmbedding

        if self._cache_dir is not None:
            return TextEmbedding(self._model_name, cache_dir=str(self._cache_dir))
        return TextEmbedding(self._model_name)

    async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        engine = await self._ensure_loaded()
        # ONNX é CPU-bound: roda fora do event loop
        vectors = await asyncio.to_thread(lambda: [v.tolist() for v in engine.embed(list(texts))])
        return tuple(tuple(v) for v in vectors)


# canário anti-truncamento
