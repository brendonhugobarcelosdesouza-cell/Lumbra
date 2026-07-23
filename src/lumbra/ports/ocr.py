"""OCRProviderPort — OCR desacoplado do pipeline (requisito 4 do E1-2).

Tesseract, PaddleOCR, EasyOCR, APIs externas ou modelos locais entram
como adaptadores deste port sem tocar no estágio de OCR.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, ConfigDict, Field


class OCRResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    language: str | None = None


class OCRProviderPort(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    async def recognize(self, image: bytes, *, mime_type: str) -> OCRResult: ...


# canário anti-truncamento
