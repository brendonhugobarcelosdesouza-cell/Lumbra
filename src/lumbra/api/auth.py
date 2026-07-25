"""Autenticação da API: registro, login (OAuth2 password), refresh e guarda.

Camada fina: valida entrada, delega a UserStorePort/PasswordHasher/
TokenService e publica eventos de auditoria (``auth.*``, doc 10) via
kernel. Erros de credencial retornam 401 genérico — nunca revelamos se
o e-mail existe (doc 18).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field

from lumbra.adapters.security.passwords import PasswordHasher
from lumbra.adapters.security.tokens import Claims, TokenError, TokenPair, TokenService, TokenType
from lumbra.domain.events import EventPayload, EventRegistry
from lumbra.domain.scopes import concede
from lumbra.kernel.kernel import LumbraKernel
from lumbra.ports.users import DuplicateEmailError, UserNotFoundError, UserStorePort
from lumbra.shared.logging import get_logger

_log = get_logger("lumbra.api.auth")

_bearer = HTTPBearer(auto_error=False)


# ------------------------------------------------------------------ eventos


class LoginSucceeded(EventPayload):
    method: str  # password | refresh


class RegistrationCompleted(EventPayload):
    pass


def register_auth_events(registry: EventRegistry) -> None:
    """Idempotente — mesmo padrão dos eventos do kernel."""
    for event_type, payload_cls in (
        ("auth.login_succeeded", LoginSucceeded),
        ("auth.registration_completed", RegistrationCompleted),
    ):
        if (event_type, 1) not in registry.known_types():
            registry.event(event_type)(payload_cls)


# ------------------------------------------------------------------ serviços


@dataclass(frozen=True)
class AuthServices:
    users: UserStorePort
    passwords: PasswordHasher
    tokens: TokenService


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=256)  # NIST: comprimento > complexidade


class RegisterResponse(BaseModel):
    user_id: str
    email: EmailStr


class RefreshRequest(BaseModel):
    refresh_token: str


def build_auth_router(services: AuthServices, kernel: LumbraKernel | None) -> APIRouter:
    router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
    if kernel is not None:
        register_auth_events(kernel.events)

    async def _publish(payload: EventPayload, user_id: UUID) -> None:
        if kernel is not None:
            await kernel.publish(payload, user_id=user_id)

    @router.post("/register", status_code=status.HTTP_201_CREATED)
    async def register(body: RegisterRequest) -> RegisterResponse:
        try:
            user = await services.users.create(
                email=body.email, password_hash=services.passwords.hash(body.password)
            )
        except DuplicateEmailError:
            # 409 sem eco do e-mail no corpo
            raise HTTPException(status.HTTP_409_CONFLICT, "e-mail já cadastrado") from None
        _log.info("user_registered", user_id=str(user.id))
        await _publish(RegistrationCompleted(), user.id)
        return RegisterResponse(user_id=str(user.id), email=user.email)

    @router.post("/token")
    async def token(form: Annotated[OAuth2PasswordRequestForm, Depends()]) -> TokenPair:
        """OAuth2 password grant: username = e-mail."""
        try:
            user = await services.users.get_by_email(form.username)
            valid = services.passwords.verify(user.password_hash, form.password)
        except UserNotFoundError:
            # hash fictício para igualar o tempo de resposta (anti-enumeração)
            services.passwords.verify(services.passwords.hash("timing-equalizer"), form.password)
            valid = False
        if not valid:
            _log.warning("login_failed")
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "credenciais inválidas",
                headers={"WWW-Authenticate": "Bearer"},
            )
        _log.info("login_succeeded", user_id=str(user.id))
        await _publish(LoginSucceeded(method="password"), user.id)
        # o DONO autenticado por senha tem autoridade total sobre o próprio Nó
        # (escopo admin "*"); dispositivos e plugins recebem escopos limitados
        # ao serem pareados (ADRs 045/047)
        return services.tokens.issue_pair(user.id, scopes=("*",))

    @router.post("/refresh")
    async def refresh(body: RefreshRequest) -> TokenPair:
        try:
            pair = services.tokens.refresh(body.refresh_token)
        except TokenError as exc:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED, str(exc), headers={"WWW-Authenticate": "Bearer"}
            ) from None
        claims = services.tokens.verify(pair.access_token, expected=TokenType.ACCESS)
        await _publish(LoginSucceeded(method="refresh"), claims.subject)
        return pair

    return router


def make_require_subject(
    tokens: TokenService,
) -> Callable[..., Awaitable[Claims]]:
    """Cria a guarda de autenticação usada pelas rotas protegidas."""

    async def require_subject(
        request: Request,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    ) -> Claims:
        if credentials is None:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "autenticação necessária",
                headers={"WWW-Authenticate": "Bearer"},
            )
        try:
            claims = tokens.verify(credentials.credentials, expected=TokenType.ACCESS)
        except TokenError as exc:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED, str(exc), headers={"WWW-Authenticate": "Bearer"}
            ) from None
        request.state.subject = claims  # disponível para auditoria
        return claims

    return require_subject


def make_require_scope(
    tokens: TokenService,
) -> Callable[[str], Callable[..., Awaitable[Claims]]]:
    """Fábrica de guardas por ESCOPO (ADRs 045/047). Autentica como
    ``require_subject`` e, além disso, exige que os escopos do principal
    cubram o escopo da rota. O dono (login por senha) carrega ``*`` e passa
    em tudo; dispositivos e plugins passam só no que lhes foi concedido."""
    require_subject = make_require_subject(tokens)

    def require_scope(scope: str) -> Callable[..., Awaitable[Claims]]:
        # Depends como VALOR DEFAULT (não dentro de Annotated): com
        # `from __future__ import annotations` a anotação vira string e o
        # FastAPI não resolveria ``require_subject`` (variável de closure).
        async def guarda(claims: Claims = Depends(require_subject)) -> Claims:
            if not concede(claims.scopes, scope):
                raise HTTPException(status.HTTP_403_FORBIDDEN, f"escopo necessário: {scope}")
            return claims

        return guarda

    return require_scope


# canário anti-truncamento
