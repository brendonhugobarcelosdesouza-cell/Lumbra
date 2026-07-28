"""Chunking ciente de estrutura (issue #10).

Duas garantias: (1) uma linha de tabela vira um chunk AUTODESCRITIVO —
com seção e cabeçalho — para que o par rótulo-valor certo seja recuperável
sozinho; (2) documento SEM tabela produz chunks idênticos ao chunker
legado (o golden set de prosa não pode se mover).
"""

from uuid import uuid4

from lumbra.adapters.chunking.basic import MarkdownChunker
from lumbra.adapters.chunking.structural import chunk_blocks
from lumbra.domain.document_structure import Block, BlockType
from lumbra.domain.pipeline import PipelineContext
from lumbra.pipeline.stages.chunk import ChunkStage
from lumbra.ports.document_store import DocumentRecord
from lumbra.ports.pipeline import StageInput


def _fatura_blocks() -> list[Block]:
    return [
        Block(type=BlockType.HEADING, text="Fatura", level=1),
        Block(type=BlockType.HEADING, text="Resumo", level=2),
        Block(type=BlockType.PARAGRAPH, text="Vencimento em 10/04/2026."),
        Block(
            type=BlockType.TABLE,
            page=1,
            rows=(
                ("Descrição", "Valor"),
                ("Total desta fatura", "R$ 7.016,60"),
                ("Total financiado", "R$ 6.314,94"),
                ("Demais faturas", "R$ 13.309,37"),
            ),
        ),
    ]


class TestLinhaDeTabelaAutodescritiva:
    def test_cada_linha_de_dados_vira_um_chunk(self):
        textos, metas = chunk_blocks(_fatura_blocks())
        de_tabela = [
            t for t, m in zip(textos, metas, strict=True) if m.block_type is BlockType.TABLE
        ]
        # 3 linhas de dados (a linha de cabeçalho não vira chunk sozinha)
        assert len(de_tabela) == 3

    def test_par_rotulo_valor_certo_fica_isolado_e_rotulado(self):
        textos, _ = chunk_blocks(_fatura_blocks())
        alvo = next(t for t in textos if "7.016,60" in t)
        # a unidade traz a seção, o cabeçalho da coluna e o par certo —
        # e NÃO mistura o 'financiado' nem o 'demais faturas'
        assert "[Fatura > Resumo]" in alvo
        assert "Descrição | Valor" in alvo
        assert "Total desta fatura | R$ 7.016,60" in alvo
        assert "6.314,94" not in alvo
        assert "13.309,37" not in alvo

    def test_metadado_estrutural_preenchido(self):
        textos, metas = chunk_blocks(_fatura_blocks())
        linha = next(m for t, m in zip(textos, metas, strict=True) if "7.016,60" in t)
        assert linha.block_type is BlockType.TABLE
        assert linha.section_path == ("Fatura", "Resumo")
        assert linha.page == 1

    def test_prosa_carrega_a_secao(self):
        textos, metas = chunk_blocks(_fatura_blocks())
        prosa = next(m for t, m in zip(textos, metas, strict=True) if "Vencimento" in t)
        assert prosa.block_type is BlockType.PARAGRAPH
        assert prosa.section_path == ("Fatura", "Resumo")


class TestDecisaoDoEstagio:
    """O ChunkStage só desvia do legado quando há tabela."""

    def _entrada(self, *, text: str, blocks: list[Block], mime: str) -> StageInput:
        doc = DocumentRecord(
            id=uuid4(),
            user_id=uuid4(),
            source="filesystem",
            uri="file:///x",
            mime_type=mime,
            title="x",
            doc_kind=None,
            metadata={},
            version=1,
            processing_state="pending",
        )
        ctx = PipelineContext(text=text, blocks=blocks)
        return StageInput(document=doc, raw=None, context=ctx)

    async def test_documento_sem_tabela_e_identico_ao_legado(self):
        # prosa markdown com cabeçalho, como o corpus do golden set
        texto = "# Aluguel\n\nO valor do aluguel é R$ 2.500,00 por mês.\n\nVence todo dia 5."
        blocks = [
            Block(type=BlockType.HEADING, text="Aluguel", level=1),
            Block(type=BlockType.PARAGRAPH, text="O valor do aluguel é R$ 2.500,00 por mês."),
            Block(type=BlockType.PARAGRAPH, text="Vence todo dia 5."),
        ]
        entrada = self._entrada(text=texto, blocks=blocks, mime="text/markdown")
        resultado = await ChunkStage(_registry()).run(entrada)
        legado = MarkdownChunker().chunk(texto)
        assert resultado.context.chunks == legado
        assert resultado.context.chunk_meta == []  # sem estrutura, colunas nulas

    async def test_documento_com_tabela_usa_estrutural(self):
        texto = "Fatura\n\nDescrição | Valor\nTotal desta fatura | R$ 7.016,60"
        entrada = self._entrada(text=texto, blocks=_fatura_blocks(), mime="application/pdf")
        resultado = await ChunkStage(_registry()).run(entrada)
        assert any("7.016,60" in c for c in resultado.context.chunks)
        assert any(m.block_type is BlockType.TABLE for m in resultado.context.chunk_meta)
        assert "structural" in resultado.message


def _registry():
    from lumbra.adapters.chunking.basic import default_chunker_registry

    return default_chunker_registry()


# canário anti-truncamento
