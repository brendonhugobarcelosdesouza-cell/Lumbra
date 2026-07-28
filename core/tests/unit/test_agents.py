"""Contrato do AgentManifest (A0.3). Só validação — não há runtime ainda."""

import pytest
from pydantic import ValidationError

from lumbra.ports.agents import (
    AgentLimits,
    AgentManifest,
    DelegationPolicy,
    InvalidAgentError,
    MemoryAccess,
)
from lumbra.ports.skills import RiskLevel


def _manifest(**over) -> AgentManifest:
    base = {
        "id": "finance-agent",
        "name": "Finanças",
        "description": "analisa finanças",
        "provider": "kernel",
    }
    return AgentManifest(**{**base, **over})


class TestAgentManifest:
    def test_defaults_conservadores(self):
        m = _manifest()
        assert m.risk_level is RiskLevel.LOW
        assert m.memory_access is MemoryAccess.NONE  # sem memória oculta
        assert m.delegation.can_delegate is False  # não delega por padrão
        assert m.limits.max_depth == 3

    def test_id_precisa_ser_slug(self):
        with pytest.raises(InvalidAgentError):
            _manifest(id="Finance Agent")  # espaço e maiúscula: inválido

    def test_tools_precisam_ser_dominio_acao(self):
        with pytest.raises(InvalidAgentError):
            _manifest(tools=("documentfind",))  # sem ponto: inválido
        # válido não levanta
        _manifest(tools=("document.find", "memory.search"))

    def test_frozen(self):
        m = _manifest()
        with pytest.raises(ValidationError):
            m.id = "outro"  # type: ignore[misc]

    def test_limits_positivos(self):
        with pytest.raises(ValidationError):
            AgentLimits(max_tokens=0)

    def test_delegacao_declara_capacidades(self):
        m = _manifest(
            delegation=DelegationPolicy(can_delegate=True, to_capabilities=("documents",))
        )
        assert m.delegation.can_delegate
        assert "documents" in m.delegation.to_capabilities


# canário anti-truncamento
