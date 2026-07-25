"""API de dispositivos: registro, pareamento, listagem, revogação e escopos.

Exercita o app real (``create_default_app`` em modo memória), então cobre o
wiring de ponta a ponta: rota → guarda de escopo → store → evento.
"""

import os

import pytest
from fastapi.testclient import TestClient

from lumbra.adapters.security import keys
from lumbra.adapters.security.tokens import TokenService
from lumbra.shared.config import get_settings

EMAIL = "dono@example.com"
PASSWORD = "senha-forte-de-teste"


@pytest.fixture()
def client():
    anterior = {k: os.environ.get(k) for k in ("LUMBRA_PERSISTENCE", "LUMBRA_EVENTBUS")}
    os.environ["LUMBRA_PERSISTENCE"] = "memory"
    os.environ["LUMBRA_EVENTBUS"] = "memory"
    get_settings.cache_clear()
    from lumbra.api.main import create_default_app

    with TestClient(create_default_app()) as c:
        yield c
    for k, v in anterior.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    get_settings.cache_clear()


def _login(client, email: str = EMAIL) -> str:
    client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
    pair = client.post("/api/v1/auth/token", data={"username": email, "password": PASSWORD}).json()
    return pair["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _register_body(**over) -> dict:
    corpo = {
        "name": "Pixel",
        "platform": "android",
        "public_key": keys.generate_keypair()[1],
        "scopes": ["chat:read", "memory:read"],
    }
    corpo.update(over)
    return corpo


class TestRegistroECicloDeVida:
    def test_registra_pendente_com_escopos(self, client):
        token = _login(client)
        r = client.post("/api/v1/devices", json=_register_body(), headers=_auth(token))
        assert r.status_code == 201
        corpo = r.json()
        assert corpo["state"] == "pending"
        assert set(corpo["scopes"]) == {"chat:read", "memory:read"}
        assert corpo["paired_at"] is None

    def test_parear_ativa(self, client):
        token = _login(client)
        did = client.post("/api/v1/devices", json=_register_body(), headers=_auth(token)).json()[
            "id"
        ]
        r = client.post(f"/api/v1/devices/{did}/pair", headers=_auth(token))
        assert r.status_code == 200
        assert r.json()["state"] == "active"
        assert r.json()["paired_at"] is not None

    def test_revogar_e_depois_nao_pareia(self, client):
        token = _login(client)
        did = client.post("/api/v1/devices", json=_register_body(), headers=_auth(token)).json()[
            "id"
        ]
        assert client.post(f"/api/v1/devices/{did}/revoke", headers=_auth(token)).status_code == 200
        r = client.post(f"/api/v1/devices/{did}/pair", headers=_auth(token))
        assert r.status_code == 409

    def test_lista_esconde_revogados(self, client):
        token = _login(client)
        a = client.post("/api/v1/devices", json=_register_body(), headers=_auth(token)).json()["id"]
        b = client.post("/api/v1/devices", json=_register_body(), headers=_auth(token)).json()["id"]
        client.post(f"/api/v1/devices/{b}/revoke", headers=_auth(token))
        visiveis = client.get("/api/v1/devices", headers=_auth(token)).json()
        assert [d["id"] for d in visiveis] == [a]
        todos = client.get("/api/v1/devices?include_revoked=true", headers=_auth(token)).json()
        assert len(todos) == 2


class TestValidacaoEIsolamento:
    def test_chave_publica_invalida_422(self, client):
        token = _login(client)
        r = client.post(
            "/api/v1/devices", json=_register_body(public_key="não-é-chave"), headers=_auth(token)
        )
        assert r.status_code == 422

    def test_escopo_malformado_422(self, client):
        token = _login(client)
        r = client.post(
            "/api/v1/devices", json=_register_body(scopes=["memory::read"]), headers=_auth(token)
        )
        assert r.status_code == 422

    def test_chave_duplicada_409(self, client):
        token = _login(client)
        corpo = _register_body()
        assert client.post("/api/v1/devices", json=corpo, headers=_auth(token)).status_code == 201
        assert client.post("/api/v1/devices", json=corpo, headers=_auth(token)).status_code == 409

    def test_dispositivo_de_outro_dono_e_404(self, client):
        token_a = _login(client, "a@example.com")
        did = client.post("/api/v1/devices", json=_register_body(), headers=_auth(token_a)).json()[
            "id"
        ]
        token_b = _login(client, "b@example.com")
        assert client.get(f"/api/v1/devices/{did}", headers=_auth(token_b)).status_code == 404


class TestAutenticacaoEEscopo:
    def test_sem_token_401(self, client):
        assert client.get("/api/v1/devices").status_code == 401

    def test_token_sem_escopo_403(self, client):
        _login(client)  # cria o usuário
        # token de "dispositivo/plugin" com escopo insuficiente para devices:*
        pair = client.post(
            "/api/v1/auth/token", data={"username": EMAIL, "password": PASSWORD}
        ).json()
        from lumbra.adapters.security.tokens import TokenType

        tokens = TokenService(get_settings().security)
        claims = tokens.verify(pair["access_token"], expected=TokenType.ACCESS)
        limitado = tokens.issue_pair(claims.subject, scopes=("chat:read",)).access_token
        r = client.get("/api/v1/devices", headers=_auth(limitado))
        assert r.status_code == 403
        assert "devices:read" in r.json()["detail"]


# canário anti-truncamento
