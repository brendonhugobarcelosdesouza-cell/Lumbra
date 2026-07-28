"""Chunking ciente de estrutura (issue #10): blocos → chunks + metadado.

O ganho central sobre o chunking por tamanho: cada LINHA de tabela vira
um chunk autodescritivo — prefixada pela trilha de seção e pelo cabeçalho
da tabela — em vez de ser diluída num bloco de 400 tokens. Assim
``[Fatura] Descrição | Valor / Total desta fatura | R$ 7.016,60`` embeda
com o par rótulo-valor DOMINANDO o vetor, e deixa de ser indistinguível
de ``Total financiado``.

A prosa (parágrafos, listas, código) segue empacotada como antes, agora
carimbada com a seção a que pertence. O estágio de chunk só aciona esta
estratégia quando o documento TEM tabela — documentos de prosa pura
seguem pelo chunker legado, sem qualquer mudança de comportamento.
"""

from __future__ import annotations

from lumbra.adapters.chunking.basic import ParagraphChunker
from lumbra.domain.document_structure import Block, BlockType, ChunkMeta

_prose = ParagraphChunker()


def chunk_blocks(blocks: list[Block]) -> tuple[list[str], list[ChunkMeta]]:
    """Chunks (texto) + metadado estrutural alinhado por posição.

    Mantém uma pilha de cabeçalhos para compor a trilha de seção de cada
    chunk. Tabelas viram chunks por linha; a prosa entre cabeçalhos é
    empacotada pelo chunker de parágrafos, preservando a seção."""
    textos: list[str] = []
    metas: list[ChunkMeta] = []
    pilha: list[tuple[int, str]] = []  # (nível, título)
    buffer_prosa: list[str] = []

    def trilha() -> tuple[str, ...]:
        return tuple(titulo for _, titulo in pilha)

    def descarregar_prosa() -> None:
        if not buffer_prosa:
            return
        texto = "\n\n".join(buffer_prosa)
        caminho = trilha()
        for pedaco in _prose.chunk(texto):
            textos.append(pedaco)
            metas.append(ChunkMeta(section_path=caminho, block_type=BlockType.PARAGRAPH))
        buffer_prosa.clear()

    for bloco in blocks:
        if bloco.type is BlockType.HEADING:
            descarregar_prosa()
            nivel = bloco.level or 1
            while pilha and pilha[-1][0] >= nivel:
                pilha.pop()
            pilha.append((nivel, bloco.text))
        elif bloco.type is BlockType.TABLE:
            descarregar_prosa()
            _emitir_tabela(bloco, trilha(), textos, metas)
        else:  # parágrafo, item de lista, código
            conteudo = bloco.rendered().strip()
            if conteudo:
                buffer_prosa.append(conteudo)

    descarregar_prosa()
    return textos, metas


def _emitir_tabela(
    bloco: Block,
    caminho: tuple[str, ...],
    textos: list[str],
    metas: list[ChunkMeta],
) -> None:
    """Uma linha de dados por chunk, cada uma autodescritiva.

    Cada linha carrega o prefixo de seção e o cabeçalho da tabela, para
    que ``Total desta fatura | R$ 7.016,60`` seja recuperável sozinho, sem
    depender de estar no mesmo chunk que o cabeçalho da coluna."""
    linhas = [linha for linha in bloco.rows if any(c.strip() for c in linha)]
    if not linhas:
        return
    prefixo = f"[{' > '.join(caminho)}] " if caminho else ""
    tem_cabecalho = len(linhas) > 1
    cabecalho = " | ".join(linhas[0]) if tem_cabecalho else ""
    dados = linhas[1:] if tem_cabecalho else linhas
    for linha in dados:
        corpo = " | ".join(linha)
        texto = f"{prefixo}{cabecalho}\n{corpo}" if tem_cabecalho else f"{prefixo}{corpo}"
        textos.append(texto)
        metas.append(ChunkMeta(section_path=caminho, block_type=BlockType.TABLE, page=bloco.page))


# canário anti-truncamento
