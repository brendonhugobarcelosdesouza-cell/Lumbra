"""Matemática da memória: decaimento, força, reforço e fusão — funções puras."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from lumbra.domain.memory import (
    HALF_LIFE_DAYS,
    boosted_importance,
    decay_factor,
    effective_strength,
)
from lumbra.modules.memory import _fuse

NOW = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)


class TestDecay:
    def test_fresh_memory_has_full_factor(self):
        assert decay_factor(kind="episodic", last_accessed_at=NOW, now=NOW) == 1.0

    @pytest.mark.parametrize("kind", ["temporary", "episodic", "semantic", "procedural"])
    def test_half_life_is_exact(self, kind):
        past = NOW - timedelta(days=HALF_LIFE_DAYS[kind])
        assert decay_factor(kind=kind, last_accessed_at=past, now=NOW) == pytest.approx(0.5)

    def test_permanent_never_decays(self):
        past = NOW - timedelta(days=10_000)
        assert decay_factor(kind="permanent", last_accessed_at=past, now=NOW) == 1.0

    def test_monotonic_in_time(self):
        factors = [
            decay_factor(kind="episodic", last_accessed_at=NOW - timedelta(days=d), now=NOW)
            for d in (0, 1, 7, 30, 90, 365)
        ]
        assert factors == sorted(factors, reverse=True)
        assert all(0.0 < f <= 1.0 for f in factors)

    def test_clock_skew_never_exceeds_one(self):
        future = NOW + timedelta(hours=2)  # last_accessed "no futuro"
        assert decay_factor(kind="episodic", last_accessed_at=future, now=NOW) == 1.0

    def test_unknown_kind_uses_default(self):
        past = NOW - timedelta(days=30)
        assert decay_factor(kind="???", last_accessed_at=past, now=NOW) == pytest.approx(0.5)


class TestStrength:
    def test_bounds(self):
        for importance in (-1.0, 0.0, 0.5, 1.0, 2.0):
            s = effective_strength(
                importance=importance, kind="episodic", last_accessed_at=NOW, now=NOW
            )
            assert 0.0 <= s <= 1.0

    def test_importance_scales_strength(self):
        past = NOW - timedelta(days=30)
        weak = effective_strength(importance=0.2, kind="episodic", last_accessed_at=past, now=NOW)
        strong = effective_strength(importance=0.9, kind="episodic", last_accessed_at=past, now=NOW)
        assert strong > weak
        assert strong == pytest.approx(0.45)  # 0.9 x 0.5


class TestBoost:
    def test_recall_strengthens(self):
        assert boosted_importance(0.5) == pytest.approx(0.55)

    def test_saturates_at_one(self):
        assert boosted_importance(0.99) == 1.0
        assert boosted_importance(1.0) == 1.0

    def test_negative_clamped(self):
        assert boosted_importance(-0.5) == pytest.approx(0.05)


class TestFusion:
    def test_both_lists_outrank_single(self):
        both, lex_only, vec_only = uuid4(), uuid4(), uuid4()
        fused = _fuse([(lex_only, 1), (both, 2)], [(both, 0.9), (vec_only, 0.8)])
        assert fused[0][0] == both
        ids = [f[0] for f in fused]
        assert set(ids) == {both, lex_only, vec_only}

    def test_reports_positions_and_similarity(self):
        m = uuid4()
        ((mid, rrf, lex, vec, sim),) = _fuse([(m, 1)], [(m, 0.87)])
        assert mid == m and lex == 1 and vec == 1
        assert sim == pytest.approx(0.87)
        # lado léxico puro + lado vetorial pesado pela similaridade
        assert rrf == pytest.approx(1 / 61 + 0.87 / 61)

    def test_similaridade_desempata_mesma_posicao(self):
        """A propriedade que corrige o defeito: entre candidatos em posições
        equivalentes, quem é mais parecido pontua mais. RRF puro empataria."""
        forte, fraco = uuid4(), uuid4()
        fused = _fuse([], [(forte, 0.80), (fraco, 0.79)])
        por_id = {f[0]: f[1] for f in fused}
        assert por_id[forte] > por_id[fraco]

    def test_candidato_fraco_nao_supera_relevante_por_posicao(self):
        """Vetorial fraco em 1º NÃO deve superar um forte em 2º."""
        fraco, forte = uuid4(), uuid4()
        fused = _fuse([], [(fraco, 0.21), (forte, 0.80)])
        assert fused[0][0] == forte

    def test_empty(self):
        assert _fuse([], []) == []


# canário anti-truncamento
