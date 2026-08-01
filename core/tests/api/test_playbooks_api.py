"""Rotas /api/v1/playbooks (L1.5).

A memória procedural onde clientes alcançam — e, principalmente, o gate de
aprovação visível no contrato: escrever procedimento devolve 409 quando a
política exige confirmação humana (HITL), em vez de falhar obscuro.
"""

from typing import Any
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from lumbra.adapters.eventbus.in_memory import InMemoryEventBus
from lumbra.adapters.eventstore.in_memory import InMemoryEventStore
from lumbra.adapters.permissions.static import StaticPermissionAdapter
from lumbra.adapters.playbooks.in_memory import InMemoryPlaybookStore
from lumbra.api.playbooks import build_playbooks_router
from lumbra.domain.events import EventRegistry
from lumbra.kernel.approval import AutoApprovePolicy
from lumbra.kernel.kernel import LumbraKernel
from lumbra.modules.playbooks import PlaybookModule
from lumbra.ports.skills import RiskLevel

_CORPO = {
    "title": "Reindexar apos mudar a extracao",
    "when_to_use": "quando o pipeline de extracao muda e os chunks ficam obsoletos",
    "steps": ["Reiniciar o No", "Rodar reindexar com force", "Conferir no dev/search"],
    "pitfalls": ["Reindexar sem reiniciar reprocessa com o codigo antigo"],
    "verification": "o valor certo aparece no topo",
}


class _Claims:
    subject = uuid4()


async def _client(*, teto: RiskLevel = RiskLevel.CRITICAL) -> TestClient:
    kernel = LumbraKernel(
        events=EventRegistry(),
        bus=InMemoryEventBus(),
        event_store=InMemoryEventStore(),
        permissions=StaticPermissionAdapter(default_allow=True),
        approval=AutoApprovePolicy(auto_ate=teto),
    )
    store = InMemoryPlaybookStore()
    kernel.register_module(PlaybookModule(store))
    await kernel.start()

    async def _require_subject() -> Any:
        return _Claims()

    app = FastAPI()
    app.include_router(build_playbooks_router(kernel, store, _require_subject))
    return TestClient(app)


class TestCicloCompleto:
    async def test_cria_lista_busca_e_apaga(self):
        c = await _client()
        criado = c.post("/api/v1/playbooks", json=_CORPO)
        assert criado.status_code == 201, criado.json()
        pid = criado.json()["playbook_id"]

        listados = c.get("/api/v1/playbooks").json()["playbooks"]
        assert len(listados) == 1
        assert listados[0]["title"] == _CORPO["title"]
        assert listados[0]["origin"] == "user"

        achados = c.get("/api/v1/playbooks/search", params={"query": "chunks obsoletos"}).json()
        assert achados["hits"][0]["playbook_id"] == pid
        assert "Reiniciar o No" in achados["hits"][0]["content"]

        apagado = c.delete(f"/api/v1/playbooks/{pid}")
        assert apagado.json() == {"forgotten": True}
        assert c.get("/api/v1/playbooks").json()["playbooks"] == []

    async def test_busca_sem_relacao_volta_vazia(self):
        c = await _client()
        c.post("/api/v1/playbooks", json=_CORPO)
        achados = c.get("/api/v1/playbooks/search", params={"query": "receita de bolo"}).json()
        assert achados["hits"] == []

    async def test_titulo_curto_e_rejeitado(self):
        c = await _client()
        assert c.post("/api/v1/playbooks", json={**_CORPO, "title": "ab"}).status_code == 422

    async def test_sem_passos_e_rejeitado(self):
        c = await _client()
        assert c.post("/api/v1/playbooks", json={**_CORPO, "steps": []}).status_code == 422


class TestGateNoContrato:
    """O HITL fica VISÍVEL na API: 409 = falta confirmação humana."""

    async def test_escrita_devolve_409_quando_exige_confirmacao(self):
        c = await _client(teto=RiskLevel.LOW)
        r = c.post("/api/v1/playbooks", json=_CORPO)
        assert r.status_code == 409
        assert "aprova" in r.json()["detail"].lower()

    async def test_leitura_continua_livre_com_gate_ativo(self):
        c = await _client(teto=RiskLevel.LOW)
        assert c.get("/api/v1/playbooks/search", params={"query": "x"}).status_code == 200


# canário anti-truncamento
