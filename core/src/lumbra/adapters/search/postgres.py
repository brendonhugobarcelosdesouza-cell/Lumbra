"""Busca sobre chunks: léxica (tsvector) e híbrida (léxica + vetorial, RRF).

RRF (Reciprocal Rank Fusion, Cormack et al. 2009): cada lista ranqueada
contribui ``1 / (k + posição)``; k=60 amortece diferenças de escala entre
ts_rank e distância de cosseno — não é preciso normalizar scores. Cada hit
carrega a explicação componente a componente (princípio nº 13).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import Float, Select, false, func, literal, select

from lumbra.adapters.persistence.database import Database
from lumbra.adapters.persistence.fulltext import tsquery_or
from lumbra.adapters.persistence.models import ChunkModel, DocumentModel
from lumbra.ports.search import SearchHit, SearchPort

_RRF_K = 60
_POOL = 50  # candidatos por componente antes da fusão

# a montagem do tsquery tolerante virou decisão compartilhada da plataforma
# (playbooks recuperam pela mesma regra); o alias mantém o nome local
_tsquery_or = tsquery_or


@dataclass
class _Candidate:
    document_id: UUID
    title: str | None
    uri: str
    snippet: str
    lexical_rank: int | None = None
    lexical_score: float = 0.0
    vector_rank: int | None = None
    vector_similarity: float = 0.0
    rrf: float = field(default=0.0)


class PostgresSearch(SearchPort):
    def __init__(self, db: Database) -> None:
        self._db = db

    # ------------------------------------------------------------ léxica

    def _lexical_stmt(self, user_id: UUID, query: str, limit: int) -> Select[Any]:
        termos = _tsquery_or(query)
        if not termos:
            # query sem palavras buscáveis (só pontuação): léxico não
            # contribui — statement que não casa nada, sem erro de sintaxe
            return select(
                ChunkModel.id,
                ChunkModel.document_id,
                DocumentModel.title,
                DocumentModel.uri,
                literal(0.0).label("rank"),
                func.left(ChunkModel.text, 240).label("snippet"),
            ).where(false())
        tsquery = func.to_tsquery("portuguese", termos)
        rank = func.ts_rank(ChunkModel.tsv, tsquery).cast(Float).label("rank")
        headline = func.ts_headline(
            "portuguese",
            ChunkModel.text,
            tsquery,
            "StartSel=**, StopSel=**, MaxWords=30, MinWords=10",
        ).label("snippet")
        return (
            select(
                ChunkModel.id,
                ChunkModel.document_id,
                DocumentModel.title,
                DocumentModel.uri,
                rank,
                headline,
            )
            .join(DocumentModel, DocumentModel.id == ChunkModel.document_id)
            .where(DocumentModel.user_id == user_id, ChunkModel.tsv.op("@@")(tsquery))
            .order_by(rank.desc())
            .limit(limit)
        )

    async def lexical(self, *, user_id: UUID, query: str, limit: int = 10) -> list[SearchHit]:
        async with self._db.session() as session:
            rows = (await session.execute(self._lexical_stmt(user_id, query, limit))).all()
        return [
            SearchHit(
                chunk_id=chunk_id,
                document_id=document_id,
                title=title,
                uri=uri,
                snippet=snippet,
                score=float(score),
                explanation=f"casamento léxico (tsquery pt) — ts_rank={float(score):.4f}",
            )
            for chunk_id, document_id, title, uri, score, snippet in rows
        ]

    # ------------------------------------------------------------ híbrida

    async def hybrid(
        self,
        *,
        user_id: UUID,
        query: str,
        query_vector: tuple[float, ...] | None,
        limit: int = 10,
    ) -> list[SearchHit]:
        if query_vector is None:
            return await self.lexical(user_id=user_id, query=query, limit=limit)

        distance = ChunkModel.embedding.cosine_distance(list(query_vector)).label("distance")
        vector_stmt = (
            select(
                ChunkModel.id,
                ChunkModel.document_id,
                DocumentModel.title,
                DocumentModel.uri,
                func.left(ChunkModel.text, 240).label("snippet"),
                distance,
            )
            .join(DocumentModel, DocumentModel.id == ChunkModel.document_id)
            .where(DocumentModel.user_id == user_id, ChunkModel.embedding.is_not(None))
            .order_by(distance)
            .limit(_POOL)
        )
        async with self._db.session() as session:
            lex_rows = (await session.execute(self._lexical_stmt(user_id, query, _POOL))).all()
            vec_rows = (await session.execute(vector_stmt)).all()
        return fuse_rrf(lex_rows, vec_rows, limit=limit)


def fuse_rrf(
    lex_rows: Sequence[Sequence[Any]],
    vec_rows: Sequence[Sequence[Any]],
    *,
    limit: int,
    k: int = _RRF_K,
) -> list[SearchHit]:
    """Fusão pura (testável sem banco): listas ranqueadas → hits explicados.

    ``lex_rows``: (chunk_id, doc_id, title, uri, ts_rank, snippet), já ordenada.
    ``vec_rows``: (chunk_id, doc_id, title, uri, snippet, distância), já ordenada.
    """
    pool: dict[UUID, _Candidate] = {}
    for position, (chunk_id, doc_id, title, uri, score, snippet) in enumerate(lex_rows, 1):
        cand = pool.setdefault(chunk_id, _Candidate(doc_id, title, uri, snippet))
        cand.lexical_rank, cand.lexical_score = position, float(score)
        cand.snippet = snippet  # headline léxico é o melhor snippet
    for position, (chunk_id, doc_id, title, uri, snippet, dist) in enumerate(vec_rows, 1):
        cand = pool.setdefault(chunk_id, _Candidate(doc_id, title, uri, snippet))
        cand.vector_rank, cand.vector_similarity = position, 1.0 - float(dist)

    for cand in pool.values():
        cand.rrf = sum(
            1.0 / (k + rank) for rank in (cand.lexical_rank, cand.vector_rank) if rank is not None
        )

    ranked = sorted(pool.items(), key=lambda item: item[1].rrf, reverse=True)[:limit]
    return [
        SearchHit(
            chunk_id=chunk_id,
            document_id=c.document_id,
            title=c.title,
            uri=c.uri,
            snippet=c.snippet,
            score=c.rrf,
            explanation=_explain(c),
        )
        for chunk_id, c in ranked
    ]


def _explain(c: _Candidate) -> str:
    parts: list[str] = []
    if c.lexical_rank is not None:
        parts.append(f"léxico: #{c.lexical_rank} (ts_rank={c.lexical_score:.4f})")
    else:
        parts.append("léxico: sem casamento de termos")
    if c.vector_rank is not None:
        parts.append(f"vetorial: #{c.vector_rank} (similaridade={c.vector_similarity:.3f})")
    else:
        parts.append("vetorial: fora do top vetorial")
    parts.append(f"fusão RRF (k={_RRF_K}) = {c.rrf:.5f}")
    return "; ".join(parts)


# retrocompatibilidade com o nome da Etapa 3a
PostgresLexicalSearch = PostgresSearch

# canário anti-truncamento
