"""SkillRegistry — o Tool Registry unificado do Lumbra (ADR-015).

Fonte única de capacidades. Responsabilidades:

* Registro e descoberta (por nome, capacidade ou texto livre).
* Execução mediada: validação de entrada, checagem de permissão por
  escopo, medição de duração, log estruturado e emissão de
  ``skill.executed``/``skill.failed``.

Agentes NUNCA importam outros módulos: descobrem e executam por aqui.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from pydantic import ValidationError

from lumbra.kernel.events import SkillExecuted, SkillFailed, SkillRegistered
from lumbra.ports.explain import ExplainPort, Explanation
from lumbra.ports.permissions import PermissionPort
from lumbra.ports.skills import (
    DuplicateSkillError,
    Skill,
    SkillContext,
    SkillManifest,
    SkillNotFoundError,
    SkillOutput,
    SkillPermissionDeniedError,
)
from lumbra.shared.logging import get_logger

_log = get_logger("lumbra.kernel.skills")

# O kernel injeta seu publish; o registro não conhece o bus (dependency rule)
PublishFn = Callable[..., Awaitable[None]]


class SkillRegistry:
    def __init__(
        self,
        permissions: PermissionPort,
        publish: PublishFn | None = None,
        explain: ExplainPort | None = None,
    ) -> None:
        self._permissions = permissions
        self._publish = publish
        self._explain = explain
        self._skills: dict[str, Skill] = {}

    # ------------------------------------------------------------ registro

    async def register(self, skill: Skill) -> None:
        name = skill.manifest.name
        if name in self._skills:
            raise DuplicateSkillError(name)
        self._skills[name] = skill
        _log.info(
            "skill_registered",
            skill=name,
            provider=skill.manifest.provider,
            capabilities=list(skill.manifest.capabilities),
        )
        if self._publish is not None:
            await self._publish(
                SkillRegistered(
                    skill=name,
                    provider=skill.manifest.provider,
                    capabilities=skill.manifest.capabilities,
                )
            )

    # ------------------------------------------------------------ discovery

    def get(self, name: str) -> Skill:
        try:
            return self._skills[name]
        except KeyError:
            raise SkillNotFoundError(name) from None

    def manifests(self) -> list[SkillManifest]:
        return [s.manifest for s in self._skills.values()]

    def find(
        self, *, capability: str | None = None, query: str | None = None
    ) -> list[SkillManifest]:
        """Capability Discovery: por tag exata e/ou texto livre."""
        results = self.manifests()
        if capability is not None:
            results = [m for m in results if capability in m.capabilities]
        if query is not None:
            needle = query.lower()
            results = [
                m
                for m in results
                if needle in m.name
                or needle in m.description.lower()
                or any(needle in c for c in m.capabilities)
            ]
        return results

    # ------------------------------------------------------------ execução

    async def execute(
        self,
        name: str,
        payload: Mapping[str, Any],
        *,
        context: SkillContext,
    ) -> SkillOutput:
        skill = self.get(name)
        manifest = skill.manifest

        for scope in manifest.required_scopes:
            allowed = await self._permissions.is_allowed(
                subject=context.subject, scope=scope, user_id=context.user_id
            )
            _log.info(
                "permission_checked",
                skill=name,
                subject=context.subject,
                scope=scope,
                allowed=allowed,
            )
            if not allowed:
                raise SkillPermissionDeniedError(name, context.subject, scope)

        try:
            validated = skill.input_model.model_validate(dict(payload))
        except ValidationError:
            _log.warning("skill_input_invalid", skill=name, subject=context.subject)
            raise

        started = time.perf_counter()
        try:
            result = await skill.handler(validated, context)
        except Exception as exc:
            duration_ms = (time.perf_counter() - started) * 1000
            _log.error(
                "skill_failed",
                skill=name,
                subject=context.subject,
                duration_ms=round(duration_ms, 2),
                error=repr(exc),
            )
            await self._emit(
                SkillFailed(
                    skill=name,
                    subject=context.subject,
                    duration_ms=round(duration_ms, 2),
                    error=repr(exc)[:500],
                ),
                context,
            )
            raise

        duration_ms = (time.perf_counter() - started) * 1000
        _log.info(
            "skill_executed",
            skill=name,
            subject=context.subject,
            duration_ms=round(duration_ms, 2),
        )
        await self._emit(
            SkillExecuted(
                skill=name,
                subject=context.subject,
                duration_ms=round(duration_ms, 2),
                success=True,
            ),
            context,
        )
        if self._explain is not None:  # Explainability First (ADR-023)
            self._explain.record(
                Explanation(
                    component=f"skill:{name}",
                    decision="executada com sucesso",
                    reason=f"solicitada por {context.subject}",
                    inputs_used={"payload_fields": sorted(dict(payload))},
                    algorithm=f"handler de {manifest.provider} v{manifest.version}",
                    consequences=("skill.executed publicado",),
                    correlation_id=context.correlation_id,
                )
            )
        return result

    async def _emit(self, payload: Any, context: SkillContext) -> None:
        if self._publish is not None:
            await self._publish(
                payload, user_id=context.user_id, correlation_id=context.correlation_id
            )


# canário anti-truncamento
