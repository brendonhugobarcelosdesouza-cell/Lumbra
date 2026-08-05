"""Módulo de Playbooks — a memória procedural como capacidade (L1).

Skills:
* ``playbook.write``  — grava um procedimento. **Risco MEDIUM**: passa pela
  política de aprovação (ADR-054) antes de virar conhecimento persistente. É
  aqui que o Human-in-the-Loop deixa de ser infraestrutura e vira proteção:
  quando um agente propuser um playbook, o usuário decide se aquilo entra.
* ``playbook.search`` — recupera procedimentos relevantes (LOW, leitura).
* ``playbook.forget`` — remove (MEDIUM: o usuário é dono, mas apagar é escrita).

Lição do dogfooding embutida no desenho: a reflexão automática guardou uma
resposta ERRADA como fato e ela contaminou o RAG depois. Conhecimento que o
sistema infere sobre si mesmo precisa de porteiro — memória procedural errada
não erra uma vez, erra sempre que o procedimento for lembrado.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from lumbra.kernel.kernel import LumbraKernel, LumbraModule, ModuleManifest
from lumbra.ports.playbooks import Playbook, PlaybookOrigin, PlaybookStorePort
from lumbra.ports.skills import (
    RiskLevel,
    Skill,
    SkillContext,
    SkillInput,
    SkillManifest,
    SkillOutput,
)
from lumbra.shared.ids import uuid7


class WriteInput(SkillInput):
    title: str
    when_to_use: str
    steps: tuple[str, ...]
    pitfalls: tuple[str, ...] = ()
    verification: str = ""
    origin: PlaybookOrigin = PlaybookOrigin.USER
    source_execution_id: str | None = None


class WriteOutput(SkillOutput):
    playbook_id: str
    title: str


class SearchInput(SkillInput):
    query: str
    limit: int = 3


class SearchOutput(SkillOutput):
    hits: tuple[dict[str, Any], ...] = ()


class ForgetInput(SkillInput):
    playbook_id: str


class ForgetOutput(SkillOutput):
    forgotten: bool


class PlaybookModule(LumbraModule):
    """Registra as skills de memória procedural."""

    def __init__(self, store: PlaybookStorePort) -> None:
        self._store = store

    @property
    def manifest(self) -> ModuleManifest:
        return ModuleManifest(
            name="playbooks",
            version="0.1.0",
            description="Memória procedural: grava, recupera e esquece procedimentos",
        )

    async def setup(self, kernel: LumbraKernel) -> None:
        await kernel.skills.register(
            Skill(
                manifest=SkillManifest(
                    name="playbook.write",
                    description="Grava um procedimento reutilizável (memória procedural)",
                    provider="playbooks",
                    capabilities=("playbook", "learning"),
                    # MEDIUM: escrever conhecimento que será lembrado depois é
                    # ação de impacto — passa pela política de aprovação
                    risk_level=RiskLevel.MEDIUM,
                    required_scopes=("write:playbooks",),
                ),
                input_model=WriteInput,
                output_model=WriteOutput,
                handler=self._write,
                describe=self._descrever_write,
            )
        )
        await kernel.skills.register(
            Skill(
                manifest=SkillManifest(
                    name="playbook.search",
                    description="Recupera procedimentos relevantes para a tarefa",
                    provider="playbooks",
                    capabilities=("playbook", "search"),
                    risk_level=RiskLevel.LOW,
                    required_scopes=("read:playbooks",),
                ),
                input_model=SearchInput,
                output_model=SearchOutput,
                handler=self._search,
            )
        )
        await kernel.skills.register(
            Skill(
                manifest=SkillManifest(
                    name="playbook.forget",
                    description="Remove um procedimento (o usuário é dono)",
                    provider="playbooks",
                    capabilities=("playbook",),
                    risk_level=RiskLevel.MEDIUM,
                    required_scopes=("write:playbooks",),
                ),
                input_model=ForgetInput,
                output_model=ForgetOutput,
                handler=self._forget,
                describe=self._descrever_forget,
            )
        )

    # ------------------------------------------------------- descrições
    # O que o usuário lê na tela de aprovação. Sem isto ele veria
    # "playbook.forget" e um id opaco — e aprovaria uma exclusão sem saber
    # o que está apagando.

    async def _descrever_write(self, payload: SkillInput, _ctx: SkillContext) -> str:
        assert isinstance(payload, WriteInput)  # noqa: S101
        origem = "a Lumbra quer guardar" if payload.origin is PlaybookOrigin.AGENT else "guardar"
        return f"{origem} o procedimento “{payload.title}” ({len(payload.steps)} passos)"

    async def _descrever_forget(self, payload: SkillInput, ctx: SkillContext) -> str:
        assert isinstance(payload, ForgetInput)  # noqa: S101
        alvo = payload.playbook_id
        if ctx.user_id is not None:
            # busca o título: apagar sem saber O QUE se apaga não é decisão
            for p in await self._store.list_by_user(ctx.user_id, limit=200):
                if str(p.id) == alvo:
                    return f"esquecer o procedimento “{p.title}”"
        return f"esquecer o procedimento {alvo}"

    # ------------------------------------------------------- handlers

    async def _write(self, payload: SkillInput, ctx: SkillContext) -> WriteOutput:
        assert isinstance(payload, WriteInput)  # noqa: S101
        if ctx.user_id is None:
            raise ValueError("playbook.write exige usuário autenticado")
        playbook = Playbook(
            id=uuid7(),
            user_id=ctx.user_id,
            title=payload.title,
            when_to_use=payload.when_to_use,
            steps=payload.steps,
            pitfalls=payload.pitfalls,
            verification=payload.verification,
            origin=payload.origin,
            source_execution_id=(
                UUID(payload.source_execution_id) if payload.source_execution_id else None
            ),
        )
        gravado = await self._store.add(playbook)
        return WriteOutput(playbook_id=str(gravado.id), title=gravado.title)

    async def _search(self, payload: SkillInput, ctx: SkillContext) -> SearchOutput:
        assert isinstance(payload, SearchInput)  # noqa: S101
        if ctx.user_id is None:
            raise ValueError("playbook.search exige usuário autenticado")
        achados = await self._store.search(
            user_id=ctx.user_id, query=payload.query, limit=payload.limit
        )
        for p in achados:  # recuperar é sinal de utilidade
            await self._store.touch(p.id)
        return SearchOutput(
            hits=tuple(
                {
                    "playbook_id": str(p.id),
                    "title": p.title,
                    "when_to_use": p.when_to_use,
                    "content": p.render(),
                    "origin": p.origin.value,
                    "uses": p.uses,
                }
                for p in achados
            )
        )

    async def _forget(self, payload: SkillInput, ctx: SkillContext) -> ForgetOutput:
        assert isinstance(payload, ForgetInput)  # noqa: S101
        if ctx.user_id is None:
            raise ValueError("playbook.forget exige usuário autenticado")
        apagado = await self._store.delete(UUID(payload.playbook_id), user_id=ctx.user_id)
        return ForgetOutput(forgotten=apagado)


# canário anti-truncamento
