"""Rotas /api/v1/chat (doc 11) — camada FINA sobre as skills chat.*.

Duas formas de enviar mensagem, mesmo motor:
* ``POST .../messages``        → JSON completo (skill ``chat.send``)
* ``POST .../messages/stream`` → SSE ``sources``/``token``/``done``
"""

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from lumbra.adapters.security.tokens import Claims
from lumbra.kernel.kernel import LumbraKernel
from lumbra.modules.chat import ChatModule, StartOutput
from lumbra.ports.ai import AIGatewayPort, ChatProviderInfo
from lumbra.ports.attachments import BlobStorePort
from lumbra.ports.conversations import ConversationNotFoundError, ConversationStorePort
from lumbra.ports.skills import SkillContext, SkillError
from lumbra.shared.cancellation import CancellationToken, CancelReason
from lumbra.shared.logging import get_logger

_log = get_logger("lumbra.api.chat")


MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # limite explícito: proteção de memória

# gerações em voo, por (usuário, conversa) — permite cancelar de outra aba
_em_andamento: dict[tuple[str, str], CancellationToken] = {}


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


class CitationOut(BaseModel):
    """Fonte citada numa resposta — espelha o Citation do domínio em tipos
    JSON. Modelo da API (contrato), separado da saída interna da skill."""

    ordinal: int
    kind: str
    ref_id: str
    title: str | None = None
    uri: str | None = None
    score: float | None = None
    snippet: str | None = None


class ChatMessageOut(BaseModel):
    """Mensagem do histórico no contrato tipado."""

    id: str
    conversation_id: str
    role: str
    content: str
    created_at: str
    provider: str | None = None
    model: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    citations: tuple[CitationOut, ...] = ()


class SendResponse(BaseModel):
    """Resposta do /messages: o texto do assistente e suas citações."""

    message_id: str
    text: str
    citations: tuple[CitationOut, ...] = ()
    provider: str
    model: str
    tokens_in: int
    tokens_out: int


class HistoryResponse(BaseModel):
    messages: tuple[ChatMessageOut, ...] = ()


class ConversationOut(BaseModel):
    """Conversa no contrato tipado (antes: dict solto na listagem)."""

    id: str
    user_id: str
    title: str | None = None
    model_policy: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    last_message_at: str | None = None


class ConversationsOut(BaseModel):
    conversations: tuple[ConversationOut, ...] = ()


class ProvidersOut(BaseModel):
    """Cardápio de modelos (E2-04) tipado — antes: mapa livre, que o cliente
    Dart não conseguia desserializar."""

    providers: tuple[ChatProviderInfo, ...] = ()


class SetPolicyResponse(BaseModel):
    conversation_id: str
    privacy: str
    provider: str | None = None  # anulável => opcional (senão quebra o Dart)


class StartBody(BaseModel):
    title: str | None = None
    privacy: str = "local_only"
    provider: str | None = None


class PolicyBody(BaseModel):
    privacy: str | None = None
    provider: str | None = None  # "" limpa a escolha


