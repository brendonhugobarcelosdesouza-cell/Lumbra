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
# Valor monetário no formato brasileiro (R$ 7.016,60), com R$ e espaço opcionais.
_VALOR_MONETARIO = re.compile(r"R?\$?\s?\d{1,3}(?:\.\d{3})*,\d{2}(?!\d)")

# Conectivos do português que colam entre palavras e raramente aparecem
# sozinhos numa fatura — completam o vocabulário do próprio documento para
# desfazer colagens do tipo "Totaldestafatura" → "Total desta fatura".
_PT_CONECTIVOS = frozenset({
    "de", "da", "do", "das", "dos", "desta", "deste", "destas", "destes",
    "dessa", "desse", "dessas", "desses", "na", "no", "nas", "nos", "em",
    "e", "a", "o", "as", "os", "ao", "aos", "com", "por", "para",
    "sua", "seu", "suas", "seus",
})  # fmt: skip
_PALAVRA_PT = re.compile(r"[A-Za-zÀ-ÿ]{2,}")
_MIN_COLAGEM = 12  # só tenta descolar tokens longos (palavra PT real raramente passa)


def _vocabulario(texto: str) -> set[str]:
    """Palavras (minúsculas) que o documento escreveu SEPARADAS — a base para
    descolar as que vieram grudadas na mesma página.

    Exclui tokens longos (> 15): as próprias COLAGENS ("totaldestafatura") são
    longas, e se entrassem no vocabulário se considerariam 'palavras conhecidas'
    e nunca seriam divididas. Palavras reais do PT quase todas cabem em 15."""
    curtas = {t.lower() for t in _PALAVRA_PT.findall(texto) if len(t) <= 15}
    return curtas | _PT_CONECTIVOS


def _descolar_token(token: str, vocab: set[str]) -> str:
    """Segmenta um token grudado em palavras conhecidas (maior prefixo primeiro).
    Só divide se TODO o token se decompõe em palavras do vocabulário — senão
    devolve intacto (não arrisca partir uma palavra real longa)."""
    if len(token) <= _MIN_COLAGEM or token.lower() in vocab:
        return token
    partes: list[str] = []
    i = 0
    while i < len(token):
        corte = next(
            (j for j in range(len(token), i + 1, -1) if token[i:j].lower() in vocab),
            None,
        )
        if corte is None:
            return token  # não segmentou: mantém original (seguro)
        partes.append(token[i:corte])
        i = corte
    return " ".join(partes) if len(partes) > 1 else token


def _descolar_linha(linha: str, vocab: set[str]) -> str:
    return " ".join(_descolar_token(tok, vocab) if tok.isalpha() else tok for tok in linha.split())


def _pdf_blocks(raw: bytes) -> list[Block]:
    try:
        import pdfplumber
    except ImportError:
        return []

    blocos: list[Block] = []
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for numero, pagina in enumerate(pdf.pages, 1):
            tabelas = list(pagina.find_tables())  # por linhas/bordas (preciso)
            if tabelas:
                _emitir_tabelas_com_borda(pagina, tabelas, numero, blocos)
            else:
                # sem bordas (fatura, extrato): a detecção por linhas acha 0
                # tabelas. Em vez de gridar a página (que cola palavras e
                # quebra números), lemos LINHA a linha, com espaçamento bom,
                # e cada linha "rótulo + valor" vira uma unidade própria (#10).
                blocos.extend(_blocos_por_linha(pagina, numero))
    return blocos


def _emitir_tabelas_com_borda(
    pagina: Any, tabelas: list[Any], numero: int, blocos: list[Block]
) -> None:
    bboxes = [t.bbox for t in tabelas]
    for tabela in tabelas:
        rows = tuple(tuple((c or "").strip() for c in linha) for linha in tabela.extract())
        if any(any(c for c in row) for row in rows):
            blocos.append(
                Block(type=BlockType.TABLE, rows=rows, text=render_rows(rows), page=numero)
            )
    fonte = pagina.filter(_fora_das_tabelas(bboxes))
    for paragrafo in _paragrafos(_melhor_texto(fonte)):
        blocos.append(Block(type=BlockType.PARAGRAPH, text=paragrafo, page=numero))


def _blocos_por_linha(pagina: Any, numero: int) -> list[Block]:
    """Lê o PDF LINHA a linha, usando a melhor variante de extração de texto
    (a de maior legibilidade, que já separa as palavras — evita a colagem do
    extract_words). Uma linha "rótulo ... valor" (``Total desta fatura
    7.016,60``) vira um par rótulo-valor autodescritivo (tabela de uma linha),
    que o chunker mantém inteiro — o valor certo deixa de se diluir num blob.
    Linhas sem valor viram prosa. Geral: fatura, extrato, relatório."""
    texto = _melhor_texto(pagina)
    vocab = _vocabulario(texto)  # o que a página escreveu separado descola o resto
    blocos: list[Block] = []
    prosa: list[str] = []

    def _descarregar_prosa() -> None:
        if prosa:
            blocos.append(Block(type=BlockType.PARAGRAPH, text=" ".join(prosa), page=numero))
            prosa.clear()

    for bruta in texto.splitlines():
        linha = _descolar_linha(bruta.strip(), vocab)
        if not linha:
            _descarregar_prosa()
            continue
        par = _rotulo_valor(linha)
        if par is not None:
            _descarregar_prosa()
            rotulo, valor = par
            blocos.append(
                Block(
                    type=BlockType.TABLE,
                    rows=((rotulo, valor),),
                    text=f"{rotulo} | {valor}",
                    page=numero,
                )
            )
        else:
            prosa.append(linha)
    _descarregar_prosa()
    return blocos


def _rotulo_valor(linha: str) -> tuple[str, str] | None:
    """Divide 'rótulo ... valor' numa linha, no primeiro valor monetário.

    Só considera par quando há um rótulo textual ANTES do valor e a linha é
    curta (rótulo-valor, não uma frase de prosa que menciona um número)."""
    m = _VALOR_MONETARIO.search(linha)
    if m is None or len(linha) > 120:
        return None
    rotulo = linha[: m.start()].strip(" .:-|")
    valor = linha[m.start() :].strip()
    # precisa de um rótulo com ao menos uma letra (senão é só número solto)
    if not any(c.isalpha() for c in rotulo):
        return None
    return rotulo, valor


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
