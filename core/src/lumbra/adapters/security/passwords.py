"""Hashing de senhas com Argon2id (doc 18).

Argon2id é o vencedor do Password Hashing Competition e a recomendação
OWASP corrente; os parâmetros padrão da lib (argon2-cffi) seguem o RFC
9106 (low-memory profile) e são recalibráveis sem migração — hashes
antigos são verificáveis e re-hasheados no próximo login se necessário.
"""

from __future__ import annotations

from argon2 import PasswordHasher as _Argon2Hasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError


class PasswordHasher:
    def __init__(self) -> None:
        self._hasher = _Argon2Hasher()

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        """Compara em tempo constante. False para qualquer falha — nunca levanta."""
        try:
            return self._hasher.verify(password_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    def needs_rehash(self, password_hash: str) -> bool:
        return self._hasher.check_needs_rehash(password_hash)


# canário anti-truncamento
