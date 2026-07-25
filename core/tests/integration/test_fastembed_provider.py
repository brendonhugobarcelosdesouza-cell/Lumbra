"""Integração: provedor local real de embeddings (fastembed/ONNX)."""

import math
from pathlib import Path

import pytest

from lumbra.adapters.ai.fastembed_local import FastEmbedProvider

pytestmark = pytest.mark.integration

CACHE = Path.home() / ".cache" / "fastembed"


async def test_real_embeddings_dim_and_similarity():
    provider = FastEmbedProvider(cache_dir=CACHE)
    vectors = await provider.embed(
        ("contrato de aluguel do apartamento", "contrato de locação do imóvel", "receita de bolo")
    )
    assert all(len(v) == provider.dim == 384 for v in vectors)

    def cos(a, b):
        dot = sum(x * y for x, y in zip(a, b, strict=True))
        return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))

    similar = cos(vectors[0], vectors[1])
    distant = cos(vectors[0], vectors[2])
    assert similar > distant + 0.15  # semântica: aluguel≈locação, ambos longe de bolo
    assert similar > 0.7
