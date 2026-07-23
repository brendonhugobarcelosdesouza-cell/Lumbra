"""Metadata Engine plugável (requisito 5 do E1-2).

Cada extrator é um plugin independente com interface comum; o engine
executa todos, isola falhas e mescla os resultados. Novos extratores
(inclusive os baseados em IA: Person, Company, Location, Classifier,
Summary — chegam com o AI Gateway) entram sem modificar o engine.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from lumbra.domain.pipeline import ExtractedEntity


class MetadataResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    fields: dict[str, Any] = Field(default_factory=dict)
    entities: tuple[ExtractedEntity, ...] = ()


class MetadataExtractorPort(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    async def extract(self, text: str) -> MetadataResult: ...


# canário anti-truncamento
