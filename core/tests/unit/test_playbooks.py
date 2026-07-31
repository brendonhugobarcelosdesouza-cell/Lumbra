"""Playbooks — memória procedural (L1).

O quarto tipo de conhecimento da Lumbra: não fatos, documentos ou relações,
mas COMO SE FAZ. E, principalmente: o primeiro uso real do gate de aprovação
(A0.2) — escrever procedimento é ação de impacto, e memória procedural errada
não erra uma vez, erra sempre que for lembrada (lição do dogfooding).
"""

from uuid import uuid4

import pytest

from lumbra.adapters.eventbus.in_memory import InMemoryEventBus
from lumbra.adapters.eventstore.in_memory import InMemoryEventStore
from lumbra.adapters.permissions.static import StaticPermissionAdapter
from lumbra.adapters.playbooks.in_memory import InMemoryPlaybookStore
from lumbra.context.providers import PlaybookContextProvider
from lumbra.domain.events import EventRegistry
from lumbra.kernel.approval import AutoApprovePolicy
from lumbra.kernel.kernel import LumbraKernel
from lumbra.modules.playbooks import PlaybookModule
from lumbra.ports.context import ContextRequest
from lumbra.ports.playbooks import Playbook, PlaybookOrigin
from lumbra.ports.skills import RiskLevel, SkillApprovalRequiredError, SkillContext


async def _kernel(*, teto: RiskLevel = RiskLevel.CRITICAL) -> LumbraKernel:
    k = LumbraKernel(
        events=EventRegistry(),
        bus=InMemoryEventBus(),
        event_store=InMemoryEventStore(),
        permissions=StaticPermissionAdapter(default_allow=True),
        approval=AutoApprovePolicy(auto_ate=teto),
    )
    k.register_module(PlaybookModule(InMemoryPlaybookStore()))
    await k.start()
    return k


def _ctx(user: object = None) -> SkillContext:
    uid = user or uuid4()
    return SkillContext(subject=f"user:{uid}", user_id=uid)  # type: ignore[arg-type]


_PROCEDIMENTO = {
    "title": "Reindexar documentos após mudança de extração",
    "when_to_use": "quando o pipeline de extração muda e os chunks antigos ficam obsoletos",
    "steps": (
        "Reiniciar o Nó para carregar o código novo",
        "Rodar /reindexar na pasta com force=true",
        "Conferir no dev/search se o trecho esperado aparece",
    ),
    "pitfalls": ("Reindexar sem reiniciar o Nó reprocessa com o código ANTIGO",),
    "verification": "o valor certo aparece no topo do dev/search",
}


class TestEscritaERecuperacao:
    async def test_grava_e_recupera_pelo_quando_usar(self):
        k = await _kernel()
        ctx = _ctx()
        await k.skills.execute("playbook.write", _PROCEDIMENTO, context=ctx)
        # a consulta casa com o 'when_to_use', não com o título
        r = await k.skills.execute(
            "playbook.search", {"query": "chunks antigos obsoletos extração"}, context=ctx
        )
        assert len(r.hits) == 1
        assert "Reindexar" in r.hits[0]["title"]
        assert "reiniciar o nó" in r.hits[0]["content"].lower()

    async def test_render_traz_passos_armadilhas_e_verificacao(self):
        p = Playbook(id=uuid4(), user_id=uuid4(), **_PROCEDIMENTO)  # type: ignore[arg-type]
        texto = p.render()
        assert "1. Reiniciar o Nó" in texto
        assert "Atenção:" in texto  # a armadilha é o que salva da repetição
        assert "Como verificar:" in texto

    async def test_uso_e_contabilizado(self):
        k = await _kernel()
        ctx = _ctx()
        await k.skills.execute("playbook.write", _PROCEDIMENTO, context=ctx)
        await k.skills.execute("playbook.search", {"query": "extração chunks"}, context=ctx)
        r = await k.skills.execute("playbook.search", {"query": "extração chunks"}, context=ctx)
        assert r.hits[0]["uses"] >= 1  # recuperar é sinal de utilidade

    async def test_consulta_sem_relacao_nao_traz_nada(self):
        k = await _kernel()
        ctx = _ctx()
        await k.skills.execute("playbook.write", _PROCEDIMENTO, context=ctx)
        r = await k.skills.execute("playbook.search", {"query": "receita de bolo"}, context=ctx)
        assert r.hits == ()

    async def test_usuario_e_dono_pode_apagar(self):
        k = await _kernel()
        ctx = _ctx()
        escrito = await k.skills.execute("playbook.write", _PROCEDIMENTO, context=ctx)
        apagado = await k.skills.execute(
            "playbook.forget", {"playbook_id": escrito.playbook_id}, context=ctx
        )
        assert apagado.forgotten is True

    async def test_isolamento_entre_usuarios(self):
        k = await _kernel()
        dono, outro = _ctx(), _ctx()
        await k.skills.execute("playbook.write", _PROCEDIMENTO, context=dono)
        r = await k.skills.execute("playbook.search", {"query": "extração"}, context=outro)
        assert r.hits == ()  # playbook de outro usuário não vaza


class TestGateDeAprovacao:
    """O primeiro uso REAL do HITL: escrever procedimento é ação MEDIUM."""

    async def test_escrita_barrada_quando_a_politica_exige_confirmacao(self):
        k = await _kernel(teto=RiskLevel.LOW)  # MEDIUM+ passa a exigir confirmação
        with pytest.raises(SkillApprovalRequiredError):
            await k.skills.execute("playbook.write", _PROCEDIMENTO, context=_ctx())

    async def test_leitura_continua_livre(self):
        """Recuperar procedimento é LOW: nunca pede aprovação, senão o
        contexto do chat quebraria a cada mensagem."""
        k = await _kernel(teto=RiskLevel.LOW)
        r = await k.skills.execute("playbook.search", {"query": "qualquer"}, context=_ctx())
        assert r.hits == ()

    async def test_apagar_tambem_passa_pelo_gate(self):
        k = await _kernel(teto=RiskLevel.LOW)
        with pytest.raises(SkillApprovalRequiredError):
            await k.skills.execute("playbook.forget", {"playbook_id": str(uuid4())}, context=_ctx())


class TestOrigemEContexto:
    async def test_origem_agente_fica_registrada(self):
        """Proveniência importa: o contexto mostra se o procedimento veio do
        usuário ou foi inferido pela plataforma."""
        k = await _kernel()
        ctx = _ctx()
        await k.skills.execute(
            "playbook.write",
            {**_PROCEDIMENTO, "origin": PlaybookOrigin.AGENT},
            context=ctx,
        )
        r = await k.skills.execute("playbook.search", {"query": "extração"}, context=ctx)
        assert r.hits[0]["origin"] == "agent"

    async def test_provider_injeta_no_contexto(self):
        k = await _kernel()
        ctx = _ctx()
        await k.skills.execute("playbook.write", _PROCEDIMENTO, context=ctx)
        provider = PlaybookContextProvider(k.skills)
        fragmentos = await provider.provide(
            ContextRequest(query="extração mudou chunks obsoletos", user_id=ctx.user_id)
        )
        assert len(fragmentos) == 1
        assert fragmentos[0].metadata["kind"] == "playbook"
        assert fragmentos[0].relevance >= 0.7  # procedimento pesa no contexto
        assert "Reiniciar o Nó" in fragmentos[0].content


# canário anti-truncamento
