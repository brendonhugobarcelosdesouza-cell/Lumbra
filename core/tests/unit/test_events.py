"""Testes do envelope e registro de eventos de domínio."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from lumbra.domain.events import (
    DomainEvent,
    DuplicateEventTypeError,
    EventPayload,
    EventRegistry,
    InvalidEventTypeNameError,
    UnknownEventTypeError,
)


@pytest.fixture()
def reg() -> EventRegistry:
    return EventRegistry()


@pytest.fixture()
def message_received(reg: EventRegistry) -> type[EventPayload]:
    @reg.event("chat.message_received")
    class ChatMessageReceived(EventPayload):
        conversation_id: str
        text: str

    return ChatMessageReceived


class TestNaming:
    def test_valid_names_accepted(self, reg):
        @reg.event("health.dose_missed")
        class P(EventPayload):
            pass

        assert ("health.dose_missed", 1) in reg.known_types()

    @pytest.mark.parametrize(
        "bad", ["NoDots", "Upper.case", "chat.", ".received", "chat.Message", "a.b.C"]
    )
    def test_invalid_names_rejected(self, reg, bad):
        with pytest.raises(InvalidEventTypeNameError):
            reg.event(bad)

    def test_duplicate_registration_rejected(self, reg, message_received):
        with pytest.raises(DuplicateEventTypeError):
            reg.event("chat.message_received")

    def test_same_type_new_version_allowed(self, reg, message_received):
        @reg.event("chat.message_received", version=2)
        class V2(EventPayload):
            conversation_id: str
            parts: list[str]

        assert reg.payload_class("chat.message_received", 2) is V2


class TestEnvelope:
    def test_envelope_carries_type_and_version(self, reg, message_received):
        evt = reg.envelope(
            message_received(conversation_id="c1", text="olá"),
            producer="api@0.1.0",
        )
        assert evt.type == "chat.message_received"
        assert evt.schema_version == 1
        assert evt.context == "chat"
        assert evt.occurred_at.tzinfo is not None  # sempre timezone-aware

    def test_envelope_is_immutable(self, reg, message_received):
        evt = reg.envelope(message_received(conversation_id="c1", text="x"), producer="t")
        with pytest.raises(ValidationError):
            evt.type = "other.event"  # type: ignore[misc]

    def test_unregistered_payload_rejected(self, reg):
        class Rogue(EventPayload):
            pass

        with pytest.raises(UnknownEventTypeError):
            reg.envelope(Rogue(), producer="t")

    def test_follows_chains_correlation_and_causation(self, reg, message_received):
        cause = reg.envelope(message_received(conversation_id="c", text="a"), producer="t")
        effect = reg.envelope(
            message_received(conversation_id="c", text="b"), producer="t"
        ).follows(cause)
        assert effect.correlation_id == cause.correlation_id
        assert effect.causation_id == cause.event_id
        assert effect.event_id != cause.event_id


class TestPartitionKey:
    """Chave de particionamento (L2-1): vem do payload, com fallback."""

    def test_payload_sem_entidade_nao_tem_chave(self, reg, message_received):
        # o payload de teste não sobrescreve partition_key -> None
        evt = reg.envelope(message_received(conversation_id="c1", text="x"), producer="t")
        assert evt.partition_key is None

    def test_routing_key_cai_para_event_id_sem_chave(self, reg, message_received):
        evt = reg.envelope(message_received(conversation_id="c1", text="x"), producer="t")
        assert evt.routing_key == str(evt.event_id)

    def test_payload_com_entidade_define_a_chave(self, reg):
        @reg.event("doc.detected")
        class DocDetected(EventPayload):
            document_id: str

            def partition_key(self) -> str:
                return f"document:{self.document_id}"

        evt = reg.envelope(DocDetected(document_id="abc"), producer="t")
        assert evt.partition_key == "document:abc"
        assert evt.routing_key == "document:abc"

    def test_chave_sobrevive_a_serializacao(self, reg):
        """O consumidor (Redis) lê a chave do envelope serializado, sem
        redecodificar o payload tipado."""

        @reg.event("doc.indexed")
        class DocIndexed(EventPayload):
            document_id: str

            def partition_key(self) -> str:
                return f"document:{self.document_id}"

        evt = reg.envelope(DocIndexed(document_id="xyz"), producer="t")
        redecodificado = DomainEvent.model_validate_json(evt.model_dump_json())
        assert redecodificado.partition_key == "document:xyz"
        assert redecodificado.routing_key == "document:xyz"

    def test_mesma_entidade_mesma_chave_ordem_garantida(self, reg):
        """Dois eventos do mesmo documento compartilham a chave -> mesma
        partição -> ordem preservada."""

        @reg.event("doc.step")
        class DocStep(EventPayload):
            document_id: str
            step: int

            def partition_key(self) -> str:
                return f"document:{self.document_id}"

        e1 = reg.envelope(DocStep(document_id="d", step=1), producer="t")
        e2 = reg.envelope(DocStep(document_id="d", step=2), producer="t")
        assert e1.routing_key == e2.routing_key

    def test_invalid_type_name_in_raw_envelope(self):
        with pytest.raises(ValidationError):
            DomainEvent(type="Bad Name", schema_version=1, producer="t", payload={})


class TestDecode:
    def test_roundtrip(self, reg, message_received):
        original = message_received(conversation_id="c1", text="olá")
        envelope = reg.envelope(original, producer="t", user_id=uuid4())
        # simula transporte: serializa e re-hidrata o envelope
        wire = DomainEvent.model_validate_json(envelope.model_dump_json())
        decoded = reg.decode(wire)
        assert decoded == original

    def test_unknown_type_fails_loudly(self, reg):
        raw = DomainEvent(type="ghost.event_happened", schema_version=1, producer="t", payload={})
        with pytest.raises(UnknownEventTypeError):
            reg.decode(raw)

    def test_malformed_payload_fails_validation(self, reg, message_received):
        raw = DomainEvent(
            type="chat.message_received",
            schema_version=1,
            producer="t",
            payload={"conversation_id": "c1"},  # falta 'text'
        )
        with pytest.raises(ValidationError):
            reg.decode(raw)

    def test_extra_fields_forbidden(self, reg, message_received):
        raw = DomainEvent(
            type="chat.message_received",
            schema_version=1,
            producer="t",
            payload={"conversation_id": "c1", "text": "x", "hacker": True},
        )
        with pytest.raises(ValidationError):
            reg.decode(raw)
