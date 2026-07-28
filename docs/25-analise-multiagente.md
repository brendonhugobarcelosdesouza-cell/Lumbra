# 25 — Análise Arquitetural: Lumbra como Plataforma Multiagente

> **Status: ANÁLISE. Nenhum código foi escrito, nenhum ADR criado, nada
> refatorado.** Este documento responde: *a Lumbra tem a fundação para se
> tornar multiagente, ou precisamos de uma nova camada?* A resposta curta
> está na seção 0; o resto sustenta essa resposta com o estado REAL do
> repositório (verificado no código, não nos documentos).

---

## 0. Conclusão primeiro (a resposta honesta)

**A fundação já existe em ~75%. Não construa uma nova plataforma — adicione
uma camada fina de Agente sobre primitivos que já estão prontos.** A hipótese
do fundador está correta: **agentes devem ser CONSUMIDORES da plataforma, não
a plataforma.** Isso não é sorte — o Princípio #15 (`docs/00-principios.md`)
diz textualmente "todo componente pode virar agente; `LumbraModule` é o
contrato". A arquitetura foi desenhada para isto e o código mostra.

Se eu tivesse que resumir a menor mudança necessária numa frase: **tornar
Agente um cidadão de primeira classe (Manifest + Registry) espelhando o que
Skill já é, ligar o Planner que hoje está dormente como Orquestrador, e
finalmente *aplicar* o `risk_level` que já é declarado mas nunca verificado.**

Não é reescrita. É evolução — e boa parte é "ligar fios que já foram
puxados".

---

## A. Estado atual (o que REALMENTE existe)

Verificado em `core/src/lumbra`. 23 ports, 52 ADRs, 480 funções de teste.

| Componente | Arquivo | Estado real |
|---|---|---|
| **Skills** (unidade universal de capacidade) | `ports/skills.py`, `kernel/skill_registry.py` | **Implementado.** `SkillManifest` com `capabilities`, `required_scopes`, `risk_level`. `execute()` valida escopo via `PermissionPort`, grava `Explanation`, emite `skill.executed`/`failed`, propaga `CancellationToken`. |
| **Capability Discovery** | `kernel/core_module.py` | **Implementado.** `system.list_capabilities` é uma skill; agentes/planner descobrem o que existe sem conhecer implementações. |
| **Planner** (objetivo → passos) | `ports/planner.py`, `kernel/planning.py` | **Implementado, porém DORMENTE.** `PlannerPort` + `Plan`/`PlanStep` com **DAG** (`depends_on` para trás) + `rationale`. `KeywordPlanner` determinístico. Instanciado no kernel (`self.planner`, `self.plan_runner`) mas **não exposto em nenhuma skill nem rota** — ninguém o chama. |
| **PlanRunner** (executa planos) | `kernel/planning.py` | **Implementado, dormente.** Executa respeitando dependências, com **falha parcial** (passo falho → dependentes `skipped`, resto segue). O docstring já diz "cooperação multi-agente concreta". |
| **ExecutionTracker** | `kernel/executions.py` | **Implementado.** `correlation_id`, `status`, cancelamento com prestação de contas (ADR-032), timeline, eventos, logs, export. `ExecutionRecord.kind` já é `"skill \| agent (futuro)"`. **Sem `parent_execution_id`** (sem árvore de delegação). |
| **Permissões / escopos** | `ports/permissions.py`, `modules/devices` | **Implementado.** `is_allowed(subject, scope 'verbo:recurso', user_id)`. Dispositivos têm escopos (ADR-045/047). |
| **Risk / HITL** | `ports/skills.py` (`RiskLevel`) | **Só DECLARADO.** `risk_level` existe no manifesto (ex.: `memory.forget=MEDIUM`), mas **não há `ApprovalPolicyPort` e nada verifica risco antes de executar.** Lacuna real. |
| **AI Gateway** | `ports/ai.py`, `modules/ai.py` | **Implementado.** `ChatProviderPort` (complete/stream), `PrivacyMode` (local_only/allow_cloud), `cost_usd`, `is_local`, `max_tokens`, `AICallRecord` (tokens/custo/latência/desfecho), AI Trace. Cancelamento fim-a-fim. |
| **Context Engine** | `kernel/context_engine.py`, `ports/context.py` | **Implementado.** `ContextProviderPort`; provedores `documents`, `memories`, `attachments`. `context.gather` como skill. |
| **Memory / RAG / KG** | `modules/memory.py`, `adapters/search`, `ports/knowledge_graph.py` | **Implementado.** Memória em 5 camadas + reflexão (`modules/reflection.py`), busca híbrida RRF explicada, KG mínimo. |
| **Event Bus** | `adapters/eventbus` | **Implementado, produção.** Concorrência particionada por chave, resiliência, DLQ, idempotência, observabilidade (Leva 2). |
| **Explain Engine** | `kernel/explain.py`, `ports/explain.py` | **Implementado.** `Explanation` (decisão, razão, inputs, alternativas, algoritmo, correlação); consultável em `/api/v1/dev/explanations`. |
| **Platform API + contrato** | `api/`, `contracts/platform-api-v1.json` | **Implementado.** OpenAPI versionado, teste que trava o build, cliente Dart gerado. Dev-console fora do contrato de propósito. |
| **Identidade de dispositivos** | `modules/devices`, ADR-045 | **Implementado.** Ed25519, pareamento, escopos por dispositivo. |
| **Cliente Flutter** | `clients/app` | **Implementado (desktop/web).** Um código, consome só o contrato; exceção nomeada para SSE (ADR-050). |

