"""ChatModule — o assistente conversacional (E2-01/E2-02).

Aqui tudo que a plataforma construiu se encontra: o Context Engine reúne
documentos (busca híbrida) e memórias (recall com decaimento), o prompt
é montado com fontes NUMERADAS, o AI Gateway responde sob a política de
privacidade da conversa, e a resposta é persistida com suas citações —
verificáveis, porque cada citação aponta para o chunk/memória exato.

Skills do domínio ``chat``:

* ``chat.start``   — abre conversa (define política de modelo/privacidade)
* ``chat.send``    — envia mensagem e recebe resposta com citações
* ``chat.history`` — histórico com citações de cada resposta

Princípios em ação: nº 5 (Context First — o chat NUNCA consulta bancos
direto), nº 6 (toda IA via Gateway), nº 13 (tudo explicável), nº 14
(privacidade: local_only é o padrão; nuvem exige escolha explícita).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from lumbra.domain.events import EventPayload, EventRegistry
from lumbra.kernel.kernel import LumbraKernel, LumbraModule, ModuleManifest
from lumbra.ports.ai import (
    AIGatewayPort,
    ChatMessage,
    ChatRequest,
    ChatResult,
    PrivacyMode,
)
from lumbra.ports.attachments import AttachmentState, AttachmentStorePort
from lumbra.ports.context import ContextFragment, ContextRequest
from lumbra.ports.conversations import Citation, Conversation, ConversationStorePort
from lumbra.ports.explain import Explanation
from lumbra.ports.skills import (
    Skill,
    SkillContext,
    SkillInput,
    SkillManifest,
    SkillOutput,
)
from lumbra.shared.cancellation import CancellationToken, OperationCancelledError
from lumbra.shared.logging import get_logger

_log = get_logger("lumbra.chat")

_HISTORY_TURNS = 10  # janela de histórico enviada ao modelo
_MAX_FRAGMENTS = 8

SYSTEM_PROMPT = """Você é o Lumbra, o assistente pessoal deste usuário.

Responda em português do Brasil, de forma direta e útil.

REGRAS SOBRE AS FONTES:
- O bloco CONTEXTO traz trechos dos documentos e memórias do usuário, numerados.
- Use APENAS o contexto para afirmar fatos sobre a vida, arquivos e dados do usuário.
- Ao usar uma fonte, cite-a no texto com o número entre colchetes, assim: [1].
- Se o contexto não contiver a resposta, diga com franqueza que não encontrou
  essa informação nos dados do usuário. NUNCA invente fatos pessoais.
- Conhecimento geral do mundo pode ser usado normalmente, sem citação.

QUANDO A PERGUNTA PEDE UM VALOR E O CONTEXTO TEM VÁRIOS CANDIDATOS:
- Os trechos vêm ROTULADOS pela estrutura do documento: cabeçalho de seção,
  linha de tabela, par "rótulo | valor". Esses rótulos são a EVIDÊNCIA que
  distingue um candidato do outro — use-os para decidir, nunca um palpite.
