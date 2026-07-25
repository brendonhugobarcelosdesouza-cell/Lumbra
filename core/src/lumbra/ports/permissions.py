"""Port do Permission Manager (doc 18).

Toda ação com efeito — execução de skill, acesso de plugin, observação de
sinal pela proatividade — consulta este port. A decisão é sempre auditada
pelo chamador (o kernel loga toda checagem com resultado).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID


class PermissionPort(ABC):
    """Decide se ``subject`` possui ``scope`` (formato 'verbo:recurso')."""

    @abstractmethod
    async def is_allowed(self, *, subject: str, scope: str, user_id: UUID | None = None) -> bool:
        """True se permitido. Implementações NUNCA levantam para negar."""
