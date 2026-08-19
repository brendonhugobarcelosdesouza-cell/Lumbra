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
        from lumbra.shared.paths import pasta_de_modelos

        self._model_name = model
        self._dim = dim
        # Sem cache_dir explícito NÃO cai mais no padrão do fastembed, que é
        # um diretório temporário. Ver `pasta_de_modelos`: temporário quer
        # dizer "o sistema pode apagar", e apagar 120 MB pelas costas do
        # usuário é ruim; pior é o download interrompido, que deixa o cache
        # pela metade e produz "não foi possível gerar embeddings".
        self._cache_dir = cache_dir or pasta_de_modelos()
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
        """Carrega o modelo; se o cache estiver pela metade, baixa de novo.

        Download interrompido é rotina, não exceção — basta o Nó ser morto no
        meio da primeira partida. O que o ``fastembed`` faz então é seguir
        com os arquivos truncados e falhar depois, na hora de gerar o vetor,
        com um "não foi possível gerar embeddings" que não menciona o
        download. Um aviso discreto ("Local file sizes do not match the
        metadata") é a única pista.

        Sem esta cura, a busca semântica fica quebrada PARA SEMPRE naquela
        instalação — a mesma armadilha do banco sujo, com outra roupa. E o
        conserto é barato porque o cache é descartável por definição: nada
        aqui é do usuário, tudo se rebaixa.
        """
        from fastembed import TextEmbedding

        try:
            return TextEmbedding(self._model_name, cache_dir=str(self._cache_dir))
        except Exception as exc:
            _log.warning(
                "modelo_local_invalido_rebaixando",
                model=self._model_name,
                cache=str(self._cache_dir),
                erro=repr(exc),
            )
            self._descartar_cache()
            return TextEmbedding(self._model_name, cache_dir=str(self._cache_dir))

    def _descartar_cache(self) -> None:
        import shutil

        if self._cache_dir is None or not self._cache_dir.exists():
            return
        # apaga SÓ a pasta de modelos: ela é 100% derivada, e o usuário não
        # tem nada dele aqui dentro
        shutil.rmtree(self._cache_dir, ignore_errors=True)

    async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        engine = await self._ensure_loaded()
        # ONNX é CPU-bound: roda fora do event loop
        vectors = await asyncio.to_thread(lambda: [v.tolist() for v in engine.embed(list(texts))])
        return tuple(tuple(v) for v in vectors)


# canário anti-truncamento
