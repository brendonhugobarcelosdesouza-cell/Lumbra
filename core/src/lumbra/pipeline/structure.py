"""Extração de ESTRUTURA por formato: bytes/texto → lista de blocos.

Complementa ``stages.extract`` (que produz o texto plano, o contrato
estável). Aqui reconstruímos a estrutura que a linearização perde:
tabelas com suas linhas, cabeçalhos com sua profundidade, listas,
código. Cada extrator DEGRADA para parágrafos em vez de levantar erro —
estrutura é um ganho aditivo, nunca um motivo para falhar a indexação.
"""

from __future__ import annotations

import io
import re
from collections.abc import Callable
from typing import Any

from lumbra.domain.document_structure import Block, BlockType, render_rows
from lumbra.pipeline.text_quality import legibilidade
from lumbra.shared.logging import get_logger

_log = get_logger("lumbra.pipeline.structure")

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_MARKDOWN_MIMES = {"text/markdown", "text/x-markdown"}
_CODE_MIMES = {"application/x-code"}

_HEADING_MD = re.compile(r"^(#{1,6})\s+(.*)$")
_LIST_MD = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")
_FENCE_MD = re.compile(r"^\s*(?:```|~~~)")


def extract_blocks(*, raw: bytes, mime: str, text: str) -> list[Block]:
    """Blocos do documento, escolhendo a estratégia pelo mime. Nunca
    levanta: qualquer falha vira parágrafos do texto plano já extraído."""
    try:
        if mime == "application/pdf":
            blocos = _pdf_blocks(raw)
        elif mime == _DOCX_MIME:
            blocos = _docx_blocks(raw)
        elif mime in _MARKDOWN_MIMES:
            blocos = _markdown_blocks(text)
        elif mime in _CODE_MIMES or mime.startswith("text/x-"):
            blocos = _code_blocks(text)
        else:  # text/plain, json, xml e desconhecidos legíveis
            blocos = _plain_blocks(text)
    except Exception as exc:  # nenhum formato pode derrubar a indexação
        _log.warning("estrutura_degradou_para_paragrafos", mime=mime, erro=repr(exc))
        return _plain_blocks(text)
    return blocos or _plain_blocks(text)


def _plain_blocks(text: str) -> list[Block]:
    """Fallback universal: parágrafos separados por linha em branco."""
    return [Block(type=BlockType.PARAGRAPH, text=p) for p in _paragrafos(text)]


def _code_blocks(text: str) -> list[Block]:
    corpo = text.strip()
    return [Block(type=BlockType.CODE, text=corpo)] if corpo else []


