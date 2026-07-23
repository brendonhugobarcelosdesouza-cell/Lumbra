# 02 — Requisitos

Prioridade MoSCoW: **M** must (MVP), **S** should (Beta), **C** could (v1.0), **W** won't (agora).

## Requisitos funcionais

### RF-MEM — Memória e conhecimento

| ID | Requisito | Prio |
|---|---|---|
| RF-MEM-01 | Manter 5 tipos de memória: temporária, episódica, semântica, procedural, permanente | M |
| RF-MEM-02 | Armazenar embeddings em banco vetorial (pgvector; Qdrant como adaptador alternativo) | M |
| RF-MEM-03 | RAG: recuperar contexto relevante e citar fontes em cada resposta | M |
| RF-MEM-04 | Consolidação: promover memórias temporárias→episódicas→semânticas por relevância/recorrência | S |
| RF-MEM-05 | Knowledge graph relacionando pessoas, locais, projetos, empresas, arquivos, conversas, medicamentos, objetivos, eventos, contas, documentos, veículos, equipamentos | S |
| RF-MEM-06 | Responder perguntas combinando busca vetorial + travessia do grafo | S |
| RF-MEM-07 | Usuário pode visualizar, editar e apagar qualquer memória ("direito ao esquecimento") | M |

### RF-IDX — Indexação e pesquisa

| ID | Requisito | Prio |
|---|---|---|
| RF-IDX-01 | Indexar PDF, DOCX, XLSX, PPTX, TXT, MD, ZIP e código-fonte | M |
| RF-IDX-02 | OCR de imagens e PDFs escaneados | S |
| RF-IDX-03 | Transcrição de áudio e vídeo | S |
| RF-IDX-04 | Indexar e-mails (IMAP/Gmail API) | S |
| RF-IDX-05 | Monitorar pastas locais (Downloads, Desktop, configuráveis) | M |
| RF-IDX-06 | Conectores Google Drive, OneDrive, Dropbox | C |
| RF-IDX-07 | Pesquisa semântica universal com filtros (tipo, data, fonte, entidade) | M |
| RF-IDX-08 | Indexação incremental com detecção de mudanças (hash + mtime) | M |

### RF-CHAT — Assistente

| ID | Requisito | Prio |
|---|---|---|
| RF-CHAT-01 | Chat com texto, voz, imagem, PDF, áudio, vídeo e arquivos (drag-and-drop) | M (texto/arquivo/imagem); S (voz); C (vídeo) |
| RF-CHAT-02 | Respostas multimodais (texto, tabelas, cartões, gráficos, áudio) | S |
| RF-CHAT-03 | Streaming de respostas com cancelamento | M |
| RF-CHAT-04 | Troca de provedor de IA (OpenAI/Anthropic/Gemini/Ollama) por conversa, sem reinício | M |
| RF-CHAT-05 | Comandos rápidos estilo Raycast (paleta ⌘K) | S |

### RF-AGT — Multi-agentes

| ID | Requisito | Prio |
|---|---|---|
| RF-AGT-01 | Agentes especializados registrados no kernel, com objetivos, API, fila, estado e memória compartilhada | M (Memory, Task, Research); S (demais) |
| RF-AGT-02 | Toda comunicação inter-agentes via Event Bus (nunca direta) | M |
| RF-AGT-03 | Orquestrador decompõe pedidos em subtarefas para agentes | S |
| RF-AGT-04 | Agentes exigem permissão explícita para ações com efeito externo | M |

### RF-AUT — Automações

| ID | Requisito | Prio |
|---|---|---|
| RF-AUT-01 | Editor visual de fluxos (nós: gatilho, condição, ação, IA) estilo n8n | S |
| RF-AUT-02 | Gatilhos: evento do sistema, agenda, arquivo novo, e-mail, webhook | S |
| RF-AUT-03 | Execução com log por passo, retry e dead-letter | S |
| RF-AUT-04 | Templates prontos (ex.: boleto → extrair → vencimento → lembrete → financeiro → arquivar → notificar) | C |

### RF-ALM — Alarmes inteligentes

| ID | Requisito | Prio |
|---|---|---|
| RF-ALM-01 | Interpretar linguagem natural ("antibiótico 7 dias de 8 em 8h") e gerar cronograma completo | S |
| RF-ALM-02 | Confirmação de tomada, histórico, atrasos e esquecimentos | S |
| RF-ALM-03 | Escalonamento: reenviar → aumentar prioridade → avisar contato (opt-in) → registrar ocorrência | S |
| RF-ALM-04 | Reagendamento automático mantendo intervalos | S |

