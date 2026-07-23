# 01 — Visão do Produto

## Missão

Ser a extensão permanente da memória, organização e produtividade do usuário: um sistema que compreende, lembra, organiza, pesquisa, automatiza e executa em nome dele.

## Declaração de visão

> Para pessoas sobrecarregadas pela fragmentação da vida digital, o Lumbra é uma Personal Intelligence Platform que centraliza memória, conhecimento, rotina, saúde, finanças e automação em um único cérebro digital proativo — diferente de assistentes reativos (Siri, Alexa) e ferramentas isoladas (Notion, Obsidian, Motion), porque combina memória de longo prazo, agentes especializados e execução real de tarefas, com privacidade e funcionamento offline como padrão.

## Posicionamento competitivo

| Categoria | Referências | O que absorvemos | O que fazemos diferente |
|---|---|---|---|
| Chat AI | ChatGPT, Claude, Gemini, Perplexity | Conversação multimodal, RAG, pesquisa | Memória persistente estruturada em 5 camadas; o chat é interface, não o produto |
| Launcher/produtividade | Raycast | Velocidade, comandos, extensões | Comandos alimentados por contexto pessoal completo |
| Segundo cérebro | Notion, Obsidian | Organização de conhecimento, grafos | Organização automática — a IA cataloga, o usuário não |
| Agenda inteligente | Motion | Scheduling automático | Scheduling integrado a saúde, finanças e hábitos |
| Memória total | Rewind, Limitless | Captura contínua | Captura seletiva com consentimento granular, offline-first |
| Assistentes de voz | Siri, Alexa, Google Assistant | Voz, dispositivos, proatividade | Proatividade baseada em conhecimento profundo, não em triggers rasos |
| Copilots | Microsoft Copilot, Apple Intelligence | Integração com SO e documentos | Cross-platform e agnóstico de fornecedor de IA |

Não copiamos nenhum. Combinamos os melhores conceitos de todos.

## Personas

**P1 — Profissional sobrecarregado (primária).** 28–45 anos, vive entre e-mail, agenda, documentos e prazos. Dor: informação espalhada em 15 apps. Ganho: pesquisa universal + proatividade ("sua CNH vence em 20 dias").

**P2 — Cuidador de si e da família.** Gerencia medicamentos, consultas, exames, documentos dos filhos/pais. Dor: esquecimento tem custo real. Ganho: alarmes inteligentes de medicação com confirmação e escalonamento.

**P3 — Construtor de conhecimento.** Estudante/pesquisador/criador. Dor: captura muito, recupera pouco. Ganho: memória semântica + knowledge graph que responde perguntas.

**P4 — Desenvolvedor/power user.** Quer estender o sistema. Ganho: SDK de plugins, automações visuais, modelos locais via Ollama.

## Princípios de produto (inegociáveis)

1. **Privacy First** — dados do usuário pertencem ao usuário; criptografia por padrão; IA local como opção de primeira classe.
2. **Offline First** — toda funcionalidade essencial opera sem internet; nuvem é sincronização, não dependência.
3. **AI First** — IA permeia tudo, mas é trocável (camada de abstração de modelos).
4. **Proatividade com consentimento** — o sistema antecipa, mas o usuário controla o que ele observa.
5. **Extensibilidade** — nada rígido; tudo é módulo, evento ou plugin.
6. **Velocidade percebida** — interface instantânea (padrão Raycast/Linear); latência de IA nunca bloqueia a UI.

## Proposta de valor em uma frase por pilar

Lembrar (memória em 5 camadas) · Pesquisar (busca semântica universal) · Organizar (catalogação automática + knowledge graph) · Executar (agentes que agem) · Automatizar (editor visual de fluxos) · Aprender (memória procedural de preferências) · Antecipar (motor de proatividade) · Conectar (desktop, mobile, web, dispositivos).

## Métricas de sucesso (North Star + guardrails)

- **North Star:** ações úteis concluídas pelo sistema por usuário/semana (respostas com fonte, lembretes confirmados, automações executadas).
- Retenção D30 > 40% no beta; NPS > 50.
- Latência de busca semântica p95 < 300 ms local.
- Zero incidentes de vazamento de dados (guardrail absoluto).

## Fora de escopo (v1)

Hardware próprio; captura contínua de tela estilo Rewind; rede social; marketplace pago de plugins (v2); execução de ordens financeiras (apenas leitura/alertas via Open Finance).
