"""LLM Planner — a camada 4 da orquestração (A9, ADR-062).

**A ÚLTIMA opção, nunca a primeira.** Só é acionado quando as camadas
determinísticas (regras → capability router → KeywordPlanner) não souberam
decompor o objetivo. Fica atrás do MESMO ``PlannerPort``, então ligá-lo não
muda nada acima: é injeção, não reescrita.

Travas que tornam o não-determinismo aceitável:

* **opt-in explícito** — o kernel não o usa por padrão;
* **pelo AI Gateway** — privacidade (local_only por padrão), custo, tokens e
  latência auditados como qualquer outra chamada de IA;
* **plano VALIDADO contra as skills reais** — o modelo não inventa passos: um
  nome que não existe no registro é descartado, e um plano inteiro inválido
  vira plano vazio (o Orchestrator então falha explicitamente em vez de
  executar algo imaginado);
* **teto de passos** — um plano gigante é truncado.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence

from lumbra.ports.ai import AIGatewayPort, ChatMessage, ChatRequest, PrivacyMode
from lumbra.ports.context import ContextFragment
from lumbra.ports.planner import Plan, PlannerPort, PlanStep
from lumbra.ports.skills import SkillManifest
from lumbra.shared.logging import get_logger

_log = get_logger("lumbra.kernel.llm_planner")

_MAX_STEPS = 8  # teto duro: plano maior que isto é truncado
_JSON = re.compile(r"\[.*\]", re.DOTALL)  # extrai o array mesmo com texto ao redor

_PROMPT = """Você decompõe um objetivo em passos executáveis.

Responda APENAS com um array JSON. Cada item:
  {"skill": "<nome exato da lista>", "rationale": "<por que este passo>"}

Regras:
- use SOMENTE skills da lista disponível (nomes exatos);
- se nenhuma skill servir, responda [];
- no máximo 8 passos, na ordem de execução.

SKILLS DISPONÍVEIS:
{skills}

OBJETIVO: {goal}"""


class LLMPlanner(PlannerPort):
    """Planejador com IA — camada 4, opt-in (ver módulo)."""

    def __init__(
        self,
        gateway: AIGatewayPort,
        *,
        privacy: PrivacyMode = PrivacyMode.LOCAL_ONLY,
        max_tokens: int = 512,
    ) -> None:
        self._gateway = gateway
        self._privacy = privacy
        self._max_tokens = max_tokens

    async def plan(
        self,
        goal: str,
        *,
        skills: Sequence[SkillManifest],
        context: Sequence[ContextFragment] = (),
    ) -> Plan:
        if not skills:
            return Plan(goal=goal, steps=())
        catalogo = "\n".join(f"- {m.name}: {m.description}" for m in skills)
        prompt = _PROMPT.replace("{skills}", catalogo).replace("{goal}", goal)
        try:
            resultado = await self._gateway.chat(
                ChatRequest(
                    messages=(ChatMessage(role="user", content=prompt),),
                    purpose="planning",
                    privacy=self._privacy,
                    max_tokens=self._max_tokens,
                    temperature=0.0,  # planejamento pede reprodutibilidade
                )
            )
        except Exception as exc:  # provedor indisponível não derruba a orquestração
            _log.warning("llm_planner_indisponivel", erro=repr(exc))
            return Plan(goal=goal, steps=())
        passos = _parse(resultado.text, validos={m.name for m in skills})
        _log.info("llm_planner_planned", goal=goal, steps=len(passos), model=resultado.model)
        return Plan(goal=goal, steps=passos)


def _parse(texto: str, *, validos: set[str]) -> tuple[PlanStep, ...]:
    """Converte a resposta do modelo em passos, DESCARTANDO o que não existe.

    Robusto de propósito: o modelo pode falar demais, devolver JSON malformado
    ou inventar skills. Nada disso pode virar execução."""
    achado = _JSON.search(texto or "")
    if achado is None:
        return ()
    try:
        bruto = json.loads(achado.group(0))
    except (ValueError, TypeError):
        _log.warning("llm_planner_json_invalido")
        return ()
    if not isinstance(bruto, list):
        return ()

    passos: list[PlanStep] = []
    for item in bruto[:_MAX_STEPS]:
        if not isinstance(item, dict):
            continue
        nome = item.get("skill")
        if not isinstance(nome, str) or nome not in validos:
            _log.warning("llm_planner_skill_inexistente", skill=nome)
            continue  # o modelo inventou: descarta o passo
        racional = item.get("rationale")
        passos.append(
            PlanStep(
                skill=nome,
                rationale=racional if isinstance(racional, str) else "sugerido pelo planner de IA",
            )
        )
    return tuple(passos)


# canário anti-truncamento
