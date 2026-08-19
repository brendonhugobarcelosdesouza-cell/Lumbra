"""Teste da composição de runtime.

Estes testes montam o Nó INTEIRO, e por isso precisam dizer em que modo —
senão herdam o ``.env`` de quem os roda. Herdando, eles passavam na máquina
do desenvolvedor com Docker aberto e falhavam com ele fechado, sempre pelo
mesmo motivo: ``ConnectionRefusedError`` ao procurar um Redis que o ``.env``
mandava usar. Um teste que muda de resultado conforme o ambiente de quem
executa não está testando o que diz testar — e o pior é que, no CI, os
serviços estão sempre de pé, então a falha só aparece para quem tem a
máquina limpa. É "funciona na minha máquina" ao contrário.
"""

import pytest
from fastapi.testclient import TestClient

from lumbra.api.main import create_default_app
from lumbra.shared.config import get_settings


@pytest.fixture(autouse=True)
def _sem_servicos_externos(monkeypatch):
    """Composição in-memory, explícita. Nada de Docker para rodar isto."""
    monkeypatch.setenv("LUMBRA_PERSISTENCE", "memory")
    monkeypatch.setenv("LUMBRA_EVENTBUS", "memory")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_default_app_protects_skills_and_serves_auth():
    with TestClient(create_default_app()) as client:
        assert client.get("/ready").status_code == 200
        # skills agora exige autenticação
        assert client.get("/api/v1/skills").status_code == 401
        # fluxo completo: registrar → logar → acessar
        client.post(
            "/api/v1/auth/register",
            json={"email": "dev@lumbra.app", "password": "senha-de-dev-forte"},
        )
        pair = client.post(
            "/api/v1/auth/token",
            data={"username": "dev@lumbra.app", "password": "senha-de-dev-forte"},
        ).json()
        resp = client.get(
            "/api/v1/skills", headers={"Authorization": f"Bearer {pair['access_token']}"}
        )
        assert resp.status_code == 200
        names = {s["name"] for s in resp.json()["skills"]}
        assert {"system.list_capabilities", "context.gather"} <= names


def test_eventbus_health_endpoint_is_public_and_shaped():
    """A saúde do Event Bus (L2-3) é pública (sem segredo, só números) e traz
    a forma esperada por consumidor."""
    with TestClient(create_default_app()) as client:
        resp = client.get("/api/v1/system/eventbus")
        assert resp.status_code == 200
        body = resp.json()
        assert body["kind"] in ("memory", "redis")
        assert isinstance(body["consumers"], list)
        for consumer in body["consumers"]:
            assert {"consumer", "dispatcher", "backlog", "pending", "dead_letters"} <= set(consumer)
            assert {"workers", "total_processed", "throughput_per_s"} <= set(consumer["dispatcher"])
