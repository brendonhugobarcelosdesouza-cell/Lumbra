"""Developer Console (ADR-022) — ferramenta PERMANENTE de engenharia.

Executa skills com parâmetros JSON, acompanha histórico/duração/erros,
cancela e reexecuta operações, observa eventos do bus, logs estruturados,
documentos/pipeline, busca com explicação e grafo. Painéis de AI Gateway,
Context Engine e embeddings são populados conforme os componentes chegam
(Etapa 3+). Nunca habilitado em produção; dados sempre atrás do Bearer.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from lumbra.adapters.security.tokens import Claims
from lumbra.kernel.executions import ExecutionNotFoundError, ExecutionTracker
from lumbra.kernel.kernel import LumbraKernel
from lumbra.pipeline.runner import PipelineRunner
from lumbra.ports.ai import AIGatewayPort
from lumbra.ports.document_store import DocumentStorePort
from lumbra.ports.knowledge_graph import KnowledgeGraphPort
from lumbra.ports.metrics import MetricsPort
from lumbra.ports.pipeline import ProcessingStorePort
from lumbra.ports.search import SearchPort
from lumbra.ports.skills import SkillNotFoundError
from lumbra.shared.cancellation import CancelReason


class ExecuteRequest(BaseModel):
    kind: str = Field(pattern="^(skill|agent)$")
    name: str
    payload: dict[str, Any] = Field(default_factory=dict)


def build_dev_router(
    *,
    kernel: LumbraKernel,
    tracker: ExecutionTracker,
    documents: DocumentStorePort,
    processing: ProcessingStorePort,
    search: SearchPort,
    metrics: MetricsPort,
    graph: KnowledgeGraphPort,
    runner: PipelineRunner,
    gateway: AIGatewayPort | None = None,
    require_subject: Callable[..., Awaitable[Claims]],
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/dev", tags=["dev-console"])
    authed = Annotated[Claims, Depends(require_subject)]

    # -------------------------------------------------------- execuções

    @router.get("/skills")
    async def list_skills(_claims: authed) -> list[dict[str, Any]]:
        return kernel.capability_catalog()

    @router.post("/executions", status_code=status.HTTP_202_ACCEPTED)
    async def execute(body: ExecuteRequest, claims: authed) -> dict[str, Any]:
        if body.kind == "agent":
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "nenhum agente registrado ainda — agentes chegam com o Orchestrator",
            )
        try:
            kernel.skills.get(body.name)
        except SkillNotFoundError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"skill {body.name}") from None
        record = tracker.start_skill(
            body.name,
            body.payload,
            subject=f"user:{claims.subject}",
            user_id=claims.subject,
        )
        return {"execution_id": str(record.id)}

    @router.get("/executions")
    async def history(_claims: authed) -> list[dict[str, Any]]:
        return [r.model_dump(mode="json", exclude={"error_detail"}) for r in tracker.history()]

    @router.get("/executions/{execution_id}")
    async def detail(execution_id: UUID, _claims: authed) -> dict[str, Any]:
        try:
            record = tracker.get(execution_id)
        except ExecutionNotFoundError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "execução") from None
        return {
            "execution": record.model_dump(mode="json"),
            "events": [e.model_dump(mode="json") for e in tracker.events_of(execution_id)],
        }

    @router.post("/executions/{execution_id}/cancel")
    async def cancel(execution_id: UUID, _claims: authed, reason: str = "user") -> dict[str, Any]:
        """Cancelamento cooperativo (ADR-032): sinaliza o token, que se
        propaga até a conexão com o provedor."""
        try:
            motivo = CancelReason(reason)
        except ValueError:
            motivo = CancelReason.USER
        cancelou = tracker.cancel(
            execution_id, reason=motivo, requested_by=f"console:{_claims.subject}"
        )
        return {"cancelled": cancelou, "reason": motivo.value}

    @router.post("/executions/{execution_id}/rerun", status_code=status.HTTP_202_ACCEPTED)
    async def rerun(execution_id: UUID, _claims: authed) -> dict[str, str]:
        try:
            record = tracker.rerun(execution_id)
        except ExecutionNotFoundError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "execução") from None
        return {"execution_id": str(record.id)}

    @router.get("/executions/{execution_id}/export")
    async def export(execution_id: UUID, _claims: authed) -> dict[str, Any]:
        try:
            return tracker.export(execution_id)
        except ExecutionNotFoundError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "execução") from None

    # -------------------------------------------------------- observabilidade

    @router.get("/events")
    async def recent_events(_claims: authed, limit: int = 100) -> list[dict[str, Any]]:
        return [e.model_dump(mode="json") for e in tracker.recent_events(limit)]

    @router.get("/logs")
    async def recent_logs(_claims: authed, limit: int = 200) -> list[dict[str, Any]]:
        return tracker.recent_logs(limit)

    @router.get("/ai-calls")
    async def ai_calls(_claims: authed, limit: int = 100) -> list[dict[str, Any]]:
        """AI Trace (princípio nº 6): toda chamada de IA, com latência e roteamento."""
        if gateway is None:
            return []
        return [r.model_dump(mode="json") for r in gateway.trace(limit=limit)]

    @router.get("/explanations")
    async def explanations(
        _claims: authed,
        correlation_id: UUID | None = None,
        component: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Explain Everything (ADR-023): decisões consultáveis sem ler logs."""
        records = kernel.explain.query(
            correlation_id=correlation_id, component=component, limit=limit
        )
        return [r.model_dump(mode="json") for r in records]

    @router.get("/metrics")
    async def metrics_snapshot(_claims: authed) -> dict[str, Any]:
        return metrics.snapshot()

    # -------------------------------------------------------- pipeline/dados

    @router.get("/documents")
    async def list_documents(claims: authed) -> list[dict[str, Any]]:
        docs = await documents.list_by_user(claims.subject)
        return [d.model_dump(mode="json") for d in docs]

    @router.get("/documents/{document_id}")
    async def inspect(document_id: UUID, _claims: authed) -> dict[str, Any]:
        document = await documents.get(document_id)
        context = await processing.load_context(document_id)
        return {
            "document": document.model_dump(mode="json"),
            "timeline": [
                t.model_dump(mode="json") for t in await processing.get_timeline(document_id)
            ],
            "versions": [v.model_dump(mode="json") for v in await documents.versions(document_id)],
            "text_preview": (context.text or "")[:5000],
            "metadata": context.metadata,
            "entities": [e.model_dump() for e in context.entities],
            "chunks": await documents.chunks_of(document_id),
        }

    @router.post("/documents/{document_id}/reprocess")
    async def reprocess(document_id: UUID, _claims: authed) -> dict[str, str]:
        document = await documents.get(document_id)
        state = await runner.process(document)
        return {"state": state.value}

    @router.get("/search")
    async def dev_search(q: str, claims: authed, limit: int = 10) -> dict[str, Any]:
        """Mesmo caminho do produto: executa a skill document.find (híbrida)."""
        record = tracker.start_skill(
            "document.find",
            {"query": q, "limit": limit},
            subject="devconsole",
            user_id=claims.subject,
        )
        finished = await tracker.wait(record.id)
        if finished.error is not None:
            return {"mode": "error", "error": finished.error, "hits": []}
        output = finished.output or {}
        return {"mode": output.get("mode", "?"), "hits": output.get("hits", [])}

    @router.get("/graph")
    async def graph_entities(claims: authed, query: str | None = None) -> list[dict[str, Any]]:
        found = await graph.find(user_id=claims.subject, query=query)
        out = []
        for entity in found:
            neighbors = await graph.neighbors(entity.id)
            out.append(
                {
                    **entity.model_dump(mode="json"),
                    "neighbors": [
                        {"rel": rel, **n.model_dump(mode="json")} for rel, n in neighbors
                    ],
                }
            )
        return out

    return router


# canário anti-truncamento
