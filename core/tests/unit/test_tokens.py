"""Testes do TokenService: emissão, verificação, tipos, expiração, adulteração."""

import pytest
from pydantic import SecretStr

from lumbra.adapters.security.tokens import TokenError, TokenService, TokenType
from lumbra.shared.config import SecuritySettings
from lumbra.shared.ids import uuid7


@pytest.fixture()
def service() -> TokenService:
    return TokenService(
        SecuritySettings(jwt_secret=SecretStr("segredo-de-teste-forte-com-32-bytes-ok!"))
    )


def test_roundtrip_access(service):
    subject = uuid7()
    pair = service.issue_pair(subject, scopes=("read:memory",))
    claims = service.verify(pair.access_token, expected=TokenType.ACCESS)
    assert claims.subject == subject
    assert claims.scopes == ("read:memory",)
    assert claims.token_type is TokenType.ACCESS


def test_refresh_token_cannot_authorize_requests(service):
    pair = service.issue_pair(uuid7())
    with pytest.raises(TokenError, match="tipo"):
        service.verify(pair.refresh_token, expected=TokenType.ACCESS)


def test_access_token_cannot_refresh(service):
    pair = service.issue_pair(uuid7())
    with pytest.raises(TokenError):
        service.refresh(pair.access_token)


def test_refresh_rotates_jti(service):
    subject = uuid7()
    pair1 = service.issue_pair(subject)
    pair2 = service.refresh(pair1.refresh_token)
    c1 = service.verify(pair1.access_token, expected=TokenType.ACCESS)
    c2 = service.verify(pair2.access_token, expected=TokenType.ACCESS)
    assert c1.subject == c2.subject
    assert c1.jti != c2.jti  # rotação real


def test_tampered_token_rejected(service):
    pair = service.issue_pair(uuid7())
    tampered = pair.access_token[:-4] + "abcd"
    with pytest.raises(TokenError):
        service.verify(tampered, expected=TokenType.ACCESS)


def test_wrong_secret_rejected(service):
    other = TokenService(
        SecuritySettings(jwt_secret=SecretStr("outro-segredo-tambem-com-32-bytes-ok!"))
    )
    pair = other.issue_pair(uuid7())
    with pytest.raises(TokenError):
        service.verify(pair.access_token, expected=TokenType.ACCESS)


def test_expired_token_rejected():
    # TTL mínimo permitido (60s) com relógio "no passado" via leeway estourado:
    # emitimos com serviço cujo TTL é 60s e verificamos manipulando exp — a via
    # honesta é gerar o token já expirado com PyJWT direto.
    from datetime import UTC, datetime, timedelta

    import jwt as pyjwt

    settings = SecuritySettings(jwt_secret=SecretStr("segredo-expirado-de-teste-32-bytes-ok!"))
    service = TokenService(settings)
    now = datetime.now(tz=UTC)
    token = pyjwt.encode(
        {
            "iss": "lumbra",
            "sub": str(uuid7()),
            "typ": "access",
            "scopes": [],
            "jti": str(uuid7()),
            "iat": now - timedelta(hours=2),
            "exp": now - timedelta(hours=1),
        },
        "segredo-expirado-de-teste-32-bytes-ok!",
        algorithm="HS256",
    )
    with pytest.raises(TokenError):
        service.verify(token, expected=TokenType.ACCESS)


def test_expires_in_matches_settings(service):
    pair = service.issue_pair(uuid7())
    assert pair.expires_in == 900
