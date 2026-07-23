"""Extratores determinísticos do Metadata Engine (plugins independentes).

Extratores baseados em IA (Person, Company, Location, DocumentClassifier,
SummaryExtractor) chegam com o AI Gateway na Etapa 3 — mesma interface.
"""

from __future__ import annotations

import re
from collections import Counter

from lumbra.domain.pipeline import ExtractedEntity
from lumbra.ports.metadata import MetadataExtractorPort, MetadataResult


def _entities(kind: str, values: list[str], confidence: float = 1.0) -> MetadataResult:
    unique = list(dict.fromkeys(values))
    return MetadataResult(
        fields={kind: unique} if unique else {},
        entities=tuple(ExtractedEntity(kind=kind, value=v, confidence=confidence) for v in unique),
    )


class EmailExtractor(MetadataExtractorPort):
    _RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

    @property
    def name(self) -> str:
        return "email"

    async def extract(self, text: str) -> MetadataResult:
        return _entities("email", self._RE.findall(text))


class PhoneExtractor(MetadataExtractorPort):
    _RE = re.compile(r"(?:\+55\s?)?(?:\(?\d{2}\)?[\s.-]?)?\d{4,5}[\s.-]?\d{4}\b")

    @property
    def name(self) -> str:
        return "phone"

    async def extract(self, text: str) -> MetadataResult:
        found = [p.strip() for p in self._RE.findall(text) if len(re.sub(r"\D", "", p)) >= 10]
        return _entities("phone", found, confidence=0.8)


class DateExtractor(MetadataExtractorPort):
    _RE = re.compile(r"\b(?:\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})\b")

    @property
    def name(self) -> str:
        return "date"

    async def extract(self, text: str) -> MetadataResult:
        return _entities("date", self._RE.findall(text))


class MoneyExtractor(MetadataExtractorPort):
    _RE = re.compile(r"R\$\s?\d{1,3}(?:\.\d{3})*(?:,\d{2})?|\bUSD?\$?\s?\d+(?:\.\d{2})?\b")

    @property
    def name(self) -> str:
        return "money"

    async def extract(self, text: str) -> MetadataResult:
        return _entities("money", [m.strip() for m in self._RE.findall(text)])


def _valid_cpf(digits: str) -> bool:
    if len(digits) != 11 or digits == digits[0] * 11:
        return False
    for split in (9, 10):
        total = sum(
            int(d) * w for d, w in zip(digits[:split], range(split + 1, 1, -1), strict=False)
        )
        check = (total * 10) % 11 % 10
        if check != int(digits[split]):
            return False
    return True


def _valid_cnpj(digits: str) -> bool:
    if len(digits) != 14 or digits == digits[0] * 14:
        return False
    weights = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    for split in (12, 13):
        w = [6, *weights][-split:]
        total = sum(int(d) * x for d, x in zip(digits[:split], w, strict=False))
        check = 11 - (total % 11)
        check = 0 if check >= 10 else check
        if check != int(digits[split]):
            return False
    return True


class CPFExtractor(MetadataExtractorPort):
    _RE = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")

    @property
    def name(self) -> str:
        return "cpf"

    async def extract(self, text: str) -> MetadataResult:
        found = [c for c in self._RE.findall(text) if _valid_cpf(re.sub(r"\D", "", c))]
        return _entities("cpf", found)


class CNPJExtractor(MetadataExtractorPort):
    _RE = re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")

    @property
    def name(self) -> str:
        return "cnpj"

    async def extract(self, text: str) -> MetadataResult:
        found = [c for c in self._RE.findall(text) if _valid_cnpj(re.sub(r"\D", "", c))]
        return _entities("cnpj", found)


_STOPWORDS_PT = frozenset(
    [
        "a",
        "o",
        "e",
        "de",
        "da",
        "do",
        "das",
        "dos",
        "em",
        "um",
        "uma",
        "para",
        "com",
        "não",
        "que",
        "os",
        "as",
        "no",
        "na",
        "por",
        "se",
        "mais",
        "foi",
        "são",
        "ser",
        "tem",
        "ao",
        "à",
        "seu",
        "sua",
        "ou",
        "quando",
        "muito",
        "nos",
        "já",
        "está",
        "eu",
        "também",
        "só",
        "pelo",
        "pela",
        "até",
        "isso",
        "ela",
        "entre",
    ]
)
_STOPWORDS_EN = frozenset(
    [
        "the",
        "of",
        "and",
        "to",
        "in",
        "a",
        "is",
        "that",
        "it",
        "for",
        "on",
        "with",
        "as",
        "was",
        "at",
        "by",
        "an",
        "be",
        "this",
        "from",
        "or",
        "are",
        "which",
    ]
)


class LanguageDetector(MetadataExtractorPort):
    """Heurística por proporção de stopwords — suficiente até o AI Gateway."""

    @property
    def name(self) -> str:
        return "language"

    async def extract(self, text: str) -> MetadataResult:
        words = re.findall(r"[a-zà-ú]+", text.lower())[:500]
        if not words:
            return MetadataResult()
        pt = sum(w in _STOPWORDS_PT for w in words)
        en = sum(w in _STOPWORDS_EN for w in words)
        language = "pt" if pt >= en else "en"
        return MetadataResult(fields={"language": language})


class KeywordExtractor(MetadataExtractorPort):
    @property
    def name(self) -> str:
        return "keywords"

    async def extract(self, text: str) -> MetadataResult:
        words = [
            w
            for w in re.findall(r"[a-zà-úA-ZÀ-Ú]{4,}", text.lower())
            if w not in _STOPWORDS_PT and w not in _STOPWORDS_EN
        ]
        top = [w for w, _count in Counter(words).most_common(10)]
        return MetadataResult(fields={"keywords": top} if top else {})


def default_extractors() -> list[MetadataExtractorPort]:
    return [
        EmailExtractor(),
        PhoneExtractor(),
        DateExtractor(),
        MoneyExtractor(),
        CPFExtractor(),
        CNPJExtractor(),
        LanguageDetector(),
        KeywordExtractor(),
    ]


# canário anti-truncamento
