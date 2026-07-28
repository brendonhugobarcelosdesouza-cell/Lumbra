"""Extração de ESTRUTURA (issue #10): o pipeline preserva tabelas,
cabeçalhos e listas ao lado do texto plano.

Foco no caso que motivou o #10: uma tabela de fatura com vários totais.
Quando cada valor vive numa LINHA de tabela (rótulo↔valor preservado),
deixa de ser diluído num parágrafo de 400 tokens — a premissa de todo o
chunking ciente de estrutura.
"""

from lumbra.domain.document_structure import Block, BlockType, StructuredDoc, render_rows
from lumbra.pipeline.structure import extract_blocks

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class TestFallbackParagrafos:
    def test_texto_plano_vira_paragrafos(self):
        blocos = extract_blocks(
            raw=b"", mime="text/plain", text="Primeiro parágrafo.\n\nSegundo parágrafo."
        )
        assert [b.type for b in blocos] == [BlockType.PARAGRAPH, BlockType.PARAGRAPH]
        assert blocos[0].text == "Primeiro parágrafo."
        assert blocos[1].text == "Segundo parágrafo."

    def test_mime_desconhecido_degrada_sem_quebrar(self):
        blocos = extract_blocks(raw=b"", mime="application/octet-stream", text="conteúdo solto")
        assert blocos == [Block(type=BlockType.PARAGRAPH, text="conteúdo solto")]

    def test_nunca_vazio_quando_ha_texto(self):
        # mesmo pdf ilegível cai no fallback do texto plano já extraído
        blocos = extract_blocks(raw=b"nao-e-pdf", mime="application/pdf", text="resumo do doc")
        assert blocos
        assert blocos[0].text == "resumo do doc"


class TestMarkdown:
    def test_cabecalhos_com_nivel(self):
        blocos = extract_blocks(raw=b"", mime="text/markdown", text="# Título\n\n## Seção")
        assert blocos[0] == Block(type=BlockType.HEADING, text="Título", level=1)
        assert blocos[1] == Block(type=BlockType.HEADING, text="Seção", level=2)

    def test_lista_e_paragrafo(self):
        texto = "Introdução do doc.\n\n- primeiro item\n- segundo item"
        tipos = [b.type for b in extract_blocks(raw=b"", mime="text/markdown", text=texto)]
        assert tipos == [BlockType.PARAGRAPH, BlockType.LIST_ITEM, BlockType.LIST_ITEM]

    def test_tabela_preserva_linhas(self):
        texto = (
            "| Descrição | Valor |\n"
            "|---|---|\n"
            "| Total desta fatura | R$ 7.016,60 |\n"
            "| Total financiado | R$ 6.314,94 |\n"
        )
        blocos = extract_blocks(raw=b"", mime="text/markdown", text=texto)
        tabela = [b for b in blocos if b.type is BlockType.TABLE]
        assert len(tabela) == 1
        rows = tabela[0].rows
        # a linha separadora (|---|) não vira dado
        assert ("Total desta fatura", "R$ 7.016,60") in rows
        assert ("Total financiado", "R$ 6.314,94") in rows
        # o rótulo e o valor certos ficam JUNTOS na mesma unidade
        assert "Total desta fatura | R$ 7.016,60" in tabela[0].rendered()

    def test_bloco_de_codigo_fenced(self):
        texto = "Veja o exemplo:\n\n```python\nx = 1\n```"
        blocos = extract_blocks(raw=b"", mime="text/markdown", text=texto)
        codigo = [b for b in blocos if b.type is BlockType.CODE]
        assert codigo and codigo[0].text == "x = 1"


class TestRenderRows:
    def test_par_rotulo_valor_fica_junto(self):
        rows = (("Total desta fatura", "R$ 7.016,60"),)
        assert render_rows(rows) == "Total desta fatura | R$ 7.016,60"


class TestStructuredDoc:
    def test_render_ignora_blocos_vazios(self):
        doc = StructuredDoc(
            blocks=(
                Block(type=BlockType.HEADING, text="Fatura", level=1),
                Block(type=BlockType.PARAGRAPH, text=""),
                Block(type=BlockType.PARAGRAPH, text="Vencimento 10/04."),
            )
        )
        assert doc.rendered() == "Fatura\n\nVencimento 10/04."


class TestDocx:
    def test_cabecalho_paragrafo_e_tabela_em_ordem(self):
        docx = __import__("docx")
        from io import BytesIO

        documento = docx.Document()
        documento.add_heading("Resumo da Fatura", level=1)
        documento.add_paragraph("Vencimento em 10/04/2026.")
        tabela = documento.add_table(rows=2, cols=2)
        tabela.cell(0, 0).text = "Total desta fatura"
        tabela.cell(0, 1).text = "R$ 7.016,60"
        tabela.cell(1, 0).text = "Total financiado"
        tabela.cell(1, 1).text = "R$ 6.314,94"
        buffer = BytesIO()
        documento.save(buffer)

        blocos = extract_blocks(raw=buffer.getvalue(), mime=_DOCX_MIME, text="ignorado")
        assert blocos[0] == Block(type=BlockType.HEADING, text="Resumo da Fatura", level=1)
        assert blocos[1].type is BlockType.PARAGRAPH
        tab = [b for b in blocos if b.type is BlockType.TABLE]
        assert len(tab) == 1
        assert ("Total desta fatura", "R$ 7.016,60") in tab[0].rows
        # a ordem documental é preservada: cabeçalho antes da tabela
        assert blocos.index(tab[0]) > 0


# canário anti-truncamento
