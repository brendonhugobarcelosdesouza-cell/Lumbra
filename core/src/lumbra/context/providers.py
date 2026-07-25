"""Provedores de contexto do Context Engine (princípio nº 5, Context First).

Agentes e o chat NUNCA consultam bancos diretamente: pedem contexto ao
Context Engine, que consulta estes provedores em paralelo, com timeout e
isolamento de falhas. Cada provedor delega às SKILLS já existentes — um
único caminho para busca (permissões, eventos e explicações incluídos),
sem duplicar lógica de ranking.

Cada fragmento carrega proveniência em ``metadata`` — é o que vira
citação verificável na resposta do assistente (ADR-029).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from lumbra.ports.attachments import AttachmentState, AttachmentStorePort
from lumbra.ports.context import ContextFragment, ContextProviderPort, ContextRequest
from lumbra.ports.document_store import DocumentStorePort
from lumbra.ports.skills import SkillContext

if TYPE_CHECKING:
    from lumbra.kernel.skill_registry import SkillRegistry

# scores de RRF/recall são pequenos e sem teto fixo; normalizamos para
# [0,1] pela posição, que é o que o Context Engine usa para ordenar.
_POSITION_DECAY = 0.9


def _relevance(position: int) -> float:
    return max(0.05, _POSITION_DECAY**position)


def _diversify(
    hits: list[dict[str, Any]], *, limite: int, por_documento: int
) -> list[dict[str, Any]]:
    """Impede que um único documento monopolize o contexto.

    Uma pergunta ampla ("o que tem nos meus documentos?") casa melhor,
    por acaso, com os muitos trechos de um documento longo — e sem isto
    as ``limite`` vagas iriam todas para ele, escondendo os demais. Aqui
    percorremos os candidatos já ordenados por relevância admitindo no
    máximo ``por_documento`` trechos de cada; se ainda sobrarem vagas,
    afrouxamos o teto em rodadas até preencher. Ou seja: variedade quando
    há de onde escolher, sem descartar relevância quando não há.
    """
    escolhidos: list[dict[str, Any]] = []
    vistos: set[str] = set()
    contagem: dict[str, int] = {}
    teto = por_documento
    while len(escolhidos) < limite and teto <= limite:
        for hit in hits:
            if hit["chunk_id"] in vistos:
                continue
            doc = hit["document_id"]
            if contagem.get(doc, 0) >= teto:
                continue
            escolhidos.append(hit)
            vistos.add(hit["chunk_id"])
            contagem[doc] = contagem.get(doc, 0) + 1
            if len(escolhidos) >= limite:
                break
        teto += 1
    return escolhidos[:limite]


class DocumentContextProvider(ContextProviderPort):
    """Trechos de documentos indexados, via skill ``document.find``."""

    def __init__(self, skills: SkillRegistry, *, limit: int = 8, per_document: int = 3) -> None:
        self._skills = skills
        self._limit = limit
        # teto de trechos por documento. Equilíbrio entre dois modos de
        # falha vistos no dogfooding: teto baixo demais corta o trecho
        # certo de um documento denso (o RESUMO da fatura era o 3º melhor
        # e não entrava); alto demais deixa um documento monopolizar
        # perguntas amplas. 3-de-8 dá fôlego ao documento dominante sem
        # sufocar os demais.
        self._per_document = per_document

    @property
    def name(self) -> str:
        return "documents"

    async def provide(self, request: ContextRequest) -> list[ContextFragment]:
        if request.user_id is None:
            return []
        # busca mais candidatos do que as vagas: sobra material para
        # diversificar por documento sem uma segunda ida ao banco
        result = await self._skills.execute(
            "document.find",
            {"query": request.query, "limit": max(self._limit * 4, 20)},
            context=SkillContext(subject="context-engine", user_id=request.user_id),
        )
        brutos: tuple[dict[str, Any], ...] = result.hits  # type: ignore[attr-defined]
        hits = _diversify(list(brutos), limite=self._limit, por_documento=self._per_document)
        return [
            ContextFragment(
                source=self.name,
                content=_clean(hit["snippet"]),
                relevance=_relevance(position),
                metadata={
                    "kind": "document",
                    "ref_id": hit["chunk_id"],
                    "document_id": hit["document_id"],
                    "title": hit.get("title") or hit["uri"].rsplit("/", 1)[-1],
                    "uri": hit["uri"],
                    "score": hit["score"],
                    "why": hit["explanation"],
                },
            )
            for position, hit in enumerate(hits)
        ]


class MemoryContextProvider(ContextProviderPort):
    """Memórias do usuário, via skill ``memory.search`` (recall reforça)."""

    def __init__(self, skills: SkillRegistry, *, limit: int = 5) -> None:
        self._skills = skills
        self._limit = limit

    @property
    def name(self) -> str:
        return "memories"

    async def provide(self, request: ContextRequest) -> list[ContextFragment]:
        if request.user_id is None:
            return []
        result = await self._skills.execute(
            "memory.search",
            {"query": request.query, "limit": self._limit},
            context=SkillContext(subject="context-engine", user_id=request.user_id),
        )
        hits: tuple[dict[str, Any], ...] = result.hits  # type: ignore[attr-defined]
        return [
            ContextFragment(
                source=self.name,
                content=hit["content"],
                relevance=_relevance(position),
                metadata={
                    "kind": "memory",
                    "ref_id": hit["memory_id"],
                    "title": f"memória ({hit['kind']})",
                    "score": hit["score"],
                    "why": hit["explanation"],
                },
            )
            for position, hit in enumerate(hits)
        ]


class AttachmentContextProvider(ContextProviderPort):
    """Anexos da conversa atual (E2-03).

    Existe além do provedor de documentos por um motivo prático: quem
    acabou de anexar um arquivo espera que a pergunta seguinte seja sobre
    ELE, mesmo que a busca por relevância o classifique abaixo de outros
    documentos. Os anexos mais recentes entram com prioridade alta, mas
    continuam sendo chunks normais — a citação é a mesma de um documento.
    """

    def __init__(
        self,
        attachments: AttachmentStorePort,
        documents: DocumentStorePort,
        *,
        max_attachments: int = 2,
        chunks_por_anexo: int = 3,
    ) -> None:
        self._attachments = attachments
        self._documents = documents
        self._max = max_attachments
        self._chunks = chunks_por_anexo

    @property
    def name(self) -> str:
        return "attachments"

    async def provide(self, request: ContextRequest) -> list[ContextFragment]:
        conversation_id = request.scope.get("conversation_id")
        if conversation_id is None:
            return []
        recentes = [
            a
            for a in await self._attachments.list_of_conversation(UUID(conversation_id))
            if a.state is AttachmentState.READY and a.document_id is not None
        ][-self._max :]
        fragments: list[ContextFragment] = []
        for anexo in reversed(recentes):  # mais recente primeiro
            assert anexo.document_id is not None  # noqa: S101
            chunks = await self._documents.chunks_of(anexo.document_id)
            for posicao, chunk in enumerate(chunks[: self._chunks]):
                fragments.append(
                    ContextFragment(
                        source=self.name,
                        content=_clean(chunk),
                        # anexo recente domina: quem anexou quer falar disso
                        relevance=min(1.0, 0.99 - posicao * 0.01),
                        metadata={
                            "kind": "document",  # é documento de verdade
                            "ref_id": str(anexo.document_id),
                            "title": anexo.filename,
                            "uri": anexo.storage_uri,
                            "why": f"anexado nesta conversa ({anexo.filename})",
                        },
                    )
                )
        return fragments


def _clean(snippet: str) -> str:
    """ts_headline marca termos com ** — ruído para o modelo."""
    return snippet.replace("**", "").strip()


# canário anti-truncamento
