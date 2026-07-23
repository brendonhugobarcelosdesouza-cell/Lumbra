"""Reflexão — o que vale ser lembrado de uma conversa (E2-06, ADR-034).

Sem isto, cada conversa começa do zero e o usuário se repete. Com isto, o
que ele contou ontem ("moro em Curitiba", "sou alérgico a dipirona") vira
memória episódica e volta pelo Context Engine na conversa de amanhã.

Três cuidados que definem o desenho:

1. **Fora do caminho crítico.** A extração roda ao receber o evento
   ``chat.message_answered``, depois da resposta já entregue. Lembrar não
   pode deixar o chat mais lento.
2. **Privacidade herdada.** Usa a MESMA política da conversa: se ela é
   ``local_only``, a reflexão também é — refletir jamais é uma porta dos
   fundos para mandar conversa privada à nuvem (princípio nº 14).
3. **Memória é cara, não gratuita.** Guardar tudo entope o recall com
   ruído e piora as respostas. Só entram fatos DURÁVEIS sobre o usuário,
   validados, deduplicados contra o que já existe e com proveniência —
   toda memória sabe de qual conversa veio e é auditável em /memory.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError

from lumbra.domain.events import EventPayload, EventRegistry
from lumbra.domain.memory import MemoryKind
from lumbra.kernel.kernel import LumbraKernel, LumbraModule, ModuleManifest
from lumbra.modules.chat import MessageAnswered
from lumbra.ports.ai import AIGatewayPort, ChatMessage, ChatRequest, PrivacyMode
from lumbra.ports.conversations import ConversationStorePort
from lumbra.ports.event_bus import ConsumerSpec
from lumbra.ports.explain import Explanation
from lumbra.ports.skills import (
    Skill,
    SkillContext,
    SkillInput,
    SkillManifest,
    SkillOutput,
)
from lumbra.shared.logging import get_logger

_log = get_logger("lumbra.reflection")

# similaridade acima disto = já sabemos; não duplica
_DUPLICATE_THRESHOLD = 0.82
_MAX_CANDIDATES = 5
_TURNS_ANALISADOS = 6

EXTRACTION_PROMPT = """Analise a conversa e extraia APENAS fatos duráveis sobre o usuário
que valham ser lembrados em conversas futuras.

INCLUA: preferências, dados pessoais estáveis, relacionamentos, rotinas,
decisões tomadas, restrições (saúde, agenda), objetivos de longo prazo.

NÃO INCLUA:
- perguntas do usuário ou respostas do assistente
- fatos sobre o mundo (isso não é sobre o usuário)
- informação efêmera ("preciso disso hoje", "estou com pressa")
- senhas, tokens, números de cartão ou qualquer credencial
- suposições: só o que foi afirmado explicitamente

Responda APENAS com JSON válido, sem texto em volta:
{"fatos": [{"fato": "...", "importancia": 0.0-1.0}]}

