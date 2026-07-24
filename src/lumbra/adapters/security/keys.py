"""Ed25519: a base criptográfica da identidade por dispositivo (ADR-045).

A identidade de um dispositivo é um par de chaves Ed25519 gerado NELE. O
Nó guarda apenas a chave PÚBLICA; a privada nunca sai do dispositivo. No
pareamento e nas requisições autenticadas por chave, o dispositivo assina
um desafio e o Nó verifica com a pública — sem senha trafegando.

Este módulo expõe primitivas puras (sem estado): geração (usada por
testes e, no futuro, pelo cliente), assinatura (lado dispositivo) e
verificação (lado Nó). Chaves e assinaturas trafegam como base64 de bytes
crus (32 bytes na pública Ed25519), formato estável entre linguagens — o
cliente Dart produz e consome exatamente o mesmo.
"""

from __future__ import annotations

import base64

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)


class InvalidPublicKeyError(ValueError):
    """Chave pública malformada (base64 inválido ou tamanho errado)."""


def _b64e(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _b64d(texto: str) -> bytes:
    try:
        return base64.b64decode(texto, validate=True)
    except (ValueError, TypeError) as exc:
        raise InvalidPublicKeyError(str(exc)) from exc


def generate_keypair() -> tuple[str, str]:
    """Gera um par Ed25519. Devolve (privada_b64, publica_b64), ambas em
    bytes crus. Uso do LADO dispositivo (e testes); o Nó nunca gera pela
    identidade de um dispositivo alheio."""
    private = Ed25519PrivateKey.generate()
    raw_private = private.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    raw_public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return _b64e(raw_private), _b64e(raw_public)


def sign(private_key_b64: str, message: bytes) -> str:
    """Assina ``message`` com a chave privada. Lado dispositivo/testes."""
    private = Ed25519PrivateKey.from_private_bytes(_b64d(private_key_b64))
    return _b64e(private.sign(message))


def verify(public_key_b64: str, message: bytes, signature_b64: str) -> bool:
    """Verifica a assinatura de ``message`` pela chave pública. Lado Nó.

    Retorna bool (nunca levanta por assinatura inválida): a decisão de
    autenticação é do chamador. Chave pública malformada é erro de
    programação/entrada e levanta ``InvalidPublicKeyError``."""
    public = load_public_key(public_key_b64)
    try:
        public.verify(_b64d(signature_b64), message)
    except InvalidSignature:
        return False
    return True


def load_public_key(public_key_b64: str) -> Ed25519PublicKey:
    """Valida e materializa uma chave pública (32 bytes crus em base64)."""
    raw = _b64d(public_key_b64)
    try:
        return Ed25519PublicKey.from_public_bytes(raw)
    except ValueError as exc:
        raise InvalidPublicKeyError(f"chave pública Ed25519 inválida: {exc}") from exc


# canário anti-truncamento
