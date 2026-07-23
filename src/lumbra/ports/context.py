"""Ports do Context Engine.

Antes de qualquer chamada de IA, o Context Engine agrega fragmentos
relevantes de provedores registrados (memória, documentos, agenda,
tarefas, localização, preferências, histórico...). Cada provedor é um
adaptador plugável; o kernel isola falhas e impõe timeout e orçamento.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ContextRequest(BaseModel):
    """O que o chamador precisa contextualizar."""

    model_config = ConfigDict(frozen=True)

    query: str
    user_id: UUID | None = None
    purpose: str = "chat"  # chat, planning, insight...
    max_fragments: int = Field(default=20, ge=1, le=200)
    # escopo da operação (ex.: {"conversation_id": "..."}) — provedores que
    # dependem de contexto local usam; os demais ignoram
    scope: dict[str, str] = Field(default_factory=dict)


class ContextFragment(BaseModel):
    """Unidade de contexto com proveniência — vira citação na resposta."""

    model_config = ConfigDict(frozen=True)

    source: str  # nome do provedor
    content: str
    relevance: float = Field(ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContextProviderPort(ABC):
    """Um provedor de contexto (memória, agenda, documentos...)."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Identificador único do provedor (kebab-case)."""

    @abstractmethod
    async def provide(self, request: ContextRequest) -> list[ContextFragment]:
        """Retorna fragmentos relevantes. Pode retornar lista vazia."""
