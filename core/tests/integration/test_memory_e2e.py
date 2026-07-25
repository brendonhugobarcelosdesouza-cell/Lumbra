"""E2E da memória: skills memory.* sobre PG real + recall semântico + API."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from lumbra.adapters.ai.fastembed_local import FastEmbedProvider
from lumbra.adapters.ai.gateway import AIGateway
from lumbra.adapters.eventbus.in_memory import InMemoryEventBus
from lumbra.adapters.eventstore.in_memory import InMemoryEventStore
from lumbra.adapters.memory.postgres import PostgresMemoryStore
from lumbra.adapters.metrics.in_memory import InMemoryMetrics
from lumbra.adapters.permissions.static import StaticPermissionAdapter
from lumbra.adapters.users.postgres import PostgresUserStore
from lumbra.domain.events import EventRegistry
from lumbra.kernel.kernel import LumbraKernel
from lumbra.modules.memory import MemoryModule
from lumbra.ports.skills import SkillContext

pytestmark = pytest.mark.integration

_provider = FastEmbedProvider()


@pytest.fixture()
async def stack(db):
    user = await PostgresUserStore(db).create(
        email=f"mem-{uuid.uuid4().hex[:8]}@lumbra.app", password_hash="h"
    )
    store = PostgresMemoryStore(db)
    gateway = AIGateway(embedding_providers=[_provider], metrics=InMemoryMetrics(), explain=None)
    kernel = LumbraKernel(
        events=EventRegistry(),
        bus=InMemoryEventBus(),
        event_store=InMemoryEventStore(),
        permissions=StaticPermissionAdapter(default_allow=True),
    )
    kernel.register_module(MemoryModule(store=store, gateway=gateway))
    await kernel.start()
    yield kernel, user, store
    await kernel.stop()


def _ctx(user) -> SkillContext:
    return SkillContext(subject=f"user:{user.id}", user_id=user.id)


class TestMemoryLifecycle:
    async def test_remember_semantic_recall_and_reconsolidation(self, stack):
        kernel, user, store = stack
        ctx = _ctx(user)
        r1 = await kernel.skills.execute(
            "memory.remember",
            {
                "content": "Deixei o carro na vaga 42 do estacionamento do shopping",
                "kind": "episodic",
            },
            context=ctx,
        )
        await kernel.skills.execute(
            "memory.remember",
            {
                "content": "A senha do wifi de casa é lumbra2026",
                "kind": "semantic",
                "importance": 0.9,
            },
            context=ctx,
        )
        assert r1.embedded  # type: ignore[attr-defined]

        # recall por paráfrase: 'automóvel' não aparece no conteúdo
        found = await kernel.skills.execute(
            "memory.search", {"query": "onde estacionei o automóvel"}, context=ctx
        )
        assert found.mode == "hybrid"  # type: ignore[attr-defined]
        hits = found.hits  # type: ignore[attr-defined]
        assert hits and "vaga 42" in hits[0]["content"]
        assert "força=" in hits[0]["explanation"]
        assert "RRF=" in hits[0]["explanation"]

        # reconsolidação: recall reforçou importância e access_count
        item = await store.get(uuid.UUID(hits[0]["memory_id"]))
        assert item.access_count == 1
        assert item.importance > 0.5

        # explicação da decisão registrada no Explain Engine
        assert kernel.explain.query(component="memory:search")

    async def test_forget_is_real_and_owned(self, stack):
        kernel, user, store = stack
        ctx = _ctx(user)
        r = await kernel.skills.execute(
            "memory.remember", {"content": "memória para apagar"}, context=ctx
        )
        memory_id = r.memory_id  # type: ignore[attr-defined]
        out = await kernel.skills.execute("memory.forget", {"memory_id": memory_id}, context=ctx)
        assert out.forgotten  # type: ignore[attr-defined]
        assert await store.list_by_user(user.id) == []

        # apagar memória de outro usuário: negado
        r2 = await kernel.skills.execute(
            "memory.remember", {"content": "minha memória"}, context=ctx
        )
        other = SkillContext(subject="user:intruso", user_id=uuid.uuid4())
        with pytest.raises(PermissionError):
            await kernel.skills.execute(
                "memory.forget",
                {"memory_id": r2.memory_id},
                context=other,  # type: ignore[attr-defined]
            )

    async def test_consolidation_expires_and_archives(self, stack):
        kernel, user, store = stack
        ctx = _ctx(user)
        # temporária já vencida
        await kernel.skills.execute(
            "memory.remember",
            {"content": "lembrete efêmero", "kind": "temporary", "expires_in_hours": 0.0},
            context=ctx,
        )
        # permanente nunca decai
        await kernel.skills.execute(
            "memory.remember",
            {"content": "aniversário da minha mãe é 3 de maio", "kind": "permanent"},
            context=ctx,
        )
        # episódica antiga e fraca (força < 0.05): importância baixa + 6 meias-vidas
        weak = await store.add(
            user_id=user.id,
            kind="episodic",
            content="detalhe irrelevante",
            importance=0.3,
            embedding=None,
            source_ref={},
            expires_at=None,
        )
        import sqlalchemy as sa

        from lumbra.adapters.persistence.models import MemoryItemModel

        async with store._db.session() as session:
            await session.execute(
                sa.update(MemoryItemModel)
                .where(MemoryItemModel.id == weak.id)
                .values(last_accessed_at=datetime.now(tz=UTC) - timedelta(days=180))
            )

        result = await kernel.skills.execute("memory.consolidate", {}, context=ctx)
        assert result.expired == 1  # type: ignore[attr-defined]
        assert result.archived == 1  # type: ignore[attr-defined]
        assert result.kept >= 1  # type: ignore[attr-defined]

        active = await store.list_by_user(user.id)
        assert {i.kind for i in active} == {"permanent"}
        # nada foi apagado: arquivadas continuam existindo
        everything = await store.list_by_user(user.id, include_archived=True)
        assert len(everything) == 3


class TestMemoryAPI:
    async def test_api_full_cycle(self, db, stack):
        from httpx import ASGITransport, AsyncClient

        from lumbra.adapters.security.passwords import PasswordHasher
        from lumbra.adapters.security.tokens import TokenService
        from lumbra.api.app import create_app
        from lumbra.api.auth import AuthServices, make_require_subject
        from lumbra.api.memory import build_memory_router
        from lumbra.shared.config import Settings

        kernel, _user, store = stack
        settings = Settings(_env_file=None, environment="test")
        auth = AuthServices(
            users=PostgresUserStore(db),
            passwords=PasswordHasher(),
            tokens=TokenService(settings.security),
        )
        app = create_app(
            settings,
            kernel=kernel,
            auth=auth,
            extra_routers=[build_memory_router(kernel, store, make_require_subject(auth.tokens))],
        )
        email = f"api-{uuid.uuid4().hex[:8]}@lumbra.app"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.post(
                "/api/v1/auth/register", json={"email": email, "password": "senha-super-forte"}
            )
            token = (
                await client.post(
                    "/api/v1/auth/token", data={"username": email, "password": "senha-super-forte"}
                )
            ).json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}

            created = await client.post(
                "/api/v1/memory",
                headers=headers,
                json={"content": "Consulta médica dia 30/07 às 14h", "kind": "prospective"},
            )
            assert created.status_code == 400  # camada inexistente → erro claro

            created = await client.post(
                "/api/v1/memory",
                headers=headers,
                json={"content": "Consulta médica dia 30/07 às 14h", "kind": "episodic"},
            )
            assert created.status_code == 201
            memory_id = created.json()["memory_id"]

            listing = (await client.get("/api/v1/memory", headers=headers)).json()
            assert len(listing["items"]) == 1

            recall = (
                await client.get(
                    "/api/v1/memory",
                    headers=headers,
                    params={"query": "quando é o médico?"},
                )
            ).json()
            assert recall["hits"] and recall["hits"][0]["memory_id"] == memory_id

            gone = await client.delete(f"/api/v1/memory/{memory_id}", headers=headers)
            assert gone.status_code == 200
            assert (await client.get("/api/v1/memory", headers=headers)).json()["items"] == []

            assert (await client.get("/api/v1/memory")).status_code == 401


# canário anti-truncamento
