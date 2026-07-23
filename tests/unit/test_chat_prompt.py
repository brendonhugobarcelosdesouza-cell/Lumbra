"""Montagem do prompt de RAG e conversão de contexto em citações — puro."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from lumbra.modules.chat import (
    SYSTEM_PROMPT,
    _build_messages,
    _context_block,
    _title_from,
    _to_citations,
)
from lumbra.ports.context import ContextFragment
from lumbra.ports.conversations import Message


def _msg(role: str, content: str) -> Message:
    return Message(
        id=uuid4(),
        conversation_id=uuid4(),
        role=role,
        content=content,
        created_at=datetime.now(tz=UTC),
    )


_KIND_BY_SOURCE = {"documents": "document", "memories": "memory"}  # igual à produção


def _fragment(source: str, content: str, **metadata) -> ContextFragment:
    base = {
        "kind": _KIND_BY_SOURCE.get(source, source),
        "ref_id": str(uuid4()),
        "title": "arquivo.md",
    }
    return ContextFragment(
        source=source, content=content, relevance=0.9, metadata={**base, **metadata}
    )


class TestSystemPrompt:
    """O prompt é a última linha de defesa contra alucinação. Estas regras
    nasceram do dogfooding e não podem sumir numa reescrita distraída."""

    def test_proibe_inventar_fatos_pessoais(self):
        assert "NUNCA invente fatos pessoais" in SYSTEM_PROMPT

    def test_manda_admitir_quando_nao_acha(self):
        assert "não encontrou" in SYSTEM_PROMPT

    def test_guardrail_de_valores_ambiguos(self):
        """Regressão do dogfooding: com vários 'totais' na fatura, o modelo
        chutava um número errado com confiança. O prompt deve mandar
        apresentar os candidatos em vez de escolher no chute."""
        prompt = SYSTEM_PROMPT.lower()
        assert "candidatos" in prompt
        assert "não escolha um no chute" in prompt or "no chute" in prompt
        # o exemplo financeiro concreto ancora a instrução
        assert "fatura" in prompt


class TestCitations:
    def test_fragments_become_numbered_citations(self):
        fragments = [_fragment("documents", "trecho A"), _fragment("memories", "memória B")]
        citations = _to_citations(fragments)
        assert [c.ordinal for c in citations] == [1, 2]
        assert [c.kind for c in citations] == ["document", "memory"]  # vem do metadata
        assert citations[0].snippet == "trecho A"

    def test_fragment_without_ref_is_not_citable(self):
        good = _fragment("documents", "com fonte")
        orphan = ContextFragment(source="x", content="sem fonte", relevance=0.5, metadata={})
        assert len(_to_citations([good, orphan])) == 1

    def test_snippet_is_truncated(self):
        citations = _to_citations([_fragment("documents", "x" * 900)])
        assert len(citations[0].snippet) == 500


class TestContextBlock:
    def test_numbering_matches_citations(self):
        fragments = [
            _fragment("documents", "aluguel custa 1800", title="aluguel.md"),
            _fragment("memories", "chaves na gaveta"),
        ]
        block = _context_block(fragments)
        assert block.startswith("CONTEXTO:")
        assert "[1] (aluguel.md) aluguel custa 1800" in block
        assert "[2]" in block
        # a numeração do bloco e a das citações são a MESMA (verificabilidade)
        citations = _to_citations(fragments)
        for citation in citations:
            assert f"[{citation.ordinal}]" in block


class TestBuildMessages:
    def test_system_prompt_first_and_question_last(self):
        history = [
            _msg("user", "Oi"),
            _msg("assistant", "Olá!"),
            _msg("user", "Quanto é o aluguel?"),
        ]
        fragments = [_fragment("documents", "aluguel de R$ 1.800")]
        messages = _build_messages(history, fragments)
        assert messages[0].role == "system"
        assert messages[0].content == SYSTEM_PROMPT
        assert messages[-1].role == "user"
        assert messages[-1].content == "Quanto é o aluguel?"
        # contexto entra logo antes da pergunta
        assert messages[-2].role == "system"
        assert "CONTEXTO:" in messages[-2].content

    def test_history_is_preserved_in_order(self):
        history = [_msg("user", "primeira"), _msg("assistant", "resposta"), _msg("user", "segunda")]
        messages = _build_messages(history, [])
        contents = [m.content for m in messages if m.role != "system"]
        assert contents == ["primeira", "resposta", "segunda"]

    def test_without_fragments_no_context_block(self):
        messages = _build_messages([_msg("user", "oi")], [])
        assert all("CONTEXTO:" not in m.content for m in messages)

    def test_empty_history_still_valid(self):
        messages = _build_messages([], [])
        assert len(messages) == 1
        assert messages[0].role == "system"


class TestTitle:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Quanto custa o aluguel?", "Quanto custa o aluguel?"),
            ("  espaços   demais  ", "espaços demais"),
        ],
    )
    def test_normalizes(self, text, expected):
        assert _title_from(text) == expected

    def test_truncates_long_titles(self):
        title = _title_from("palavra " * 40)
        assert len(title) == 61  # 60 + reticências
        assert title.endswith("…")


# canário anti-truncamento
