"""MemoryModule — memória em cinco camadas como módulo do kernel.

Skills do domínio ``memory``:

* ``memory.remember``    — grava memória (embedding via AI Gateway, local_only)
* ``memory.search``      — recall híbrido (RRF léxico+vetorial x força) explicado
* ``memory.forget``      — exclusão REAL pelo usuário (risco MEDIUM, auditada)
* ``memory.consolidate`` — expira temporárias e arquiva fracas (nunca apaga)

Recall fortalece a memória acessada (reconsolidação), como um cérebro:
lembrar de algo torna mais provável lembrar de novo.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic import Field

from lumbra.domain.events import EventPayload, EventRegistry
from lumbra.domain.memory import (
    ARCHIVE_THRESHOLD,
    MemoryKind,
    boosted_importance,
    effective_strength,
)
from lumbra.kernel.kernel import LumbraKernel, LumbraModule, ModuleManifest
from lumbra.ports.ai import AIGatewayPort, EmbedRequest, NoEligibleProviderError, PrivacyMode
from lumbra.ports.explain import Explanation
from lumbra.ports.memory import MemoryStorePort
from lumbra.ports.skills import (
    RiskLevel,
    Skill,
    SkillContext,
    SkillInput,
    SkillManifest,
    SkillOutput,
)
from lumbra.shared.logging import get_logger

_log = get_logger("lumbra.memory")

_RRF_K = 60
_POOL = 50
# Calibrado com o modelo multilíngue em uso (MiniLM-L12 paraphrase), medindo
# pares reais em PT-BR: pergunta pertinente x memória fica entre 0,24 e 0,75
# ("Onde eu moro mesmo?" x "O usuário mora em Curitiba" = 0,29), enquanto
# pergunta sem relação fica em ~0,08. O corte antigo (0,30) descartava
# recall legítimo por uma casa decimal. Ver tests/integration/test_memory_recall.py,
# que trava esta calibração — mudar o modelo de embedding exige revisitar.
_MIN_SIMILARITY = 0.20


class MemoryRemembered(EventPayload):
    memory_id: str
    kind: str


class MemoryForgotten(EventPayload):
    memory_id: str


class MemoryConsolidated(EventPayload):
    expired: int
    archived: int


def register_memory_events(registry: EventRegistry) -> None:
    for event_type, payload_cls in (
        ("memory.remembered", MemoryRemembered),
        ("memory.forgotten", MemoryForgotten),
        ("memory.consolidated", MemoryConsolidated),
    ):
        if (event_type, 1) not in registry.known_types():
            registry.event(event_type)(payload_cls)


# ------------------------------------------------------------------ skills I/O


class RememberInput(SkillInput):
    content: str
    kind: MemoryKind = MemoryKind.EPISODIC
    importance: float = 0.5
    source_ref: dict[str, Any] = Field(default_factory=dict)
    expires_in_hours: float | None = None  # exigido para temporary


class RememberOutput(SkillOutput):
    memory_id: str
    kind: str
    embedded: bool


class SearchInput(SkillInput):
    query: str
    limit: int = 10
    kinds: tuple[MemoryKind, ...] | None = None


class SearchOutput(SkillOutput):
    hits: tuple[dict[str, Any], ...]
    mode: str  # hybrid | lexical


class ForgetInput(SkillInput):
    memory_id: str


class ForgetOutput(SkillOutput):
    forgotten: bool


class ConsolidateInput(SkillInput):
    pass


class ConsolidateOutput(SkillOutput):
    expired: int
    archived: int
    kept: int


class MemoryModule(LumbraModule):
    def __init__(self, *, store: MemoryStorePort, gateway: AIGatewayPort | None = None) -> None:
        self._store = store
        self._gateway = gateway
        self._kernel: LumbraKernel | None = None

    @property
    def manifest(self) -> ModuleManifest:
        return ModuleManifest(
            name="memory",
            version="0.1.0",
            description="Memória em cinco camadas: gravar, recall, esquecer, consolidar",
        )

    async def setup(self, kernel: LumbraKernel) -> None:
        self._kernel = kernel
        register_memory_events(kernel.events)
        await kernel.skills.register(
            Skill(
                manifest=SkillManifest(
                    name="memory.remember",
                    description="Grava uma memória em uma das cinco camadas",
                    provider="memory",
                    capabilities=("memory", "write"),
                ),
                input_model=RememberInput,
                output_model=RememberOutput,
                handler=self._remember,
            )
        )
        await kernel.skills.register(
            Skill(
                manifest=SkillManifest(
                    name="memory.search",
                    description="Recall híbrido com explicação (léxico+vetorialxforça)",
                    provider="memory",
                    capabilities=("memory", "search"),
                ),
                input_model=SearchInput,
                output_model=SearchOutput,
                handler=self._search,
            )
        )
        await kernel.skills.register(
            Skill(
                manifest=SkillManifest(
                    name="memory.forget",
                    description="Apaga uma memória em definitivo (direito do usuário)",
                    provider="memory",
                    capabilities=("memory", "delete"),
                    risk_level=RiskLevel.MEDIUM,
                ),
                input_model=ForgetInput,
                output_model=ForgetOutput,
                handler=self._forget,
            )
        )
        await kernel.skills.register(
            Skill(
                manifest=SkillManifest(
                    name="memory.consolidate",
                    description="Expira temporárias vencidas e arquiva memórias fracas",
                    provider="memory",
                    capabilities=("memory", "maintenance"),
                ),
                input_model=ConsolidateInput,
                output_model=ConsolidateOutput,
                handler=self._consolidate,
            )
        )

    # ------------------------------------------------------------ handlers

    async def _embed(self, text: str) -> tuple[float, ...] | None:
        if self._gateway is None:
            return None
        try:
            result = await self._gateway.embed(
                EmbedRequest(texts=(text,), purpose="memory", privacy=PrivacyMode.LOCAL_ONLY)
            )
        except NoEligibleProviderError:
            return None
        return result.vectors[0]

    async def _remember(self, payload: SkillInput, ctx: SkillContext) -> RememberOutput:
        assert isinstance(payload, RememberInput)  # noqa: S101
        assert self._kernel is not None  # noqa: S101
        if ctx.user_id is None:
            raise ValueError("memory.remember exige usuário autenticado")
        if not payload.content.strip():
            raise ValueError("conteúdo vazio não vira memória")
        expires_at = None
        if payload.kind is MemoryKind.TEMPORARY:
            hours = payload.expires_in_hours if payload.expires_in_hours is not None else 24.0
            expires_at = datetime.now(tz=UTC) + timedelta(hours=hours)
        elif payload.expires_in_hours is not None:
            raise ValueError("expires_in_hours só se aplica à camada temporary")
        vector = await self._embed(payload.content)
        item = await self._store.add(
            user_id=ctx.user_id,
            kind=payload.kind.value,
            content=payload.content,
            importance=min(1.0, max(0.0, payload.importance)),
            embedding=vector,
            source_ref=payload.source_ref or {"subject": ctx.subject},
            expires_at=expires_at,
        )
        await self._kernel.publish(
            MemoryRemembered(memory_id=str(item.id), kind=item.kind),
            user_id=ctx.user_id,
            correlation_id=ctx.correlation_id,
        )
        return RememberOutput(memory_id=str(item.id), kind=item.kind, embedded=vector is not None)

    async def _search(self, payload: SkillInput, ctx: SkillContext) -> SearchOutput:
        assert isinstance(payload, SearchInput)  # noqa: S101
        assert self._kernel is not None  # noqa: S101
        if ctx.user_id is None:
            raise ValueError("memory.search exige usuário autenticado")
        query_vector = await self._embed(payload.query)
        mode = "hybrid" if query_vector is not None else "lexical"
        kinds = tuple(k.value for k in payload.kinds) if payload.kinds else None
        lexical, vector = await self._store.search_rows(
            user_id=ctx.user_id,
            query=payload.query,
            query_vector=query_vector,
            kinds=kinds,
            pool=_POOL,
        )
        vector = [(mid, sim) for mid, sim in vector if sim >= _MIN_SIMILARITY]
        now = datetime.now(tz=UTC)
        fused = _fuse(lexical, vector)
        # uma consulta para todos os candidatos (antes: uma por candidato,
        # ~50 idas ao banco por busca)
        itens = await self._store.get_many([f[0] for f in fused])
        hits: list[dict[str, Any]] = []
        for memory_id, rrf, lex_pos, vec_pos, similarity in fused:
            item = itens.get(memory_id)
            if item is None:  # apagada entre a busca e a leitura
                continue
            strength = effective_strength(
                importance=item.importance,
                kind=item.kind,
                last_accessed_at=item.last_accessed_at,
                now=now,
            )
            score = rrf * (0.5 + 0.5 * strength)
            hits.append(
                {
                    "memory_id": str(item.id),
                    "kind": item.kind,
                    "content": item.content,
                    "score": score,
                    # similaridade de cosseno em [0,1]: escala comparável,
                    # usada por dedup (o score é RRF e não serve para isso)
                    "similarity": similarity,
                    "source_ref": item.source_ref,
                    "explanation": _explain(lex_pos, vec_pos, similarity, rrf, strength, score),
                    "_importance": item.importance,
                }
            )
        hits.sort(key=lambda h: h["score"], reverse=True)
        hits = hits[: payload.limit]
        # reconsolidação: recall fortalece — em lote, uma ida ao banco
        await self._store.touch_many(
            [(UUID(hit["memory_id"]), boosted_importance(hit.pop("_importance"))) for hit in hits]
        )
        self._kernel.explain.record(
            Explanation(
                component="memory:search",
                decision=f"recall {mode} com {len(hits)} memórias",
                reason="RRF léxico+vetorial modulado pela força (importânciaxdecaimento)",
                inputs_used={"limit": payload.limit, "kinds": list(kinds or ())},
                algorithm=(
                    "score = RRF(k=60, lado vetorial pesado pela similaridade) "
                    "x (0.5 + 0.5xforça); vetorial só com "
                    "similaridade >= 0.30; recall reforça importância"
                ),
                correlation_id=ctx.correlation_id,
            )
        )
        return SearchOutput(hits=tuple(hits), mode=mode)

    async def _forget(self, payload: SkillInput, ctx: SkillContext) -> ForgetOutput:
        assert isinstance(payload, ForgetInput)  # noqa: S101
        assert self._kernel is not None  # noqa: S101
        if ctx.user_id is None:
            raise ValueError("memory.forget exige usuário autenticado")
        memory_id = UUID(payload.memory_id)
        item = await self._store.get(memory_id)
        if item.user_id != ctx.user_id:
            raise PermissionError("memória de outro usuário")
        await self._store.forget(memory_id)
        await self._kernel.publish(
            MemoryForgotten(memory_id=payload.memory_id),
            user_id=ctx.user_id,
            correlation_id=ctx.correlation_id,
        )
        return ForgetOutput(forgotten=True)

    async def _consolidate(self, payload: SkillInput, ctx: SkillContext) -> ConsolidateOutput:
        assert isinstance(payload, ConsolidateInput)  # noqa: S101
        assert self._kernel is not None  # noqa: S101
        if ctx.user_id is None:
            raise ValueError("memory.consolidate exige usuário autenticado")
        now = datetime.now(tz=UTC)
        expired = await self._store.expire_temporary(now=now)
        archived = kept = 0
        for item in await self._store.list_by_user(ctx.user_id):
            if item.kind == MemoryKind.PERMANENT.value:
                kept += 1
                continue
            strength = effective_strength(
                importance=item.importance,
                kind=item.kind,
                last_accessed_at=item.last_accessed_at,
                now=now,
            )
            if strength < ARCHIVE_THRESHOLD:
                await self._store.archive(item.id)
                archived += 1
            else:
                kept += 1
        self._kernel.explain.record(
            Explanation(
                component="memory:consolidate",
                decision=f"{expired} temporárias expiradas, {archived} arquivadas, {kept} mantidas",
                reason=f"força < {ARCHIVE_THRESHOLD} → arquivada (permanent nunca decai)",
                algorithm="força = importância x 0.5^(dias/meia-vida da camada)",
                consequences=("arquivadas saem do recall; nada foi apagado",),
                correlation_id=ctx.correlation_id,
            )
        )
        await self._kernel.publish(
            MemoryConsolidated(expired=expired, archived=archived),
            user_id=ctx.user_id,
            correlation_id=ctx.correlation_id,
        )
        return ConsolidateOutput(expired=expired, archived=archived, kept=kept)


def _fuse(
    lexical: list[tuple[UUID, int]], vector: list[tuple[UUID, float]]
) -> list[tuple[UUID, float, int | None, int | None, float]]:
    """RRF com o lado vetorial PESADO PELA SIMILARIDADE.

    RRF puro considera apenas a posição, descartando o quanto um candidato
    é parecido — e essa informação nós temos. Sem o peso, uma memória
    fracamente relacionada (similaridade 0,21) que aparece em 2º lugar
    contribui quase tanto quanto a resposta certa (0,80) em 1º, e pode
    vencer no desempate pela força da memória. Multiplicar a contribuição
    vetorial pela similaridade mantém a robustez do RRF (posições ainda
    dominam entre candidatos comparáveis) e impede que ruído admitido pelo
    limiar de recall suba ao topo. O lado léxico continua puro: ali a
    posição já reflete o ts_rank.
    """
    lex_pos = dict(lexical)
    vec_pos = {mid: pos for pos, (mid, _sim) in enumerate(vector, 1)}
    similarity = dict(vector)
    out = []
    for mid in {*lex_pos, *vec_pos}:
        rrf = 0.0
        posicao_lexica = lex_pos.get(mid)
        if posicao_lexica is not None:
            rrf += 1.0 / (_RRF_K + posicao_lexica)
        posicao_vetorial = vec_pos.get(mid)
        if posicao_vetorial is not None:
            rrf += similarity.get(mid, 0.0) / (_RRF_K + posicao_vetorial)
        out.append((mid, rrf, lex_pos.get(mid), vec_pos.get(mid), similarity.get(mid, 0.0)))
    out.sort(key=lambda t: t[1], reverse=True)
    return out


def _explain(
    lex_pos: int | None,
    vec_pos: int | None,
    similarity: float,
    rrf: float,
    strength: float,
    score: float,
) -> str:
    parts = [
        f"léxico: #{lex_pos}" if lex_pos is not None else "léxico: sem casamento",
        (
            f"vetorial: #{vec_pos} (similaridade={similarity:.3f})"
            if vec_pos is not None
            else "vetorial: fora do top"
        ),
        f"RRF={rrf:.5f}",
        f"força={strength:.3f} (importânciaxdecaimento)",
        f"score final={score:.5f}",
    ]
    return "; ".join(parts)


# canário anti-truncamento
