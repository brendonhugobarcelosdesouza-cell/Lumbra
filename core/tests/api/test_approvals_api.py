"""Rotas /api/v1/approvals (L2.0).

O 409 que a API já devolvia agora tem destino: o cliente lê a fila, mostra o
pedido ao usuário e volta com a decisão. O teste central é o ciclo inteiro —
409 na escrita, ticket na fila, aprovar, efeito real.
"""

from typing import Any
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from lumbra.adapters.approvals.in_memory import InMemoryApprovalStore
from lumbra.adapters.eventbus.in_memory import InMemoryEventBus
from lumbra.adapters.eventstore.in_memory import InMemoryEventStore
from lumbra.adapters.permissions.static import StaticPermissionAdapter
from lumbra.adapters.playbooks.in_memory import InMemoryPlaybookStore
from lumbra.api.approvals import build_approvals_router
from lumbra.api.playbooks import build_playbooks_router
from lumbra.domain.events import EventRegistry
from lumbra.kernel.approval import RecordingApprovalPolicy
from lumbra.kernel.approval_service import ApprovalService
from lumbra.kernel.kernel import LumbraKernel
from lumbra.modules.playbooks import PlaybookModule
from lumbra.ports.skills import RiskLevel

_CORPO = {
    "title": "Reindexar apos mudar a extracao",
    "when_to_use": "quando o pipeline de extracao muda e os chunks ficam obsoletos",
    "steps": ["Reiniciar o No", "Rodar reindexar com force"],
}


class _Claims:
    subject = uuid4()


async def _client(*, teto: RiskLevel = RiskLevel.LOW) -> TestClient:
    store = InMemoryApprovalStore()
    kernel = LumbraKernel(
        events=EventRegistry(),
        bus=InMemoryEventBus(),
        event_store=InMemoryEventStore(),
        permissions=StaticPermissionAdapter(default_allow=True),
        approval=RecordingApprovalPolicy(store, auto_ate=teto),
    )
    playbooks = InMemoryPlaybookStore()
    kernel.register_module(PlaybookModule(playbooks))
    await kernel.start()

    async def _require_subject() -> Any:
        return _Claims()

    app = FastAPI()
    app.include_router(build_playbooks_router(kernel, playbooks, _require_subject))
    app.include_router(
        build_approvals_router(ApprovalService(kernel.skills, store), _require_subject)
    )
    return TestClient(app)


class TestCicloDeConfirmacao:
    async def test_409_vira_pendente_e_o_sim_executa(self):
        c = await _client()
        assert c.post("/api/v1/playbooks", json=_CORPO).status_code == 409
        assert c.get("/api/v1/playbooks").json()["playbooks"] == []

        fila = c.get("/api/v1/approvals").json()["approvals"]
        assert len(fila) == 1
        assert fila[0]["action"] == "playbook.write"
        assert fila[0]["risk_level"] == "medium"
        # o pedido cru vai junto: o usuário decide vendo o que será feito
        assert fila[0]["payload"]["title"] == _CORPO["title"]

        ok = c.post(f"/api/v1/approvals/{fila[0]['id']}/approve")
        assert ok.status_code == 200, ok.json()
        assert ok.json()["approved"] is True
        assert ok.json()["result"]["title"] == _CORPO["title"]

        # efeito real, e a fila esvazia
        assert len(c.get("/api/v1/playbooks").json()["playbooks"]) == 1
        assert c.get("/api/v1/approvals").json()["approvals"] == []

    async def test_recusa_nao_executa(self):
        c = await _client()
        c.post("/api/v1/playbooks", json=_CORPO)
        pendente = c.get("/api/v1/approvals").json()["approvals"][0]
        assert c.post(f"/api/v1/approvals/{pendente['id']}/reject").json()["rejected"] is True
        assert c.get("/api/v1/playbooks").json()["playbooks"] == []

    async def test_decidir_duas_vezes_e_409(self):
        c = await _client()
        c.post("/api/v1/playbooks", json=_CORPO)
        pid = c.get("/api/v1/approvals").json()["approvals"][0]["id"]
        assert c.post(f"/api/v1/approvals/{pid}/approve").status_code == 200
        assert c.post(f"/api/v1/approvals/{pid}/approve").status_code == 409
        assert c.post(f"/api/v1/approvals/{pid}/reject").status_code == 409

    async def test_ticket_inexistente_e_404(self):
        c = await _client()
        assert c.post(f"/api/v1/approvals/{uuid4()}/approve").status_code == 404
        assert c.post(f"/api/v1/approvals/{uuid4()}/reject").status_code == 404


class TestSemRegressao:
    async def test_com_teto_alto_nada_fica_pendente(self):
        """Default do Nó: aprova tudo. Quem já usa não vê diferença."""
        c = await _client(teto=RiskLevel.CRITICAL)
        assert c.post("/api/v1/playbooks", json=_CORPO).status_code == 201
        assert c.get("/api/v1/approvals").json()["approvals"] == []


# canário anti-truncamento
