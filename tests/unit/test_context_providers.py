"""Provedores de contexto — foco na diversidade de fontes.

O bug que estes testes travam foi encontrado no dogfooding: uma pergunta
ampla trazia 5 trechos, todos do mesmo documento (o mais longo), como se
os demais nem existissem. A busca estava certa; faltava distribuir as
vagas entre documentos.
"""

from types import SimpleNamespace
from uuid import uuid4

from lumbra.context.providers import DocumentContextProvider, _diversify


def _hit(doc: str, chunk: str, score: float) -> dict:
    return {
        "chunk_id": chunk,
        "document_id": doc,
        "title": f"doc-{doc}",
        "uri": f"file:///{doc}.txt",
        "snippet": f"trecho {chunk}",
        "score": score,
        "explanation": "teste",
    }


class TestDiversify:
    def test_um_documento_nao_ocupa_todas_as_vagas(self):
        """O caso do dogfooding: doc longo domina a relevância bruta.

        A garantia é que TODAS as fontes com trechos aparecem. As vagas
        que sobram (B e C só têm um trecho cada) voltam ao doc mais
        relevante — variedade primeiro, relevância no resto."""
        hits = [_hit("A", f"a{i}", 1.0 - i * 0.01) for i in range(10)]
        hits += [_hit("B", "b0", 0.30), _hit("C", "c0", 0.20)]
        escolhidos = _diversify(hits, limite=5, por_documento=2)
        docs = {h["document_id"] for h in escolhidos}
        assert docs == {"A", "B", "C"}, "as três fontes deveriam aparecer"
        # na primeira rodada A é limitado a 2, dando espaço a B e C; sem
        # esse teto A levaria as 5 vagas (o bug original)
        primeiros_tres = {h["document_id"] for h in escolhidos[:4]}
        assert {"B", "C"} <= primeiros_tres

    def test_preenche_as_vagas_mesmo_com_poucas_fontes(self):
        """Diversidade não pode custar relevância: com um só documento,
        as vagas se enchem com os melhores trechos dele."""
        hits = [_hit("A", f"a{i}", 1.0 - i * 0.01) for i in range(10)]
        escolhidos = _diversify(hits, limite=5, por_documento=2)
        assert len(escolhidos) == 5
        assert all(h["document_id"] == "A" for h in escolhidos)

    def test_preserva_ordem_de_relevancia(self):
        hits = [_hit("A", "a0", 0.9), _hit("B", "b0", 0.8), _hit("A", "a1", 0.7)]
        escolhidos = _diversify(hits, limite=3, por_documento=2)
        assert [h["chunk_id"] for h in escolhidos] == ["a0", "b0", "a1"]

    def test_nunca_repete_um_trecho(self):
        hits = [_hit("A", "a0", 0.9), _hit("A", "a0", 0.9)]  # id repetido
        escolhidos = _diversify(hits, limite=5, por_documento=5)
        assert len(escolhidos) == 1

    def test_lista_vazia(self):
        assert _diversify([], limite=5, por_documento=2) == []

    def test_trecho_certo_de_documento_denso_entra(self):
        """Regressão do dogfooding: numa fatura densa, o RESUMO com o valor
        total era o 3º melhor trecho do documento. Com teto 2 e outros
        documentos competindo, ele ficava de fora e o assistente respondia
        sem o total. Teto 3 e orçamento 8 garantem que ele entre."""
        fatura = [_hit("fatura", f"f{i}", 0.42 - i * 0.01) for i in range(6)]
        resumo = fatura[2]  # o trecho com o total é o 3º melhor da fatura
        outros = [_hit("dindin", "d0", 0.34), _hit("salario", "s0", 0.30)]
        # ordem por relevância global (como chega da busca)
        candidatos = [fatura[0], fatura[1], resumo, outros[0], *fatura[3:], outros[1]]
        escolhidos = _diversify(candidatos, limite=8, por_documento=3)
        assert resumo in escolhidos, "o resumo com o total precisa entrar no contexto"


class _FakeSkills:
    """Registro de skills falso que devolve hits controlados."""

    def __init__(self, hits: list[dict]) -> None:
        self._hits = hits
        self.limite_pedido: int | None = None

    async def execute(self, name, payload, context):
        assert name == "document.find"
        self.limite_pedido = payload["limit"]
        return SimpleNamespace(hits=tuple(self._hits))


class TestDocumentContextProvider:
    async def test_diversifica_ao_prover_contexto(self):
        hits = [_hit("A", f"a{i}", 1.0 - i * 0.01) for i in range(10)]
        hits += [_hit("B", "b0", 0.30)]
        provider = DocumentContextProvider(_FakeSkills(hits), limit=3, per_document=2)  # type: ignore[arg-type]
        req = SimpleNamespace(user_id=uuid4(), query="qualquer")
        frags = await provider.provide(req)  # type: ignore[arg-type]
        docs = {f.metadata["document_id"] for f in frags}
        assert docs == {"A", "B"}
        assert len(frags) == 3

    async def test_sobrebusca_para_ter_material(self):
        """Pede mais candidatos do que as vagas — senão não há o que
        diversificar."""
        skills = _FakeSkills([_hit("A", "a0", 0.9)])
        provider = DocumentContextProvider(skills, limit=5, per_document=2)  # type: ignore[arg-type]
        req = SimpleNamespace(user_id=uuid4(), query="x")
        await provider.provide(req)  # type: ignore[arg-type]
        assert skills.limite_pedido is not None and skills.limite_pedido >= 20

    async def test_sem_usuario_nao_busca(self):
        provider = DocumentContextProvider(_FakeSkills([]), limit=5)  # type: ignore[arg-type]
        req = SimpleNamespace(user_id=None, query="x")
        assert await provider.provide(req) == []  # type: ignore[arg-type]


# canário anti-truncamento
