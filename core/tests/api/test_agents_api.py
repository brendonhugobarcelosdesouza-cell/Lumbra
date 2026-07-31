"""Rotas /api/v1/agents (A7.5).

A regra que estas rotas existem para preservar: o cliente pede uma CAPABILITY,
nunca um agente por nome. Quem escolhe o provedor é o Orchestrator.
"""

from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lumbra.adapters.eventbus.in_memory import InMemoryEventBus
from lumbra.adapters.eventstore.in_memory import InMemoryEventStore
from lumbra.adapters.permissions.static import StaticPermissionAdapter
from lumbra.api.agents import build_agents_router
from lumbra.domain.events import EventRegistry
from lumbra.kernel.kernel import LumbraKernel
from lumbra.ports.capabilities import CapabilityProvider, CapabilitySpec, ProviderKind
from lumbra.ports.skills import (
    Skill,
    SkillContext,
    SkillInput,
    SkillManifest,
    SkillOutput,
)


class _In(SkillInput):
    query: str = ""


class _Out(SkillOutput):
    hits: tuple[dict[str, Any], ...] = ()


async def _busca(payload: SkillInput, _c: SkillContext) -> _Out:
    assert isinstance(payload, _In)
    return _Out(hits=({"snippet": f"achei {payload.query}"},))


class _Claims:
    # subject é o id do usuário (UUID), como no token real
    subject = uuid4()


@pytest.fixture()
async def client():
    kernel = LumbraKernel(
        events=EventRegistry(),
        bus=InMemoryEventBus(),
        event_store=InMemoryEventStore(),
        permissions=StaticPermissionAdapter(default_allow=True),
    )
    await kernel.skills.register(
        Skill(
            manifest=SkillManifest(name="doc.find", description="busca", provider="test"),
            input_model=_In,
            output_model=_Out,
            handler=_busca,
        )
    )
    kernel.capabilities.register_capability(
        CapabilitySpec(id="documents.search", description="busca nos documentos")
    )
    kernel.capabilities.register_provider(
        CapabilityProvider(
            capability_id="documents.search", kind=ProviderKind.SKILL, ref="doc.find"
        )
    )

    async def _require_subject() -> Any:
        return _Claims()

    # o kernel precisa estar iniciado: publicar skill.executed exige o registro
    # de eventos montado (mesmo caminho do produto)
    await kernel.start()
    app = FastAPI()
    app.include_router(build_agents_router(kernel, _require_subject))
    yield TestClient(app)
    await kernel.stop()


class TestCapabilities:
    def test_lista_capabilities_e_quem_atende(self, client):
        r = client.get("/api/v1/agents/capabilities")
        assert r.status_code == 200
        (cap,) = r.json()["capabilities"]
        assert cap["id"] == "documents.search"
        assert cap["provider_kind"] == "skill"
        assert cap["provider_ref"] == "doc.find"

    def test_lista_agentes_vazia_quando_nao_ha(self, client):
        assert client.get("/api/v1/agents").json() == {"agents": []}


class TestExecucao:
    def test_executa_por_capability(self, client):
        r = client.post(
            "/api/v1/agents/execute",
            json={"capability": "documents.search", "payload": {"query": "fatura"}},
        )
        assert r.status_code == 200, r.json()
        corpo = r.json()
        assert corpo["capability"] == "documents.search"
        assert corpo["provider_kind"] == "skill"
        assert corpo["layer"] == "capability_router"
        assert "fatura" in corpo["output"]["hits"][0]["snippet"]

    def test_capability_inexistente_da_404(self, client):
        r = client.post("/api/v1/agents/execute", json={"capability": "nao.existe"})
        assert r.status_code == 404

    def test_payload_invalido_da_400(self, client):
        r = client.post(
            "/api/v1/agents/execute",
            json={"capability": "documents.search", "payload": {"campo_errado": 1}},
        )
        assert r.status_code in (400, 422)


# canário anti-truncamento
