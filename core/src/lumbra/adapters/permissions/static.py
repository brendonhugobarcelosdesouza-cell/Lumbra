"""Adaptador de permissões estático (desenvolvimento e testes).

Política padrão explícita por construção — nada de allow-all implícito.
O adaptador real (consents em banco, doc 18) chega com a camada de
persistência, atrás do MESMO port.
"""

from __future__ import annotations

from uuid import UUID

from lumbra.ports.permissions import PermissionPort


class StaticPermissionAdapter(PermissionPort):
    """Permite/nega por lista explícita de escopos, com default configurável."""

    def __init__(
        self,
        *,
        default_allow: bool,
        denied_scopes: frozenset[str] = frozenset(),
        allowed_scopes: frozenset[str] = frozenset(),
    ) -> None:
        self._default = default_allow
        self._denied = denied_scopes
        self._allowed = allowed_scopes

    async def is_allowed(self, *, subject: str, scope: str, user_id: UUID | None = None) -> bool:
        if scope in self._denied:
            return False
        if scope in self._allowed:
            return True
        return self._default
