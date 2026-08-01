"""PlaybookStorePort sobre PostgreSQL (L1.6) — o mesmo contrato do in-memory.

A busca é a tradução fiel da regra do in-memory para SQL: o 'quando usar'
pesa mais que o corpo. Lá isso era aritmética na mão (2.0 vs 0.5); aqui é o
``ts_rank`` com o mesmo vetor de pesos sobre um ``tsvector`` ponderado — o
banco faz stemming e ignora stopwords de brinde.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Float, func, literal_column, select, update

from lumbra.adapters.persistence.database import Database
from lumbra.adapters.persistence.fulltext import tsquery_or
from lumbra.adapters.persistence.models import PlaybookModel
from lumbra.ports.playbooks import Playbook, PlaybookOrigin, PlaybookStorePort

# {D, C, B, A} — mesma PROPORÇÃO do store in-memory (gatilho 4x o corpo:
# lá 2.0 contra 0.5). Aqui em escala 0..1 porque ts_rank recusa peso fora
# desse intervalo; o que importa para a ordenação é a razão, não a escala.
# Literal SQL tipado: ts_rank exige real[], e um bind param chega como texto.
_PESOS = literal_column("'{0.0, 0.0, 0.25, 1.0}'::real[]")


def _to_domain(row: PlaybookModel) -> Playbook:
    return Playbook(
        id=row.id,
        user_id=row.user_id,
        title=row.title,
        when_to_use=row.when_to_use,
        steps=tuple(row.steps),
        pitfalls=tuple(row.pitfalls),
        verification=row.verification,
        origin=PlaybookOrigin(row.origin),
        source_execution_id=row.source_execution_id,
        uses=row.uses,
        created_at=row.created_at,
    )


class PostgresPlaybookStore(PlaybookStorePort):
    def __init__(self, db: Database) -> None:
        self._db = db

    async def add(self, playbook: Playbook) -> Playbook:
        row = PlaybookModel(
            id=playbook.id,
            user_id=playbook.user_id,
            title=playbook.title,
            when_to_use=playbook.when_to_use,
            steps=list(playbook.steps),
            pitfalls=list(playbook.pitfalls),
            verification=playbook.verification,
            origin=playbook.origin.value,
            source_execution_id=playbook.source_execution_id,
            uses=playbook.uses,
            search_body="\n".join((*playbook.steps, *playbook.pitfalls)),
            created_at=playbook.created_at,
        )
        async with self._db.session() as session:
            session.add(row)
            await session.flush()
            return _to_domain(row)

    async def search(self, *, user_id: UUID, query: str, limit: int = 3) -> list[Playbook]:
        termos = tsquery_or(query)
        if not termos:  # consulta só com pontuação: nada a casar, sem SQL inválido
            return []
        tsquery = func.to_tsquery("portuguese", termos)
        rank = func.ts_rank(_PESOS, PlaybookModel.tsv, tsquery).cast(Float)
        stmt = (
            select(PlaybookModel)
            .where(
                PlaybookModel.user_id == user_id,  # isolamento entre usuários
                PlaybookModel.tsv.op("@@")(tsquery),
            )
            # empate desfeito pelo uso: procedimento que já ajudou vem antes
            .order_by(rank.desc(), PlaybookModel.uses.desc())
            .limit(limit)
        )
        async with self._db.session() as session:
            return [_to_domain(r) for r in (await session.execute(stmt)).scalars().all()]

    async def list_by_user(self, user_id: UUID, *, limit: int = 50) -> list[Playbook]:
        stmt = (
            select(PlaybookModel)
            .where(PlaybookModel.user_id == user_id)
            .order_by(PlaybookModel.created_at.desc())
            .limit(limit)
        )
        async with self._db.session() as session:
            return [_to_domain(r) for r in (await session.execute(stmt)).scalars().all()]

    async def delete(self, playbook_id: UUID, *, user_id: UUID) -> bool:
        async with self._db.session() as session:
            row = await session.get(PlaybookModel, playbook_id)
            if row is None or row.user_id != user_id:  # não vaza existência alheia
                return False
            await session.delete(row)
            return True

    async def touch(self, playbook_id: UUID) -> None:
        async with self._db.session() as session:
            await session.execute(
                update(PlaybookModel)
                .where(PlaybookModel.id == playbook_id)
                .values(uses=PlaybookModel.uses + 1)
            )


# canário anti-truncamento
