"""Rotas /api/v1/documents (P2-d).

O acervo — a coisa mais central da Lumbra — só era alcançável pelo Developer
Console, que vive fora do contrato. Indexar uma pasta exigia console de
desenvolvedor.

O teste que mais importa aqui é o do Nó SEM banco: a rota não pode sumir do
contrato conforme a configuração do servidor, ou o cliente gerado passaria a
depender de como cada Nó foi montado.
"""

from typing import Any
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from lumbra.adapters.eventbus.in_memory import InMemoryEventBus
from lumbra.adapters.eventstore.in_memory import InMemoryEventStore
from lumbra.adapters.permissions.static import StaticPermissionAdapter
from lumbra.api.documents import build_documents_router
from lumbra.domain.events import EventRegistry
from lumbra.kernel.kernel import LumbraKernel
from lumbra.ports.document_store import DocumentRecord, DocumentStorePort
from lumbra.shared.ids import uuid7

_USUARIO = uuid4()


class _Claims:
    subject = _USUARIO


class _AcervoFalso(DocumentStorePort):
    """Só o que a rota usa; o resto do port não é exercido aqui."""

    def __init__(self, registros: list[DocumentRecord]) -> None:
        self._registros = registros

    async def list_by_user(self, user_id, *, limit: int = 100) -> list[DocumentRecord]:
        return [d for d in self._registros if d.user_id == user_id][:limit]

    async def register(self, *a: Any, **k: Any) -> Any: ...
    async def versions(self, *a: Any, **k: Any) -> Any: ...
    async def chunks_of(self, *a: Any, **k: Any) -> Any: ...
    async def set_chunk_embeddings(self, *a: Any, **k: Any) -> Any: ...
    async def replace_chunks(self, *a: Any, **k: Any) -> Any: ...
    async def get(self, *a: Any, **k: Any) -> Any: ...


def _documento(**over: Any) -> DocumentRecord:
    base = {
        "id": uuid7(),
        "user_id": _USUARIO,
        "source": "filesystem",
        "uri": "file:///C:/faturas/itau.pdf",
        "mime_type": "application/pdf",
        "title": "Fatura Itaú",
        "doc_kind": "invoice",
        "metadata": {},
        "version": 1,
        "processing_state": "indexed",
    }
    return DocumentRecord(**{**base, **over})


async def _client(*, acervo: DocumentStorePort | None) -> TestClient:
    kernel = LumbraKernel(
        events=EventRegistry(),
        bus=InMemoryEventBus(),
        event_store=InMemoryEventStore(),
        permissions=StaticPermissionAdapter(default_allow=True),
    )
    await kernel.start()

    async def _require_subject() -> Any:
        return _Claims()

    app = FastAPI()
    app.include_router(build_documents_router(kernel, acervo, _require_subject))
    return TestClient(app)


class TestAcervo:
    async def test_lista_o_que_a_lumbra_leu(self):
        c = await _client(acervo=_AcervoFalso([_documento()]))
        corpo = c.get("/api/v1/documents").json()
        assert len(corpo["documents"]) == 1
        assert corpo["documents"][0]["title"] == "Fatura Itaú"
        assert corpo["documents"][0]["uri"].endswith("itau.pdf")

    async def test_estado_do_pipeline_vem_junto(self):
        """Saber que o arquivo foi visto mas ainda não indexado é a diferença
        entre 'a Lumbra não sabe' e 'a Lumbra ainda não terminou'."""
        c = await _client(acervo=_AcervoFalso([_documento(processing_state="pending")]))
        assert c.get("/api/v1/documents").json()["documents"][0]["processing_state"] == "pending"

    async def test_documento_de_outro_usuario_nao_aparece(self):
        c = await _client(acervo=_AcervoFalso([_documento(user_id=uuid4())]))
        assert c.get("/api/v1/documents").json()["documents"] == []


class TestSemBanco:
    """A rota não some conforme a configuração do servidor."""

    async def test_lista_responde_503_explicando(self):
        c = await _client(acervo=None)
        r = c.get("/api/v1/documents")
        assert r.status_code == 503
        assert "acervo indisponível" in r.json()["detail"]

    async def test_indexar_tambem_explica_em_vez_de_estourar(self):
        c = await _client(acervo=None)
        r = c.post("/api/v1/documents/index", json={"path": "C:/faturas"})
        assert r.status_code == 503

    async def test_caminho_vazio_e_rejeitado(self):
        c = await _client(acervo=_AcervoFalso([]))
        assert c.post("/api/v1/documents/index", json={"path": ""}).status_code == 422


# canário anti-truncamento