def _paragrafos(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


# --------------------------------------------------------------------------- #
# Markdown — estrutura nativa (cabeçalhos, listas, tabelas, código)            #
# --------------------------------------------------------------------------- #
def _markdown_blocks(text: str) -> list[Block]:
    blocos: list[Block] = []
    buffer: list[str] = []
    tabela: list[str] = []
    dentro_codigo = False
    codigo: list[str] = []

    def _flush_paragrafo() -> None:
        if buffer:
            juntado = " ".join(linha.strip() for linha in buffer).strip()
            if juntado:
                blocos.append(Block(type=BlockType.PARAGRAPH, text=juntado))
            buffer.clear()

    def _flush_tabela() -> None:
        if tabela:
            rows = _parse_md_table(tabela)
            if rows:
                blocos.append(Block(type=BlockType.TABLE, rows=rows, text=render_rows(rows)))
            tabela.clear()

    for linha in text.splitlines():
        if _FENCE_MD.match(linha):
            if dentro_codigo:
                blocos.append(Block(type=BlockType.CODE, text="\n".join(codigo)))
                codigo.clear()
                dentro_codigo = False
            else:
                _flush_paragrafo()
                _flush_tabela()
                dentro_codigo = True
            continue
        if dentro_codigo:
            codigo.append(linha)
            continue
        if linha.strip().startswith("|") and "|" in linha.strip()[1:]:
            _flush_paragrafo()
            tabela.append(linha)
            continue
        _flush_tabela()
        cabecalho = _HEADING_MD.match(linha)
        if cabecalho:
            _flush_paragrafo()
            blocos.append(
                Block(
                    type=BlockType.HEADING,
                    text=cabecalho.group(2).strip(),
                    level=len(cabecalho.group(1)),
                )
            )
            continue
        item = _LIST_MD.match(linha)
        if item:
            _flush_paragrafo()
            blocos.append(Block(type=BlockType.LIST_ITEM, text=item.group(1).strip()))
            continue
        if not linha.strip():
            _flush_paragrafo()
            continue
        buffer.append(linha)

    if dentro_codigo and codigo:
        blocos.append(Block(type=BlockType.CODE, text="\n".join(codigo)))
    _flush_paragrafo()
    _flush_tabela()
    return blocos


def _parse_md_table(linhas: list[str]) -> tuple[tuple[str, ...], ...]:
    rows: list[tuple[str, ...]] = []
    for linha in linhas:
        celulas = [c.strip() for c in linha.strip().strip("|").split("|")]
        # pula a linha separadora (|---|:--:|)
        if celulas and all(set(c) <= {"-", ":", " "} and c for c in celulas):
            continue
        rows.append(tuple(celulas))
    return tuple(rows)


# --------------------------------------------------------------------------- #
# DOCX — parágrafos (com nível de cabeçalho pelo estilo) e tabelas, em ordem   #
# --------------------------------------------------------------------------- #
def _docx_blocks(raw: bytes) -> list[Block]:
    import docx
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    documento = docx.Document(io.BytesIO(raw))
    blocos: list[Block] = []
    # iterar o corpo preserva a ORDEM real entre parágrafos e tabelas
    for filho in documento.element.body.iterchildren():
        if filho.tag == qn("w:p"):
            paragrafo = Paragraph(filho, documento)
            texto = paragrafo.text.strip()
            if not texto:
                continue
            estilo = (paragrafo.style.name if paragrafo.style else "") or ""
            nivel = _nivel_de_estilo(estilo)
            if nivel is not None:
                blocos.append(Block(type=BlockType.HEADING, text=texto, level=nivel))
            else:
                blocos.append(Block(type=BlockType.PARAGRAPH, text=texto))
        elif filho.tag == qn("w:tbl"):
            tabela = Table(filho, documento)
            rows = tuple(
                tuple(celula.text.strip() for celula in linha.cells) for linha in tabela.rows
            )
            if any(any(c for c in row) for row in rows):
                blocos.append(Block(type=BlockType.TABLE, rows=rows, text=render_rows(rows)))
    return blocos


def _nivel_de_estilo(estilo: str) -> int | None:
    if estilo == "Title":
        return 1
    if estilo.startswith("Heading"):
        sufixo = estilo.split()[-1]
        return int(sufixo) if sufixo.isdigit() else 1
    return None


# --------------------------------------------------------------------------- #
# PDF — tabelas por página + prosa fora das tabelas (sem duplicar)             #
# --------------------------------------------------------------------------- #
def _pdf_blocks(raw: bytes) -> list[Block]:
    try:
        import pdfplumber
    except ImportError:
        return []

    blocos: list[Block] = []
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for numero, pagina in enumerate(pdf.pages, 1):
            tabelas = pagina.find_tables()
            bboxes = [t.bbox for t in tabelas]
            for tabela in tabelas:
                dados = tabela.extract()
                rows = tuple(tuple((c or "").strip() for c in linha) for linha in dados)
                if any(any(c for c in row) for row in rows):
                    blocos.append(
                        Block(
                            type=BlockType.TABLE,
                            rows=rows,
                            text=render_rows(rows),
                            page=numero,
                        )
                    )
            # prosa = texto FORA das áreas de tabela (evita duplicar a tabela)
            fonte = pagina.filter(_fora_das_tabelas(bboxes)) if bboxes else pagina
            for paragrafo in _paragrafos(_melhor_texto(fonte)):
                blocos.append(Block(type=BlockType.PARAGRAPH, text=paragrafo, page=numero))
    return blocos


def _fora_das_tabelas(
    bboxes: list[tuple[float, float, float, float]],
) -> Callable[[dict[str, Any]], bool]:
    def _predicado(obj: dict[str, Any]) -> bool:
        top = obj.get("top", 0.0)
        bottom = obj.get("bottom", 0.0)
        x0 = obj.get("x0", 0.0)
        x1 = obj.get("x1", 0.0)
        for bx0, btop, bx1, bbottom in bboxes:
            if x0 >= bx0 - 1 and x1 <= bx1 + 1 and top >= btop - 1 and bottom <= bbottom + 1:
                return False
        return True

    return _predicado


def _melhor_texto(pagina: Any) -> str:
    """A variante de tolerância (1.5 vs padrão) com maior legibilidade —
    a mesma escolha que o extrator de texto plano faz para faturas."""
    try:
        candidatos = [
            pagina.extract_text(x_tolerance=1.5) or "",
            pagina.extract_text() or "",
        ]
    except Exception:
        return ""
    return max(candidatos, key=legibilidade)


# canário anti-truncamento
