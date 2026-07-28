"""Fábrica da aplicação FastAPI.

Segurança desde o nascimento (doc 18): cabeçalhos de segurança,
correlation-id, autenticação Bearer nas rotas de negócio e trilha de
auditoria estruturada de todo request. API é camada fina — nenhuma
lógica de negócio aqui.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse

from lumbra import __version__
from lumbra.api.auth import AuthServices, build_auth_router, make_require_subject
from lumbra.kernel.kernel import LumbraKernel
from lumbra.shared.config import Settings, get_settings
from lumbra.shared.ids import uuid7
from lumbra.shared.logging import bind_correlation_id, configure_logging, get_logger

_CORRELATION_HEADER = "X-Correlation-Id"

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def create_app(
    settings: Settings | None = None,
    kernel: LumbraKernel | None = None,
    auth: AuthServices | None = None,
    dev_router: APIRouter | None = None,
    extra_routers: list[APIRouter] | None = None,
) -> FastAPI:
    """Cria a aplicação. Settings, kernel e auth injetáveis para testes."""
    cfg = settings or get_settings()
    configure_logging(
        level=cfg.observability.log_level,
        json_output=cfg.observability.log_json,
    )
    log = get_logger("lumbra.api")
    audit = get_logger("lumbra.api.audit")

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if kernel is not None:
            await kernel.start()
        yield
        if kernel is not None:
            await kernel.stop()

    app = FastAPI(
        title="Lumbra",
        version=__version__,
        docs_url=None if cfg.is_production else "/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = cfg
    app.state.kernel = kernel

    @app.middleware("http")
    async def observe_request(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        correlation_id = request.headers.get(_CORRELATION_HEADER) or str(uuid7())
        bind_correlation_id(correlation_id)
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        subject = getattr(request.state, "subject", None)
        # Trilha de auditoria: método, rota, status, duração, sujeito — sem corpos
        audit.info(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=duration_ms,
            subject=str(subject.subject) if subject else None,
        )
        response.headers[_CORRELATION_HEADER] = correlation_id
        for header, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        return response

    @app.get("/health", tags=["ops"])
    async def health() -> dict[str, str]:
        """Liveness: o processo está de pé."""
        return {"status": "ok", "version": __version__}

    @app.get("/ready", tags=["ops"])
    async def ready() -> Response:
        """Readiness: checks registrados pelo kernel. 503 se algo não está pronto."""
        checks: dict[str, bool] = {}
        if kernel is not None:
            checks = await kernel.readiness()
        all_ready = all(checks.values()) if checks else True
        body: dict[str, Any] = {
            "status": "ready" if all_ready else "not_ready",
            "environment": cfg.environment,
            "checks": checks,
        }
        return JSONResponse(body, status_code=200 if all_ready else 503)

    if auth is not None:
        app.include_router(build_auth_router(auth, kernel))
        require_subject = make_require_subject(auth.tokens)
        for router in extra_routers or []:
            app.include_router(router)
        if dev_router is not None and not cfg.is_production:
            # rotas de dados já carregam a guarda internamente (claims por rota).
            # include_in_schema=False: o Developer Console é ferramenta interna
            # de primeira parte, não a Platform API que clientes/plugins
            # consomem — não pertence ao contrato público (docs/24, Regra 1).
            app.include_router(dev_router, include_in_schema=False)
            from fastapi.responses import HTMLResponse

            from lumbra.api.console_ui import CONSOLE_HTML

            @app.get(
                "/api/v1/dev/console",
                response_class=HTMLResponse,
                include_in_schema=False,
            )
            async def console_page() -> str:
                # página estática pública (dev only); TODOS os dados exigem Bearer
                return CONSOLE_HTML

        @app.get("/api/v1/skills", tags=["skills"], dependencies=[Depends(require_subject)])
        async def list_skills() -> dict[str, Any]:
            """Capability Discovery via API — autenticado."""
            if kernel is None:
                return {"skills": []}
            return {"skills": kernel.capability_catalog()}

    # CORS: clientes web (Flutter web, ADR-043) rodam num origin diferente do
    # Nó, e o navegador bloqueia a chamada sem estes cabeçalhos. Adicionado por
    # ÚLTIMO para ser a camada mais externa (trata o preflight OPTIONS). O app
    # autentica por Bearer no header (não cookie), então não precisamos de
    # credenciais e podemos liberar origins amplamente fora de produção. Em
    # produção, só os origins explicitamente configurados.
    origins = ["*"] if not cfg.is_production else list(cfg.security.cors_allow_origins)
    if origins:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    log.info(
        "app_created",
        environment=cfg.environment,
        kernel=kernel is not None,
        auth=auth is not None,
    )
    return app


# canário anti-truncamento
