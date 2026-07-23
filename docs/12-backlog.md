# 12 — Backlog Inicial

Priorização: P0 (MVP, bloqueante), P1 (MVP, importante), P2 (Beta), P3 (v1.0+). Estimativas em story points (Fibonacci).

## Épico E0 — Fundação técnica

| ID | História | Prio | SP |
|---|---|---|---|
| E0-01 | Como dev, quero o monorepo com core/adapters/api/apps e CI verde, para ter base de trabalho | P0 | 5 |
| E0-02 | Como dev, quero docker-compose com PG+pgvector, Redis e API, para subir tudo com um comando | P0 | 3 |
| E0-03 | Como dev, quero o Event Bus tipado (publish/subscribe/DLQ/replay) com testes, para toda comunicação | P0 | 8 |
| E0-04 | Como dev, quero DI configurada (ports/adapters) e esqueleto Clean Architecture, para manter dependências corretas | P0 | 5 |
| E0-05 | Como dev, quero a camada `AIProviderPort` com adaptadores OpenAI/Anthropic/Ollama e roteamento por política, para trocar modelo sem tocar no domínio | P0 | 8 |
| E0-06 | Como usuário, quero criar conta e autenticar (JWT/OAuth2, 2FA), para proteger meus dados | P0 | 8 |

## Épico E1 — Memória & RAG (coração do MVP)

| ID | História | Prio | SP |
|---|---|---|---|
| E1-01 | Como usuário, quero conectar pastas locais e ver documentos indexados, para dar memória ao sistema | P0 | 8 |
| E1-02 | Como sistema, quero extrair texto de PDF/DOCX/XLSX/PPTX/TXT/MD/código, para indexar qualquer arquivo | P0 | 8 |
| E1-03 | Como sistema, quero chunking + embeddings + upsert em pgvector com indexação incremental por hash, para busca semântica | P0 | 8 |
| E1-04 | Como usuário, quero busca universal híbrida (vetorial+léxica) com filtros, em < 300 ms, para achar qualquer coisa | P0 | 8 |
| E1-05 | Como sistema, quero as 5 camadas de memória com consolidação e decaimento agendados, para lembrar como um cérebro | P1 | 13 |
| E1-06 | Como usuário, quero ver/editar/apagar minhas memórias, para ter controle total | P0 | 5 |
| E1-07 | Como dev, quero um golden set de avaliação de RAG rodando no CI, para medir qualidade a cada mudança | P1 | 5 |

## Épico E2 — Chat assistente

| ID | História | Prio | SP | Status |
|---|---|---|---|---|
| E2-01 | Como usuário, quero chat com streaming e cancelamento, para conversar fluidamente | P0 | 5 | Implementado (ADR-030 streaming, ADR-032 cancelamento) |
| E2-02 | Como usuário, quero respostas com citações clicáveis das fontes, para confiar no sistema | P0 | 5 | Backend pronto (ADR-029): citações persistidas com ref_id verificável; falta UI |
| E2-03 | Como usuário, quero arrastar arquivos/imagens para o chat, para perguntar sobre eles | P0 | 5 | Backend pronto (ADR-033): arquivo vira documento indexado e citável. Imagens exigem OCRProvider (não configurado) ou modelo de visão — pendente |
| E2-04 | Como usuário, quero escolher provedor/modelo por conversa (incl. Ollama local), para controlar custo e privacidade | P1 | 3 | Implementado (ADR-031) |
| E2-05 | Como usuário, quero paleta de comandos ⌘K, para agir sem mouse | P1 | 5 | Pendente (UI) |
| E2-06 | Como usuário, quero que o chat lembre contexto de conversas anteriores (memória episódica), para não me repetir | P1 | 8 | Implementado (ADR-034) |

Nota: a numeração das entregas nesta sessão não seguiu a do backlog —
"E2 Etapa 1/2/3" correspondem, respectivamente, a chat/completions no
Gateway (base para tudo), E2-02 e a metade de streaming do E2-01. O
cancelamento que fecha o E2-01 virou infraestrutura de plataforma
(ADR-032), reutilizável por indexação, OCR, embeddings, agentes e
automações — não é específico do chat.

