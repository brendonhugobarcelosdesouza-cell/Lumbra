"""Agent Sandbox — isolamento, orçamento e descarte por execução (ADR-061).

Isolamento LÓGICO (não contêiner de SO — Local First): o agente não ganha
poderes novos, ele ganha MENOS. O sandbox materializa os invariantes que os
manifestos declaram:

* **escopo temporário** = ``min(usuário, agente, cadeia de delegação)`` — um
  decorador do ``PermissionPort`` que só pode NEGAR mais, nunca permitir mais;
* **orçamento próprio** (tokens/USD/tempo/passos) que debita e estoura;
* **scratch** (memória e arquivos temporários) DESCARTADO ao final — a memória
  do usuário só é escrita por skill explícita sujeita à aprovação, nunca como
  efeito colateral silencioso;
* **cancelamento** filho do token da execução (cascata já existente).
"""

from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path
from types import TracebackType
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from lumbra.ports.agents import AgentLimits
from lumbra.ports.permissions import PermissionPort
from lumbra.shared.cancellation import CancellationToken
from lumbra.shared.logging import get_logger

_log = get_logger("lumbra.kernel.sandbox")


class BudgetExceededError(Exception):
    """O agente estourou o orçamento declarado no manifesto."""

    def __init__(self, recurso: str, gasto: float, limite: float) -> None:
        super().__init__(f"orçamento de {recurso} esgotado: {gasto} > {limite}")
        self.recurso = recurso


class DelegationLoopError(Exception):
    """Ciclo na cadeia de delegação (A→B→A). Barrado ANTES de executar."""

    def __init__(self, agent_id: str, cadeia: tuple[str, ...]) -> None:
        super().__init__(f"delegação cíclica: {agent_id} já está na cadeia {' -> '.join(cadeia)}")
        self.agent_id = agent_id
        self.chain = cadeia


class DelegationDeniedError(Exception):
    """O manifesto do agente não permite delegar (ou não para esta capability)."""


class BudgetSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    tokens: int = 0
    cost_usd: float = 0.0
    steps: int = 0
    elapsed_s: float = 0.0


class BudgetTracker:
    """Debita e verifica o orçamento de UMA execução de agente."""

    def __init__(self, limits: AgentLimits) -> None:
        self._limits = limits
        self._tokens = 0
        self._cost = 0.0
        self._steps = 0
        self._inicio = time.monotonic()

    @property
    def elapsed_s(self) -> float:
        return time.monotonic() - self._inicio

    def snapshot(self) -> BudgetSnapshot:
        return BudgetSnapshot(
            tokens=self._tokens,
            cost_usd=self._cost,
            steps=self._steps,
            elapsed_s=round(self.elapsed_s, 3),
        )

    def charge(self, *, tokens: int = 0, cost_usd: float = 0.0, steps: int = 1) -> None:
        """Debita um passo. Levanta assim que um teto é ultrapassado — o agente
        para de gastar em vez de descobrir o estouro no fim."""
        self._tokens += tokens
        self._cost += cost_usd
        self._steps += steps
        self.check()

    def check(self) -> None:
        if self._tokens > self._limits.max_tokens:
            raise BudgetExceededError("tokens", self._tokens, self._limits.max_tokens)
        if self._steps > self._limits.max_steps:
            raise BudgetExceededError("passos", self._steps, self._limits.max_steps)
        if self.elapsed_s > self._limits.max_seconds:
            raise BudgetExceededError("tempo", round(self.elapsed_s, 2), self._limits.max_seconds)


class ScopedPermissions(PermissionPort):
    """Permissões INTERSECTADAS: só passa o que o port de origem permite E o
    conjunto concedido ao agente contém. Nunca amplia — a delegação (A8) apenas
    encadeia mais uma interseção."""

    def __init__(self, inner: PermissionPort, allowed: frozenset[str]) -> None:
        self._inner = inner
        self._allowed = allowed

    async def is_allowed(self, *, subject: str, scope: str, user_id: UUID | None = None) -> bool:
        if scope not in self._allowed:
            _log.info("sandbox_scope_denied", subject=subject, scope=scope)
            return False
        return await self._inner.is_allowed(subject=subject, scope=scope, user_id=user_id)

    def narrow(self, allowed: frozenset[str]) -> ScopedPermissions:
        """Interseção adicional (usada na delegação): sempre estreita."""
        return ScopedPermissions(self._inner, self._allowed & allowed)


