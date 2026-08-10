"""Rotas /api/v1/documents (P2-d) — o acervo na Platform API.

Os documentos eram alcançáveis só pelo Developer Console, que é ferramenta
de engenharia e vive FORA do contrato (docs/24, Regra 1). O resultado é que
a coisa mais central da Lumbra — o que ela leu — não tinha caminho de
usuário: indexar uma pasta exigia console de desenvolvedor.

Mesma forma das rotas de playbooks: camada FINA sobre as skills
``document.*``, sem lógica própria, tudo tipado (o cliente Dart é gerado
daqui). Indexar continua passando pelo SkillRegistry — escopo ``read:files``,
risco e explicação valem igual.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from lumbra.adapters.security.tokens import Claims
from lumbra.kernel.kernel import LumbraKernel
from lumbra.ports.document_store import DocumentStorePort
from lumbra.ports.skills import (
    SkillApprovalRequiredError,
    SkillContext,
    SkillError,
    SkillPermissionDeniedError,
)


class DocumentOut(BaseModel):
    """Um documento do acervo, com o estado do pipeline junto.

    ``processing_state`` vai na lista de propósito: saber que um arquivo foi
    visto mas ainda não indexado é a diferença entre "a Lumbra não sabe" e
    "a Lumbra ainda não terminou".
    """

    id: str
    uri: str
    title: str | None = None
    source: str
    mime_type: str | None = None
    doc_kind: str | None = None
    version: int
    processing_state: str


class DocumentsOut(BaseModel):
    documents: tuple[DocumentOut, ...] = ()


class IndexBody(BaseModel):
    path: str = Field(min_length=1)
    # reprocessa mesmo o que não mudou: necessário quando a MÁQUINA muda
    # (novo extrator, novo chunker), porque o arquivo é o mesmo mas o que
    # extraímos dele não é
    force: bool = False


class IndexOut(BaseModel):
    discovered: int
    queued: int
    unchanged: int
    new_versions: int


class TimelineEntryOut(BaseModel):
    """Uma etapa do pipeline naquele documento."""

    stage: str
    started_at: str
    duration_ms: float
    success: bool
    message: str = ""


class DocumentVersionOut(BaseModel):
    version: int
    parent_version: int | None = None
    reason: str
    created_at: str
    indexed_at: str | None = None


class DocumentStatusOut(BaseModel):
    """Por que aquele arquivo está (ou não está) pesquisável.

    Etapas e versões são TIPADAS, não dicionários livres. Dois motivos: o
    cliente gerado só sabe navegar o que tem forma — o gerador Dart produz
    código quebrado para lista de objetos sem esquema (`Map.listFromJson`) —
    e um campo sem forma no contrato é um campo que ninguém consegue usar
    sem ler o código do servidor.
    """

    state: str
    version: int
    timeline: tuple[TimelineEntryOut, ...] = ()
    versions: tuple[DocumentVersionOut, ...] = ()


def build_documents_router(
    kernel: LumbraKernel,
    store: DocumentStorePort | None,
    require_subject: Callable[..., Awaitable[Claims]],
) -> APIRouter:
    """As rotas existem SEMPRE, mesmo sem acervo.

    O contrato é o mesmo independentemente do adaptador (docs/24, Regra 1):
    um Nó sem banco não pode ter uma API diferente, ou o cliente gerado
    passaria a depender de como o servidor foi configurado. Sem acervo, as
    rotas respondem 503 dizendo o porquê — indisponível é um estado, não uma
    rota que some.
    """
    router = APIRouter(prefix="/api/v1/documents", tags=["documents"])
    authed = Annotated[Claims, Depends(require_subject)]

    def _exigir_acervo() -> DocumentStorePort:
        if store is None:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "acervo indisponível: este Nó está sem banco de dados "
                "(LUMBRA_PERSISTENCE=postgres habilita a indexação)",
            )
        return store

    async def _run(name: str, payload: dict[str, Any], claims: Claims) -> Any:
        _exigir_acervo()  # sem acervo, a skill nem está registrada
        ctx = SkillContext(subject=f"user:{claims.subject}", user_id=claims.subject)
        try:
            return await kernel.skills.execute(name, payload, context=ctx)
        except SkillApprovalRequiredError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
        except SkillPermissionDeniedError as exc:
            raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
        except (SkillError, ValueError) as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None

    @router.get("", response_model=DocumentsOut)
    async def list_documents(claims: authed, limit: int = 100) -> dict[str, Any]:
        """O acervo do usuário — o que a Lumbra leu."""
        registros = await _exigir_acervo().list_by_user(claims.subject, limit=limit)
        return {
            "documents": [
                {
                    "id": str(d.id),
                    "uri": d.uri,
                    "title": d.title,
                    "source": d.source,
                    "mime_type": d.mime_type,
                    "doc_kind": d.doc_kind,
                    "version": d.version,
                    "processing_state": d.processing_state,
                }
                for d in registros
            ]
        }

    @router.post("/index", response_model=IndexOut)
    async def index_folder(body: IndexBody, claims: authed) -> dict[str, Any]:
        """Indexa uma pasta local. Devolve o que foi DESCOBERTO e o que foi
        enfileirado — indexar é assíncrono, e prometer 'pronto' aqui seria
        mentira: quem termina é o worker."""
        result = await _run("document.index", body.model_dump(), claims)
        return dict(result.model_dump(mode="json"))

    @router.get("/{document_id}/status", response_model=DocumentStatusOut)
    async def document_status(document_id: str, claims: authed) -> dict[str, Any]:
        """Estado, linha do tempo e versões — por que aquele arquivo está
        (ou não está) pesquisável."""
        result = await _run("document.status", {"document_id": document_id}, claims)
        # a skill devolve dicionários; a API dá forma a eles (só os campos do
        # contrato passam — o que o pipeline guarda a mais não vaza)
        return {
            "state": result.state,
            "version": result.version,
            "timeline": [
                {
                    "stage": t.get("stage", ""),
                    "started_at": str(t.get("started_at", "")),
                    "duration_ms": float(t.get("duration_ms", 0)),
                    "success": bool(t.get("success", False)),
                    "message": t.get("message", ""),
                }
                for t in result.timeline
            ],
            "versions": [
                {
                    "version": int(v.get("version", 0)),
                    "parent_version": v.get("parent_version"),
                    "reason": v.get("reason", ""),
                    "created_at": str(v.get("created_at", "")),
                    "indexed_at": (
                        str(v["indexed_at"]) if v.get("indexed_at") is not None else None
                    ),
                }
                for v in result.versions
            ],
        }

    return router


# canário anti-truncamento
