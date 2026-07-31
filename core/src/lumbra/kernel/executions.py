"""ExecutionTracker — motor do Developer Console (ADR-022).

Executa skills (e, futuramente, agentes) como tarefas rastreadas:
entrada/saída, duração, status, erro detalhado, eventos correlacionados
do Event Bus e logs estruturados do período. Suporta cancelamento,
reexecução e histórico em anel (as N últimas execuções).

Ferramenta permanente de engenharia — não é exposta a usuários finais.
"""

from __future__ import annotations

import asyncio
import time
import traceback
from collections import deque
from collections.abc import MutableMapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from lumbra.domain.events import DomainEvent
from lumbra.kernel.kernel import LumbraKernel
from lumbra.ports.explain import Explanation
from lumbra.ports.skills import SkillContext
from lumbra.shared.cancellation import (
    CancellationToken,
    CancelReason,
    OperationCancelledError,
    with_deadline,
)
from lumbra.shared.ids import uuid7
from lumbra.shared.logging import get_logger

_log = get_logger("lumbra.executions")


class ExecutionStatus(StrEnum):
    """Estado final de uma execução (ADR-032).

    ``CANCELLED`` e ``TIMEOUT`` NÃO são falhas: ninguém deve ser acordado
    de madrugada porque um usuário desistiu de uma resposta. Por isso são
    estados próprios, e não variações de ``FAILED``.
    """

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class StepMetric(BaseModel):
    """Contabilidade de UMA etapa dentro de uma execução (ADR-059).

    Uma etapa é um passo observável do trabalho (uma skill chamada por um
    agente, um estágio, uma chamada de modelo). Tempo/custo/tokens permitem o
    rollup da subárvore; ``explanation_ref`` liga à explicação daquele passo."""

    model_config = ConfigDict(frozen=True)

    name: str
    duration_ms: float = 0.0
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    explanation_ref: str | None = None


class BudgetUsage(BaseModel):
    """Soma de uma subárvore de execução — o que a raiz realmente custou."""

    model_config = ConfigDict(frozen=True)

    duration_ms: float = 0.0
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    steps: int = 0
    executions: int = 0


class ExecutionRecord(BaseModel):
    model_config = ConfigDict(frozen=False)  # tracker atualiza in-place

    id: UUID
    kind: str  # skill | agent (futuro)
    name: str
    input: dict[str, Any]
    subject: str
    user_id: UUID | None
    correlation_id: UUID
    # árvore de execução (base da delegação de agentes, A0): uma execução
    # disparada por outra referencia o pai e HERDA seu correlation_id, para
    # que a árvore inteira (orquestrador → agente → skill → agente delegado)
    # seja rastreável por uma só correlação. Nulo = execução raiz.
    parent_execution_id: UUID | None = None
    status: ExecutionStatus = ExecutionStatus.RUNNING
    output: dict[str, Any] | None = None
    error: str | None = None
    error_detail: str | None = None  # traceback completo (só no console)
    started_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    duration_ms: float | None = None
    # prestação de contas do cancelamento (ADR-032)
    cancel_reason: str | None = None
    cancelled_by: str | None = None
    completed_steps: list[str] = Field(default_factory=list)
    # contabilidade por etapa (ADR-059): tempo/custo/tokens/explicação
    step_metrics: list[StepMetric] = Field(default_factory=list)

    @property
    def is_failure(self) -> bool:
        """Cancelamento e timeout não contam como falha do sistema."""
        return self.status is ExecutionStatus.FAILED


class ExecutionNode(BaseModel):
    """Um nó da árvore de execução: o registro e seus filhos (recursivo)."""

    model_config = ConfigDict(frozen=True)

    execution: ExecutionRecord
    children: tuple[ExecutionNode, ...] = ()


class ExecutionNotFoundError(Exception):
    pass


