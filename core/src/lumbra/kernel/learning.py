"""Learning Loop (L2) — a plataforma propõe procedimento a partir do que deu certo.

Quando um objetivo multi-passo é atingido, o caminho que funcionou é
conhecimento: da próxima vez não precisa ser redescoberto. Este é o quarto
tipo de memória (procedural) nascendo sozinha.

**A regra dura deste módulo: propor NUNCA é escrever.** A proposta vira um
pedido pendente na caixa de aprovações (ADR-063) e só existe de fato depois
do sim humano — independentemente do teto de aprovação automática. Não é
excesso de zelo: a reflexão automática já guardou uma resposta ERRADA como
fato e contaminou o RAG por dias. Memória procedural errada é pior, porque
não erra uma vez — erra sempre que o procedimento for lembrado.

Por isso o proposer fala com a fila de aprovações, e não com o
SkillRegistry: escrever direto seria justamente o caminho que o teto
`critical` (default) deixaria passar em silêncio.
"""

from __future__ import annotations

from lumbra.kernel.events import ApprovalRequested
from lumbra.kernel.planning import PlanResult
from lumbra.kernel.skill_registry import PublishFn
from lumbra.ports.approval import ApprovalStorePort, ApprovalTicket
from lumbra.ports.playbooks import PlaybookOrigin, PlaybookStorePort
from lumbra.ports.skills import RiskLevel, SkillContext
from lumbra.shared.ids import uuid7
from lumbra.shared.logging import get_logger

_log = get_logger("lumbra.kernel.learning")

_ACAO = "playbook.write"


class PlaybookProposer:
    """Transforma execução bem-sucedida em proposta de procedimento."""

    def __init__(
        self,
        playbooks: PlaybookStorePort,
        approvals: ApprovalStorePort,
        *,
        min_passos: int = 2,
        publish: PublishFn | None = None,
    ) -> None:
        self._playbooks = playbooks
        self._approvals = approvals
        self._publish = publish
        # 1 passo não é procedimento, é uma chamada: não vale a pena guardar
        self._min_passos = min_passos

    async def propose(
        self, goal: str, result: PlanResult, *, ctx: SkillContext
    ) -> ApprovalTicket | None:
        """Devolve o pedido pendente, ou ``None`` quando não há o que aprender.

        Silencioso de propósito: aprender é efeito colateral de ter feito algo
        útil, e não pode interromper nem falhar o trabalho principal."""
        if ctx.user_id is None:  # sem dono não há a quem perguntar
            return None
        if not result.succeeded or len(result.results) < self._min_passos:
            # só se aprende com o que funcionou INTEIRO: guardar um caminho
            # parcial ensinaria a repetir o erro
            return None
        titulo = goal.strip()[:120]
        if len(titulo) < 3:
            return None

        if await self._ja_conhecido(titulo, ctx):
            return None

        passos = tuple(f"Executar {r.skill}" for r in result.results)
        ticket = await self._approvals.add(
            ApprovalTicket(
                id=uuid7(),
                user_id=ctx.user_id,
                action=_ACAO,
                subject=ctx.subject,
                risk_level=RiskLevel.MEDIUM,
                reason=f"procedimento aprendido de uma execução bem-sucedida: {titulo!r}",
                payload={
                    "title": titulo,
                    "when_to_use": goal.strip()[:500],
                    "steps": list(passos),
                    "pitfalls": [],
                    "verification": "",
                    # proveniência: quem revisar vê que veio da plataforma
                    "origin": PlaybookOrigin.AGENT.value,
                },
            )
        )
        _log.info(
            "playbook_proposed",
            ticket=str(ticket.id),
            goal=titulo,
            steps=len(passos),
            subject=ctx.subject,
        )
        # mesmo evento de um pedido barrado pelo gate: para a auditoria, o que
        # importa é que a plataforma quis escrever e foi perguntar
        if self._publish is not None:
            await self._publish(
                ApprovalRequested(
                    ticket=str(ticket.id),
                    action=_ACAO,
                    subject=ctx.subject,
                    risk_level=RiskLevel.MEDIUM.value,
                ),
                user_id=ctx.user_id,
            )
        return ticket

    async def _ja_conhecido(self, titulo: str, ctx: SkillContext) -> bool:
        """Não propõe o que já existe nem o que já está na fila — senão cada
        repetição do mesmo objetivo viraria mais um pedido para o usuário."""
        assert ctx.user_id is not None  # noqa: S101
        if await self._playbooks.search(user_id=ctx.user_id, query=titulo, limit=1):
            return True
        pendentes = await self._approvals.list_pending(ctx.user_id, limit=200)
        return any(t.action == _ACAO and t.payload.get("title") == titulo for t in pendentes)


# canário anti-truncamento
