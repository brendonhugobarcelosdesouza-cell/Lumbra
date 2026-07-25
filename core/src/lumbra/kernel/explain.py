"""Explain Engine — implementação in-memory do ExplainPort (ADR-023).

Persistência dedicada chega quando o replay completo exigir; o contrato
não muda.
"""

from __future__ import annotations

from collections import deque
from uuid import UUID

from lumbra.ports.explain import ExplainPort, Explanation


class ExplainEngine(ExplainPort):
    def __init__(self, *, capacity: int = 2000) -> None:
        self._records: deque[Explanation] = deque(maxlen=capacity)

    def record(self, explanation: Explanation) -> None:
        self._records.appendleft(explanation)

    def query(
        self,
        *,
        correlation_id: UUID | None = None,
        component: str | None = None,
        limit: int = 100,
    ) -> list[Explanation]:
        out: list[Explanation] = []
        for record in self._records:
            if correlation_id is not None and record.correlation_id != correlation_id:
                continue
            if component is not None and not record.component.startswith(component):
                continue
            out.append(record)
            if len(out) >= limit:
                break
        return out


# canário anti-truncamento