## Épico E3 — Desktop app

| ID | História | Prio | SP |
|---|---|---|---|
| E3-01 | Como usuário, quero instalador para Windows/macOS/Linux com backend embutido, para usar sem configurar nada | P0 | 13 |
| E3-02 | Como usuário, quero tema claro/escuro e UI minimalista rápida, para uma experiência agradável | P1 | 5 |
| E3-03 | Como usuário, quero funcionar 100% offline com Ollama, para privacidade total | P1 | 8 |
| E3-04 | Como usuário, quero dashboard personalizável com widgets, para ver o que importa | P2 | 8 |

## Épico E4 — Agentes básicos

| ID | História | Prio | SP |
|---|---|---|---|
| E4-01 | Como dev, quero o Orchestrator com registro/manifesto/supervisão, para plugar agentes | P0 | 8 |
| E4-02 | Como usuário, quero que o Memory Agent grave episódios das conversas automaticamente | P0 | 5 |
| E4-03 | Como usuário, quero que o Task Agent crie tarefas detectadas no chat ("preciso pagar X sexta") | P1 | 5 |
| E4-04 | Como usuário, quero que o Research Agent pesquise (web+local) e sintetize com fontes | P1 | 8 |

## Épico E5 — Lembretes e alarmes inteligentes (Beta)

| ID | História | Prio | SP |
|---|---|---|---|
| E5-01 | Lembretes simples e recorrentes (RRULE) com notificações | P2 | 5 |
| E5-02 | Interpretar instrução de medicação em linguagem natural → cronograma confirmável | P2 | 8 |
| E5-03 | Confirmação/adiamento de dose com histórico | P2 | 5 |
| E5-04 | Escalonamento: reenvio → prioridade → contato de confiança (opt-in) → ocorrência | P2 | 8 |

## Épico E6 — Documentos & knowledge graph (Beta)

| ID | História | Prio | SP |
|---|---|---|---|
| E6-01 | OCR de imagens e PDFs escaneados | P2 | 5 |
| E6-02 | Classificação automática de documentos + extração de campos (vencimento, valor) | P2 | 8 |
| E6-03 | Cofre de documentos com lembretes de vencimento | P2 | 5 |
| E6-04 | Knowledge graph: extração de entidades/relações na indexação + `/kg/ask` | P2 | 13 |

## Épico E7 — Automações (Beta)

| ID | História | Prio | SP |
|---|---|---|---|
| E7-01 | Motor de execução de DAG com retry/DLQ/logs por passo | P2 | 13 |
| E7-02 | Editor visual de fluxos (nós de gatilho/condição/ação/IA) | P2 | 13 |
| E7-03 | Templates prontos (boleto, arquivamento, resumo semanal) | P3 | 5 |

## Épico E8 — Mobile (Beta→v1.0)

| ID | História | Prio | SP |
|---|---|---|---|
| E8-01 | App Flutter: login, chat, tarefas, lembretes, notificações push | P2 | 13 |
| E8-02 | Alarmes de medicação nativos (funcionam com app fechado) | P2 | 8 |
| E8-03 | Captura rápida: foto de documento → OCR → cofre | P3 | 8 |
| E8-04 | Widgets, voz, QR/NFC | P3 | 13 |

## Épico E9 — Sync, plugins, proatividade, finanças (v1.0)

| ID | História | Prio | SP |
|---|---|---|---|
| E9-01 | Sync multi-dispositivo E2E-criptografado | P3 | 21 |
| E9-02 | SDK de plugins + Plugin Host sandbox + diretório | P3 | 21 |
| E9-03 | Motor de proatividade com insights explicáveis e feedback | P3 | 13 |
| E9-04 | Financeiro: importação CSV/OFX, categorização automática, alertas | P3 | 13 |
| E9-05 | Conectores e-mail e Google Drive | P3 | 13 |

Definition of Done (toda história): código de produção + testes (cobertura do domínio ≥ 80%) + documentação técnica + exemplo de uso + checklist de validação aprovado no PR.