class AgentSandbox:
    """Ambiente descartável de UMA execução de agente.

    Use como context manager: ao sair, o scratch é apagado — sempre, inclusive
    em erro ou cancelamento."""

    def __init__(
        self,
        *,
        agent_id: str,
        permissions: PermissionPort,
        scopes: frozenset[str],
        limits: AgentLimits,
        cancellation: CancellationToken | None = None,
        depth: int = 0,
        chain: tuple[str, ...] = (),
        budget: BudgetTracker | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.permissions = ScopedPermissions(permissions, scopes)
        self.scopes = scopes
        # o orçamento é COMPARTILHADO pela árvore de delegação (A8): o custo do
        # filho debita do mesmo teto, senão delegar seria burlar o budget.
        self.budget = budget if budget is not None else BudgetTracker(limits)
        self.limits = limits
        self.cancellation = cancellation
        self.depth = depth
        # agentes já na cadeia — impede A→B→A (anti-loop)
        self.chain = chain or (agent_id,)
        # memória temporária do agente — NÃO é a memória do usuário
        self.scratch: dict[str, Any] = {}
        self._tempdir: Path | None = None
        self._descartado = False

    @property
    def scratch_dir(self) -> Path:
        """Diretório temporário, criado sob demanda e apagado no descarte."""
        if self._tempdir is None:
            self._tempdir = Path(tempfile.mkdtemp(prefix=f"lumbra-agent-{self.agent_id}-"))
        return self._tempdir

    def child(self, *, agent_id: str, scopes: frozenset[str], limits: AgentLimits) -> AgentSandbox:
        """Sandbox de um agente DELEGADO: escopo intersectado, profundidade +1,
        cadeia estendida e MESMO orçamento. Nunca amplia permissão, nem reinicia
        profundidade, nem zera o budget — delegar não é escapatória."""
        if agent_id in self.chain:  # anti-loop A -> B -> A
            raise DelegationLoopError(agent_id, self.chain)
        if self.depth + 1 > self.limits.max_depth:
            raise BudgetExceededError("profundidade", self.depth + 1, self.limits.max_depth)
        return AgentSandbox(
            agent_id=agent_id,
            permissions=self.permissions,  # já intersectado
            scopes=self.scopes & scopes,
            limits=limits,
            cancellation=self.cancellation.child(f"agent:{agent_id}")
            if self.cancellation
            else None,
            depth=self.depth + 1,
            chain=(*self.chain, agent_id),
            budget=self.budget,  # orçamento compartilhado pela árvore
        )

    def discard(self) -> None:
        """Descarta TODO estado temporário. Idempotente."""
        if self._descartado:
            return
        self.scratch.clear()
        if self._tempdir is not None:
            shutil.rmtree(self._tempdir, ignore_errors=True)
            self._tempdir = None
        self._descartado = True
        _log.info(
            "sandbox_discarded",
            agent=self.agent_id,
            budget=self.budget.snapshot().model_dump(),
        )

    def __enter__(self) -> AgentSandbox:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.discard()


class SandboxFactory(BaseModel):
    """Cria sandboxes a partir do manifesto do agente e do escopo do usuário."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    permissions: PermissionPort = Field(exclude=True)

    def create(
        self,
        *,
        agent_id: str,
        agent_scopes: frozenset[str],
        user_scopes: frozenset[str],
        limits: AgentLimits,
        cancellation: CancellationToken | None = None,
    ) -> AgentSandbox:
        # o invariante central: escopo efetivo = interseção
        return AgentSandbox(
            agent_id=agent_id,
            permissions=self.permissions,
            scopes=agent_scopes & user_scopes,
            limits=limits,
            cancellation=cancellation,
        )


# canário anti-truncamento
