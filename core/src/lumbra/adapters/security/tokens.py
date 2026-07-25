"""Emissão e verificação de tokens JWT (doc 18).

Par access/refresh com claims tipadas. Regras:

* ``access`` curto (15 min padrão) autoriza requests; ``refresh`` longo
  (14 dias) só serve para obter novo par (tipo verificado — um refresh
  nunca autoriza um request, e um access nunca gera par novo).
* ``jti`` UUIDv7 em todo token: base para revogação/detecção de reuso
  quando o armazenamento de sessões chegar (doc 18), sem quebrar tokens.
* HS256 com segredo de configuração nesta fase; migração para chaves
  assimétricas gerenciadas é troca de configuração, não de código.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID

import jwt
from pydantic import BaseModel, ConfigDict

from lumbra.shared.config import SecuritySettings
from lumbra.shared.ids import uuid7

_ISSUER = "lumbra"
_LEEWAY_SECONDS = 10


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


class TokenError(Exception):
    """Token inválido, expirado ou do tipo errado. Mensagem segura para logs."""


class Claims(BaseModel):
    model_config = ConfigDict(frozen=True)

    subject: UUID  # user id
    token_type: TokenType
    scopes: tuple[str, ...]
    jti: UUID
    expires_at: datetime


class TokenPair(BaseModel):
    model_config = ConfigDict(frozen=True)

    access_token: str
    refresh_token: str
    token_type: str = "Bearer"  # noqa: S105 — nome do esquema HTTP, não um segredo
    expires_in: int  # segundos do access token


class TokenService:
    def __init__(self, settings: SecuritySettings) -> None:
        self._settings = settings

    # ------------------------------------------------------------ emissão

    def issue_pair(self, subject: UUID, *, scopes: tuple[str, ...] = ()) -> TokenPair:
        return TokenPair(
            access_token=self._issue(
                subject, TokenType.ACCESS, scopes, self._settings.access_token_ttl_seconds
            ),
            refresh_token=self._issue(
                subject, TokenType.REFRESH, scopes, self._settings.refresh_token_ttl_seconds
            ),
            expires_in=self._settings.access_token_ttl_seconds,
        )

    def refresh(self, refresh_token: str) -> TokenPair:
        """Rotação: um refresh válido gera um par NOVO (jti novos)."""
        claims = self.verify(refresh_token, expected=TokenType.REFRESH)
        return self.issue_pair(claims.subject, scopes=claims.scopes)

    # ------------------------------------------------------------ verificação

    def verify(self, token: str, *, expected: TokenType) -> Claims:
        try:
            payload = jwt.decode(
                token,
                self._settings.jwt_secret.get_secret_value(),
                algorithms=[self._settings.jwt_algorithm],
                issuer=_ISSUER,
                leeway=_LEEWAY_SECONDS,
                options={"require": ["exp", "iat", "sub", "jti", "typ", "iss"]},
            )
        except jwt.PyJWTError as exc:
            raise TokenError("token inválido ou expirado") from exc
        if payload["typ"] != expected.value:
            raise TokenError(f"tipo de token inesperado (esperado {expected.value})")
        return Claims(
            subject=UUID(payload["sub"]),
            token_type=TokenType(payload["typ"]),
            scopes=tuple(payload.get("scopes", ())),
            jti=UUID(payload["jti"]),
            expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
        )

    def _issue(
        self, subject: UUID, token_type: TokenType, scopes: tuple[str, ...], ttl_seconds: int
    ) -> str:
        now = datetime.now(tz=UTC)
        return jwt.encode(
            {
                "iss": _ISSUER,
                "sub": str(subject),
                "typ": token_type.value,
                "scopes": list(scopes),
                "jti": str(uuid7()),
                "iat": now,
                "exp": now + timedelta(seconds=ttl_seconds),
            },
            self._settings.jwt_secret.get_secret_value(),
            algorithm=self._settings.jwt_algorithm,
        )


# canário anti-truncamento
