# 00 — Princípios Arquiteturais Permanentes

> Constituição técnica do Lumbra. Todo épico, ADR, módulo, agente e
> funcionalidade DEVE respeitar estes princípios. Mudanças aqui exigem
> decisão explícita do fundador.

| # | Princípio | Onde vive hoje | Status |
|---|-----------|----------------|--------|
| 1 | **Explainability First** — nenhum componente inteligente é caixa-preta; toda decisão responde: por quê, com quais dados, quais alternativas, qual algoritmo, qual confiança, quais consequências | ADR-023; `ExplainPort` + ExplainEngine no kernel; explicações já presentes em busca (`explanation` por hit), pipeline (timeline por estágio) e insights (ADR-012) | Semente implementada; adoção obrigatória em todo componente novo |
| 2 | **Human-in-the-Loop** — ações com impacto real têm nível de risco (LOW/MEDIUM/HIGH/CRITICAL) e política de aprovação configurável por usuário (auto / confirmar / nunca) | ADR-024; `risk_level` no SkillManifest; ApprovalPolicyPort chega com as primeiras skills de escrita no mundo real | Semente implementada; enforcement no SkillRegistry quando houver skill ≥ MEDIUM |
| 3 | **Capability Driven** — agentes nunca conhecem implementações; tudo é Capability `domínio.ação` descoberta no SkillRegistry | ADR-015, ADR-018 | Implementado |
| 4 | **Event Driven by Default** — fluxos importantes via Event Bus; módulos não se chamam diretamente; event sourcing seletivo | ADR-001, ADR-004, ADR-014, ADR-016 | Implementado |
| 5 | **Context First** — agentes não consultam bancos; todo contexto vem do Context Engine (memórias, agenda, docs, grafo, preferências, tempo, conversa) | Context Engine no kernel + `ContextProviderPort`; skill `context.gather` | Implementado (provedores `documents` e `memories` ativos no chat — ADR-029) |
| 6 | **AI Gateway** — nenhum componente fala com OpenAI/Anthropic/Gemini/Ollama diretamente; o Gateway registra modelo, provider, tokens, custo, latência, prompt, contexto e resposta | ADR-005, ADR-025; `AIGatewayPort` + FastEmbed local + AI Trace no console | Implementado (embeddings; chat na fase do assistente) |
| 7 | **Data Source Abstraction** — toda origem implementa `DataSourcePort`; jamais pipeline por fonte | ADR-019 | Implementado |
| 8 | **Pipeline Modular** — estágios canônicos (Receive→Extract→OCR→Metadata→Classification→Chunking→Embedding→KG→Memory→Index→Search) desacoplados, substituíveis e habilitáveis por plano | ADR-020; `PipelineResolver`/`PipelineRunner` | Implementado (Embedding no plano canônico — ADR-026; Classification/Memory nas Etapas 3c–4) |
| 9 | **Metadata Engine** — extratores independentes com interface comum; documentos viram conhecimento | ADR-021 | Implementado (extractors de IA na Etapa 3) |
| 10 | **Knowledge Graph** — fonte primária de conhecimento; relações com confiança, origem e histórico | ADR-006; `KnowledgeGraphPort` (confiança já modelada; origem/histórico de relações: evolução no Beta com o Knowledge Agent) | Implementado (mínimo viável) |
| 11 | **Observabilidade total** — toda execução produz logs estruturados, métricas, timeline, eventos, explicação e auditoria | doc 16; `MetricsPort`, timeline, event store, log tap, ExplainPort | Implementado e crescendo |
| 12 | **Developer Console** — parte oficial da arquitetura; evolui continuamente (roadmap: Live Dashboard, Pipeline Visual, KG Viewer, Event Timeline, RAG Inspector, AI Trace, Metrics, Dependency Graph, Execution Replay, Feature Flags, Health, Profiler) | ADR-022 | Implementado (núcleo); roadmap contínuo |
| 13 | **Explain Everything** — "por que este documento apareceu?", "por que esta memória foi usada?" respondíveis sem ler logs | Consequência dos princípios 1+11; consultável no console (`/api/v1/dev/explanations`) | Semente implementada |
| 14 | **Privacy First** — usuário é dono absoluto dos dados; modos Local/Híbrido/Cloud; nada sensível sai sem autorização explícita | ADR-002; doc 18; roteamento `local_only` no AI Gateway (Etapa 3) | Implementado como fundação |
| 15 | **Pronto para agentes autônomos** — todo componente pode virar agente; capacidades reutilizáveis, descobríveis, explicáveis, com HITL | Consequência de 1+2+3+5; `LumbraModule` é o contrato | Norma de projeto |

Regra prática de revisão: um PR que viole qualquer princípio exige ADR
justificando a exceção — sem ADR, não entra.
