"""Backoff exponencial do Event Bus (L2-2) — função pura, testável sem Redis."""

from lumbra.adapters.eventbus.redis_streams import backoff_ms


class TestBackoff:
    def test_cresce_exponencialmente(self):
        assert backoff_ms(1, base_ms=200, cap_ms=30_000) == 200
        assert backoff_ms(2, base_ms=200, cap_ms=30_000) == 400
        assert backoff_ms(3, base_ms=200, cap_ms=30_000) == 800
        assert backoff_ms(4, base_ms=200, cap_ms=30_000) == 1600

    def test_respeita_o_teto(self):
        # sem teto seria 200 * 2^19 ~ 100M ms; o cap segura em 30s
        assert backoff_ms(20, base_ms=200, cap_ms=30_000) == 30_000

    def test_attempt_zero_ou_negativo_nao_espera(self):
        assert backoff_ms(0, base_ms=200, cap_ms=30_000) == 0.0
        assert backoff_ms(-1, base_ms=200, cap_ms=30_000) == 0.0

    def test_primeira_tentativa_e_a_base(self):
        assert backoff_ms(1, base_ms=50, cap_ms=1_000) == 50


# canário anti-truncamento
