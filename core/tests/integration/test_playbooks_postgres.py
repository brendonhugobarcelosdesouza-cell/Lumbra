"""Integração: PostgresPlaybookStore (migração 0010, ADR-061).

Os unitários já cobrem a semântica pelo in-memory; aqui provamos que a
migração e o SQL real se comportam IGUAL — em especial a peça que muda de
implementação: a busca ponderada. No in-memory o 'quando usar' pesa 2.0 e o
corpo 0.5 em aritmética na mão; aqui isso vira tsvector com peso A/B e
ts_rank. Se essa tradução estiver errada, o playbook certo deixa de ser
recuperado — falha silenciosa, o pior tipo.
"""

import uuid

import pytest

from lumbra.adapters.playbooks.postgres import PostgresPlaybookStore
from lumbra.adapters.users.postgres import PostgresUserStore
from lumbra.ports.playbooks import Playbook, PlaybookOrigin
from lumbra.shared.ids import uuid7

pytestmark = pytest.mark.integration


async def _user(db):
    return await PostgresUserStore(db).create(
        email=f"pb-{uuid.uuid4().hex[:8]}@lumbra.app", password_hash="h"
    )


def _playbook(user_id, **over) -> Playbook:
    base = {
        "id": uuid7(),
        "user_id": user_id,
        "title": "Reindexar documentos após mudança de extração",
        "when_to_use": "quando o pipeline de extração muda e os chunks antigos ficam obsoletos",
        "steps": (
            "Reiniciar o Nó para carregar o código novo",
            "Rodar /reindexar na pasta com force=true",
        ),
        "pitfalls": ("Reindexar sem reiniciar o Nó reprocessa com o código ANTIGO",),
        "verification": "o valor certo aparece no topo do dev/search",
    }
    return Playbook(**{**base, **over})  # type: ignore[arg-type]


class TestPersistenciaEBusca:
    async def test_grava_e_recupera_pelo_quando_usar(self, db):
        store = PostgresPlaybookStore(db)
        user = await _user(db)
        gravado = await store.add(_playbook(user.id))

        achados = await store.search(user_id=user.id, query="chunks antigos obsoletos extração")
        assert [p.id for p in achados] == [gravado.id]
        # o round-trip preserva a estrutura, não só o texto
        assert achados[0].steps == gravado.steps
        assert achados[0].pitfalls == gravado.pitfalls
        assert achados[0].origin is PlaybookOrigin.USER

    async def test_consulta_tolerante_a_termo_ausente(self, db):
        """OR, não AND: uma palavra que não existe não pode zerar a busca —
        é a mesma regra da busca de documentos (tsquery_or)."""
        store = PostgresPlaybookStore(db)
        user = await _user(db)
        await store.add(_playbook(user.id))
        achados = await store.search(user_id=user.id, query="como faço para reindexar jabuticaba")
        assert len(achados) == 1

    async def test_gatilho_pesa_mais_que_o_corpo(self, db):
        """O playbook cujo 'quando usar' casa vence o que só menciona o termo
        nos passos. É a tradução do peso 2.0/0.5 para A/B."""
        store = PostgresPlaybookStore(db)
        user = await _user(db)
        no_corpo = await store.add(
            _playbook(
                user.id,
                title="Subir o ambiente local",
                when_to_use="quando for começar o dia de trabalho",
                steps=("Rodar docker compose up", "Conferir o backup do banco"),
                pitfalls=(),
            )
        )
        no_gatilho = await store.add(
            _playbook(
                user.id,
                title="Restaurar backup",
                when_to_use="quando o backup do banco precisar ser restaurado",
                steps=("Parar o Nó", "Rodar o restore"),
                pitfalls=(),
            )
        )
        achados = await store.search(user_id=user.id, query="backup do banco", limit=2)
        assert [p.id for p in achados] == [no_gatilho.id, no_corpo.id]

    async def test_consulta_sem_palavras_nao_quebra(self, db):
        store = PostgresPlaybookStore(db)
        user = await _user(db)
        await store.add(_playbook(user.id))
        assert await store.search(user_id=user.id, query="!!! ???") == []

    async def test_consulta_sem_relacao_volta_vazia(self, db):
        store = PostgresPlaybookStore(db)
        user = await _user(db)
        await store.add(_playbook(user.id))
        assert await store.search(user_id=user.id, query="receita de bolo de cenoura") == []


class TestPropriedadeEIsolamento:
    async def test_playbook_de_outro_usuario_nao_vaza(self, db):
        store = PostgresPlaybookStore(db)
        dono, outro = await _user(db), await _user(db)
        await store.add(_playbook(dono.id))
        assert await store.search(user_id=outro.id, query="extração chunks") == []
        assert await store.list_by_user(outro.id) == []

    async def test_apagar_exige_ser_dono(self, db):
        store = PostgresPlaybookStore(db)
        dono, outro = await _user(db), await _user(db)
        p = await store.add(_playbook(dono.id))
        assert await store.delete(p.id, user_id=outro.id) is False
        assert await store.delete(p.id, user_id=dono.id) is True
        assert await store.list_by_user(dono.id) == []

    async def test_apagar_inexistente_e_falso_sem_erro(self, db):
        store = PostgresPlaybookStore(db)
        user = await _user(db)
        assert await store.delete(uuid7(), user_id=user.id) is False


class TestUsoEOrdenacao:
    async def test_touch_contabiliza_uso(self, db):
        store = PostgresPlaybookStore(db)
        user = await _user(db)
        p = await store.add(_playbook(user.id))
        await store.touch(p.id)
        await store.touch(p.id)
        assert (await store.list_by_user(user.id))[0].uses == 2

    async def test_lista_mais_recente_primeiro(self, db):
        store = PostgresPlaybookStore(db)
        user = await _user(db)
        antigo = await store.add(_playbook(user.id, title="Procedimento antigo"))
        novo = await store.add(_playbook(user.id, title="Procedimento novo"))
        ids = [p.id for p in await store.list_by_user(user.id)]
        assert ids.index(novo.id) < ids.index(antigo.id)

    async def test_origem_agente_sobrevive_ao_round_trip(self, db):
        """Proveniência é o que sustenta a regra de aprovação (ADR-061):
        perder isso na persistência apagaria a diferença entre o que o
        usuário ditou e o que a plataforma inferiu."""
        store = PostgresPlaybookStore(db)
        user = await _user(db)
        execucao = uuid7()
        p = await store.add(
            _playbook(user.id, origin=PlaybookOrigin.AGENT, source_execution_id=execucao)
        )
        recuperado = (await store.list_by_user(user.id))[0]
        assert recuperado.id == p.id
        assert recuperado.origin is PlaybookOrigin.AGENT
        assert recuperado.source_execution_id == execucao


# canário anti-truncamento