**Classificação honesta do que toca "agente":**
- *Implementado:* Skills, Discovery, Permissões/escopos, ExecutionTracker, AI Gateway, Context, Memory/RAG/KG, Event Bus, Explain, Contrato, Devices.
- *Parcial:* Planner/PlanRunner (existem e funcionam, mas **dormentes**); `ExecutionRecord.kind` prevê agente mas nada o usa.
- *Planejado (não existe):* Agente de primeira classe, Orquestrador, delegação, budgets, `ApprovalPolicyPort`.
- *Contraditório:* o Princípio #2 diz HITL "semente implementada; enforcement no SkillRegistry quando houver skill ≥ MEDIUM" — mas `memory.forget` já é MEDIUM e **não há enforcement**. A doc está à frente do código aqui.

---

## B. O que já suporta multiagentes (reutilizar, não recriar)

1. **Skill = Tool.** A "Agent Tool" que toda arquitetura multiagente precisa
   já existe, tipada, com escopo, risco declarado, explicação e cancelamento.
   Um agente não precisa de um conceito novo de ferramenta.
2. **PlanRunner = micro-orquestrador com DAG e falha parcial.** O paralelismo
   por dependências e o "resultado parcial > falha total" já estão prontos.
3. **PlannerPort abstrai a decisão.** Trocar `KeywordPlanner` por um planner
   com IA (ou por um router determinístico melhor) **não toca em mais nada** —
   é exatamente o ponto de extensão que a pergunta 6 do fundador pede.
4. **ExecutionTracker = Agent Trace.** Correlação, timeline, cancelamento e
   export já dão a espinha da observabilidade de agentes.
5. **PermissionPort + escopos = Agent Permissions.** O modelo `verbo:recurso`
   já serve para agentes; `subject` já aceita `"agent:<id>"`.
6. **AI Gateway = a única porta de modelo.** Agentes herdam roteamento de
   privacidade, custo e cancelamento de graça.
