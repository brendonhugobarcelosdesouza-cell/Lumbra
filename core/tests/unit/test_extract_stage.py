"""Extração de texto — foco na qualidade do PDF (issue #6 do dogfooding).

Uma fatura de layout de colunas era extraída pelo pypdf como lixo
vertical (``1 L anç a m ent o s``), e o modelo respondia valores errados
a partir desse ruído. Estes testes travam a heurística de legibilidade e
a escolha do melhor extrator.
"""

from lumbra.pipeline.stages import extract
from lumbra.pipeline.stages.extract import _legibilidade, _pdf_text


class TestLegibilidade:
    def test_prosa_normal_pontua_alto(self):
        texto = "A fatura do cartão tem vencimento no dia dez de cada mês."
        assert _legibilidade(texto) > 0.6

    def test_lixo_vertical_pontua_baixo(self):
        # o padrão exato que o pypdf produziu na fatura do Itaú
        lixo = "L\nanç\na\nm\nent\no\ns\nco\nm\np\nras\ne\nsa\nqu\ne\ns"
        assert _legibilidade(lixo) < 0.4

    def test_palavras_coladas_pontuam_baixo(self):
        """A colagem é o outro extremo: parece ter palavras, mas são
        vários termos grudados num token gigante (o que o pdfplumber
        padrão produziu na fatura)."""
        colado = "TotaldestafaturaanteriorOpagamentoobrigatoriocompostopelosaldo"
        assert _legibilidade(colado) < 0.5

    def test_numeros_nao_derrubam_tabela_financeira(self):
        """Uma tabela com muitos valores não pode ser julgada ilegível só
        por ter números — eles não contam como palavras."""
        texto = "Total desta fatura 7.016,60 vencimento 10/04/2026 limite 32.760,00"
        assert _legibilidade(texto) > 0.9

    def test_texto_vazio_e_zero(self):
        assert _legibilidade("") == 0.0
        assert _legibilidade("   \n  ") == 0.0
        assert _legibilidade("7.016,60 10/04 32.760,00") == 0.0  # só números

    def test_separa_prosa_de_lixo(self):
        boa = "Valor total da fatura anterior seis mil setecentos e noventa reais"
        ruim = "6 . 7 9 1 , 0 7 T o t a l d a f a t u r a"
        assert _legibilidade(boa) - _legibilidade(ruim) > 0.4


class TestEscolhaDeExtrator:
    def test_usa_pypdf_quando_legivel(self, monkeypatch):
        """Caso comum: pypdf resolve, não paga o custo do pdfplumber."""
        limpo = "texto completamente limpo bastante legível claro aqui agora"
        monkeypatch.setattr(extract, "_pypdf_text", lambda _raw: limpo)

        def _nao_deveria(_raw):
            raise AssertionError("pdfplumber não deveria ser chamado")

        monkeypatch.setattr(extract, "_pdfplumber_variants", _nao_deveria)
        assert _pdf_text(b"%PDF") == limpo

    def test_cai_para_pdfplumber_quando_pypdf_fragmenta(self, monkeypatch):
        monkeypatch.setattr(extract, "_pypdf_text", lambda _raw: "1\nL\na\nn\nç\na\nm")
        monkeypatch.setattr(
            extract, "_pdfplumber_variants", lambda _raw: ["Lançamentos compras e saques"]
        )
        assert _pdf_text(b"%PDF") == "Lançamentos compras e saques"

    def test_prefere_variante_que_separa_palavras(self, monkeypatch):
        """A variante padrão gruda ('Totaldestafatura'); a de tolerância
        menor separa. A de maior legibilidade vence (o caso da fatura)."""
        monkeypatch.setattr(extract, "_pypdf_text", lambda _raw: "1\nT\no\nt\na\nl")
        monkeypatch.setattr(
            extract,
            "_pdfplumber_variants",
            lambda _raw: [
                "Total da fatura anterior 7.016,60",  # x_tolerance=1.5, separado
                "Totaldafaturaanterior Opagamentoobrigatoriocomposto",  # padrão, colado
            ],
        )
        assert _pdf_text(b"%PDF") == "Total da fatura anterior 7.016,60"

    def test_fica_com_pypdf_se_nada_ajudar(self, monkeypatch):
        """Nunca troca por algo pior: se todas as variantes fragmentam,
        mantém o pypdf (não introduz regressão)."""
        monkeypatch.setattr(extract, "_pypdf_text", lambda _raw: "abc de f g h i")
        monkeypatch.setattr(extract, "_pdfplumber_variants", lambda _raw: ["1 2 3", "4 5 6"])
        assert _pdf_text(b"%PDF") == "abc de f g h i"

    def test_degrada_sem_pdfplumber_instalado(self, monkeypatch):
        """Se a lib não estiver disponível, retorna o pypdf em vez de
        quebrar a indexação."""
        monkeypatch.setattr(extract, "_pypdf_text", lambda _raw: "ab c d e f")
        monkeypatch.setattr(extract, "_pdfplumber_variants", lambda _raw: [])
        assert _pdf_text(b"%PDF") == "ab c d e f"


# canário anti-truncamento
