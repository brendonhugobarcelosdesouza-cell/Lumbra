"""Estrutura de documento: a representação que preserva o que a extração
plana joga fora (issue #10).

Um documento vira uma sequência ORDENADA de blocos tipados — cabeçalho,
parágrafo, item de lista, tabela, código. O que importa para a
recuperação não é só o texto, mas o *tipo* e a *posição hierárquica* de
cada trecho: um valor dentro de uma linha de tabela, sob um cabeçalho de
seção, é uma unidade autodescritiva; o mesmo valor diluído num parágrafo
de 400 tokens vira um embedding borrado.

Este módulo define apenas o modelo (dados). Quem PRODUZ blocos é
``pipeline.structure`` (por formato); quem os CONSOME para gerar chunks é
o estágio de chunking. O modelo é serializável em JSONB: vive no
``PipelineContext`` persistido, como o texto.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class BlockType(StrEnum):
    HEADING = "heading"  # título de seção; ``level`` dá a profundidade (1..6)
    PARAGRAPH = "paragraph"  # prosa corrida
    LIST_ITEM = "list_item"  # um item de lista
    TABLE = "table"  # tabela inteira; células em ``rows``
    CODE = "code"  # bloco de código


class Block(BaseModel):
    """Um trecho tipado do documento, na ordem em que aparece.

    ``rows`` só é usado por tabelas (linhas por células). ``text`` guarda a
    forma textual do bloco — para tabela, uma renderização legível das
    linhas — para que qualquer consumidor tenha texto sem precisar
    conhecer o tipo.
    """

    model_config = ConfigDict(frozen=True)

    type: BlockType
    text: str = ""
    level: int | None = None  # profundidade do cabeçalho (1 = topo)
    page: int | None = None  # página 1-based, quando o formato informa (PDF)
    rows: tuple[tuple[str, ...], ...] = ()  # células, só para TABLE

    def rendered(self) -> str:
        """Texto legível do bloco, independentemente do tipo."""
        if self.type is BlockType.TABLE and self.rows:
            return render_rows(self.rows)
        return self.text


class StructuredDoc(BaseModel):
    """Documento como sequência de blocos. Fino de propósito: metadados de
    documento vivem no ``DocumentRecord``; aqui é só a estrutura interna."""

    model_config = ConfigDict(frozen=True)

    blocks: tuple[Block, ...] = Field(default_factory=tuple)

    def rendered(self) -> str:
        return "\n\n".join(b.rendered() for b in self.blocks if b.rendered().strip())


class ChunkMeta(BaseModel):
    """Metadado estrutural de um chunk (issue #10), alinhado ao texto por
    ordinal. Vazio para chunks legados/prosa simples — a recuperação trata
    ausência como parágrafo sem seção (retrocompatível)."""

    model_config = ConfigDict(frozen=True)

    section_path: tuple[str, ...] = ()  # trilha de cabecalhos (H1 > H2 > H3)
    block_type: BlockType | None = None
    page: int | None = None

    def breadcrumb(self) -> str:
        return " > ".join(self.section_path)


def render_rows(rows: tuple[tuple[str, ...], ...]) -> str:
    """Linhas de tabela em texto: uma linha por linha, células com ' | '.

    Preserva a associação rótulo↔valor que a extração plana embaralha
    (``Total desta fatura | R$ 7.016,60``)."""
    return "\n".join(" | ".join(c for c in row if c is not None) for row in rows)


# canário anti-truncamento
