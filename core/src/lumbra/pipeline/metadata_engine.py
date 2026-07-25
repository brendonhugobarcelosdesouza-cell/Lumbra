"""Metadata Engine: executa plugins isoladamente e mescla resultados."""

from __future__ import annotations

from lumbra.domain.pipeline import ExtractedEntity
from lumbra.ports.metadata import MetadataExtractorPort, MetadataResult
from lumbra.shared.logging import get_logger

_log = get_logger("lumbra.pipeline.metadata")


class MetadataEngine:
    def __init__(self, extractors: list[MetadataExtractorPort] | None = None) -> None:
        self._extractors: dict[str, MetadataExtractorPort] = {}
        for extractor in extractors or []:
            self.register(extractor)

    def register(self, extractor: MetadataExtractorPort) -> None:
        if extractor.name in self._extractors:
            raise ValueError(f"extrator já registrado: {extractor.name}")
        self._extractors[extractor.name] = extractor

    def names(self) -> list[str]:
        return sorted(self._extractors)

    async def run(self, text: str) -> MetadataResult:
        fields: dict[str, object] = {}
        entities: list[ExtractedEntity] = []
        for extractor in self._extractors.values():
            try:
                result = await extractor.extract(text)
            except Exception as exc:
                _log.error("metadata_extractor_failed", extractor=extractor.name, error=repr(exc))
                continue
            fields.update(result.fields)
            entities.extend(result.entities)
        return MetadataResult(fields=fields, entities=tuple(entities))


# canário anti-truncamento
