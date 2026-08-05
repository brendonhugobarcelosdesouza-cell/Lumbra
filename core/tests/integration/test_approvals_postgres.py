"""Integração: PostgresApprovalStore (migração 0011, ADR-063 revisado).

Existe por causa de um bug real: a fila era in-memory, o Nó reiniciou entre
listar o pedido e decidir, e a aprovação virou 404 sem explicação. O teste
que mais importa aqui é o da decisão única — no in-memory ela era garantida
por um `if`; no Postgres, pelo próprio UPDATE.
"""

import asyncio
import uuid

import pytest

from lumbra.adapters.approvals.postgres import PostgresApprovalStore
from lumbra.adapters.users.postgres import PostgresUserStore
from lumbra.ports.approval import (
    ApprovalAlreadyDecidedError,
    ApprovalNotFoundError,
    ApprovalState,
    ApprovalTicket,
)
from lumbra.ports.skills import RiskLevel
from lumbra.shared.ids import uuid7

pytestmark = pytest.mark.integration


async def _user(db):
    return await PostgresUserStore(db).create(
        email=f"ap-{uuid.uuid4().hex[:8]}@lumbra.app", password_hash="h"
    )


def _ticket(user_id, **over) -> ApprovalTicket:
    base = {
        "id": uuid7(),
        "user_id": user_id,
        "action": "playbook.write",
        "subject": f"user:{user_id}",
        "risk_level": RiskLevel.MEDIUM,
        "reason": "execucao solicitada",
        "payload": {"title": "Reindexar", "steps": ["Reiniciar o No"]},
    }
    return ApprovalTicket(**{**base, **over})  # type: ignore[arg-type]


class TestPersistencia:
    async def test_grava_lista_e_preserva_o_pedido_inteiro(self, db):
        store = PostgresApprovalStore(db)
        user = await _user(db)
        criado = await store.add(_ticket(user.id))

        pendentes = await store.list_pending(user.id)
        assert [t.id for t in pendentes] == [criado.id]
        # sem o payload, o "sim" nao teria o que reexecutar
        assert pendentes[0].payload["title"] == "Reindexar"
        assert pendentes[0].payload["steps"] == ["Reiniciar o No"]
        assert pendentes[0].risk_level is RiskLevel.MEDIUM
        assert pendentes[0].state is ApprovalState.PENDING

    async def test_decidido_sai_da_fila_mas_continua_existindo(self, db):
        """O historico fica: 'o usuario recusou' e informacao de auditoria."""
        store = PostgresApprovalStore(db)
        user = await _user(db)
        t = await store.add(_ticket(user.id))
        await store.resolve(t.id, user_id=user.id, state=ApprovalState.REJECTED)

        assert await store.list_pending(user.id) == []
        guardado = await store.get(t.id, user_id=user.id)
        assert guardado.state is ApprovalState.REJECTED
        assert guardado.decided_at is not None


class TestDecisaoUnica:
    async def test_decidir_duas_vezes_levanta(self, db):
        store = PostgresApprovalStore(db)
        user = await _user(db)
        t = await store.add(_ticket(user.id))
        await store.resolve(t.id, user_id=user.id, state=ApprovalState.APPROVED)
        with pytest.raises(ApprovalAlreadyDecidedError):
            await store.resolve(t.id, user_id=user.id, state=ApprovalState.APPROVED)

    async def test_corrida_so_uma_vence(self, db):
        """Duas abas clicando 'Aprovar' juntas nao podem executar a acao duas
        vezes. Aqui a trava e o proprio UPDATE ... WHERE state='pending'."""
        store = PostgresApprovalStore(db)
        user = await _user(db)
        t = await store.add(_ticket(user.id))

        resultados = await asyncio.gather(
            store.resolve(t.id, user_id=user.id, state=ApprovalState.APPROVED),
            store.resolve(t.id, user_id=user.id, state=ApprovalState.APPROVED),
            return_exceptions=True,
        )
        vencedores = [r for r in resultados if isinstance(r, ApprovalTicket)]
        perdedores = [r for r in resultados if isinstance(r, Exception)]
        assert len(vencedores) == 1, resultados
        assert len(perdedores) == 1


class TestIsolamento:
    async def test_pedido_alheio_e_indistinguivel_de_inexistente(self, db):
        store = PostgresApprovalStore(db)
        dono, outro = await _user(db), await _user(db)
        t = await store.add(_ticket(dono.id))

        assert await store.list_pending(outro.id) == []
        with pytest.raises(ApprovalNotFoundError):
            await store.get(t.id, user_id=outro.id)
        with pytest.raises(ApprovalNotFoundError):
            await store.resolve(t.id, user_id=outro.id, state=ApprovalState.APPROVED)
        # e continua pendente para o dono
        assert len(await store.list_pending(dono.id)) == 1

    async def test_inexistente_levanta_not_found(self, db):
        store = PostgresApprovalStore(db)
        user = await _user(db)
        with pytest.raises(ApprovalNotFoundError):
            await store.get(uuid7(), user_id=user.id)


# canário anti-truncamento
