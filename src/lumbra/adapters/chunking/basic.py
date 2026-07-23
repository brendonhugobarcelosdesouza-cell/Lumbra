"""Estratégias de chunking determinísticas + registro configurável por mime."""

from __future__ import annotations

import re

from lumbra.ports.chunking import ChunkerPort

_MAX_CHUNK_CHARS = 1600  # ~400 tokens
_MIN_CHUNK_CHARS = 200


def _pack(pieces: list[str]) -> list[str]:
    """Agrupa pedaços pequenos e reparte grandes, preservando a ordem."""
    chunks: list[str] = []
    buffer = ""
    for piece in (p.strip() for p in pieces):
        if not piece:
            continue
        candidate = f"{buffer}\n\n{piece}".strip() if buffer else piece
        if len(candidate) <= _MAX_CHUNK_CHARS:
            buffer = candidate
            continue
        if buffer:
            chunks.append(buffer)
        while len(piece) > _MAX_CHUNK_CHARS:  # pedaço maior que o limite: corta
            chunks.append(piece[:_MAX_CHUNK_CHARS])
            piece = piece[_MAX_CHUNK_CHARS:]
        buffer = piece
    if buffer:
        chunks.append(buffer)
    # une resto minúsculo ao anterior
    if len(chunks) >= 2 and len(chunks[-1]) < _MIN_CHUNK_CHARS:
        chunks[-2] = f"{chunks[-2]}\n\n{chunks[-1]}"
        chunks.pop()
    return chunks


class ParagraphChunker(ChunkerPort):
    @property
    def name(self) -> str:
        return "paragraph"

    def chunk(self, text: str) -> list[str]:
        return _pack(re.split(r"\n\s*\n", text))


class SentenceChunker(ChunkerPort):
    @property
    def name(self) -> str:
        return "sentence"

    def chunk(self, text: str) -> list[str]:
        return _pack(re.split(r"(?<=[.!?])\s+(?=[A-ZÀ-Ú0-9])", text))


class MarkdownChunker(ChunkerPort):
    """Divide por cabeçalhos, mantendo o título junto do corpo da seção."""

    @property
    def name(self) -> str:
        return "markdown"

    def chunk(self, text: str) -> list[str]:
        sections = re.split(r"(?m)^(?=#{1,6}\s)", text)
        return _pack(sections)


class CodeChunker(ChunkerPort):
    """Divide por blocos de nível superior (def/class/blocos separados)."""

    @property
    def name(self) -> str:
        return "code"

    def chunk(self, text: str) -> list[str]:
        blocks = re.split(r"(?m)^(?=(?:def |class |function |const |public |private ))", text)
        if len(blocks) <= 1:
            blocks = re.split(r"\n\s*\n", text)
        return _pack(blocks)


class ChunkerRegistry:
    """Seleção de estratégia por tipo de documento (configurável)."""

    def __init__(self) -> None:
        self._chunkers: dict[str, ChunkerPort] = {}
        self._by_mime: list[tuple[str, str]] = []  # (prefixo/mime, chunker)
        self._default = "paragraph"

    def register(self, chunker: ChunkerPort) -> None:
        self._chunkers[chunker.name] = chunker

    def map_mime(self, mime_prefix: str, chunker_name: str) -> None:
        self._by_mime.append((mime_prefix, chunker_name))

    def for_mime(self, mime_type: str | None) -> ChunkerPort:
        if mime_type:
            for prefix, name in self._by_mime:
                if mime_type.startswith(prefix):
                    return self._chunkers[name]
        return self._chunkers[self._default]


def default_chunker_registry() -> ChunkerRegistry:
    registry = ChunkerRegistry()
    for chunker in (ParagraphChunker(), SentenceChunker(), MarkdownChunker(), CodeChunker()):
        registry.register(chunker)
    registry.map_mime("text/markdown", "markdown")
    registry.map_mime("text/x-", "code")  # text/x-python etc.
    registry.map_mime("application/x-code", "code")
    return registry


# canário anti-truncamento
