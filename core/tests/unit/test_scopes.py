"""Álgebra de escopos: a base de permissão de dispositivos e plugins.

Least-privilege é a regra: cada teste que concede é acompanhado da certeza
de que o vizinho próximo NÃO é concedido — o perigo de um modelo de
permissão é conceder demais por engano.
"""

import pytest

from lumbra.domain.scopes import (
    CATALOGO,
    InvalidScopeError,
    ScopeSet,
    concede,
    parse_scope,
    scope_cobre,
)


class TestCasamentoExato:
    def test_igual_cobre(self):
        assert scope_cobre("memory:read", "memory:read")

    def test_acao_diferente_nao_cobre(self):
        assert not scope_cobre("memory:read", "memory:write")

    def test_recurso_diferente_nao_cobre(self):
        assert not scope_cobre("chat:read", "memory:read")

    def test_profundidade_diferente_nao_cobre(self):
        assert not scope_cobre("chat:read", "chat:read:extra")
        assert not scope_cobre("chat:read:extra", "chat:read")


class TestCuringas:
    def test_estrela_final_cobre_mais_profundo(self):
        assert scope_cobre("memory:*", "memory:read")
        assert scope_cobre("memory:*", "memory:read:item")

    def test_estrela_final_exige_ao_menos_um_segmento(self):
        # 'memory:*' não cobre o bare 'memory' (precisa de profundidade)
        assert not scope_cobre("memory:*", "memory")

    def test_estrela_interna_cobre_exatamente_um(self):
        assert scope_cobre("*:read", "memory:read")
        assert scope_cobre("*:read", "chat:read")
        assert not scope_cobre("*:read", "memory:write")

    def test_prefixo_pontilhado(self):
        assert scope_cobre("events:subscribe:document.*", "events:subscribe:document.created")
        assert not scope_cobre("events:subscribe:document.*", "events:subscribe:memory.created")

    def test_admin_cobre_tudo(self):
        assert scope_cobre("*", "memory:read")
        assert scope_cobre("*", "events:subscribe:document.created")


class TestConcede:
    def test_qualquer_um_do_conjunto_basta(self):
        concedidos = ["chat:read", "memory:*"]
        assert concede(concedidos, "memory:write")
        assert concede(concedidos, "chat:read")

    def test_conjunto_vazio_nao_concede(self):
        assert not concede([], "memory:read")

    def test_nenhum_cobre_nega(self):
        assert not concede(["chat:read", "system:read"], "memory:write")


class TestScopeSet:
    def test_concede_pela_instancia(self):
        s = ScopeSet(scopes={"memory:*", "chat:read"})
        assert s.concede("memory:delete")
        assert not s.concede("devices:write")

    def test_duplicatas_colapsam(self):
        s = ScopeSet(scopes=["memory:read", "memory:read"])
        assert s.scopes == frozenset({"memory:read"})

    def test_escopo_malformado_e_rejeitado_na_construcao(self):
        with pytest.raises(InvalidScopeError):
            ScopeSet(scopes={"memory::read"})

    def test_iteracao_e_ordenada(self):
        s = ScopeSet(scopes={"memory:read", "chat:read", "system:read"})
        assert list(s) == ["chat:read", "memory:read", "system:read"]


class TestValidacao:
    @pytest.mark.parametrize(
        "ruim",
        ["", ":", "memory:", ":read", "memory::read", "MEMORY:read", "mem ory:read", "a:*:b:"],
    )
    def test_formato_invalido_levanta(self, ruim):
        with pytest.raises(InvalidScopeError):
            parse_scope(ruim)

    def test_catalogo_todo_valido(self):
        for scope in CATALOGO:
            assert parse_scope(scope)  # não levanta


# canário anti-truncamento
