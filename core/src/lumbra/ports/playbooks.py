"""Playbooks — memória PROCEDURAL do usuário (L1).

A Lumbra já guarda três tipos de conhecimento: fatos (memória), documentos
(RAG) e relações (grafo). Faltava o quarto: **como se faz** — o procedimento
que funcionou da última vez.

Um Playbook é um documento curto e estruturado (quando usar, passos,
armadilhas, verificação), escrito em linguagem natural e carregado no contexto
quando for relevante. NÃO é código: não executa nada, não ganha permissão, não
substitui Skill. É conhecimento que o modelo lê — a mesma natureza de uma
memória, com estrutura de receita.

Por que estruturado e não texto solto: "quando usar" é o que permite recuperar
o playbook certo; "armadilhas" é onde mora o valor real (o erro que já custou
caro); "verificação" é o que impede dar por feito o que não funcionou.

Regra dura (ADR-061 e a lição do dogfooding): playbook escrito por um AGENTE é
uma escrita de risco — passa pela política de aprovação antes de virar
conhecimento persistente. Memória procedural errada é pior que ausente, porque
se repete.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PlaybookOrigin(StrEnum):
    """De onde veio o procedimento — muda o quanto se confia nele."""

    USER = "user"  # o usuário ditou: confiança alta
    AGENT = "agent"  # o agente inferiu de uma execução: exige aprovação
    IMPORTED = "imported"  # veio de fora (pacote/compartilhado)


class Playbook(BaseModel):
    """Um procedimento reutilizável, na estrutura que o torna recuperável."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    user_id: UUID
    title: str = Field(min_length=3, max_length=120)
    # quando este playbook se aplica — é por aqui que ele é encontrado
    when_to_use: str = Field(min_length=3, max_length=500)
    steps: tuple[str, ...] = Field(min_length=1)  # o procedimento em si
    pitfalls: tuple[str, ...] = ()  # o que deu errado antes
    verification: str = ""  # como saber que funcionou
    origin: PlaybookOrigin = PlaybookOrigin.USER
    # execução que originou o playbook (rastreabilidade até a árvore, ADR-059)
    source_execution_id: UUID | None = None
    uses: int = 0  # quantas vezes já foi recuperado
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))

    def render(self) -> str:
        """Forma textual — o que entra no contexto do modelo."""
        partes = [f"# {self.title}", f"Quando usar: {self.when_to_use}", "Procedimento:"]
        partes += [f"  {i}. {passo}" for i, passo in enumerate(self.steps, 1)]
        if self.pitfalls:
            partes.append("Atenção:")
            partes += [f"  - {p}" for p in self.pitfalls]
        if self.verification:
            partes.append(f"Como verificar: {self.verification}")
        return "\n".join(partes)


class PlaybookStorePort(ABC):
    """Persistência de playbooks. Busca por texto — o volume é pequeno por
    natureza (procedimentos, não documentos), então não precisa de vetor."""

    @abstractmethod
    async def add(self, playbook: Playbook) -> Playbook: ...

    @abstractmethod
    async def search(self, *, user_id: UUID, query: str, limit: int = 3) -> list[Playbook]:
        """Playbooks relevantes para a consulta, mais pertinentes primeiro."""

    @abstractmethod
    async def list_by_user(self, user_id: UUID, *, limit: int = 50) -> list[Playbook]: ...

    @abstractmethod
    async def delete(self, playbook_id: UUID, *, user_id: UUID) -> bool:
        """Remove — o usuário é dono do que a plataforma aprendeu sobre ele."""

    @abstractmethod
    async def touch(self, playbook_id: UUID) -> None:
        """Registra um uso (sinal de utilidade real)."""


# canário anti-truncamento