class ExecutionTracker:
    def __init__(
        self,
        kernel: LumbraKernel,
        *,
        history_size: int = 200,
        cancel_grace_seconds: float = 0.5,
    ) -> None:
        # prazo de cortesia entre pedir e forçar: tempo para a operação
        # encerrar sozinha e salvar trabalho parcial (ver ``cancel``)
        self._grace = cancel_grace_seconds
        self._kernel = kernel
        self._records: deque[ExecutionRecord] = deque(maxlen=history_size)
        self._by_id: dict[UUID, ExecutionRecord] = {}
        self._tasks: dict[UUID, asyncio.Task[None]] = {}
        self._tokens: dict[UUID, CancellationToken] = {}
        self._force_tasks: dict[UUID, asyncio.Task[None]] = {}
        self._events: deque[DomainEvent] = deque(maxlen=500)
        self._logs: deque[dict[str, Any]] = deque(maxlen=1000)

    # ------------------------------------------------------------ observadores

    async def on_event(self, event: DomainEvent) -> None:
        """Consumidor curinga do bus (registrado pelo composition root)."""
        self._events.append(event)

    def on_log(self, entry: MutableMapping[str, Any]) -> None:
        """Tap de logs estruturados (instalado pelo composition root)."""
        self._logs.append(dict(entry))

    # ------------------------------------------------------------ execução

    def start_skill(
        self,
        name: str,
        payload: dict[str, Any],
        *,
        subject: str,
        user_id: UUID | None,
        timeout_seconds: float | None = None,
        parent_execution_id: UUID | None = None,
    ) -> ExecutionRecord:
        # execução filha herda a correlação do pai — a árvore toda fica sob
        # um só correlation_id (delegação rastreável); raiz ganha uma nova.
        correlation_id = uuid7()
        parent = self._by_id.get(parent_execution_id) if parent_execution_id else None
        if parent is not None:
            correlation_id = parent.correlation_id
        record = ExecutionRecord(
            id=uuid7(),
            kind="skill",
            name=name,
            input=payload,
            subject=subject,
            user_id=user_id,
            correlation_id=correlation_id,
            parent_execution_id=parent_execution_id,
        )
        # filho do token do kernel: desligar o processo cancela isto também
        token = self._kernel.cancellation.child(f"execution:{name}")
        self._records.appendleft(record)
        self._by_id[record.id] = record
        self._tokens[record.id] = token
        self._tasks[record.id] = asyncio.create_task(self._run(record, token, timeout_seconds))
        return record

    async def _run(
        self,
        record: ExecutionRecord,
        token: CancellationToken,
        timeout_seconds: float | None,
    ) -> None:
        started = time.perf_counter()
        deadline = (
            await with_deadline(token, timeout_seconds, requested_by=f"execution:{record.id}")
            if timeout_seconds is not None
            else None
        )
        try:
            output = await self._kernel.skills.execute(
                record.name,
                record.input,
                context=SkillContext(
                    subject=record.subject,
                    user_id=record.user_id,
                    correlation_id=record.correlation_id,
                    cancellation=token,
                ),
            )
            record.output = output.model_dump(mode="json")
            record.status = ExecutionStatus.COMPLETED
        except OperationCancelledError as cancelled:
            self._mark_cancelled(record, token, cancelled.reason, cancelled.requested_by)
        except asyncio.CancelledError:
            # a task foi abortada por fora (ex.: shutdown do loop)
            self._mark_cancelled(
                record,
                token,
                token.reason or CancelReason.SHUTDOWN,
                token.requested_by or "runtime",
            )
        except Exception as exc:
            record.status = ExecutionStatus.FAILED
            record.error = repr(exc)
            record.error_detail = traceback.format_exc()
            record.completed_steps = list(token.completed_steps)
        finally:
            if deadline is not None:
                deadline.cancel()
            record.duration_ms = round((time.perf_counter() - started) * 1000, 2)
            self._tasks.pop(record.id, None)
            self._tokens.pop(record.id, None)

    def _mark_cancelled(
        self,
        record: ExecutionRecord,
        token: CancellationToken,
        reason: CancelReason,
        requested_by: str,
    ) -> None:
        """Timeout tem estado próprio — é diagnóstico diferente de desistência."""
        record.status = (
            ExecutionStatus.TIMEOUT if reason is CancelReason.TIMEOUT else ExecutionStatus.CANCELLED
        )
        record.cancel_reason = reason.value
        record.cancelled_by = requested_by
        record.completed_steps = list(token.completed_steps)
        record.error = f"interrompida ({reason.value}) por {requested_by}"
        self._kernel.explain.record(
            Explanation(
                component="execution_tracker",
                decision=f"execução {record.name} terminou como {record.status.value}",
                reason=f"cancelamento solicitado por {requested_by} ({reason.value})",
                inputs_used={"execution_id": str(record.id), "skill": record.name},
                algorithm="cancelamento cooperativo por token (ADR-032)",
                consequences=(
                    f"etapas concluídas antes da interrupção: "
                    f"{', '.join(token.completed_steps) or 'nenhuma'}",
                    "recursos liberados (conexões e tarefas encerradas)",
                ),
                correlation_id=record.correlation_id,
            )
        )

    # ------------------------------------------------------------ árvore (ADR-059)

    def add_step(self, execution_id: UUID, metric: StepMetric) -> None:
        """Registra a contabilidade de uma etapa na execução (tempo/custo/tokens)."""
        self.get(execution_id).step_metrics.append(metric)

    def children_of(self, execution_id: UUID) -> list[ExecutionRecord]:
        return [r for r in self._records if r.parent_execution_id == execution_id]

    def tree(self, root_execution_id: UUID) -> ExecutionNode:
        """Árvore completa a partir da raiz (execução + subexecuções)."""
        raiz = self.get(root_execution_id)
        return ExecutionNode(
            execution=raiz,
            children=tuple(self.tree(f.id) for f in self.children_of(root_execution_id)),
        )

    def rollup(self, root_execution_id: UUID) -> BudgetUsage:
        """Soma tempo/custo/tokens/passos de TODA a subárvore — o que a raiz
        custou de fato, incluindo o trabalho delegado."""
        raiz = self.get(root_execution_id)
        duracao = raiz.duration_ms or 0.0
        custo = sum(s.cost_usd for s in raiz.step_metrics)
        entrada = sum(s.tokens_in for s in raiz.step_metrics)
        saida = sum(s.tokens_out for s in raiz.step_metrics)
        passos = len(raiz.step_metrics)
        execucoes = 1
        for filho in self.children_of(root_execution_id):
            sub = self.rollup(filho.id)
            duracao += sub.duration_ms
            custo += sub.cost_usd
            entrada += sub.tokens_in
            saida += sub.tokens_out
            passos += sub.steps
            execucoes += sub.executions
        return BudgetUsage(
            duration_ms=round(duracao, 2),
            cost_usd=custo,
            tokens_in=entrada,
            tokens_out=saida,
            steps=passos,
            executions=execucoes,
        )

    def cancel_tree(
        self,
        root_execution_id: UUID,
        *,
        reason: CancelReason = CancelReason.USER,
        requested_by: str = "console",
    ) -> int:
        """Cancelamento em CASCATA: cancela a raiz e toda a subárvore. Devolve
        quantas execuções foram efetivamente sinalizadas."""
        cancelados = (
            1 if self.cancel(root_execution_id, reason=reason, requested_by=requested_by) else 0
        )
        for filho in self.children_of(root_execution_id):
            cancelados += self.cancel_tree(filho.id, reason=reason, requested_by=requested_by)
        return cancelados

    # ------------------------------------------------------------ consultas/ações

    def history(self) -> list[ExecutionRecord]:
        return list(self._records)

    def get(self, execution_id: UUID) -> ExecutionRecord:
        try:
            return self._by_id[execution_id]
        except KeyError:
            raise ExecutionNotFoundError(str(execution_id)) from None

    def events_of(self, execution_id: UUID) -> list[DomainEvent]:
        record = self.get(execution_id)
        return [e for e in self._events if e.correlation_id == record.correlation_id]

    def recent_events(self, limit: int = 100) -> list[DomainEvent]:
        return list(self._events)[-limit:]

    def recent_logs(self, limit: int = 200) -> list[dict[str, Any]]:
        return list(self._logs)[-limit:]

    def cancel(
        self,
        execution_id: UUID,
        *,
        reason: CancelReason = CancelReason.USER,
        requested_by: str = "console",
    ) -> bool:
        """Cancelamento COOPERATIVO: sinaliza o token, que se propaga para
        dentro (gateway → provedor → conexão HTTP). Não é ``task.cancel()``
        cru, que mataria o handler sem deixá-lo salvar o trabalho parcial."""
        token = self._tokens.get(execution_id)
        task = self._tasks.get(execution_id)
        if token is None or task is None or task.done():
            return False
        cancelou = token.cancel(reason, requested_by=requested_by)
        # Cooperativo primeiro, forçado depois: uma skill bem-comportada
        # encerra sozinha e salva o parcial; uma que ignora o token (ou
        # está presa em I/O sem ponto de verificação) é abortada assim que
        # o prazo de cortesia passa. Sem esse fallback, "cancelar" seria
        # uma sugestão, não uma garantia.
        self._force_tasks[execution_id] = asyncio.create_task(
            self._force_after_grace(execution_id, task)
        )
        return cancelou

    async def _force_after_grace(self, execution_id: UUID, task: asyncio.Task[None]) -> None:
        try:
            await asyncio.wait({task}, timeout=self._grace)
            if not task.done():
                _log.warning(
                    "cancellation_forced",
                    execution_id=str(execution_id),
                    grace_seconds=self._grace,
                )
                task.cancel()
        except asyncio.CancelledError:
            pass
        finally:
            self._force_tasks.pop(execution_id, None)

    def rerun(self, execution_id: UUID) -> ExecutionRecord:
        original = self.get(execution_id)
        return self.start_skill(
            original.name,
            original.input,
            subject=original.subject,
            user_id=original.user_id,
        )

    def export(self, execution_id: UUID) -> dict[str, Any]:
        record = self.get(execution_id)
        return {
            "execution": record.model_dump(mode="json"),
            "events": [e.model_dump(mode="json") for e in self.events_of(execution_id)],
        }

    async def wait(self, execution_id: UUID) -> ExecutionRecord:
        """Aguarda a conclusão (uso em testes/validação)."""
        task = self._tasks.get(execution_id)
        if task is not None:
            await asyncio.wait({task})
        return self.get(execution_id)


# canário anti-truncamento
