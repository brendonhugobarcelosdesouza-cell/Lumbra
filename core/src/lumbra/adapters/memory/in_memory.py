"""Memory store in-memory: o Nó leve de desenvolvimento (P1-b.1).

Cumpre o `MemoryStorePort` fielmente para que a API de memória exista e
funcione sem Postgres — a mesma superfície de contrato nos dois modos
(docs/24, Regra 1). Semântica deliberadamente simples: a busca léxica é
por sobreposição de termos (substring/token), sem vetor. Fidelidade de
produção (tsvector + pgvector + RRF) permanece no adapter Postgres; este
existe para desenvolvimento, testes e para clientes exercitarem o contrato.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from lumbra.ports.memory import MemoryItem, MemoryNotFoundError, MemoryStorePort
from lumbra.shared.ids import uuid7

_PALAVRA = re.compile(r"\w+", re.UNICODE)


def _termos(texto: str) -> set[str]:
    return {t.lower() for t in _PALAVRA.findall(texto)}


class InMemoryMemoryStore(MemoryStorePort):
    def __init__(self) -> None:
        self._itens: dict[UUID, MemoryItem] = {}

    async def add(
        self,
        *,
        user_id: UUID,
        kind: str,
        content: str,
        importance: float,
        embedding: tuple[float, ...] | None,
        source_ref: dict[str, Any],
        expires_at: datetime | None,
    ) -> MemoryItem:
        now = datetime.now(tz=UTC)
        item = MemoryItem(
            id=uuid7(),
            user_id=user_id,
            kind=kind,
            content=content,
            importance=importance,
            source_ref=source_ref,
            access_count=0,
            expires_at=expires_at,
            last_accessed_at=now,
            created_at=now,
            archived_at=None,
        )
        self._itens[item.id] = item
        return item

    async def get(self, memory_id: UUID) -> MemoryItem:
        try:
            return self._itens[memory_id]
        except KeyError:
            raise MemoryNotFoundError from None

    async def get_many(self, memory_ids: Sequence[UUID]) -> dict[UUID, MemoryItem]:
        return {mid: self._itens[mid] for mid in memory_ids if mid in self._itens}

    async def touch_many(self, updates: Sequence[tuple[UUID, float]]) -> None:
        for memory_id, importance in updates:
            await self.touch(memory_id, new_importance=importance)

    async def touch(self, memory_id: UUID, *, new_importance: float) -> None:
        item = self._itens.get(memory_id)
        if item is None:
            return
        self._itens[memory_id] = item.model_copy(
            update={
                "last_accessed_at": datetime.now(tz=UTC),
                "access_count": item.access_count + 1,
                "importance": new_importance,
            }
        )

    async def list_by_user(
        self, user_id: UUID, *, kind: str | None = None, include_archived: bool = False
    ) -> list[MemoryItem]:
        itens = [
            i
            for i in self._itens.values()
            if i.user_id == user_id
            and (kind is None or i.kind == kind)
            and (include_archived or i.archived_at is None)
        ]
        return sorted(itens, key=lambda i: i.created_at, reverse=True)

    async def search_rows(
        self,
        *,
        user_id: UUID,
        query: str,
        query_vector: tuple[float, ...] | None,
        kinds: tuple[str, ...] | None,
        pool: int,
    ) -> tuple[list[tuple[UUID, int]], list[tuple[UUID, float]]]:
        alvo = _termos(query)
        marcados: list[tuple[int, UUID]] = []
        for item in self._itens.values():
            if item.user_id != user_id or item.archived_at is not None:
                continue
            if kinds and item.kind not in kinds:
                continue
            comuns = len(alvo & _termos(item.content))
            if comuns:
                marcados.append((comuns, item.id))
        # mais termos em comum primeiro; a posição (1-based) é o que o
        # domínio funde por RRF — vetor vazio (sem embeddings neste modo)
        marcados.sort(key=lambda t: t[0], reverse=True)
        lexical = [(mid, pos) for pos, (_, mid) in enumerate(marcados[:pool], 1)]
        return lexical, []

    async def forget(self, memory_id: UUID) -> None:
        if memory_id not in self._itens:
            raise MemoryNotFoundError
        del self._itens[memory_id]

    async def archive(self, memory_id: UUID) -> None:
        item = self._itens.get(memory_id)
        if item is None:
            raise MemoryNotFoundError
        self._itens[memory_id] = item.model_copy(update={"archived_at": datetime.now(tz=UTC)})

    async def expire_temporary(self, *, now: datetime) -> int:
        arquivadas = 0
        for memory_id, item in list(self._itens.items()):
            if item.archived_at is None and item.expires_at is not None and item.expires_at <= now:
                self._itens[memory_id] = item.model_copy(update={"archived_at": now})
                arquivadas += 1
        return arquivadas


# canário anti-truncamento
