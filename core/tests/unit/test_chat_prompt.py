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
    prompt_do_sistema,
)
from lumbra.ports.ai import PrivacyMode
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

    def test_nao_inventa_as_proprias_capacidades(self):
        """Encontrado no PRIMEIRO uso depois de instalada. Perguntada "o que
        você faz?", a Lumbra listou agenda, lembretes e tarefas domésticas —
        nada disso existe (agenda é o P5, que nem começou).

        O prompt ensinava muito bem a não inventar FATOS do usuário e nunca
        dizia o que a Lumbra É; o modelo preencheu o vazio com o repertório
        genérico de assistente. Inventar competência é pior que inventar
        fato: alguém pode contar com ela.
        """
        # quebras de linha do prompt não podem quebrar o teste: procuramos
        # a FRASE, não a formatação dela
        prompt = " ".join(SYSTEM_PROMPT.lower().split())
        assert "ainda não faz" in prompt
        # as ausências mais tentadoras para um modelo genérico
        for ausente in ("agenda", "alarmes", "lembretes", "internet"):
            assert ausente in prompt, f"o prompt não nega {ausente}"
        assert "nunca descreva capacidades que você não tem" in prompt

    def test_declara_o_que_a_lumbra_realmente_faz(self):
        prompt = SYSTEM_PROMPT.lower()
        for capacidade in ("documentos", "memórias", "procedimentos", "confirmação"):
            assert capacidade in prompt, f"o prompt não declara {capacidade}"

    def test_reforca_o_idioma_no_fim(self):
        """O modelo local padrão (qwen2.5) é chinês e escorregou para o
        chinês a partir do sexto item de uma lista: a instrução do topo
        tinha perdido força. A última linha é a que mais pesa na geração."""
        fim = " ".join(SYSTEM_PROMPT.strip().lower().split())[-200:]
        assert "português do brasil" in fim

    def test_guardrail_de_valores_ambiguos(self):
        """Regressão do dogfooding: com vários 'totais' na fatura, o modelo
        chutava um número errado com confiança. O prompt deve mandar
        apresentar os candidatos em vez de escolher no chute."""
        prompt = SYSTEM_PROMPT.lower()
        assert "candidatos" in prompt
        assert "não escolha um no chute" in prompt or "no chute" in prompt
        # o exemplo financeiro concreto ancora a instrução
        assert "fatura" in prompt

    def test_guardrail_ancora_na_evidencia_rotulada(self):
        """O guardrail (issue #11, ADR-052) é dirigido por EVIDÊNCIA: os
        rótulos estruturais que o chunking ciente de estrutura coloca no
        contexto — não por um grau de confiança inventado."""
        prompt = SYSTEM_PROMPT.lower()
        assert "rótulo" in prompt or "rotulados" in prompt
        assert "evidência" in prompt
        # apresentar candidatos rotulados exige citá-los
        assert "cite [n]" in prompt or "citação\n  [n]" in prompt or "sua citação" in prompt
        # explicitamente NÃO é um score de confiança cosmético
        assert "confiança" in prompt


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


class TestPromessaDePrivacidade:
    """A frase sobre privacidade tem de corresponder ao caminho real.

    Descoberto usando o produto: com a conversa em `allow_cloud`, rodando no
    Claude, a Lumbra respondeu "nada sai deste computador" — enquanto o texto
    daquela resposta atravessava a internet até a Anthropic.

    É o mesmo pecado que o prompt já foi consertado para evitar (afirmar o que
    não se pode sustentar), agora na frase que É o argumento central do
    produto — e a mais cara de todas, porque alguém decide o que perguntar
    com base nela. Pior: a INTERFACE já dizia a verdade, lendo `model_policy`
    e mostrando "Nuvem" no cabeçalho. Quem mentia era o assistente.
    """

    def test_local_promete_que_nada_sai(self):
        prompt = prompt_do_sistema(PrivacyMode.LOCAL_ONLY)
        assert "nada sai daqui" in prompt
        assert "modelo LOCAL" in prompt

    def test_nuvem_nao_promete_que_nada_sai(self):
        prompt = prompt_do_sistema(PrivacyMode.ALLOW_CLOUD)
        assert "nada sai daqui" not in prompt
        assert "NUVEM" in prompt
        # e diz O QUE sai: não basta remover a promessa falsa, é preciso
        # colocar a verdade no lugar
        assert "provedor externo" in prompt

    def test_as_duas_versoes_mantem_as_regras_do_corpo(self):
        # trocar a promessa não pode custar as defesas contra alucinação
        for modo in PrivacyMode:
            prompt = prompt_do_sistema(modo)
            assert "NUNCA invente fatos pessoais" in prompt
            assert "O QUE VOCÊ AINDA NÃO FAZ" in prompt
            assert prompt.strip().endswith("inclusive em listas longas.")

    def test_o_prompt_montado_segue_a_privacidade_da_conversa(self):
        # o teste que pega a regressão de verdade: não basta a função estar
        # certa se `_build_messages` seguir chamando a versão local
        nuvem = _build_messages([_msg("user", "oi")], [], PrivacyMode.ALLOW_CLOUD)
        assert "nada sai daqui" not in nuvem[0].content

        local = _build_messages([_msg("user", "oi")], [], PrivacyMode.LOCAL_ONLY)
        assert "nada sai daqui" in local[0].content


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
