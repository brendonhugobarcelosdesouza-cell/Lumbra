"""Decision Engine (A4, ADR-060): decisões de orquestração rastreáveis.

Especialização do ExplainPort — a decisão vira uma Explanation no MESMO motor,
com vocabulário estruturado (tipo, escolhido, candidatos, determinístico).
"""

from uuid import uuid4

from lumbra.kernel.decisions import (
    Candidate,
    DecisionEngine,
    DecisionKind,
    DecisionRecord,
)
from lumbra.kernel.explain import ExplainEngine


def _engine() -> tuple[DecisionEngine, ExplainEngine]:
    explain = ExplainEngine()
    return DecisionEngine(explain), explain


class TestConversaoParaExplanation:
    def test_decisao_vira_explanation_no_mesmo_motor(self):
        decisions, explain = _engine()
        decisions.record(
            DecisionRecord(
                kind=DecisionKind.PROVIDER_SELECTION,
                chosen="finance-agent",
                candidates=(
                    Candidate(ref="finance-agent", reason="prioridade 9"),
                    Candidate(ref="doc-agent", reason="prioridade 1"),
                ),
                algorithm="prioridade desc, local primeiro",
            )
        )
        # gravou no Explain (uma trilha só de auditoria)
        registros = explain.query(component="decision")
        assert len(registros) == 1
        assert registros[0].decision == "escolhido: finance-agent"

    def test_candidatos_perdedores_viram_alternativas(self):
        decisions, explain = _engine()
        decisions.record(
            DecisionRecord(
                kind=DecisionKind.CAPABILITY_ROUTING,
                chosen="documents.search",
                candidates=(
                    Candidate(ref="documents.search"),
                    Candidate(ref="memory.search", reason="score menor"),
                ),
            )
        )
        (registro,) = explain.query(component="decision")
        # o que venceu não repete em alternatives; o que perdeu, sim
        assert registro.alternatives == ("memory.search: score menor",)

    def test_marca_se_foi_deterministica(self):
        decisions, explain = _engine()
        decisions.record(
            DecisionRecord(kind=DecisionKind.PLANNING, chosen="KeywordPlanner", deterministic=True)
        )
        (registro,) = explain.query(component="decision")
        assert registro.inputs_used["deterministic"] is True
        assert "determinística" in registro.reason

    def test_decisao_com_ia_e_marcada(self):
        decisions, explain = _engine()
        decisions.record(
            DecisionRecord(kind=DecisionKind.MODEL_SELECTION, chosen="claude", deterministic=False)
        )
        (registro,) = explain.query(component="decision")
        assert registro.inputs_used["deterministic"] is False
        assert "IA" in registro.reason


class TestConsulta:
    def test_filtra_por_tipo(self):
        decisions, _ = _engine()
        decisions.record(DecisionRecord(kind=DecisionKind.FALLBACK, chosen="lexical"))
        decisions.record(DecisionRecord(kind=DecisionKind.APPROVAL, chosen="allow"))
        somente_fallback = decisions.query(kind=DecisionKind.FALLBACK)
        assert len(somente_fallback) == 1
        assert somente_fallback[0].component == "decision:fallback"

    def test_consulta_todas_as_decisoes(self):
        decisions, _ = _engine()
        decisions.record(DecisionRecord(kind=DecisionKind.FALLBACK, chosen="a"))
        decisions.record(DecisionRecord(kind=DecisionKind.PLANNING, chosen="b"))
        assert len(decisions.query()) == 2

    def test_filtra_por_correlacao(self):
        decisions, _ = _engine()
        corr = uuid4()
        decisions.record(
            DecisionRecord(kind=DecisionKind.PLANNING, chosen="x", correlation_id=corr)
        )
        decisions.record(DecisionRecord(kind=DecisionKind.PLANNING, chosen="y"))
        assert len(decisions.query(correlation_id=corr)) == 1


# canário anti-truncamento
