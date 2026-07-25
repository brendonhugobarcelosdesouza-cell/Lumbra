"""Testes do Metadata Engine e extratores determinísticos."""

import pytest

from lumbra.adapters.metadata.regex_extractors import (
    CNPJExtractor,
    CPFExtractor,
    EmailExtractor,
    LanguageDetector,
    MoneyExtractor,
    default_extractors,
)
from lumbra.pipeline.metadata_engine import MetadataEngine
from lumbra.ports.metadata import MetadataExtractorPort, MetadataResult

TEXT = (
    "Contrato firmado em 12/03/2026 com a ACME (CNPJ 11.222.333/0001-81). "
    "Contato: ana@acme.com.br, telefone (11) 98765-4321. "
    "CPF do contratante: 529.982.247-25. Valor mensal de R$ 1.234,56."
)


class TestExtractors:
    async def test_email(self):
        result = await EmailExtractor().extract(TEXT)
        assert result.fields["email"] == ["ana@acme.com.br"]

    async def test_cpf_validates_check_digits(self):
        valid = await CPFExtractor().extract("CPF 529.982.247-25")
        invalid = await CPFExtractor().extract("CPF 111.111.111-11 e 123.456.789-00")
        assert valid.fields["cpf"] == ["529.982.247-25"]
        assert invalid.fields == {}  # inválidos são descartados

    async def test_cnpj_validates_check_digits(self):
        valid = await CNPJExtractor().extract("CNPJ 11.222.333/0001-81")
        invalid = await CNPJExtractor().extract("CNPJ 11.222.333/0001-99")
        assert valid.fields["cnpj"] == ["11.222.333/0001-81"]
        assert invalid.fields == {}

    async def test_money(self):
        result = await MoneyExtractor().extract(TEXT)
        assert "R$ 1.234,56" in result.fields["money"]

    async def test_language_pt(self):
        result = await LanguageDetector().extract(
            "O sistema deve lembrar de tudo que é importante para o usuário"
        )
        assert result.fields["language"] == "pt"

    async def test_language_en(self):
        result = await LanguageDetector().extract(
            "The system must remember everything that is important to the user"
        )
        assert result.fields["language"] == "en"


class _Broken(MetadataExtractorPort):
    @property
    def name(self) -> str:
        return "broken"

    async def extract(self, text: str) -> MetadataResult:
        raise RuntimeError("plugin quebrado")


class TestEngine:
    async def test_merges_all_extractors(self):
        engine = MetadataEngine(default_extractors())
        result = await engine.run(TEXT)
        kinds = {e.kind for e in result.entities}
        assert {"email", "cpf", "cnpj", "money", "date", "phone"} <= kinds
        assert result.fields["language"] == "pt"

    async def test_broken_plugin_is_isolated(self):
        engine = MetadataEngine([_Broken(), EmailExtractor()])
        result = await engine.run(TEXT)
        assert result.fields["email"] == ["ana@acme.com.br"]  # os demais seguem

    async def test_duplicate_plugin_rejected(self):
        engine = MetadataEngine([EmailExtractor()])
        with pytest.raises(ValueError, match="já registrado"):
            engine.register(EmailExtractor())