Se nada merecer ser lembrado, responda {"fatos": []}. É comum e é o
esperado na maioria das conversas — prefira lembrar de menos a poluir a
memória do usuário."""

_PADROES_SENSIVEIS = ("senha", "password", "token", "cartão de crédito", "cvv", "api key")


class ReflectionCompleted(EventPayload):
    conversation_id: str
    candidates: int
    stored: int
    skipped_duplicates: int

    def partition_key(self) -> str:
        return f"conversation:{self.conversation_id}"


def register_reflection_events(registry: EventRegistry) -> None:
    if ("reflection.completed", 1) not in registry.known_types():
        registry.event("reflection.completed")(ReflectionCompleted)


class _Fato(BaseModel):
    fato: str = Field(min_length=3, max_length=500)
    importancia: float = Field(default=0.5, ge=0.0, le=1.0)


class _Extracao(BaseModel):
    fatos: list[_Fato] = Field(default_factory=list)


class ReflectInput(SkillInput):
    conversation_id: str
    max_messages: int = Field(default=_TURNS_ANALISADOS * 2, ge=2, le=50)


class ReflectOutput(SkillOutput):
    candidates: int
    stored: int
    skipped_duplicates: int
    memories: tuple[str, ...]


class ReflectionModule(LumbraModule):
    def __init__(
        self,
        *,
        conversations: ConversationStorePort,
        gateway: AIGatewayPort,
        every_n_answers: int = 4,
    ) -> None:
        self._conversations = conversations
        self._gateway = gateway
        # refletir a cada resposta custaria uma chamada de LLM por mensagem,
        # para pouco ganho: fatos duráveis aparecem devagar. Em lote, o custo
        # cai e a conversa já tem contexto suficiente para valer a análise.
        self._every = max(1, every_n_answers)
        self._kernel: LumbraKernel | None = None

    @property
    def manifest(self) -> ModuleManifest:
        return ModuleManifest(
            name="reflection",
            version="0.1.0",
            description="Extrai memórias duráveis das conversas (E2-06)",
        )

    async def setup(self, kernel: LumbraKernel) -> None:
        self._kernel = kernel
        register_reflection_events(kernel.events)
        kernel.bus.register(
            ConsumerSpec(
                name="reflection-on-answer",
                patterns=("chat.message_answered",),
                handler=self._on_message_answered,
            )
        )
        await kernel.skills.register(
            Skill(
                manifest=SkillManifest(
                    name="reflection.from_conversation",
                    description="Extrai fatos duráveis de uma conversa e memoriza",
                    provider="reflection",
                    capabilities=("memory", "write"),
                ),
                input_model=ReflectInput,
                output_model=ReflectOutput,
                handler=self._reflect,
            )
        )

    async def _on_message_answered(self, event: Any) -> None:
        """Gatilho FORA do caminho crítico: a resposta já foi entregue.

        Uma falha aqui nunca pode contaminar o chat — no pior caso, deixa-se
        de lembrar algo, o que é bem menos grave que quebrar a conversa."""
        assert self._kernel is not None  # noqa: S101
        payload = self._kernel.events.decode(event)
        assert isinstance(payload, MessageAnswered)  # noqa: S101
        if event.user_id is None:
            return
        conversation_id = UUID(payload.conversation_id)
        history = await self._conversations.history(conversation_id, limit=200)
        respostas = sum(1 for m in history if m.role == "assistant")
        if respostas == 0 or respostas % self._every != 0:
            return
        try:
            await self._kernel.skills.execute(
                "reflection.from_conversation",
                {"conversation_id": payload.conversation_id},
                context=SkillContext(
                    subject="reflection",
                    user_id=event.user_id,
                    correlation_id=event.correlation_id,
                    # herda o token do kernel: desligar cancela a reflexão
                    cancellation=self._kernel.cancellation.child("reflection"),
                ),
            )
        except Exception as exc:
            _log.warning("reflection_failed", error=repr(exc))

    # ------------------------------------------------------------ extração

    async def _reflect(self, payload: SkillInput, ctx: SkillContext) -> ReflectOutput:
        assert isinstance(payload, ReflectInput)  # noqa: S101
        assert self._kernel is not None  # noqa: S101
        if ctx.user_id is None:
            raise ValueError("reflection exige usuário autenticado")
        conversation_id = UUID(payload.conversation_id)
        conversation = await self._conversations.get(conversation_id)
        if conversation.user_id != ctx.user_id:
            raise PermissionError("conversa de outro usuário")

        history = await self._conversations.history(conversation_id, limit=payload.max_messages)
        trocas = [m for m in history if m.role in ("user", "assistant")]
        if not trocas:
            return ReflectOutput(candidates=0, stored=0, skipped_duplicates=0, memories=())

        # privacidade HERDADA da conversa: refletir não é porta dos fundos
        politica = conversation.model_policy
        privacy = PrivacyMode(politica.get("privacy", PrivacyMode.LOCAL_ONLY.value))
        transcricao = "\n".join(
            f"{'Usuário' if m.role == 'user' else 'Assistente'}: {m.content}" for m in trocas
        )
        resposta = await self._gateway.chat(
            ChatRequest(
                messages=(
                    ChatMessage(role="system", content=EXTRACTION_PROMPT),
                    ChatMessage(role="user", content=transcricao),
                ),
                purpose="reflection",
                privacy=privacy,
                provider=politica.get("provider"),
                temperature=0.0,  # extração é tarefa determinística
                correlation_id=ctx.correlation_id,
            ),
            cancellation=ctx.cancellation,
        )

        candidatos = _parse(resposta.text)[:_MAX_CANDIDATES]
        armazenados: list[str] = []
        duplicados = 0
        for candidato in candidatos:
            if _parece_sensivel(candidato.fato):
                _log.info("reflection_skipped_sensitive")
                continue
            if await self._ja_sabemos(candidato.fato, ctx):
                duplicados += 1
                continue
            memoria = await self._kernel.skills.execute(
                "memory.remember",
                {
                    "content": candidato.fato,
                    "kind": MemoryKind.EPISODIC.value,
                    "importance": candidato.importancia,
                    "source_ref": {
                        "origin": "chat-reflection",
                        "conversation_id": payload.conversation_id,
                    },
                },
                context=ctx,
            )
            armazenados.append(memoria.memory_id)  # type: ignore[attr-defined]

        self._kernel.explain.record(
            Explanation(
                component="reflection",
                decision=f"{len(armazenados)} memórias novas de {len(candidatos)} candidatos",
                reason="fatos duráveis sobre o usuário extraídos da conversa",
                inputs_used={
                    "messages": len(trocas),
                    "conversation_id": payload.conversation_id,
                    "privacy": privacy.value,
                },
                algorithm=(
                    f"extração por LLM (temp. 0) + descarte de sensíveis + dedup por "
                    f"similaridade > {_DUPLICATE_THRESHOLD}"
                ),
                consequences=(
                    f"{duplicados} descartados por já existirem",
                    "memórias auditáveis e editáveis em /memory",
                ),
                correlation_id=ctx.correlation_id,
            )
        )
        await self._kernel.publish(
            ReflectionCompleted(
                conversation_id=payload.conversation_id,
                candidates=len(candidatos),
                stored=len(armazenados),
                skipped_duplicates=duplicados,
            ),
            user_id=ctx.user_id,
            correlation_id=ctx.correlation_id,
        )
        return ReflectOutput(
            candidates=len(candidatos),
            stored=len(armazenados),
            skipped_duplicates=duplicados,
            memories=tuple(armazenados),
        )

    async def _ja_sabemos(self, fato: str, ctx: SkillContext) -> bool:
        """Memória duplicada é pior que memória ausente: entope o recall."""
        assert self._kernel is not None  # noqa: S101
        try:
            resultado = await self._kernel.skills.execute(
                "memory.search", {"query": fato, "limit": 1}, context=ctx
            )
        except Exception as exc:  # busca indisponível não impede lembrar
            _log.warning("reflection_dedup_failed", error=repr(exc))
            return False
        hits: tuple[dict[str, Any], ...] = resultado.hits  # type: ignore[attr-defined]
        if not hits:
            return False
        # compara por SIMILARIDADE (cosseno, [0,1]), não pelo score da busca,
        # que é RRF e vive numa escala minúscula sem significado absoluto
        similaridade = hits[0].get("similarity")
        if similaridade is None:  # sem vetorial disponível: não arrisca
            return False
        return float(similaridade) >= _DUPLICATE_THRESHOLD


def _parse(texto: str) -> list[_Fato]:
    """Modelos locais às vezes embrulham o JSON em texto ou cercas de
    código. Extrair o objeto é mais barato que insistir em obediência."""
    bruto = texto.strip()
    if "```" in bruto:
        partes = bruto.split("```")
        bruto = max(partes, key=len).removeprefix("json").strip()
    inicio, fim = bruto.find("{"), bruto.rfind("}")
    if inicio < 0 or fim <= inicio:
        _log.warning("reflection_unparseable")
        return []
    try:
        return _Extracao.model_validate(json.loads(bruto[inicio : fim + 1])).fatos
    except (json.JSONDecodeError, ValidationError) as exc:
        _log.warning("reflection_invalid_json", error=repr(exc))
        return []  # falhar em silêncio: reflexão é opcional, chat não pode quebrar


def _parece_sensivel(fato: str) -> bool:
    minusculo = fato.lower()
    return any(padrao in minusculo for padrao in _PADROES_SENSIVEIS)


# canário anti-truncamento
