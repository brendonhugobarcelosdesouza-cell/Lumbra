"""Capability Model + Registry (A1, ADR-055/056).

Resolução DETERMINÍSTICA capability→provedor: prioridade, preferência local,
ordem de registro. Sem IA. Skills viram provedores 'finos'.
"""

import pytest

from lumbra.kernel.capability_registry import CapabilityRegistry
from lumbra.ports.capabilities import (
    CapabilityMode,
    CapabilityNotFoundError,
    CapabilityProvider,
    CapabilitySpec,
    DuplicateCapabilityError,
    InvalidCapabilityError,
    NoProviderError,
    ProviderKind,
)
from lumbra.ports.skills import RiskLevel


def _reg() -> CapabilityRegistry:
    r = CapabilityRegistry()
    r.register_capability(CapabilitySpec(id="documents.summarize", description="resume"))
    return r


def _prov(ref: str, **over) -> CapabilityProvider:
    base = {"capability_id": "documents.summarize", "kind": ProviderKind.SKILL, "ref": ref}
    return CapabilityProvider(**{**base, **over})


class TestCapabilitySpec:
    def test_id_precisa_ser_dominio_acao(self):
        with pytest.raises(InvalidCapabilityError):
            CapabilitySpec(id="documentssummarize")

    def test_defaults(self):
        s = CapabilitySpec(id="memory.search")
        assert s.mode is CapabilityMode.READ
        assert s.risk_level is RiskLevel.LOW


class TestRegistro:
    def test_capability_duplicada(self):
        r = _reg()
        with pytest.raises(DuplicateCapabilityError):
            r.register_capability(CapabilitySpec(id="documents.summarize"))

    def test_provedor_de_capability_inexistente(self):
        r = _reg()
        with pytest.raises(CapabilityNotFoundError):
            r.register_provider(_prov("x.y", capability_id="nao.existe"))

    def test_re_registro_substitui_o_mesmo_ref(self):
        r = _reg()
        r.register_provider(_prov("document.find", priority=1))
        r.register_provider(_prov("document.find", priority=5))  # atualiza
        assert len(r.providers_of("documents.summarize")) == 1
        assert r.resolve("documents.summarize").priority == 5


class TestResolucaoDeterministica:
    def test_maior_prioridade_vence(self):
        r = _reg()
        r.register_provider(_prov("skill.a", priority=1))
        r.register_provider(_prov("skill.b", priority=9))
        assert r.resolve("documents.summarize").ref == "skill.b"

    def test_local_vence_nuvem_no_empate(self):
        r = _reg()
        r.register_provider(_prov("nuvem", priority=5, local=False))
        r.register_provider(_prov("local", priority=5, local=True))
        assert r.resolve("documents.summarize").ref == "local"

    def test_desempate_pela_ordem_de_registro(self):
        r = _reg()
        r.register_provider(_prov("primeiro", priority=5))
        r.register_provider(_prov("segundo", priority=5))
        assert r.resolve("documents.summarize").ref == "primeiro"

    def test_desabilitado_nao_e_resolvido(self):
        r = _reg()
        r.register_provider(_prov("desligado", priority=9))
        r.register_provider(_prov("ligado", priority=1))
        r.set_enabled("documents.summarize", "desligado", False)
        assert r.resolve("documents.summarize").ref == "ligado"

    def test_sem_provedor_habilitado_levanta(self):
        r = _reg()
        with pytest.raises(NoProviderError):
            r.resolve("documents.summarize")

    def test_resolver_capability_inexistente_levanta(self):
        with pytest.raises(CapabilityNotFoundError):
            _reg().resolve("nao.existe")


class TestSkillComoProvedor:
    def test_skill_fina_atende_capability(self):
        r = _reg()
        r.register_provider(
            CapabilityProvider(
                capability_id="documents.summarize",
                kind=ProviderKind.SKILL,
                ref="document.find",
            )
        )
        escolhido = r.resolve("documents.summarize")
        assert escolhido.kind is ProviderKind.SKILL
        assert escolhido.ref == "document.find"


# canário anti-truncamento
