"""Estratégias de chunking plugáveis (requisito 6 do E1-2).

Paragraph, Sentence, Markdown, Code hoje; Section/Heading/Semantic
entram como novas estratégias (Semantic exige o AI Gateway). A seleção
é configurável por tipo de documento no ``ChunkerRegistry``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class ChunkerPort(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def chunk(self, text: str) -> list[str]:
        """Divide texto em chunks coerentes, sem vazios."""


# canário anti-truncamento