### RF-VIDA — Saúde, finanças, documentos, rotina

| ID | Requisito | Prio |
|---|---|---|
| RF-SAU-01 | Histórico médico: receitas, consultas, exames, medicamentos, vacinas, sintomas, relatórios | S |
| RF-FIN-01 | Financeiro: Open Finance (leitura), PIX, cartões, assinaturas, categorização automática, metas, fluxo de caixa, projeções, alertas | C (MVP: manual + importação) |
| RF-DOC-01 | Cofre de documentos (RG, CPF, CNH, passaporte, contratos, garantias, notas) com lembretes de vencimento | S |
| RF-ROT-01 | Hábitos, metas, sono, exercícios, estudos, checklists, Pomodoro | C |

### RF-PRO — Proatividade

| ID | Requisito | Prio |
|---|---|---|
| RF-PRO-01 | Motor de insights analisa agenda, hábitos, documentos, tarefas, clima, finanças, saúde e (com autorização) localização | S |
| RF-PRO-02 | Sugestões acionáveis com explicação da origem ("por que estou vendo isso?") | S |
| RF-PRO-03 | Controle granular por fonte de observação; modo "não perturbe" | M |

### RF-PLG — Plugins

| ID | Requisito | Prio |
|---|---|---|
| RF-PLG-01 | SDK: plugins adicionam agentes, integrações, comandos, widgets, páginas, automações, menus, painéis | S |
| RF-PLG-02 | Sandbox com manifesto de permissões; instalação/remoção a quente | S |
| RF-PLG-03 | Versionamento e compatibilidade semântica de API do SDK | S |

### RF-MOB — Mobile

| ID | Requisito | Prio |
|---|---|---|
| RF-MOB-01 | Alarmes, agenda, tarefas, medicamentos, notificações, widgets, captura rápida, chat, sincronização | S |
| RF-MOB-02 | Voz, GPS, QR Code, NFC, OCR por câmera, digitalização de documentos | C |

### RF-SYNC — Sincronização

| ID | Requisito | Prio |
|---|---|---|
| RF-SYNC-01 | Sync multi-dispositivo com resolução de conflitos (CRDT/LWW por tipo de dado) | S |
| RF-SYNC-02 | Operação 100% offline com fila de mudanças e reconciliação | M (desktop) |
| RF-SYNC-03 | Sync E2E-criptografado; servidor não lê conteúdo | S |

## Requisitos não funcionais

| ID | Categoria | Requisito |
|---|---|---|
| RNF-01 | Desempenho | Busca semântica local p95 < 300 ms; abertura da paleta < 100 ms; primeiro token de IA < 2 s (cloud) |
| RNF-02 | Desempenho | Indexação ≥ 50 docs/min em hardware médio, sem degradar UI (prioridade de I/O baixa) |
| RNF-03 | Disponibilidade | Núcleo local sem dependência de rede; serviços cloud 99,9% |
| RNF-04 | Escalabilidade | Arquitetura cloud dimensionada para 1M+ usuários (doc 19) |
| RNF-05 | Segurança | AES-256 em repouso, TLS 1.3 em trânsito, JWT + OAuth2 + 2FA + biometria (doc 18) |
| RNF-06 | Privacidade | LGPD/GDPR: consentimento granular, exportação e exclusão total de dados |
| RNF-07 | Extensibilidade | Nenhuma feature acoplada; novos módulos sem alterar o kernel (microkernel + eventos) |
| RNF-08 | Portabilidade | Windows, Linux, macOS, Android, iOS, Web com paridade do núcleo |
| RNF-09 | Observabilidade | Logs estruturados, métricas e tracing distribuído (doc 16); telemetria opt-in |
| RNF-10 | Testabilidade | Cobertura ≥ 80% no domínio; contratos de API testados; DI em todos os módulos |
| RNF-11 | Usabilidade | Tema claro/escuro, dashboard personalizável, atalhos completos, acessibilidade WCAG 2.1 AA |
| RNF-12 | Confiabilidade | Nenhuma perda de dados confirmados; WAL + backups verificados (doc 17) |
| RNF-13 | Custo | Modo 100% local (Ollama) sem custo de API; orçamento de tokens configurável |
| RNF-14 | Manutenibilidade | SOLID, Clean Architecture, DDD; ADRs para toda decisão relevante (doc 20) |
