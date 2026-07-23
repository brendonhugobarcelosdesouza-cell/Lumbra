"""Métricas in-memory — snapshot para o playground; Prometheus vem como adapter."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from lumbra.ports.metrics import MetricsPort


def _key(name: str, labels: dict[str, str]) -> str:
    if not labels:
        return name
    rendered = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
    return f"{name}{{{rendered}}}"


class InMemoryMetrics(MetricsPort):
    def __init__(self) -> None:
        self._counters: dict[str, float] = defaultdict(float)
        self._samples: dict[str, list[float]] = defaultdict(list)

    def increment(self, name: str, value: float = 1.0, **labels: str) -> None:
        self._counters[_key(name, labels)] += value

    def observe(self, name: str, value: float, **labels: str) -> None:
        self._samples[_key(name, labels)].append(value)

    def snapshot(self) -> dict[str, Any]:
        histograms = {
            key: {
                "count": len(values),
                "avg_ms": round(sum(values) / len(values), 2),
                "max_ms": round(max(values), 2),
            }
            for key, values in self._samples.items()
            if values
        }
        return {"counters": dict(self._counters), "durations": histograms}


# canário anti-truncamento
