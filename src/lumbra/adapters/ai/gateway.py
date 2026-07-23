"""AI Gateway — roteamento por política, trace completo e explicações."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import AsyncIterator

from lumbra.ports.ai import (
    AICallRecord,
    AIGatewayPort,
    ChatProviderInfo,
    ChatProviderPort,
    ChatRequest,
    ChatResult,
    ChatStreamEvent,
    EmbeddingProviderPort,
    EmbedRequest,
    EmbedResult,
    NoEligibleProviderError,
    PrivacyMode,
)
from lumbra.ports.explain import ExplainPort, Explanation
from lumbra.ports.metrics import MetricsPort
from lumbra.shared.cancellation import CancellationToken, CancelReason, OperationCancelledError
from lumbra.shared.logging import get_logger


def _outcome(cancelled: OperationCancelledError) -> str:
    """Timeout é desfecho próprio — diagnóstico diferente de desistência."""
    return "timeout" if cancelled.reason is CancelReason.TIMEOUT else "cancelled"


_log = get_logger("lumbra.ai.gateway")


class AIGateway(AIGatewayPort):
    def __init__(
        self,
        *,
        embedding_providers: list[EmbeddingProviderPort],
        metrics: MetricsPort,
        chat_providers: list[ChatProviderPort] | None = None,
        explain: ExplainPort | None = None,
        trace_capacity: int = 500,
    ) -> None:
        if not embedding_providers:
            raise ValueError("AI Gateway exige ao menos um provedor de embeddings")
        self._embedders = embedding_providers
        self._chatters = chat_providers or []
        self._metrics = metrics
        self._explain = explain
        self._trace: deque[AICallRecord] = deque(maxlen=trace_capacity)

    # ------------------------------------------------------------ roteamento

    def _pick_embedder(self, privacy: PrivacyMode) -> EmbeddingProviderPort:
        candidates = [
            p for p in self._embedders if p.is_local or privacy is PrivacyMode.ALLOW_CLOUD
        ]
        if not candidates:
            raise NoEligibleProviderError(
                f"nenhum provedor de embeddings satisfaz a política {privacy.value}"
            )
        return candidates[0]  # ordem de registro = prioridade (local primeiro)

    def _pick_chatter(self, privacy: PrivacyMode, preferred: str | None) -> ChatProviderPort:
        candidates = [p for p in self._chatters if p.is_local or privacy is PrivacyMode.ALLOW_CLOUD]
        if preferred is not None:
            candidates = [p for p in candidates if p.name == preferred]
            if not candidates:
                raise NoEligibleProviderError(
                    f"provedor {preferred!r} indisponível ou não elegível para {privacy.value}"
                )
            return candidates[0]
        if not candidates:
            raise NoEligibleProviderError(
                f"nenhum provedor de chat satisfaz a política {privacy.value}"
            )
        return candidates[0]  # ordem de registro = prioridade (local primeiro)

    # ------------------------------------------------------------ embeddings

    async def embed(
        self, request: EmbedRequest, *, cancellation: CancellationToken | None = None
    ) -> EmbedResult:
        provider = self._pick_embedder(request.privacy)
        chars = sum(len(t) for t in request.texts)
        started = time.perf_counter()
        try:
            call = provider.embed(request.texts)
            vectors = await (cancellation.guard(call) if cancellation else call)
        except OperationCancelledError as cancelled:
            self._record(
                request,
                provider,
                started,
                chars,
                success=False,
                error=str(cancelled),
                outcome=_outcome(cancelled),
            )
            raise
        except Exception as exc:
            self._record(
                request,
                provider,
                started,
                chars,
                success=False,
                error=repr(exc),
                outcome="failed",
            )
            raise
        self._record(request, provider, started, chars, success=True, error=None)
        return EmbedResult(
            vectors=vectors, dim=provider.dim, provider=provider.name, model=provider.model
        )

    # ------------------------------------------------------------ chat

    async def chat(
        self, request: ChatRequest, *, cancellation: CancellationToken | None = None
    ) -> ChatResult:
        provider = self._pick_chatter(request.privacy, request.provider)
        chars = sum(len(m.content) for m in request.messages)
        started = time.perf_counter()
        try:
            call = provider.complete(
                request.messages, max_tokens=request.max_tokens, temperature=request.temperature
            )
            completion = await (cancellation.guard(call) if cancellation else call)
        except OperationCancelledError as cancelled:
            self._record_chat(
                request,
                provider,
                started,
                chars,
                0,
                0,
                success=False,
                error=str(cancelled),
                outcome=_outcome(cancelled),
            )
            raise
        except Exception as exc:
            self._record_chat(
                request,
                provider,
                started,
                chars,
                0,
                0,
                success=False,
                error=repr(exc),
                outcome="failed",
            )
            raise
        self._record_chat(
            request,
            provider,
            started,
            chars,
            completion.input_tokens,
            completion.output_tokens,
            success=True,
            error=None,
        )
        return ChatResult(
            text=completion.text,
            provider=provider.name,
            model=provider.model,
            input_tokens=completion.input_tokens,
            output_tokens=completion.output_tokens,
            finish_reason=completion.finish_reason,
        )

    async def chat_stream(
        self, request: ChatRequest, *, cancellation: CancellationToken | None = None
    ) -> AsyncIterator[ChatStreamEvent]:
        """Streaming com a MESMA política, trace e explicação do ``chat``.

        O trace só fecha quando a transmissão termina — é lá que os tokens
        são conhecidos. Se a conexão cair no meio, o erro também é
        registrado (com o que já havia sido gerado), então uma resposta
        interrompida nunca some do histórico de chamadas.
        """
        provider = self._pick_chatter(request.privacy, request.provider)
        chars = sum(len(m.content) for m in request.messages)
        started = time.perf_counter()
        parts: list[str] = []
        input_tokens = output_tokens = 0
        finish_reason = "stop"
        source = provider.stream(
            request.messages, max_tokens=request.max_tokens, temperature=request.temperature
        )
        # guard_stream fecha a conexão com o provedor ao cancelar: o modelo
        # local para de gerar e libera a GPU imediatamente (ADR-032)
        guarded = cancellation.guard_stream(source) if cancellation else source
        try:
            async for chunk in guarded:
                if chunk.done:
                    input_tokens = chunk.input_tokens
                    output_tokens = chunk.output_tokens
                    finish_reason = chunk.finish_reason or finish_reason
                    continue
                if chunk.delta:
                    parts.append(chunk.delta)
                    yield ChatStreamEvent(kind="delta", delta=chunk.delta)
        except OperationCancelledError as cancelled:
            # o texto já gerado NÃO é descartado: segue na exceção para que
            # quem chamou decida aproveitá-lo (o chat persiste como parcial)
            cancelled.partial = "".join(parts)
            self._record_chat(
                request,
                provider,
                started,
                chars,
                input_tokens,
                output_tokens,
                success=False,
                error=str(cancelled),
                outcome=_outcome(cancelled),
            )
            raise
        except Exception as exc:
            self._record_chat(
                request,
                provider,
                started,
                chars,
                input_tokens,
                output_tokens,
                success=False,
                error=repr(exc),
                outcome="failed",
            )
            raise
        self._record_chat(
            request,
            provider,
            started,
            chars,
            input_tokens,
            output_tokens,
            success=True,
            error=None,
        )
        yield ChatStreamEvent(
            kind="final",
            result=ChatResult(
                text="".join(parts),
                provider=provider.name,
                model=provider.model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                finish_reason=finish_reason,
            ),
        )

    def _record_chat(
        self,
        request: ChatRequest,
        provider: ChatProviderPort,
        started: float,
        chars: int,
        input_tokens: int,
        output_tokens: int,
        *,
        success: bool,
        error: str | None,
        outcome: str = "completed",
    ) -> None:
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        cost = (
            provider.cost_usd(input_tokens=input_tokens, output_tokens=output_tokens)
            if success
            else 0.0
        )
        record = AICallRecord(
            kind="completion",
            provider=provider.name,
            model=provider.model,
            purpose=request.purpose,
            privacy=request.privacy,
            input_units=input_tokens,
            input_chars=chars,
            duration_ms=duration_ms,
            cost_usd=cost,
            success=success,
            outcome=outcome,
            error=error,
            correlation_id=request.correlation_id,
        )
        self._trace.appendleft(record)
        self._metrics.increment("ai_calls", kind="completion", provider=provider.name)
        self._metrics.observe("ai_call_ms", duration_ms, kind="completion")
        if outcome == "failed":  # cancelamento não é falha (ADR-032)
            self._metrics.increment("ai_calls_failed", kind="completion")
        elif outcome in ("cancelled", "timeout"):
            self._metrics.increment("ai_calls_cancelled", kind="completion", outcome=outcome)
        _log.info(
            "ai_call",
            kind="completion",
            provider=provider.name,
            model=provider.model,
            duration_ms=duration_ms,
            success=success,
        )
        if self._explain is not None:  # ADR-023
            local_names = [p.name for p in self._chatters if p.is_local]
            self._explain.record(
                Explanation(
                    component="ai_gateway",
                    decision=f"chat via {provider.name}",
                    reason=f"política {request.privacy.value}; propósito {request.purpose}"
                    + (f"; provedor forçado {request.provider!r}" if request.provider else ""),
                    inputs_used={"messages": len(request.messages), "chars": chars},
                    alternatives=tuple(p.name for p in self._chatters if p.name != provider.name),
                    algorithm=f"roteamento por privacidade (locais: {local_names})",
                    confidence=1.0,
                    consequences=(f"custo estimado ${cost:.5f}",) if not provider.is_local else (),
                    correlation_id=request.correlation_id,
                )
            )

    # ------------------------------------------------------------ trace

    def _record(
        self,
        request: EmbedRequest,
        provider: EmbeddingProviderPort,
        started: float,
        chars: int,
        *,
        success: bool,
        error: str | None,
        outcome: str = "completed",
    ) -> None:
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        record = AICallRecord(
            kind="embedding",
            provider=provider.name,
            model=provider.model,
            purpose=request.purpose,
            privacy=request.privacy,
            input_units=len(request.texts),
            input_chars=chars,
            duration_ms=duration_ms,
            cost_usd=0.0,  # local; custo real entra com provedores cloud
            success=success,
            outcome=outcome,
            error=error,
            correlation_id=request.correlation_id,
        )
        self._trace.appendleft(record)
        self._metrics.increment("ai_calls", kind="embedding", provider=provider.name)
        self._metrics.observe("ai_call_ms", duration_ms, kind="embedding")
        if outcome == "failed":
            self._metrics.increment("ai_calls_failed", kind="embedding")
        elif outcome in ("cancelled", "timeout"):
            self._metrics.increment("ai_calls_cancelled", kind="embedding", outcome=outcome)
        _log.info(
            "ai_call",
            kind="embedding",
            provider=provider.name,
            model=provider.model,
            units=len(request.texts),
            duration_ms=duration_ms,
            success=success,
        )
        if self._explain is not None:  # ADR-023
            local_names = [p.name for p in self._embedders if p.is_local]
            self._explain.record(
                Explanation(
                    component="ai_gateway",
                    decision=f"embeddings via {provider.name}",
                    reason=f"política {request.privacy.value}; propósito {request.purpose}",
                    inputs_used={"texts": len(request.texts), "chars": chars},
                    alternatives=tuple(p.name for p in self._embedders if p.name != provider.name),
                    algorithm=f"roteamento por privacidade (locais: {local_names})",
                    confidence=1.0,
                    consequences=(f"{len(request.texts)} vetores de {provider.dim} dims",),
                    correlation_id=request.correlation_id,
                )
            )

    def trace(self, *, limit: int = 100) -> list[AICallRecord]:
        return list(self._trace)[:limit]

    def chat_providers(self) -> list[ChatProviderInfo]:
        return [
            ChatProviderInfo(
                name=p.name,
                model=p.model,
                is_local=p.is_local,
                # preço unitário derivado do contrato cost_usd (1M de cada lado)
                input_price_per_mtok=p.cost_usd(input_tokens=1_000_000, output_tokens=0),
                output_price_per_mtok=p.cost_usd(input_tokens=0, output_tokens=1_000_000),
            )
            for p in self._chatters
        ]


# canário anti-truncamento