class SendBody(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    use_context: bool = True


def build_chat_router(
    kernel: LumbraKernel,
    conversations: ConversationStorePort,
    require_subject: Callable[..., Awaitable[Claims]],
    chat_module: ChatModule,
    gateway: AIGatewayPort,
    blobs: BlobStorePort | None = None,
) -> APIRouter:
    def kernel_gateway_providers() -> list[Any]:
        return gateway.chat_providers()

    router = APIRouter(prefix="/api/v1/chat", tags=["chat"])
    authed = Annotated[Claims, Depends(require_subject)]

    async def _run(name: str, payload: dict[str, Any], claims: Claims) -> Any:
        try:
            return await kernel.skills.execute(
                name,
                payload,
                context=SkillContext(subject=f"user:{claims.subject}", user_id=claims.subject),
            )
        except ConversationNotFoundError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "conversa não encontrada") from None
        except PermissionError:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "conversa de outro usuário") from None
        except (SkillError, ValueError) as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None

    @router.post(
        "/conversations",
        status_code=status.HTTP_201_CREATED,
        response_model=StartOutput,
    )
    async def start(body: StartBody, claims: authed) -> dict[str, Any]:
        result = await _run("chat.start", body.model_dump(), claims)
        return dict(result.model_dump(mode="json"))

    @router.post("/conversations/{conversation_id}/attachments", status_code=201)
    async def upload(
        conversation_id: str,
        claims: authed,
        file: Annotated[UploadFile, File()],
    ) -> dict[str, Any]:
        """Arrastar arquivo/imagem para o chat (E2-03).

        O arquivo é gravado no BlobStore e ingerido pelo pipeline padrão —
        vira documento indexado, citável como qualquer outro."""
        if blobs is None:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "anexos indisponíveis")
        conteudo = await file.read()
        if len(conteudo) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                f"arquivo maior que {MAX_UPLOAD_BYTES // (1024 * 1024)}MB",
            )
        if not conteudo:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "arquivo vazio")
        uri = await blobs.save(conteudo, filename=file.filename or "arquivo", owner=claims.subject)
        result = await _run(
            "chat.attach",
            {
                "conversation_id": conversation_id,
                "storage_uri": uri,
                "filename": file.filename or "arquivo",
                "mime_type": file.content_type,
                "size_bytes": len(conteudo),
            },
            claims,
        )
        return dict(result.model_dump(mode="json"))

    @router.get("/conversations/{conversation_id}/attachments")
    async def list_attachments(conversation_id: str, claims: authed) -> dict[str, Any]:
        result = await _run("chat.attachments", {"conversation_id": conversation_id}, claims)
        return dict(result.model_dump(mode="json"))

    @router.get("/providers", response_model=ProvidersOut)
    async def providers(claims: authed) -> dict[str, Any]:
        """Cardápio de modelos para a interface (E2-04): nome, modelo,
        local ou cloud e preço por milhão de tokens."""
        del claims  # exige apenas autenticação
        return {"providers": [p.model_dump(mode="json") for p in kernel_gateway_providers()]}

    @router.patch("/conversations/{conversation_id}/policy", response_model=SetPolicyResponse)
    async def set_policy(conversation_id: str, body: PolicyBody, claims: authed) -> dict[str, Any]:
        result = await _run(
            "chat.set_policy", {"conversation_id": conversation_id, **body.model_dump()}, claims
        )
        return dict(result.model_dump(mode="json"))

    @router.get("/conversations", response_model=ConversationsOut)
    async def list_conversations(claims: authed, limit: int = 50) -> dict[str, Any]:
        items = await conversations.list_by_user(claims.subject, limit=limit)
        return {"conversations": [c.model_dump(mode="json") for c in items]}

    @router.post("/conversations/{conversation_id}/messages", response_model=SendResponse)
    async def send(conversation_id: str, body: SendBody, claims: authed) -> dict[str, Any]:
        result = await _run(
            "chat.send", {"conversation_id": conversation_id, **body.model_dump()}, claims
        )
        return dict(result.model_dump(mode="json"))

    @router.post("/conversations/{conversation_id}/messages/cancel")
    async def cancel_generation(conversation_id: str, claims: authed) -> dict[str, Any]:
        """Cancela a geração em andamento desta conversa (ADR-032).

        Existe além da desconexão do SSE porque nem todo cliente pode
        simplesmente fechar a conexão (aba em segundo plano, app móvel
        suspenso) — e porque cancelar deve ser uma ação explícita e
        auditável, não um efeito colateral de rede."""
        chave = (str(claims.subject), conversation_id)
        token = _em_andamento.get(chave)
        if token is None:
            return {"cancelled": False, "detail": "nenhuma geração em andamento"}
        cancelou = token.cancel(CancelReason.USER, requested_by=f"user:{claims.subject}")
        return {"cancelled": cancelou}

    @router.post("/conversations/{conversation_id}/messages/stream")
    async def send_stream(
        conversation_id: str, body: SendBody, claims: authed, request: Request
    ) -> StreamingResponse:
        """SSE (doc 11): ``sources`` com as citações, ``token`` por pedaço
        de texto, ``done`` ao final. As fontes chegam ANTES do primeiro
        token — a interface já mostra de onde a resposta vem enquanto ela
        ainda está sendo escrita."""
        module = chat_module
        # filho do token do kernel: desligar o servidor encerra a geração
        token = kernel.cancellation.child(f"chat:{conversation_id}")
        chave = (str(claims.subject), conversation_id)
        _em_andamento[chave] = token
        ctx = SkillContext(
            subject=f"user:{claims.subject}", user_id=claims.subject, cancellation=token
        )

        async def vigiar_desconexao() -> None:
            """Cliente sumiu = ninguém vai ler a resposta. Parar de gerar
            libera a GPU imediatamente em vez de terminar no vazio."""
            try:
                while not token.is_cancelled:
                    if await request.is_disconnected():
                        token.cancel(CancelReason.CLIENT_GONE, requested_by="conexão encerrada")
                        return
                    await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                pass

        async def events() -> AsyncIterator[str]:
            vigia = asyncio.create_task(vigiar_desconexao())
            try:
                async for event in module.stream(
                    conversation_id=UUID(conversation_id),
                    content=body.content,
                    ctx=ctx,
                    use_context=body.use_context,
                ):
                    if event.kind == "token":
                        yield _sse("token", {"delta": event.delta})
                    elif event.kind == "sources":
                        yield _sse("sources", {"citations": list(event.citations)})
                    elif event.kind == "cancelled":
                        yield _sse(
                            "cancelled",
                            {
                                "message_id": event.message_id,
                                "reason": event.reason,
                                "requested_by": event.requested_by,
                                "partial_saved": bool(event.delta),
                            },
                        )
                    else:
                        yield _sse(
                            "done",
                            {
                                "message_id": event.message_id,
                                "provider": event.provider,
                                "model": event.model,
                                "usage": {"in": event.tokens_in, "out": event.tokens_out},
                            },
                        )
            except (ConversationNotFoundError, PermissionError, ValueError) as exc:
                # a conexão SSE já está aberta: o erro vai como evento,
                # não como status HTTP (que já foi 200)
                yield _sse("error", {"detail": str(exc) or type(exc).__name__})
            except Exception as exc:  # provedor caiu no meio da geração
                _log.error("chat_stream_failed", error=repr(exc))
                yield _sse("error", {"detail": "falha ao gerar a resposta"})
            finally:
                vigia.cancel()
                _em_andamento.pop(chave, None)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.get(
        "/conversations/{conversation_id}/messages",
        response_model=HistoryResponse,
    )
    async def history(conversation_id: str, claims: authed, limit: int = 50) -> dict[str, Any]:
        result = await _run(
            "chat.history", {"conversation_id": conversation_id, "limit": limit}, claims
        )
        return dict(result.model_dump(mode="json"))

    return router


# canário anti-truncamento
