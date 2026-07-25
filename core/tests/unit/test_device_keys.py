"""Ed25519: a base da identidade por dispositivo (ADR-045).

Prova as garantias de que a autenticação por chave depende: uma
assinatura legítima verifica, qualquer adulteração falha, e chave/entrada
malformada é rejeitada — nunca aceita por engano.
"""

import pytest

from lumbra.adapters.security import keys


class TestRoundtrip:
    def test_assinatura_legitima_verifica(self):
        priv, pub = keys.generate_keypair()
        msg = b"desafio-de-pareamento-123"
        assert keys.verify(pub, msg, keys.sign(priv, msg)) is True

    def test_cada_par_e_unico(self):
        assert keys.generate_keypair()[1] != keys.generate_keypair()[1]


class TestFalhas:
    def test_mensagem_adulterada_falha(self):
        priv, pub = keys.generate_keypair()
        assinatura = keys.sign(priv, b"valor original")
        assert keys.verify(pub, b"valor ADULTERADO", assinatura) is False

    def test_assinatura_de_outra_chave_falha(self):
        priv_a, _ = keys.generate_keypair()
        _, pub_b = keys.generate_keypair()
        msg = b"mensagem"
        assert keys.verify(pub_b, msg, keys.sign(priv_a, msg)) is False

    def test_assinatura_corrompida_falha_sem_explodir(self):
        _, pub = keys.generate_keypair()
        # base64 válido, mas não é uma assinatura Ed25519 correta
        assert keys.verify(pub, b"m", "AAAA") is False

    def test_chave_publica_malformada_e_erro(self):
        with pytest.raises(keys.InvalidPublicKeyError):
            keys.load_public_key("isto não é base64 válido !!!")

    def test_chave_publica_tamanho_errado_e_erro(self):
        with pytest.raises(keys.InvalidPublicKeyError):
            keys.load_public_key("AAAA")  # base64 ok, mas != 32 bytes


# canário anti-truncamento
