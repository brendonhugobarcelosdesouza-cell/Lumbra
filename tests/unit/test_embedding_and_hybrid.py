"""Estágio embedding (com gateway stub) e fusão RRF pura."""

from uuid import uuid4

import pytest

from lumbra.adapters.search.postgres import _tsquery_or, fuse_rrf
from lumbra.domain.pipeline import PipelineContext, PipelineError
from lumbra.pipeline.stages.embedding import EmbeddingStage
from lumbra.ports.ai import AIGatewayPort, EmbedRequest, EmbedResult
from lumbra.ports.document_store import DocumentRecord
from lumbra.ports.pipeline import StageInput


@pytest.fixture()
def fake_document() -> DocumentRecord:
    return DocumentRecord(
        id=uuid4(),
        user_id=uuid4(),
        source="filesystem",
        uri="file:///x.txt",
        mime_type="text/plain",
        title="x",
        doc_kind=None,
        metadata={},
        version=1,
        processing_state="pending",
    )


class StubGateway(AIGatewayPort):
    def __init__(self) -> None:
        self.requests: list[EmbedRequest] = []

    async def embed(self, request: EmbedRequest) -> EmbedResult:
        self.requests.append(request)
        return EmbedResult(
            vectors=tuple((float(i), 0.0) for i, _ in enumerate(request.texts)),
            dim=2,
            provider="stub",
            model="stub-model",
        )

    def trace(self, limit: int = 100):
        return []

    async def chat(self, request):
        raise NotImplementedError("stub não usa chat")

    def chat_stream(self, request):
        raise NotImplementedError("stub não usa chat_stream")

    def chat_providers(self):
        return []


class StubDocuments:
    def __init__(self) -> None:
        self.saved: dict = {}

    async def set_chunk_embeddings(self, document_id, vectors):
        self.saved[document_id] = list(vectors)
        return len(vectors)


def _payload(document, chunks):
    return StageInput(document=document, raw=None, context=PipelineContext(chunks=list(chunks)))


class TestEmbeddingStage:
    async def test_embeds_chunks_and_persists(self, fake_document):
        gateway, documents = StubGateway(), StubDocuments()
        stage = EmbeddingStage(gateway, documents)  # type: ignore[arg-type]
        outcome = await stage.run(_payload(fake_document, ["um", "dois", "três"]))
        assert outcome.metrics == {"embeddings": 3.0}
        assert len(documents.saved[fake_document.id]) == 3
        assert gateway.requests[0].purpose == "indexing"
        assert gateway.requests[0].privacy.value == "local_only"
        assert "stub-model" in outcome.message

    async def test_batches_large_documents(self, fake_document):
        gateway, documents = StubGateway(), StubDocuments()
        stage = EmbeddingStage(gateway, documents)  # type: ignore[arg-type]
        await stage.run(_payload(fake_document, [f"chunk {i}" for i in range(130)]))
        assert [len(r.texts) for r in gateway.requests] == [64, 64, 2]
        assert len(documents.saved[fake_document.id]) == 130

    async def test_requires_chunks(self, fake_document):
        stage = EmbeddingStage(StubGateway(), StubDocuments())  # type: ignore[arg-type]
        with pytest.raises(PipelineError, match="chunks"):
            await stage.run(_payload(fake_document, []))


def _lex(chunk_id, rank_score, snippet="s"):
    return (chunk_id, uuid4(), "t", "file:///x", rank_score, snippet)


def _vec(chunk_id, distance, snippet="s"):
    return (chunk_id, uuid4(), "t", "file:///x", snippet, distance)


class TestTsqueryOr:
    """A query léxica precisa ser tolerante: unir termos por OR, não AND.

    Bug do dogfooding (#5): 'total desta fatura' não casava com um documento
    que tem 'total' e 'fatura' porque o websearch_to_tsquery exigia TODOS os
    termos, e 'desta' não estava no texto. Com OR, qualquer termo conta e o
    ts_rank ordena por quantos casam.
    """

    def test_une_termos_por_ou(self):
        assert _tsquery_or("total desta fatura") == "total | desta | fatura"

    def test_ignora_pontuacao(self):
        assert _tsquery_or("valor: R$ 7.016,60?") == "valor | R | 7 | 016 | 60"

    def test_preserva_acentos(self):
        # o stemming/normalização é do to_tsquery('portuguese'), não nosso
        assert _tsquery_or("saldo à vista") == "saldo | à | vista"

    def test_query_vazia_ou_so_pontuacao(self):
        assert _tsquery_or("") == ""
        assert _tsquery_or("!!! ??? ...") == ""

    def test_termo_unico(self):
        assert _tsquery_or("fatura") == "fatura"


class TestRRFFusion:
    def test_hit_in_both_lists_outranks_single_list(self):
        both, lex_only, vec_only = uuid4(), uuid4(), uuid4()
        hits = fuse_rrf(
            [_lex(lex_only, 0.9), _lex(both, 0.5)],
            [_vec(both, 0.1), _vec(vec_only, 0.2)],
            limit=10,
        )
        assert hits[0].chunk_id == both  # 1/62 + 1/61 > 1/61
        assert {h.chunk_id for h in hits} == {both, lex_only, vec_only}

    def test_explanation_details_each_component(self):
        both = uuid4()
        hits = fuse_rrf([_lex(both, 0.42)], [_vec(both, 0.25)], limit=5)
        exp = hits[0].explanation
        assert "léxico: #1" in exp
        assert "ts_rank=0.4200" in exp
        assert "vetorial: #1" in exp
        assert "similaridade=0.750" in exp
        assert "RRF (k=60)" in exp

    def test_single_component_hits_are_explained_as_missing(self):
        lex_only = uuid4()
        (hit,) = fuse_rrf([_lex(lex_only, 0.9)], [], limit=5)
        assert "vetorial: fora do top vetorial" in hit.explanation

    def test_limit_and_ordering(self):
        rows = [_lex(uuid4(), 1.0 - i * 0.1) for i in range(5)]
        hits = fuse_rrf(rows, [], limit=3)
        assert len(hits) == 3
        assert hits[0].score > hits[1].score > hits[2].score

    def test_empty_inputs(self):
        assert fuse_rrf([], [], limit=5) == []


# canário anti-truncamento
