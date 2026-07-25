"""Cancelamento cooperativo — capacidade da PLATAFORMA (ADR-032).

Qualquer operação longa da Lumbra — indexar documentos, OCR, embeddings,
buscas, geração de texto, agentes, automações, sincronizações — precisa
poder ser interrompida sem deixar recurso pendurado. Este módulo é o
mecanismo único para isso; ninguém inventa o seu.

Três garantias:

1. **Propagação.** Tokens formam uma árvore: cancelar um pai cancela todos
   os filhos. O kernel tem um token raiz que é cancelado no desligamento,
   então nenhuma operação sobrevive ao processo.
2. **Liberação imediata.** ``guard``/``guard_stream`` cancelam a tarefa
   subjacente na hora. Uma conexão HTTP aberta (Ollama gerando na GPU) é
   fechada, e o servidor do outro lado para de trabalhar — não é só o
   cliente que desiste de esperar.
3. **Prestação de contas.** O token registra QUEM pediu, POR QUE, e quais
   etapas já haviam terminado. É isso que distingue "cancelado" de
   "quebrou" no Developer Console e no Explain Engine.

O cancelamento é *cooperativo*: chamadas em execução são interrompidas
via ``asyncio``, mas trechos síncronos e longos (um laço apertado de CPU)
precisam chamar ``token.raise_if_cancelled()`` entre as etapas.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, TypeVar

from lumbra.shared.logging import get_logger

_log = get_logger("lumbra.cancellation")

T = TypeVar("T")


class CancelReason(StrEnum):
    """Por que a operação parou. ``TIMEOUT`` é separado de propósito:
    'demorou demais' e 'alguém desistiu' exigem respostas diferentes."""

    USER = "user"  # pedido explícito (botão, /cancel, Ctrl+C)
    CLIENT_GONE = "client_gone"  # quem pediu fechou a conexão
    TIMEOUT = "timeout"  # estourou o prazo
    SHUTDOWN = "shutdown"  # processo desligando
    PARENT = "parent"  # o escopo pai foi cancelado
    POLICY = "policy"  # regra do sistema (orçamento, permissão revogada)


class OperationCancelledError(Exception):
    """Interrupção deliberada — NÃO é falha.

    Carrega o contexto necessário para explicar o que aconteceu sem
    precisar caçar o motivo em logs.
    """

    def __init__(
        self,
        reason: CancelReason,
        *,
        requested_by: str,
        completed_steps: tuple[str, ...] = (),
        detail: str | None = None,
        partial: str | None = None,
    ) -> None:
        self.reason = reason
        self.requested_by = requested_by
        self.completed_steps = completed_steps
        self.detail = detail
        # trabalho já produzido antes da interrupção (ex.: texto gerado até
        # ali). Cancelar não é motivo para JOGAR FORA o que já ficou pronto.
        self.partial = partial
        texto = detail or f"operação cancelada ({reason.value}) por {requested_by}"
        super().__init__(texto)


class CancellationToken:
    """Sinal de cancelamento propagável, com trilha de progresso.

    Uso típico::

        token = CancellationToken(name="chat.send")
        token.step("contexto reunido")
        texto = await token.guard(gerar_resposta())

    Não é thread-safe por design: vive dentro de um event loop.
    """

    def __init__(self, *, name: str = "root", parent: CancellationToken | None = None) -> None:
        self.name = name
        self._event = asyncio.Event()
        self._reason: CancelReason | None = None
        self._requested_by: str | None = None
        self._requested_at: datetime | None = None
        self._steps: list[str] = []
        self._children: list[CancellationToken] = []
        self._callbacks: list[Callable[[CancellationToken], None]] = []
        self._parent = parent
        if parent is not None:
            parent._children.append(self)
            if parent.is_cancelled:  # pai já cancelado: nasce cancelado
                self.cancel(CancelReason.PARENT, requested_by=parent.name)

    # ------------------------------------------------------------ estado

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> CancelReason | None:
        return self._reason

    @property
    def requested_by(self) -> str | None:
        return self._requested_by

    @property
    def requested_at(self) -> datetime | None:
        return self._requested_at

    @property
    def completed_steps(self) -> tuple[str, ...]:
        """Etapas concluídas ANTES da interrupção — o que não se perdeu."""
        return tuple(self._steps)

    def step(self, description: str) -> None:
        """Marca uma etapa concluída (aparece na explicação do cancelamento)."""
        self._steps.append(description)

    # ------------------------------------------------------------ cancelamento

    def cancel(self, reason: CancelReason, *, requested_by: str) -> bool:
        """Sinaliza o cancelamento. Idempotente: o primeiro motivo vence,
        porque é ele que explica a interrupção — os seguintes são apenas
        consequência."""
        if self._event.is_set():
            return False
        self._reason = reason
        self._requested_by = requested_by
        self._requested_at = datetime.now(tz=UTC)
        self._event.set()
        _log.info(
            "cancellation_requested",
            scope=self.name,
            reason=reason.value,
            requested_by=requested_by,
            completed_steps=len(self._steps),
        )
        for child in self._children:
            child.cancel(CancelReason.PARENT, requested_by=self.name)
        for callback in self._callbacks:
            try:
                callback(self)
            except Exception as exc:  # um observador ruim não trava o resto
                _log.error("cancellation_callback_failed", scope=self.name, error=repr(exc))
        return True

    def on_cancel(self, callback: Callable[[CancellationToken], None]) -> None:
        """Observador para liberar recursos (fechar arquivo, devolver lock)."""
        if self.is_cancelled:
            callback(self)
            return
        self._callbacks.append(callback)

    def child(self, name: str) -> CancellationToken:
        """Escopo filho: cancelar o pai cancela o filho, nunca o contrário."""
        return CancellationToken(name=name, parent=self)

    def raise_if_cancelled(self) -> None:
        """Ponto de verificação para código síncrono entre etapas."""
        if self.is_cancelled:
            raise self._build_error()

    def _build_error(self) -> OperationCancelledError:
        return OperationCancelledError(
            self._reason or CancelReason.USER,
            requested_by=self._requested_by or "desconhecido",
            completed_steps=self.completed_steps,
        )

    async def wait_cancelled(self) -> None:
        await self._event.wait()

    # ------------------------------------------------------------ execução guardada

    async def guard(self, awaitable: Awaitable[T]) -> T:
        """Executa até terminar OU até o cancelamento, o que vier primeiro.

        No cancelamento a tarefa é abortada de verdade (não é só parar de
        esperar): conexões HTTP fecham, e o servidor do outro lado — o
        Ollama ocupando a GPU, por exemplo — para de trabalhar.
        """
        if self.is_cancelled:
            raise self._build_error()
        task: asyncio.Task[T] = asyncio.ensure_future(awaitable)
        waiter = asyncio.ensure_future(self._event.wait())
        try:
            done, _ = await asyncio.wait({task, waiter}, return_when=asyncio.FIRST_COMPLETED)
            if task in done:
                return task.result()
            task.cancel()
            # deixa o finally/aclose do alvo rodar; erro na saida e
            # irrelevante — a decisao de parar ja foi tomada
            with suppress(asyncio.CancelledError, Exception):
                await task
            raise self._build_error()
        finally:
            waiter.cancel()

    async def guard_stream(self, source: AsyncIterator[T]) -> AsyncIterator[T]:
        """Igual ao ``guard``, para fluxos: entrega itens até o
        cancelamento e então FECHA a fonte (``aclose``), liberando a
        conexão subjacente imediatamente."""
        iterator = source.__aiter__()
        waiter = asyncio.ensure_future(self._event.wait())
        try:
            while True:
                if self.is_cancelled:
                    raise self._build_error()
                nxt: asyncio.Task[T] = asyncio.ensure_future(iterator.__anext__())
                done, _ = await asyncio.wait({nxt, waiter}, return_when=asyncio.FIRST_COMPLETED)
                if nxt in done:
                    try:
                        yield nxt.result()
                    except StopAsyncIteration:
                        return
                    continue
                nxt.cancel()
                with suppress(asyncio.CancelledError, StopAsyncIteration, Exception):
                    await nxt
                raise self._build_error()
        finally:
            waiter.cancel()
            aclose = getattr(iterator, "aclose", None)
            if aclose is not None:
                try:
                    await aclose()
                except Exception as exc:
                    _log.warning("stream_close_failed", scope=self.name, error=repr(exc))

    def snapshot(self) -> dict[str, Any]:
        """Estado para trace/explicação/console."""
        return {
            "scope": self.name,
            "cancelled": self.is_cancelled,
            "reason": self._reason.value if self._reason else None,
            "requested_by": self._requested_by,
            "requested_at": self._requested_at.isoformat() if self._requested_at else None,
            "completed_steps": list(self._steps),
        }


async def with_deadline(
    token: CancellationToken, seconds: float, *, requested_by: str = "deadline"
) -> asyncio.Task[None]:
    """Agenda ``TIMEOUT`` no token depois de N segundos.

    Timeout é modelado como um cancelamento com motivo próprio: o caminho
    de limpeza é o mesmo, mas o estado final é distinguível de uma
    desistência do usuário.
    """

    async def _armar() -> None:
        try:
            await asyncio.sleep(seconds)
            token.cancel(CancelReason.TIMEOUT, requested_by=requested_by)
        except asyncio.CancelledError:  # operação terminou antes do prazo
            pass

    return asyncio.create_task(_armar())


# canário anti-truncamento
