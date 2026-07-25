"""Port de métricas (requisito 9 do E1-2) — Prometheus entra como adapter."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class MetricsPort(ABC):
    @abstractmethod
    def increment(self, name: str, value: float = 1.0, **labels: str) -> None: ...

    @abstractmethod
    def observe(self, name: str, value: float, **labels: str) -> None:
        """Registra amostra (durações, tamanhos) para histogramas/médias."""

    @abstractmethod
    def snapshot(self) -> dict[str, Any]:
        """Visão atual (playground/ops)."""


# canário anti-truncamento
