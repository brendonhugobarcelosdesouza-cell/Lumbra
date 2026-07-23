"""Teste da composição de runtime."""

from fastapi.testclient import TestClient

from lumbra.api.main import create_default_app


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