- Documentos financeiros e tabelas costumam ter vários números parecidos
  (ex.: "total desta fatura", "total financiado", "demais faturas", "pagamento
  mínimo"). Se a pergunta pede UM valor e o contexto tem vários candidatos com
  rótulos diferentes, NÃO escolha um no chute.
- Se o rótulo de um candidato corresponde CLARAMENTE à pergunta, responda com
  ele e cite [n]. Se dois ou mais candidatos são plausíveis e os rótulos não
  decidem qual, apresente cada candidato com o seu RÓTULO exato e a sua citação
  [n], e peça que o usuário confirme qual se aplica.
- A decisão se apoia na evidência recuperada (os candidatos e seus rótulos),
  não num grau de confiança inventado. Chutar um valor plausível é pior que
  dizer "encontrei estes valores rotulados, qual você quer?" — especialmente
  em finanças, onde um número errado engana."""


class ConversationStarted(EventPayload):
    conversation_id: str

    def partition_key(self) -> str:
        return f"conversation:{self.conversation_id}"


class AttachmentIngested(EventPayload):
    conversation_id: str
    attachment_id: str
    state: str
    chunks: int

    def partition_key(self) -> str:
        return f"conversation:{self.conversation_id}"


class MessageAnswered(EventPayload):
    conversation_id: str
    message_id: str
    provider: str
    citations: int

    def partition_key(self) -> str:
        return f"conversation:{self.conversation_id}"


def register_chat_events(registry: EventRegistry) -> None:
    for event_type, payload_cls in (
        ("chat.conversation_started", ConversationStarted),
        ("chat.message_answered", MessageAnswered),
        ("chat.attachment_ingested", AttachmentIngested),
    ):
        if (event_type, 1) not in registry.known_types():
            registry.event(event_type)(payload_cls)


# ------------------------------------------------------------------ skills I/O


class StartInput(SkillInput):
    title: str | None = None
    privacy: PrivacyMode = PrivacyMode.LOCAL_ONLY
    provider: str | None = None  # None = roteamento padrão (local primeiro)


class StartOutput(SkillOutput):
    conversation_id: str
    privacy: str
    # anulável => OPCIONAL no contrato (default None): sem isso o schema o
    # marca "required porém null", e o gerador Dart crava assert(!= null) e
    # quebra quando não há provedor forçado.
    provider: str | None = None


class AttachInput(SkillInput):
    """O arquivo já está no BlobStore; aqui ele vira documento indexado."""

    conversation_id: str
    storage_uri: str
    filename: str
    mime_type: str | None = None
    size_bytes: int = 0


class AttachOutput(SkillOutput):
    attachment_id: str
    document_id: str | None
    state: str
    chunks: int
    detail: str | None = None


class ListAttachmentsInput(SkillInput):
    conversation_id: str


class ListAttachmentsOutput(SkillOutput):
    attachments: tuple[dict[str, Any], ...]


class SetPolicyInput(SkillInput):
    conversation_id: str
    privacy: PrivacyMode | None = None  # None = mantém
    provider: str | None = None  # "" limpa a escolha (volta ao roteamento padrão)


class SetPolicyOutput(SkillOutput):
    conversation_id: str
    privacy: str
    provider: str | None


class SendInput(SkillInput):
    conversation_id: str
    content: str
    use_context: bool = True


class SendOutput(SkillOutput):
    message_id: str
    text: str
    citations: tuple[dict[str, Any], ...]
    provider: str
    model: str
    tokens_in: int
    tokens_out: int


class HistoryInput(SkillInput):
    conversation_id: str
    limit: int = 50


class HistoryOutput(SkillOutput):
    messages: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class _Turn:
    """Tudo que uma troca precisa depois do preparo."""

    conversation: Conversation
    fragments: list[ContextFragment]
    citations: tuple[Citation, ...]
    messages: tuple[ChatMessage, ...]
    history_size: int
    privacy: PrivacyMode
    provider: str | None


@dataclass(frozen=True)
class _StreamEvent:
    """Evento de streaming: vira SSE na borda (doc 11)."""

    kind: str  # sources | token | done | cancelled
    delta: str = ""
    reason: str = ""
    requested_by: str = ""
    citations: tuple[dict[str, Any], ...] = ()
    message_id: str = ""
    provider: str = ""
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0


class ChatModule(LumbraModule):
    def __init__(
        self,
        *,
        conversations: ConversationStorePort,
        gateway: AIGatewayPort,
        attachments: AttachmentStorePort | None = None,
    ) -> None:
        self._conversations = conversations
        self._gateway = gateway
        self._attachments = attachments
        self._kernel: LumbraKernel | None = None

    @property
    def manifest(self) -> ModuleManifest:
        return ModuleManifest(
            name="chat",
            version="0.1.0",
            description="Assistente conversacional com RAG e citações verificáveis",
        )

    async def setup(self, kernel: LumbraKernel) -> None:
        self._kernel = kernel
        register_chat_events(kernel.events)
        for skill in (
            Skill(
                manifest=SkillManifest(
                    name="chat.start",
                    description="Abre uma conversa com política de modelo e privacidade",
                    provider="chat",
                    capabilities=("chat",),
                ),
                input_model=StartInput,
                output_model=StartOutput,
                handler=self._start,
            ),
            Skill(
                manifest=SkillManifest(
                    name="chat.send",
                    description="Envia mensagem e responde com contexto e citações",
                    provider="chat",
                    capabilities=("chat", "rag"),
                ),
                input_model=SendInput,
                output_model=SendOutput,
                handler=self._send,
            ),
            Skill(
                manifest=SkillManifest(
                    name="chat.attach",
                    description="Anexa um arquivo à conversa e o indexa (E2-03)",
                    provider="chat",
                    capabilities=("chat", "documents", "write"),
                ),
                input_model=AttachInput,
                output_model=AttachOutput,
                handler=self._attach,
            ),
            Skill(
                manifest=SkillManifest(
                    name="chat.attachments",
                    description="Lista os anexos de uma conversa e seu estado",
                    provider="chat",
                    capabilities=("chat", "documents"),
                ),
                input_model=ListAttachmentsInput,
                output_model=ListAttachmentsOutput,
                handler=self._list_attachments,
            ),
            Skill(
                manifest=SkillManifest(
                    name="chat.set_policy",
                    description="Troca provedor/privacidade de uma conversa existente",
                    provider="chat",
                    capabilities=("chat", "policy"),
                ),
                input_model=SetPolicyInput,
                output_model=SetPolicyOutput,
                handler=self._set_policy,
            ),
            Skill(
                manifest=SkillManifest(
                    name="chat.history",
                    description="Histórico da conversa com as citações de cada resposta",
                    provider="chat",
                    capabilities=("chat", "observability"),
                ),
                input_model=HistoryInput,
                output_model=HistoryOutput,
                handler=self._history,
            ),
        ):
            await kernel.skills.register(skill)

    # ------------------------------------------------------------ handlers

    def _validate_policy(self, privacy: PrivacyMode, provider: str | None) -> None:
        """Falha na ESCOLHA, não no primeiro envio: erro claro e imediato.

        Regra de privacidade (princípio nº 14): escolher um provedor cloud
        exige allow_cloud na mesma conversa — não existe combinação em que
        um dado saia da máquina sem opt-in explícito.
        """
        if provider is None:
            return
        registered = {p.name: p for p in self._gateway.chat_providers()}
        if provider not in registered:
            available = ", ".join(sorted(registered)) or "nenhum registrado"
            raise ValueError(f"provedor {provider!r} não existe (disponíveis: {available})")
        if not registered[provider].is_local and privacy is not PrivacyMode.ALLOW_CLOUD:
            raise ValueError(
                f"provedor {provider!r} é cloud; a conversa precisa de privacy=allow_cloud"
            )

    async def _start(self, payload: SkillInput, ctx: SkillContext) -> StartOutput:
        assert isinstance(payload, StartInput)  # noqa: S101
        assert self._kernel is not None  # noqa: S101
        if ctx.user_id is None:
            raise ValueError("chat.start exige usuário autenticado")
        self._validate_policy(payload.privacy, payload.provider)
        conversation = await self._conversations.create(
            user_id=ctx.user_id,
            title=payload.title,
            model_policy={"privacy": payload.privacy.value, "provider": payload.provider},
        )
        await self._kernel.publish(
            ConversationStarted(conversation_id=str(conversation.id)),
            user_id=ctx.user_id,
            correlation_id=ctx.correlation_id,
        )
        return StartOutput(
            conversation_id=str(conversation.id),
            privacy=payload.privacy.value,
            provider=payload.provider,
        )

    async def _prepare(
        self,
        *,
        conversation_id: UUID,
        content: str,
        user_id: UUID,
        use_context: bool,
        token: CancellationToken | None = None,
    ) -> _Turn:
        """Passos comuns a chat.send e ao streaming: posse, persistência da
        pergunta, contexto, citações e montagem do prompt."""
        assert self._kernel is not None  # noqa: S101
        if not content.strip():
            raise ValueError("mensagem vazia")
        conversation = await self._conversations.get(conversation_id)
        if conversation.user_id != user_id:
            raise PermissionError("conversa de outro usuário")
        await self._conversations.add_message(
            conversation_id=conversation_id, role="user", content=content
        )
        if token:
            token.step("pergunta registrada")
        fragments: list[ContextFragment] = []
        if use_context:
            fragments = await self._kernel.context.gather(
                ContextRequest(
                    query=content,
                    user_id=user_id,
                    purpose="chat",
                    max_fragments=_MAX_FRAGMENTS,
                    scope={"conversation_id": str(conversation_id)},
                )
            )
        if token:
            token.step(f"contexto reunido ({len(fragments)} fragmentos)")
            token.raise_if_cancelled()  # não gasta GPU se já desistiram
        history = await self._conversations.history(conversation_id, limit=_HISTORY_TURNS * 2)
        policy = conversation.model_policy
        return _Turn(
            conversation=conversation,
            fragments=fragments,
            citations=_to_citations(fragments),
            messages=_build_messages(history, fragments),
            history_size=len(history),
            privacy=PrivacyMode(policy.get("privacy", PrivacyMode.LOCAL_ONLY.value)),
            provider=policy.get("provider"),
        )

    async def _finalize(
        self,
        *,
        turn: _Turn,
        result: ChatResult,
        first_message: str,
        ctx: SkillContext,
        streamed: bool,
        cancelled: OperationCancelledError | None = None,
    ) -> UUID:
        """Persiste a resposta com suas citações, nomeia a conversa na
        primeira troca, explica a decisão e publica o evento."""
        assert self._kernel is not None  # noqa: S101
        conversation_id = turn.conversation.id
        message = await self._conversations.add_message(
            conversation_id=conversation_id,
            role="assistant",
            content=result.text,
            tokens_in=result.input_tokens,
            tokens_out=result.output_tokens,
            provider=result.provider,
            model=result.model,
            citations=turn.citations,
        )
        if turn.conversation.title is None:
            await self._conversations.set_title(conversation_id, _title_from(first_message))
        self._kernel.explain.record(
            Explanation(
                component="chat:send",
                decision=(
                    f"resposta INTERROMPIDA de {result.provider} "
                    f"({cancelled.reason.value}), parcial preservado"
                    if cancelled
                    else f"resposta de {result.provider} com {len(turn.citations)} citações"
                ),
                reason=(
                    f"cancelamento pedido por {cancelled.requested_by}"
                    if cancelled
                    else "contexto reunido pelo Context Engine (documentos + memórias)"
                ),
                inputs_used={
                    "fragments": len(turn.fragments),
                    "sources": sorted({f.source for f in turn.fragments}),
                    "history_messages": turn.history_size,
                    "streamed": streamed,
                    **({"completed_steps": list(cancelled.completed_steps)} if cancelled else {}),
                },
                algorithm="RAG: contexto numerado no prompt; modelo cita [n]",
                consequences=(
                    (
                        f"{len(result.text)} caracteres preservados no histórico",
                        "conexão com o provedor encerrada; GPU liberada",
                    )
                    if cancelled
                    else (f"{result.output_tokens} tokens gerados",)
                ),
                correlation_id=ctx.correlation_id,
            )
        )
        await self._kernel.publish(
            MessageAnswered(
                conversation_id=str(conversation_id),
                message_id=str(message.id),
                provider=result.provider,
                citations=len(turn.citations),
            ),
            user_id=ctx.user_id,
            correlation_id=ctx.correlation_id,
        )
        return message.id

    async def stream(
        self,
        *,
        conversation_id: UUID,
        content: str,
        ctx: SkillContext,
        use_context: bool = True,
        cancellation: CancellationToken | None = None,
    ) -> AsyncIterator[_StreamEvent]:
        """Resposta incremental (E2-03).

        Fora do envelope de skill de propósito — skills são pedido→resposta
        única — mas com as MESMAS garantias: posse verificada, contexto pelo
        Context Engine, citações persistidas, explicação e evento ao final.
        As citações são emitidas ANTES do primeiro token: a interface já
        mostra as fontes enquanto o texto ainda está sendo gerado.
        """
        assert self._kernel is not None  # noqa: S101
        if ctx.user_id is None:
            raise ValueError("chat exige usuário autenticado")
        token = cancellation or ctx.cancellation
        turn = await self._prepare(
            conversation_id=conversation_id,
            content=content,
            user_id=ctx.user_id,
            use_context=use_context,
            token=token,
        )
        yield _StreamEvent(
            kind="sources",
            citations=tuple(c.model_dump(mode="json") for c in turn.citations),
        )
        result: ChatResult | None = None
        request = ChatRequest(
            messages=turn.messages,
            purpose="chat",
            privacy=turn.privacy,
            provider=turn.provider,
            correlation_id=ctx.correlation_id,
        )
        try:
            async for event in self._gateway.chat_stream(request, cancellation=token):
                if event.kind == "delta":
                    yield _StreamEvent(kind="token", delta=event.delta)
                elif event.result is not None:
                    result = event.result
        except OperationCancelledError as cancelled:
            # Interrupção não apaga trabalho: o texto gerado até aqui vira
            # mensagem no histórico, marcada como parcial, com as citações
            # que já haviam sido levantadas.
            partial = cancelled.partial or ""
            message_id = await self._finalize(
                turn=turn,
                result=ChatResult(
                    text=partial,
                    provider=turn.provider or "auto",
                    model="",
                    input_tokens=0,
                    output_tokens=0,
                    finish_reason="cancelled",
                ),
                first_message=content,
                ctx=ctx,
                streamed=True,
                cancelled=cancelled,
            )
            yield _StreamEvent(
                kind="cancelled",
                message_id=str(message_id),
                delta=partial,
                reason=cancelled.reason.value,
                requested_by=cancelled.requested_by,
            )
            return
        if result is None:  # transmissão terminou sem resultado final
            raise RuntimeError("stream encerrado sem resposta")
        if token:
            token.step("resposta gerada")
        message_id = await self._finalize(
            turn=turn, result=result, first_message=content, ctx=ctx, streamed=True
        )
        yield _StreamEvent(
            kind="done",
            message_id=str(message_id),
            provider=result.provider,
            model=result.model,
            tokens_in=result.input_tokens,
            tokens_out=result.output_tokens,
        )

    async def _send(self, payload: SkillInput, ctx: SkillContext) -> SendOutput:
        assert isinstance(payload, SendInput)  # noqa: S101
        assert self._kernel is not None  # noqa: S101
        if ctx.user_id is None:
            raise ValueError("chat.send exige usuário autenticado")
        turn = await self._prepare(
            conversation_id=UUID(payload.conversation_id),
            content=payload.content,
            user_id=ctx.user_id,
            use_context=payload.use_context,
            token=ctx.cancellation,
        )
        result = await self._gateway.chat(
            ChatRequest(
                messages=turn.messages,
                purpose="chat",
                privacy=turn.privacy,
                provider=turn.provider,
                correlation_id=ctx.correlation_id,
            ),
            cancellation=ctx.cancellation,
        )
        message_id = await self._finalize(
            turn=turn, result=result, first_message=payload.content, ctx=ctx, streamed=False
        )
        return SendOutput(
            message_id=str(message_id),
            text=result.text,
            citations=tuple(c.model_dump(mode="json") for c in turn.citations),
            provider=result.provider,
            model=result.model,
            tokens_in=result.input_tokens,
            tokens_out=result.output_tokens,
        )

    async def _attach(self, payload: SkillInput, ctx: SkillContext) -> AttachOutput:
        """Anexo NÃO é caminho paralelo: o arquivo entra pelo mesmo pipeline
        de ingestão (extração/OCR, chunking, embeddings, grafo). Por isso um
        anexo vira citação verificável igual a qualquer documento."""
        assert isinstance(payload, AttachInput)  # noqa: S101
        assert self._kernel is not None  # noqa: S101
        if ctx.user_id is None:
            raise ValueError("chat.attach exige usuário autenticado")
        if self._attachments is None:
            raise RuntimeError("armazenamento de anexos não configurado")
        conversation_id = UUID(payload.conversation_id)
        conversation = await self._conversations.get(conversation_id)
        if conversation.user_id != ctx.user_id:
            raise PermissionError("conversa de outro usuário")

        attachment = await self._attachments.create(
            conversation_id=conversation_id,
            user_id=ctx.user_id,
            filename=payload.filename,
            mime_type=payload.mime_type,
            size_bytes=payload.size_bytes,
            storage_uri=payload.storage_uri,
        )
        try:
            result = await self._kernel.skills.execute(
                "document.ingest_file",
                {
                    "uri": payload.storage_uri,
                    "mime_type": payload.mime_type,
                    "title": payload.filename,
                    "source": "chat-upload",
                    "wait": True,  # o usuário quer perguntar sobre isso agora
                },
                context=ctx,
            )
        except Exception as exc:
            await self._attachments.mark(
                attachment.id, state=AttachmentState.FAILED, detail=repr(exc)[:500]
            )
            raise

        indexado = result.state == "indexed"  # type: ignore[attr-defined]
        chunks: int = result.chunks  # type: ignore[attr-defined]
        # sem extrator/OCR o arquivo não vira texto: estado próprio, não erro
        estado = AttachmentState.READY if indexado and chunks else AttachmentState.UNSUPPORTED
        detalhe = (
            None
            if estado is AttachmentState.READY
            else (
                result.detail  # type: ignore[attr-defined]
                or f"sem texto extraível ({payload.mime_type or 'tipo desconhecido'})"
            )
        )
        await self._attachments.mark(
            attachment.id,
            state=estado,
            document_id=UUID(result.document_id),  # type: ignore[attr-defined]
            detail=detalhe,
            extracted_chars=chunks,
        )
        self._kernel.explain.record(
            Explanation(
                component="chat:attach",
                decision=f"anexo {payload.filename} → {estado.value}",
                reason="arquivo processado pelo pipeline de ingestão padrão",
                inputs_used={
                    "mime": payload.mime_type,
                    "bytes": payload.size_bytes,
                    "conversation": payload.conversation_id,
                },
                algorithm="mesmo pipeline dos documentos (extract/OCR → chunk → embedding)",
                consequences=(
                    f"{chunks} trechos indexados e citáveis"
                    if estado is AttachmentState.READY
                    else "conteúdo não pôde ser lido; nada indexado",
                ),
                correlation_id=ctx.correlation_id,
            )
        )
        await self._kernel.publish(
            AttachmentIngested(
                conversation_id=payload.conversation_id,
                attachment_id=str(attachment.id),
                state=estado.value,
                chunks=chunks,
            ),
            user_id=ctx.user_id,
            correlation_id=ctx.correlation_id,
        )
        return AttachOutput(
            attachment_id=str(attachment.id),
            document_id=result.document_id,  # type: ignore[attr-defined]
            state=estado.value,
            chunks=chunks,
            detail=detalhe,
        )

    async def _list_attachments(
        self, payload: SkillInput, ctx: SkillContext
    ) -> ListAttachmentsOutput:
        assert isinstance(payload, ListAttachmentsInput)  # noqa: S101
        if ctx.user_id is None:
            raise ValueError("chat.attachments exige usuário autenticado")
        if self._attachments is None:
            return ListAttachmentsOutput(attachments=())
        conversation_id = UUID(payload.conversation_id)
        conversation = await self._conversations.get(conversation_id)
        if conversation.user_id != ctx.user_id:
            raise PermissionError("conversa de outro usuário")
        itens = await self._attachments.list_of_conversation(conversation_id)
        return ListAttachmentsOutput(attachments=tuple(a.model_dump(mode="json") for a in itens))

    async def _set_policy(self, payload: SkillInput, ctx: SkillContext) -> SetPolicyOutput:
        assert isinstance(payload, SetPolicyInput)  # noqa: S101
        assert self._kernel is not None  # noqa: S101
        if ctx.user_id is None:
            raise ValueError("chat.set_policy exige usuário autenticado")
        conversation_id = UUID(payload.conversation_id)
        conversation = await self._conversations.get(conversation_id)
        if conversation.user_id != ctx.user_id:
            raise PermissionError("conversa de outro usuário")
        current = conversation.model_policy
        privacy = payload.privacy or PrivacyMode(
            current.get("privacy", PrivacyMode.LOCAL_ONLY.value)
        )
        provider: str | None
        if payload.provider is None:
            provider = current.get("provider")
        elif payload.provider == "":
            provider = None  # limpa: volta ao roteamento padrão (local primeiro)
        else:
            provider = payload.provider
        self._validate_policy(privacy, provider)
        await self._conversations.set_model_policy(
            conversation_id, {"privacy": privacy.value, "provider": provider}
        )
        self._kernel.explain.record(
            Explanation(
                component="chat:policy",
                decision=f"conversa agora usa privacy={privacy.value}, provider={provider}",
                reason="escolha explícita do usuário (E2-04)",
                inputs_used={"before": current},
                algorithm="validação contra provedores registrados + regra de privacidade",
                consequences=(
                    ("respostas futuras podem usar provedor cloud (custo por token)",)
                    if provider is not None
                    and not next(
                        p.is_local for p in self._gateway.chat_providers() if p.name == provider
                    )
                    else ("respostas futuras ficam na máquina",)
                ),
                correlation_id=ctx.correlation_id,
            )
        )
        return SetPolicyOutput(
            conversation_id=payload.conversation_id, privacy=privacy.value, provider=provider
        )

    async def _history(self, payload: SkillInput, ctx: SkillContext) -> HistoryOutput:
        assert isinstance(payload, HistoryInput)  # noqa: S101
        if ctx.user_id is None:
            raise ValueError("chat.history exige usuário autenticado")
        conversation_id = UUID(payload.conversation_id)
        conversation = await self._conversations.get(conversation_id)
        if conversation.user_id != ctx.user_id:
            raise PermissionError("conversa de outro usuário")
        messages = await self._conversations.history(conversation_id, limit=payload.limit)
        return HistoryOutput(messages=tuple(m.model_dump(mode="json") for m in messages))


# ------------------------------------------------------------------ montagem do prompt


def _to_citations(fragments: list[ContextFragment]) -> tuple[Citation, ...]:
    return tuple(
        Citation(
            ordinal=position,
            kind=str(fragment.metadata.get("kind", fragment.source)),
            ref_id=UUID(str(fragment.metadata["ref_id"])),
            title=fragment.metadata.get("title"),
            uri=fragment.metadata.get("uri"),
            score=fragment.metadata.get("score"),
            snippet=fragment.content[:500],
        )
        for position, fragment in enumerate(fragments, 1)
        if fragment.metadata.get("ref_id")
    )


def _context_block(fragments: list[ContextFragment]) -> str:
    lines = []
    for position, fragment in enumerate(fragments, 1):
        title = fragment.metadata.get("title", fragment.source)
        lines.append(f"[{position}] ({title}) {fragment.content}")
    return "CONTEXTO:\n" + "\n\n".join(lines)


def _build_messages(
    history: list[Any], fragments: list[ContextFragment]
) -> tuple[ChatMessage, ...]:
    """System + contexto + histórico. O contexto vai como turno de sistema
    logo antes da última pergunta: fica próximo do que deve ser respondido
    e não polui os turnos anteriores."""
    messages: list[ChatMessage] = [ChatMessage(role="system", content=SYSTEM_PROMPT)]
    previous = [m for m in history if m.role in ("user", "assistant")]
    last_user = previous[-1] if previous and previous[-1].role == "user" else None
    body = previous[:-1] if last_user is not None else previous
    messages.extend(
        ChatMessage(role=m.role, content=m.content) for m in body[-(_HISTORY_TURNS * 2) :]
    )
    if fragments:
        messages.append(ChatMessage(role="system", content=_context_block(fragments)))
    if last_user is not None:
        messages.append(ChatMessage(role="user", content=last_user.content))
    return tuple(messages)


def _title_from(first_message: str) -> str:
    clean = " ".join(first_message.split())
    return clean[:60] + ("…" if len(clean) > 60 else "")


# canário anti-truncamento
