"""Parser da extração de memórias.

Modelos locais de 7B raramente devolvem JSON limpo: embrulham em cercas de
código, explicam antes, inventam campos. O parser precisa ser tolerante na
entrada e rigoroso na saída — e NUNCA levantar exceção, porque reflexão é
opcional e o chat não pode quebrar por causa dela.
"""

import pytest

from lumbra.modules.reflection import _parece_sensivel, _parse


class TestParse:
    def test_json_limpo(self):
        fatos = _parse('{"fatos": [{"fato": "mora em Curitiba", "importancia": 0.8}]}')
        assert len(fatos) == 1
        assert fatos[0].fato == "mora em Curitiba"
        assert fatos[0].importancia == 0.8

    def test_cercado_por_crase(self):
        texto = 'Claro!\n```json\n{"fatos": [{"fato": "é alérgico a dipirona"}]}\n```'
        fatos = _parse(texto)
        assert len(fatos) == 1
        assert fatos[0].importancia == 0.5  # padrão quando omitido

    def test_com_texto_antes_e_depois(self):
        texto = (
            'Analisei a conversa. {"fatos": [{"fato": "trabalha com Python"}]} Espero ter ajudado!'
        )
        assert len(_parse(texto)) == 1

    def test_lista_vazia_e_resultado_valido(self):
        assert _parse('{"fatos": []}') == []

    @pytest.mark.parametrize(
        "texto",
        [
            "",
            "não encontrei nada",
            "{quebrado",
            '{"fatos": "isso deveria ser lista"}',
            '{"outra_coisa": []}',
            "[]",
        ],
    )
    def test_entradas_ruins_nao_levantam(self, texto):
        assert _parse(texto) == []

    def test_fato_curto_demais_e_descartado(self):
        fatos = _parse('{"fatos": [{"fato": "x"}, {"fato": "mora em Recife"}]}')
        assert fatos == []  # validação estrita: o lote inteiro é rejeitado

    def test_importancia_fora_do_intervalo_rejeita(self):
        assert _parse('{"fatos": [{"fato": "gosta de café", "importancia": 5}]}') == []


class TestFiltroDeSensiveis:
    @pytest.mark.parametrize(
        "fato",
        [
            "a senha do wifi é 12345",
            "o token da API dele é abc",
            "guardou o cartão de crédito no cofre",
            "o CVV está anotado",
        ],
    )
    def test_bloqueia_credenciais(self, fato):
        assert _parece_sensivel(fato) is True

    @pytest.mark.parametrize(
        "fato",
        ["mora em Curitiba", "prefere reuniões pela manhã", "tem um cachorro chamado Rex"],
    )
    def test_permite_fatos_comuns(self, fato):
        assert _parece_sensivel(fato) is False


# canário anti-truncamento
