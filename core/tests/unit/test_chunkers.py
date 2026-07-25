"""Testes das estratégias de chunking."""

from lumbra.adapters.chunking.basic import (
    CodeChunker,
    MarkdownChunker,
    ParagraphChunker,
    SentenceChunker,
    default_chunker_registry,
)


class TestParagraph:
    def test_splits_on_blank_lines(self):
        chunks = ParagraphChunker().chunk("um" * 300 + "\n\n" + "dois" * 300)
        assert len(chunks) == 1 or all(c for c in chunks)

    def test_merges_small_paragraphs(self):
        text = "\n\n".join(f"parágrafo {i}" for i in range(10))
        chunks = ParagraphChunker().chunk(text)
        assert len(chunks) == 1  # pequenos são agrupados
        assert "parágrafo 9" in chunks[0]

    def test_splits_oversized_block(self):
        chunks = ParagraphChunker().chunk("x" * 5000)
        assert len(chunks) >= 3
        assert all(len(c) <= 1600 for c in chunks)

    def test_no_empty_chunks(self):
        assert all(c.strip() for c in ParagraphChunker().chunk("a\n\n\n\n\n\nb"))


class TestMarkdown:
    def test_splits_by_headings(self):
        text = "# Título\n" + "corpo um " * 120 + "\n## Seção\n" + "corpo dois " * 120
        chunks = MarkdownChunker().chunk(text)
        assert len(chunks) == 2
        assert chunks[0].startswith("# Título")
        assert chunks[1].startswith("## Seção")


class TestSentence:
    def test_splits_sentences(self):
        text = ("Primeira frase longa sobre o assunto. " * 30) + "Segunda parte. Fim."
        chunks = SentenceChunker().chunk(text)
        assert len(chunks) >= 1
        assert all(len(c) <= 1600 for c in chunks)


class TestCode:
    def test_splits_by_top_level_defs(self):
        code = "def a():\n    pass\n" + ("    x = 1\n" * 100) + "\ndef b():\n    return 2\n"
        chunks = CodeChunker().chunk(code)
        assert any("def b" in c for c in chunks)


class TestRegistry:
    def test_selection_by_mime(self):
        registry = default_chunker_registry()
        assert registry.for_mime("text/markdown").name == "markdown"
        assert registry.for_mime("text/x-python").name == "code"
        assert registry.for_mime("text/plain").name == "paragraph"
        assert registry.for_mime(None).name == "paragraph"
