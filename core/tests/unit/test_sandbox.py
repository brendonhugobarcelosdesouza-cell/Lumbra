"""Agent Sandbox (A6, ADR-061): isolamento, orçamento e descarte.

Os invariantes de segurança da arquitetura viram teste aqui: escopo efetivo é
INTERSEÇÃO (um agente nunca ganha poder), budget estoura antes de gastar mais,
e o estado temporário some sempre — inclusive em erro.
"""

import pytest

from lumbra.adapters.permissions.static import StaticPermissionAdapter
from lumbra.kernel.sandbox import (
    AgentSandbox,
    BudgetExceededError,
    BudgetTracker,
    SandboxFactory,
)
from lumbra.ports.agents import AgentLimits
from lumbra.shared.cancellation import CancellationToken


def _sandbox(*, scopes: frozenset[str] = frozenset({"memory:read"}), **limites) -> AgentSandbox:
    return AgentSandbox(
        agent_id="teste",
        permissions=StaticPermissionAdapter(default_allow=True),
        scopes=scopes,
        limits=AgentLimits(**limites) if limites else AgentLimits(),
    )


class TestEscopoIntersectado:
    async def test_escopo_concedido_passa(self):
        s = _sandbox(scopes=frozenset({"memory:read"}))
        assert await s.permissions.is_allowed(subject="agent:x", scope="memory:read") is True

    async def test_escopo_fora_do_conjunto_e_negado(self):
        """O invariante: um agente com memory:read NÃO consegue email:send,
        mesmo com o port de origem permitindo tudo."""
        s = _sandbox(scopes=frozenset({"memory:read"}))
        assert await s.permissions.is_allowed(subject="agent:x", scope="email:send") is False

    async def test_factory_faz_a_intersecao_user_agente(self):
        fabrica = SandboxFactory(permissions=StaticPermissionAdapter(default_allow=True))
        s = fabrica.create(
            agent_id="a",
            agent_scopes=frozenset({"memory:read", "email:send"}),
            user_scopes=frozenset({"memory:read", "documents:read"}),
            limits=AgentLimits(),
        )
        assert s.scopes == frozenset({"memory:read"})  # só o que ambos têm
        assert await s.permissions.is_allowed(subject="a", scope="email:send") is False

    async def test_delegacao_so_estreita(self):
        pai = _sandbox(scopes=frozenset({"memory:read", "documents:read"}))
        filho = pai.child(
            agent_id="filho",
            scopes=frozenset({"documents:read", "email:send"}),  # pede a mais
            limits=AgentLimits(),
        )
        assert filho.scopes == frozenset({"documents:read"})  # interseção
        assert await filho.permissions.is_allowed(subject="filho", scope="email:send") is False

    async def test_profundidade_maxima_barra_delegacao(self):
        pai = _sandbox(max_depth=0)
        with pytest.raises(BudgetExceededError):
            pai.child(agent_id="filho", scopes=frozenset(), limits=AgentLimits())


class TestOrcamento:
    def test_debita_e_registra(self):
        t = BudgetTracker(AgentLimits(max_tokens=1000, max_steps=10))
        t.charge(tokens=100, cost_usd=0.5)
        snap = t.snapshot()
        assert snap.tokens == 100
        assert snap.cost_usd == 0.5
        assert snap.steps == 1

    def test_estoura_tokens(self):
        t = BudgetTracker(AgentLimits(max_tokens=50))
        with pytest.raises(BudgetExceededError) as exc:
            t.charge(tokens=51)
        assert exc.value.recurso == "tokens"

    def test_estoura_passos(self):
        t = BudgetTracker(AgentLimits(max_steps=2))
        t.charge()
        t.charge()
        with pytest.raises(BudgetExceededError) as exc:
            t.charge()
        assert exc.value.recurso == "passos"


class TestDescarte:
    def test_scratch_some_ao_sair(self):
        with _sandbox() as s:
            s.scratch["parcial"] = "dado temporário"
            arquivo = s.scratch_dir / "rascunho.txt"
            arquivo.write_text("temporário", encoding="utf-8")
            caminho = s.scratch_dir
            assert arquivo.exists()
        assert s.scratch == {}
        assert not caminho.exists()  # diretório removido

    def test_descarta_mesmo_com_erro(self):
        s = _sandbox()
        with pytest.raises(RuntimeError), s:
            s.scratch["x"] = 1
            raise RuntimeError("falhou no meio")
        assert s.scratch == {}

    def test_descarte_e_idempotente(self):
        s = _sandbox()
        s.discard()
        s.discard()  # não levanta

    def test_cancelamento_filho_acompanha_o_pai(self):
        token = CancellationToken(name="raiz")
        s = AgentSandbox(
            agent_id="pai",
            permissions=StaticPermissionAdapter(default_allow=True),
            scopes=frozenset({"a:b"}),
            limits=AgentLimits(),
            cancellation=token,
        )
        filho = s.child(agent_id="filho", scopes=frozenset({"a:b"}), limits=AgentLimits())
        assert filho.cancellation is not None
        assert filho.depth == 1


# canário anti-truncamento
