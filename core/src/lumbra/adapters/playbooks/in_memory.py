"""Store de playbooks in-memory (dev/testes; Postgres chega com o uso real).

A busca é lexical simples e DELIBERADAMENTE assim: playbooks são poucos por
natureza (dezenas, não milhares) e o campo que decide a recuperação é o
``when_to_use``, escrito justamente para casar com a intenção. Vetor aqui seria
peso sem ganho — se o volume crescer, o port permite trocar sem tocar em nada.
"""

from __future__ import annotations

import re
from uuid import UUID

from lumbra.ports.playbooks import Playbook, PlaybookStorePort

_PALAVRA = re.compile(r"[\wÀ-ÿ]{3,}")  # ignora artigos e ruído curto


def _termos(texto: str) -> set[str]:
    return {t.lower() for t in _PALAVRA.findall(texto)}


def _pontuacao(playbook: Playbook, consulta: set[str]) -> float:
    """Relevância: o 'quando usar' pesa mais que o resto — é o campo escrito
    para ser casado com a intenção do usuário."""
    if not consulta:
        return 0.0
    gatilho = _termos(f"{playbook.title} {playbook.when_to_use}")
    corpo = _termos(" ".join(playbook.steps) + " " + " ".join(playbook.pitfalls))
    forte = len(consulta & gatilho) * 2.0
    fraco = len(consulta & corpo) * 0.5
    return forte + fraco


class InMemoryPlaybookStore(PlaybookStorePort):
    def __init__(self) -> None:
        self._itens: dict[UUID, Playbook] = {}

    async def add(self, playbook: Playbook) -> Playbook:
        self._itens[playbook.id] = playbook
        return playbook

    async def search(self, *, user_id: UUID, query: str, limit: int = 3) -> list[Playbook]:
        consulta = _termos(query)
        candidatos = [
            (p, _pontuacao(p, consulta)) for p in self._itens.values() if p.user_id == user_id
        ]
        relevantes = [(p, s) for p, s in candidatos if s > 0]
        relevantes.sort(key=lambda par: (-par[1], -par[0].uses))
        return [p for p, _ in relevantes[:limit]]

    async def list_by_user(self, user_id: UUID, *, limit: int = 50) -> list[Playbook]:
        do_usuario = [p for p in self._itens.values() if p.user_id == user_id]
        do_usuario.sort(key=lambda p: p.created_at, reverse=True)
        return do_usuario[:limit]

    async def delete(self, playbook_id: UUID, *, user_id: UUID) -> bool:
        alvo = self._itens.get(playbook_id)
        if alvo is None or alvo.user_id != user_id:  # isolamento entre usuários
            return False
        del self._itens[playbook_id]
        return True

    async def touch(self, playbook_id: UUID) -> None:
        alvo = self._itens.get(playbook_id)
        if alvo is not None:
            self._itens[playbook_id] = alvo.model_copy(update={"uses": alvo.uses + 1})


# canário anti-truncamento
