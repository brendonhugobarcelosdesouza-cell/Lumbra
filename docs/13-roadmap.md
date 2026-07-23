# 13 — Roadmap

Princípio: cada versão entrega valor completo e utilizável. O risco nº 1 é escopo (R-01); feature fora da versão corrente exige ADR aprovado.

```mermaid
gantt
    title Lumbra — Roadmap macro
    dateFormat YYYY-MM-DD
    axisFormat %m/%y
    section MVP (0.1-0.4)
    Fundacao + Event Bus + IA Layer       :2026-08-01, 60d
    Indexacao + Busca + Memoria           :2026-09-01, 60d
    Chat RAG + Desktop app                :2026-10-01, 60d
    MVP fechado (dogfooding)              :milestone, 2026-12-01, 0d
    section Beta (0.5-0.9)
    Alarmes inteligentes + Saude          :2027-01-01, 60d
    Documentos + Knowledge Graph          :2027-01-01, 90d
    Automacoes + Mobile essencial         :2027-03-01, 90d
    Beta publico                          :milestone, 2027-06-01, 0d
    section v1.0
    Sync E2E + Plugins SDK + Proatividade :2027-06-01, 120d
    Financeiro + Conectores               :2027-08-01, 90d
    Lancamento v1.0                       :milestone, 2027-11-01, 0d
    section v2.0
    Open Finance + Voz + Dispositivos     :2027-11-01, 150d
    Marketplace de plugins                :2028-02-01, 90d
```

## MVP — "o segundo cérebro mínimo" (desktop)

**Promessa:** "Aponte para suas pastas e converse com tudo que você tem."

Entra: monorepo + CI, Event Bus, camada de IA multi-provedor (OpenAI/Anthropic/Ollama), indexação de pastas locais (PDF/Office/texto/código), busca híbrida < 300 ms, memória em 5 camadas (consolidação básica), chat com streaming + citações + drag-and-drop, Memory/Task/Research Agents, app desktop com backend embutido, controle total das memórias, golden set de RAG no CI.

Fora (com data para entrar): mobile, sync, automações, plugins, saúde, finanças, proatividade.

**Critério de saída:** 4 semanas de dogfooding diário pela equipe; precisão do golden set ≥ alvo; zero perda de dados.

## Beta — "cuida da sua vida, não só dos seus arquivos"

Entra: alarmes inteligentes de medicação (parse NL → cronograma → confirmação → escalonamento), módulo saúde, cofre de documentos com OCR/classificação/vencimentos, knowledge graph + `/kg/ask`, motor + editor visual de automações, mobile essencial (chat, tarefas, alarmes nativos, push), Notification/Health/Document/Calendar/Email/Automation/Plugin Agents.

**Critério de saída:** beta público com ≥ 1.000 usuários ativos; D30 ≥ 40%; zero incidentes de segurança; pentest concluído.

## v1.0 — "plataforma"

Entra: sync multi-dispositivo E2E, SDK de plugins + diretório oficial, motor de proatividade (insights explicáveis com feedback), financeiro (importação, categorização, assinaturas, alertas), conectores Gmail/Drive, web app completo, dashboard com widgets.

**Critério de saída:** NPS ≥ 50; 10 plugins de terceiros no diretório; SLO 99,9% nos serviços cloud.

## v2.0 — "ecossistema"

Entra: Open Finance real (agregador licenciado), voz completa (wake word local, TTS), Travel/Shopping/Device Agents, NFC/QR/IoT, marketplace de plugins com monetização, times/família (multiusuário), API pública para desenvolvedores.

## Cadência

Release train quinzenal interno; canal stable mensal. Feature flags para tudo que cruza versões. Cada