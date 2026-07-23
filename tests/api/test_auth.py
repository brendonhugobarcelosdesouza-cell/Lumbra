"""Testes de autenticação da API: registro, login, refresh, rotas protegidas."""

import pytest
from fastapi.testclient import TestClient

from lumbra.adapters.eventbus.in_memory import InMemoryEventBus
from lumbra.adapters.eventstore.in_memory import InMemoryEventStore
from lumbra.adapters.permissions.static import StaticPermissionAdapter
from lumbra.adapters.security.passwords import PasswordHasher
from lumbra.adapters.security.tokens import TokenService
from lumbra.adapters.users.in_memory import InMemoryUserStore
from lumbra.api.app import create_app
from lumbra.api.auth import AuthServices
from lumbra.domain.events import EventRegistry
from lumbra.kernel.core_module import KernelCoreModule
from lumbra.kernel.kernel import LumbraKernel
from lumbra.shared.config import Settings

EMAIL = "brendon@example.com"
PASSWORD = "senha-forte-de-teste"


def _make_app():
    settings = Settings(_env_file=None, environment="test")
    kernel = LumbraKernel(
        events=EventRegistry(),
        bus=InMemoryEventBus(),
        event_store=InMemoryEventStore(),
        permissions=StaticPermissionAdapter(default_allow=True),
    )
    kernel.register_module(KernelCoreModule())
    auth = AuthServices(
        users=InMemoryUserStore(),
        passwords=PasswordHasher(),
        tokens=TokenService(settings.security),
    )
    return create_app(settings, kernel=kernel, auth=auth), kernel


@pytest.fixture()
def client():
    app, _kernel = _make_app()
    with TestClient(app) as test_client:
        yield test_client


def _register_and_login(client) -> dict:
    resp = client.post("/api/v1/auth/register", json={"email": EMAIL, "password": PASSWORD})
    assert resp.status_code == 201
    resp = client.post("/api/v1/auth/token", data={"username": EMAIL, "password": PASSWORD})
    assert resp.status_code == 200
    return resp.json()


class TestRegistration:
    def test_register_success(self, client):
        resp = client.post("/api/v1/auth/register", json={"email": EMAIL, "password": PASSWORD})
        assert resp.status_code == 201
        assert resp.json()["email"] == EMAIL

    def test_duplicate_email_409(self, client):
        client.post("/api/v1/auth/register", json={"email": EMAIL, "password": PASSWORD})
        resp = client.post("/api/v1/auth/register", json={"email": EMAIL, "password": PASSWORD})
        assert resp.status_code == 409

    def test_short_password_rejected(self, client):
        resp = client.post("/api/v1/auth/register", json={"email": EMAIL, "password": "curta"})
        assert resp.status_code == 422


class TestLogin:
    def test_login_returns_bearer_pair(self, client):
        pair = _register_and_login(client)
        assert pair["token_type"] == "Bearer"
        assert pair["access_token"] != pair["refresh_token"]
        assert pair["expires_in"] == 900

    def test_wrong_password_401(self, client):
        client.post("/api/v1/auth/register", json={"email": EMAIL, "password": PASSWORD})
        resp = client.post("/api/v1/auth/token", data={"username": EMAIL, "password": "errada!!!"})
        assert resp.status_code == 401

    def test_unknown_email_401_same_shape(self, client):
        resp = client.post("/api/v1/auth/token", data={"username": "ghost@x.com", "password": "x"})
        assert resp.status_code == 401
        assert resp.json()["detail"] == "credenciais inválidas"  # sem vazamento de existência


class TestRefresh:
    def test_refresh_rotates_pair(self, client):
        pair = _register_and_login(client)
        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": pair["refresh_token"]})
        assert resp.status_code == 200
        assert resp.json()["access_token"] != pair["access_token"]

    def test_access_token_rejected_as_refresh(self, client):
        pair = _register_and_login(client)
        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": pair["access_token"]})
        assert resp.status_code == 401


class TestProtectedRoutes:
    def test_skills_requires_auth(self, client):
        assert client.get("/api/v1/skills").status_code == 401

    def test_skills_with_token(self, client):
        pair = _register_and_login(client)
        resp = client.get(
            "/api/v1/skills", headers={"Authorization": f"Bearer {pair['access_token']}"}
        )
        assert resp.status_code == 200
        names = {s["name"] for s in resp.json()["skills"]}
        assert "system.list_capabilities" in names

    def test_garbage_token_401(self, client):
        resp = client.get("/api/v1/skills", headers={"Authorization": "Bearer lixo.token.aqui"})
        assert resp.status_code == 401

    def test_health_and_ready_remain_public(self, client):
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 200


class TestAuditEvents:
    def test_registration_and_login_are_audited_in_event_store(self):
        import asyncio

        app, kernel = _make_app()
        with TestClient(app) as client:
            _register_and_login(client)
        stored = asyncio.run(kernel.event_store.read())
        types = {e.type for e in stored}
        assert "auth.registration_completed" in types
        assert "auth.login_succeeded" in types
        # eventos de auth carregam o user_id (trilha auditável por usuário)
        login = next(e for e in stored if e.type == "auth.login_succeeded")
        assert login.user_id is not None
