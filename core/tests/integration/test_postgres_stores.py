"""Integração: adapters PostgreSQL (users, event store, documents, knowledge graph)."""

import hashlib

import pytest

from lumbra.adapters.documents.postgres import PostgresDocumentStore
from lumbra.adapters.eventstore.postgres import PostgresEventStore
from lumbra.adapters.knowledge.postgres import PostgresKnowledgeGraph
from lumbra.adapters.users.postgres import PostgresUserStore
from lumbra.domain.events import EventPayload, EventRegistry
from lumbra.ports.document_store import IngestOutcome
from lumbra.ports.users import DuplicateEmailError, UserNotFoundError

pytestmark = pytest.mark.integration


async def _user(db):
    import uuid

    return await PostgresUserStore(db).create(
        email=f"it-{uuid.uuid4().hex[:8]}@lumbra.app", password_hash="h"
    )


class TestUsers:
    async def test_create_and_lookup(self, db):
        store = PostgresUserStore(db)
        user = await store.create(email="Brendon@Lumbra.App", password_hash="hash")
        assert user.email == "brendon@lumbra.app"
        assert (await store.get_by_email("BRENDON@lumbra.app")).id == user.id
        assert (await store.get_by_id(user.id)).email == user.email

    async def test_duplicate_email(self, db):
        store = PostgresUserStore(db)
        await store.create(email="dup@lumbra.app", password_hash="h")
        with pytest.raises(DuplicateEmailError):
            await store.create(email="DUP@lumbra.app", password_hash="h2")

    async def test_not_found(self, db):
        with pytest.raises(UserNotFoundError):
            await PostgresUserStore(db).get_by_email("ghost@lumbra.app")


class TestEventStore:
    async def test_append_read_and_idempotency(self, db):
        registry = EventRegistry()

        @registry.event("it.event_happened")
        class Happened(EventPayload):
            n: int

        store = PostgresEventStore(db)
        envelope = registry.envelope(Happened(n=1), producer="it@test")
        await store.append(envelope)
        await store.append(envelope)  # idempotente por event_id

        events = await store.read(event_types=("it.event_happened",))
        assert len(events) == 1
        wire = events[0]
        assert wire.event_id == envelope.event_id
        assert registry.decode(wire).n == 1  # roundtrip completo pelo banco


class TestDocuments:
    async def test_register_dedup_and_versioning(self, db):
        user = await _user(db)
        store = PostgresDocumentStore(db)
        h1 = hashlib.sha256(b"conteudo-v1").digest()
        h2 = hashlib.sha256(b"conteudo-v2").digest()

        doc, outcome = await store.register(
            user_id=user.id,
            source="filesystem",
            uri="file:///docs/a.pdf",
            content_hash=h1,
            mime_type="application/pdf",
            title="A",
        )
        assert outcome is IngestOutcome.NEW
        assert doc.version == 1

        same, outcome2 = await store.register(
            user_id=user.id, source="filesystem", uri="file:///docs/a.pdf", content_hash=h1
        )
        assert outcome2 is IngestOutcome.UNCHANGED
        assert same.id == doc.id

        v2, outcome3 = await store.register(
            user_id=user.id, source="filesystem", uri="file:///docs/a.pdf", content_hash=h2
        )
        assert outcome3 is IngestOutcome.NEW_VERSION
        assert v2.version == 2

        history = await store.versions(doc.id)
        assert [(v.version, v.parent_version, v.reason) for v in history] == [
            (2, 1, "content_changed"),
            (1, None, "initial"),
        ]

    async def test_replace_and_read_chunks(self, db):
        user = await _user(db)
        store = PostgresDocumentStore(db)
        doc, _ = await store.register(
            user_id=user.id,
            source="filesystem",
            uri="file:///docs/b.txt",
            content_hash=b"h1",
        )
        assert await store.replace_chunks(doc.id, ["primeiro", "segundo"]) == 2
        assert await store.replace_chunks(doc.id, ["novo"]) == 1
        assert await store.chunks_of(doc.id) == ["novo"]


class TestKnowledgeGraph:
    async def test_upsert_merges_by_normalized_name(self, db):
        user = await _user(db)
        kg = PostgresKnowledgeGraph(db)
        a = await kg.upsert_entity(user_id=user.id, kind="person", name="Ana Silva")
        b = await kg.upsert_entity(
            user_id=user.id, kind="person", name="ana silva", attrs={"role": "médica"}
        )
        assert a.id == b.id  # merge, não duplica
        assert b.attrs == {"role": "médica"}  # atributos mesclados

    async def test_relations_and_neighbors(self, db):
        user = await _user(db)
        kg = PostgresKnowledgeGraph(db)
        ana = await kg.upsert_entity(user_id=user.id, kind="person", name="Ana")
        acme = await kg.upsert_entity(user_id=user.id, kind="company", name="ACME")
        await kg.relate(from_id=ana.id, to_id=acme.id, rel="works_at")
        await kg.relate(from_id=ana.id, to_id=acme.id, rel="works_at")  # idempotente

        neighbors = await kg.neighbors(ana.id)
        assert neighbors == [("works_at", acme)]
        # direção inversa também é vizinhança
        assert ("works_at", ana) in await kg.neighbors(acme.id)

    async def test_find_by_kind_and_query(self, db):
        user = await _user(db)
        kg = PostgresKnowledgeGraph(db)
        await kg.upsert_entity(user_id=user.id, kind="medication", name="Amoxicilina")
        found = await kg.find(user_id=user.id, kind="medication", query="amoxi")
        assert [e.name for e in found] == ["Amoxicilina"]
