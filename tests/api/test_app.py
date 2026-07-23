"""Testes da fábrica da API (saúde, correlação, cabeçalhos de segurança)."""

import pytest
from fastapi.testclient import TestClient

from lumbra.api.app import create_app
from lumbra.shared.config import Settings


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app(Settings(_env_file=None, environment="test")))


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_ready_without_kernel(client):
    resp = client.get("/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["checks"] == {}


def test_correlation_id_generated_when_absent(client):
    resp = client.get("/health")
    assert resp.headers["X-Correlation-Id"]


def test_correlation_id_propagated_when_present(client):
    resp = client.get("/health", headers={"X-Correlation-Id": "abc-123"})
    assert resp.headers["X-Correlation-Id"] == "abc-123"


def test_security_headers_present(client):
    resp = client.get("/health")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Referrer-Policy"] == "no-referrer"


def test_docs_disabled_in_production():
    app = create_app(Settings(_env_file=None, environment="production"))
    client = TestClient(app)
    assert client.get("/docs").status_code == 404


def _kernel():
    from lumbra.adapters.eventbus.in_memory import InMemoryEventBus
    from lumbra.adapters.eventstore.in_memory import InMemoryEventStore
    from lumbra.adapters.permissions.static import StaticPermissionAdapter
    from lumbra.domain.events import EventRegistry
    from lumbra.kernel.core_module import KernelCoreModule
    from lumbra.kernel.kernel import LumbraKernel

    kernel = LumbraKernel(
        events=EventRegistry(),
        bus=InMemoryEventBus(),
        event_store=InMemoryEventStore(),
        permissions=StaticPermissionAdapter(default_allow=True),
    )
    kernel.register_module(KernelCoreModule())
    return kernel


def test_skills_endpoint_absent_without_auth_services():
    # sem AuthServices não há rotas de negócio — superfície mínima
    app = create_app(Settings(_env_file=None, environment="test"), kernel=_kernel())
    with TestClient(app) as client:  # with: dispara lifespan (start/stop do kernel)
        assert client.get("/api/v1/skills").status_code == 404


def test_ready_with_failing_kernel_check_returns_503():
    kernel = _kernel()

    async def bad() -> bool:
        return False

    kernel.add_readiness_check("db", bad)
    app = create_app(Settings(_env_file=None, environment="test"), kernel=kernel)
    with TestClient(app) as client:
        resp = client.get("/ready")
        assert resp.status_code == 503
        assert resp.json()["checks"] == {"db": False}