7. **Context Engine = AgentContext.** "Agentes não consultam bancos" já é lei
   (Princípio #5); o contexto agregado já é uma skill.
8. **Event Bus particionado = paralelismo de agentes.** A mesma filosofia de
   concorrência por chave vale para execução paralela de agentes.

---

## C. Lacunas (o que falta — e é pouco)

| # | Lacuna | Tamanho | Observação |
|---|---|---|---|
| C1 | **Agente de primeira classe**: `AgentManifest` + `AgentRegistry` | Pequeno | Espelha `SkillManifest`/`SkillRegistry`. Um agente é um manifesto + um handler que compõe skills. |
| C2 | **Orquestrador**: "qual agente atua?" | Médio | Evoluir o Planner dormente; começar determinístico. |
| C3 | **Delegação agente→agente** | Médio | Falta `parent_execution_id`, `depth`/`budget`/`visited` para evitar loops A→B→A. |
| C4 | **Enforcement de risco (HITL)**: `ApprovalPolicyPort` | Pequeno-Médio | **Já projetado (ADR-024), nunca construído.** Gate no `SkillRegistry.execute` quando `risk >= MEDIUM`. |
| C5 | **Budgets** (token/tempo/requests) por execução | Pequeno | `AICallRecord` já mede custo; falta agregação e teto por run. |
| C6 | **Identidade de agente** (registro/escopo próprios) | Pequeno | Reusa `PermissionPort`; agente ganha escopos como dispositivo ganhou. |
| C7 | **Propagação de privacidade na delegação** | Pequeno | Um run `local_only` não pode delegar a ferramenta/agente cloud. |

Nenhuma dessas é uma reescrita. C1, C4, C5, C6 são "pequenas". C2 e C3 são as
únicas de porte médio, e mesmo elas reaproveitam Planner/PlanRunner/Tracker.

---

## D. O que NÃO deve ser tocado (explícito, a pedido)

Estes componentes são carga estrutural e estão corretos. Mexer aqui é risco
sem retorno:

- **Event Bus** (produção, Leva 2) — a base de concorrência/paralelismo.
- **AI Gateway** e `ChatProviderPort`/`PrivacyMode` — a única porta de modelo.
- **SkillManifest / SkillRegistry.execute** — o contrato de capacidade. Agentes
  se encaixam nele; não o alteram.
- **Context Engine / `ContextProviderPort`** — a forma como contexto chega.
- **Ports de Memory / Search / KnowledgeGraph** — agentes consomem, não
  reimplementam (regra dura da pergunta 9).
- **Explain Engine / `ExplainPort`** — só passa a ser *emitido também* por
  agentes.
- **Identidade de dispositivo + escopos (ADR-045/047)** — o modelo de
  identidade que a identidade de agente vai imitar.
- **Contrato OpenAPI e sua disciplina** (snapshot + teste) — agentes entram
  como novos caminhos versionados, sem afrouxar a regra.
- **Cliente Flutter / Regra do cliente gerado (ADR-043/048/050)** — o mobile
  consome resultado; não ganha um segundo cérebro.

---

## E. Arquitetura proposta (adaptada à realidade)

Camadas em **negrito já existem**; as demais são a camada fina a adicionar.

```
                 **Flutter Client** (Desktop / Android / Web)
                                │  (só o contrato — Regra 1)
                        **Platform API** (OpenAPI versionado)
                                │
                          **Lumbra Node** (kernel local-first)
                                │
                   Agent Orchestrator     ← evolui do Planner dormente
                                │
                   Agent Runtime          ← reusa ExecutionTracker + budgets
                                │
                   Agents (Manifest+Registry)  ← espelha Skills
                                │
                        **Skills / Tools**  (escopo, risco, explain, cancel)
                                │
         **Context Engine** → **Memory / RAG / KG / Documents**
                                │
                        **AI Gateway** (privacidade, custo, cancel)
                                │
                **Event Bus / Event Store** (concorrência particionada)
```

Ponto-chave: o Orchestrator e o Agent Runtime **não são um sistema paralelo** —
são consumidores das mesmas skills, do mesmo tracker, do mesmo gateway. Um
agente que "analisa finanças" é um manifesto + um handler que chama
`document.find`, `memory.search`, e talvez delega a outro agente — tudo pelo
`SkillRegistry`/`PlanRunner` que já existem.

---

## F. Agent Manifest (contrato conceitual proposto)

Espelha `SkillManifest` — mesma filosofia declarativa, mesma validação no
registro. **Proposta, não implementação:**

```
AgentManifest:
  id                 # 'finance-agent'
  name, version, description
  provider           # 'kernel' | 'plugin:acme'
  capabilities       # tags de discovery (como nas skills)
  tools              # skills que pode chamar (subconjunto do SkillRegistry)
  required_scopes    # 'verbo:recurso' — o TETO de permissão do agente
  risk_level         # risco intrínseco do agente
  model_requirements # ex.: precisa de contexto grande / multimodal
  memory_access      # read | none  (nunca 'memória oculta' — ver seção 9)
  delegation_policy  # pode delegar? a quais capacidades? profundidade máx.
  limits             # budgets: max_tokens, max_time_s, max_steps, max_depth
  lifecycle          # singleton | por-request
```

Invariante de segurança que o Manifest carrega: **o escopo efetivo de um
agente é sempre `min(escopo do usuário, required_scopes do agente, cadeia de
delegação)`** — um agente nunca ganha poder ao ser chamado.

---

## G. Agent Execution Model (ciclo proposto)

```
request
  → orchestration   (determinístico primeiro: qual agente/plano?)
  → context         (Context Engine — nada de acesso direto a banco)
  → execution       (Agent Runtime: registra no ExecutionTracker, aplica budget)
  → tools           (SkillRegistry.execute — escopo + risco + explain + cancel)
  → delegation      (opcional: parent_execution_id, depth/visited/budget)
  → verification    (opcional: agente Verifier — mesma mecânica)
  → result          (parcial > falha total, como o PlanRunner já faz)
  → explanation     (ExplainPort emitido em cada nó da árvore)
```

Cada seta é rastreável por `correlation_id` (já existe) + um novo
`parent_execution_id` (a adicionar). Cancelamento se propaga pela árvore de
tokens (a base já existe em `cancellation.child`).

---

## H. Agent Orchestration Model (recomendação justificada)

**Recomendado: híbrido determinístico-primeiro.** (E) na lista do fundador.

1. **Router determinístico por intenção** resolve o caso comum (uma pergunta
   simples não aciona um enxame). Barato, previsível, testável, offline,
   explicável.
2. **Planner (via `PlannerPort`)** para objetivos multi-passo — começar
   evoluindo o `KeywordPlanner`, e só então um planner com IA **atrás do mesmo
   port**, acionado quando o determinístico não sabe.
3. **Supervisor/hierárquico** fica para depois, se o dogfooding provar
   necessidade — não por moda.

**Por que não LLM-como-orquestrador por padrão:** a preferência do fundador é
viável precisamente porque `PlannerPort` já isola a decisão. Latência, custo,
previsibilidade, debugging e offline todos favorecem o determinístico; o LLM
entra como *estratégia de planner*, não como o trilho central. A Lumbra
"sabe ser simples quando o problema é simples" (pergunta 19) porque o router
determinístico é a porta de entrada.

---

## I. Modelo de segurança (User → Device → Plugin → Agent → Skill → Tool → Provider)

- **Identidade:** `subject` já distingue `user:<id>`, `device`, e aceita
  `agent:<id>`. Agente ganha um registro e escopos como o dispositivo tem.
- **Escopo efetivo (regra dura):** `min(user, device, agent, cadeia de
  delegação)`. Um Agent A com `memory:read, documents:read` **não pode** fazer
  o Agent B executar `email:send` — o `SkillRegistry.execute` já nega escopo
  faltante; a delegação apenas *estreita*, nunca amplia.
- **Risco (regra dura):** a ação efetiva usa `max(risco do agente, risco da
  tool, risco da ação)` — o mais alto vence — e passa pela `ApprovalPolicy`.
- **Plugin ≠ segunda arquitetura:** um agente externo é um **plugin = cliente
  com escopos** (ADR-047 já vale). Autentica por chave (como dispositivo),
  declara capabilities/scopes, é revogável e auditável. Não há dois sistemas
  de plugin.
- **Anti-escalada:** agente não pode chamar skill fora de `tools`; não pode
  delegar ação proibida; não pode usar agente como atalho para contornar
  escopo (a interseção é reavaliada a cada salto).

---

## J. Observabilidade (como tudo é rastreado)

Reaproveita o que existe, adicionando a dimensão de árvore:
- `correlation_id` amarra o request inteiro (já existe).
- `parent_execution_id` (novo) monta a árvore Orchestrator → Agent → Skill →
  Agent delegado.
- Cada nó emite `Explanation` (quem decidiu, qual modelo, quais docs/memórias,
  quais tools, quais agentes, qual alternativa, qual risco, quem autorizou).
- `ExecutionTracker` + Event Timeline + AI Trace já dão a linha do tempo; o
  console (`/api/v1/dev`) ganha uma visão de árvore de execução.

---

## K. Mobile / Desktop (um sistema, não dois)

Coerente com ADR-042/044: **agentes rodam no Node** (o desktop como Node
principal). O Android é cliente — dispara um agente pela Platform API, recebe
resultado/notificação, acompanha o trace, continua a conversa. Nenhum agente
roda "no telefone como cérebro separado". Offline: a fila local e o sync
(planejados) valem para pedidos de agente como valem para mensagens; um run
disparado offline enfileira e executa quando o Node volta. Privacidade: um run
`local_only` não delega a ferramenta/agente cloud — a propagação de
privacidade é a mesma do AI Gateway, estendida à delegação (C7).

---

## L. Roadmap (fases pequenas e seguras)

Sem épico gigante. Cada fase entrega algo utilizável e testável, e nenhuma
exige tocar nos componentes da seção D.

- **A0 — Contratos.** `AgentManifest` + `ApprovalPolicyPort` (fecha a lacuna
  C4, que já é dívida hoje) + `parent_execution_id` no `ExecutionRecord`.
  Só tipos e portas. Enforcement de risco entra aqui (vale por si só, mesmo
  sem agentes).
- **A1 — Agent Registry.** Espelha `SkillRegistry`: registrar, descobrir,
  validar manifesto, escopos. Um agente "trivial" que só chama uma skill,
  como prova de conceito.
- **A2 — Agent Runtime.** Executa um agente reusando `ExecutionTracker`
  (agora com `parent_execution_id`) + budgets (C5). Cancelamento e timeout
  pela árvore de tokens existente.
- **A3 — Orchestrator.** Liga o Planner dormente: router determinístico +
  `PlanRunner`. Expor no contrato (`/api/v1/...`) e no console. É aqui que o
  que já foi construído "acorda".
- **A4 — Agentes especialistas.** Document/Finance/Research como manifestos
  que compõem skills existentes. Golden set de agentes no CI (replay
  determinístico com AI Gateway mockado).
- **A5 — Delegação.** Agente→agente com escopo intersectado, `depth`/`visited`/
  budget, propagação de privacidade (C7). Testes adversariais de escalada.
- **A6 — Integração mobile.** Disparo/acompanhamento de agentes pelo Android
  via contrato; notificação de resultado; continuação de conversa.

---

## 21. Matriz de decisões

| Decisão | Estado atual | Mudança necessária | Risco | Prioridade |
|---|---|---|---|---|
| Agente como consumidor (não plataforma) | Implícito no Princípio #15 | Formalizar `AgentManifest`/`Registry` | Baixo | Alta |
| Orquestração determinística-primeiro | `PlannerPort`+`PlanRunner` prontos, **dormentes** | Ligar + router de intenção | Médio | Alta |
| Enforcement de risco (HITL) | `risk_level` declarado, **nunca verificado** | `ApprovalPolicyPort` + gate no registry | Médio (segurança) | **Alta (é dívida hoje)** |
| Delegação agente→agente | Inexistente | `parent_execution_id` + budgets/depth/visited | Médio | Média |
| Identidade/escopo de agente | `subject` aceita `agent:`; sem registro | Escopos de agente (imita dispositivo) | Baixo | Média |
| Budgets (token/tempo/passos) | `AICallRecord` mede custo | Agregar + teto por run | Baixo | Média |
| Plugin-como-agente | ADR-047 (plugin = cliente com escopo) | Reusar; não criar 2º sistema | Baixo | Média |
| Propagação de privacidade na delegação | Roteamento existe no AI Gateway | Estender à cadeia de delegação | Médio (privacidade) | Alta |
| LLM como orquestrador | Não usado | **Evitar como trilho**; usar como planner opcional | — | (decisão: não) |
| Agent Runtime como camada nova | Parcial (Tracker+Planner) | Camada FINA sobre o existente | Baixo | Alta |

---

## 22. ADRs que seriam necessários (propostos, NÃO criados)

- **ADR-053 — Agente de primeira classe (Manifest + Registry).** Por quê:
  formaliza "agente é consumidor", reusando o padrão de Skill; sem isso,
  "agente" fica como conceito difuso (hoje = módulo que registra skill).
- **ADR-054 — Agent Runtime e modelo de execução.** Por quê: define o ciclo
  request→context→execução→delegação→verificação→resultado→explicação e como
  reusa `ExecutionTracker` + `parent_execution_id` + budgets.
- **ADR-055 — Orquestração determinística-primeiro.** Por quê: registra a
  escolha de não usar LLM como orquestrador por padrão e como o `PlannerPort`
  acomoda evolução sem reescrita.
- **ADR-056 — Delegação, budgets e prevenção de loops.** Por quê: `depth`,
  `visited`, budgets, e a regra de interseção de escopo entre agentes.
- **ADR-057 — Enforcement de risco / `ApprovalPolicyPort` (HITL).** Por quê:
  fecha a contradição atual (risco declarado, não aplicado); vale mesmo sem
  agentes.
- **ADR-058 — Identidade e escopo de agente; agente-como-plugin.** Por quê:
  estende ADR-045/047 a agentes, garantindo um só modelo de identidade e um só
  sistema de plugin.
- **(possível) ADR-059 — Propagação de privacidade na delegação.** Por quê:
  impede que delegação vire atalho para vazar dados de conversa `local_only`.

---

## 23. Critério mais importante — vale a pena?

**Sim, mas de forma mínima e faseada — e uma parte deveria ser feita mesmo se
agentes fossem cancelados.** Especificamente:

- **Não** precisamos de um "Agent Runtime" grande e novo agora. Precisamos de
  uma camada fina, e A0/A1 já entregam valor real.
- **O enforcement de risco (C4/A0) é dívida técnica hoje**, independente de
  agentes: há uma skill MEDIUM (`memory.forget`) sem gate de aprovação. Isso
  deveria ser feito de qualquer jeito.
- **O Planner dormente é desperdício**: já foi construído e testado, e não é
  consumido. Ligá-lo (A3) é retorno alto por esforço baixo.
- Se a análise apontasse "não vale a pena", eu diria — mas o oposto é
  verdadeiro: o custo de evoluir é baixo *porque* a fundação foi desenhada
  para isto. O risco real seria construir um **segundo** sistema (orquestrador
  LLM paralelo, plugins de agente separados, memória oculta de agente) — e é
  exatamente isso que as regras acima proíbem.

---

## 24. Perguntas finais

**"Se estivéssemos começando hoje sabendo o que sabemos, construiríamos igual?"**

Em grande parte, **sim**. As decisões que sustentam multiagentes — Skills como
capacidade universal, ports por toda parte, Explain/Permissões/Cancelamento
transversais, AI Gateway como porta única, Context Engine, Event Bus
particionado — se pagam agora. Três coisas eu teria feito mais cedo: (1)
`parent_execution_id` desde o `ExecutionTracker` (barato então, chato de
retrofitar); (2) o `ApprovalPolicyPort` junto da primeira skill MEDIUM, em vez
de deixar `risk_level` como enfeite; (3) ter exposto o Planner cedo, para não
virar código dormente. Nenhuma dessas é uma falha de arquitetura — são
sequenciamentos que a clareza de hoje corrigiria.

**"Qual a menor mudança para virar multiagente robusto sem jogar fora o
construído?"** — *a pergunta mais importante:*

> Adicionar **Agente como uma camada fina sobre os primitivos existentes**:
> um `AgentManifest` + `AgentRegistry` que espelham Skill; um Agent Runtime que
> **reusa o `ExecutionTracker`** (com `parent_execution_id` e budgets); **ligar
> o `PlannerPort`/`PlanRunner` dormentes** como Orquestrador determinístico; e
> **aplicar o `risk_level`** via `ApprovalPolicyPort`. Delegação e identidade de
> agente reusam, respectivamente, a interseção de escopos e o modelo de
> identidade de dispositivo. Nada de reescrever Core, Event Bus, AI Gateway,
> Skills, Context, Memory/RAG/KG ou o contrato.

Não reconstruir. **Evoluir** — ligando fios já puxados e fechando uma dívida
(risco) que já existe.
