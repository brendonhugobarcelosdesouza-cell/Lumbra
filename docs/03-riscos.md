# 03 — Riscos Técnicos

Escala: probabilidade e impacto de 1 (baixo) a 5 (crítico). Exposição = P × I.

| ID | Risco | P | I | Exp | Mitigação |
|---|---|---|---|---|---|
| R-01 | **Escopo excessivo** — plataforma compete com 15 produtos ao mesmo tempo; risco nº 1 do projeto | 5 | 5 | 25 | Roadmap rígido: MVP = memória+RAG+chat apenas. Tudo além disso atrás de feature flags. Critério de corte explícito por versão (doc 13) |
| R-02 | Qualidade do RAG insuficiente (respostas erradas minam confiança de forma irreversível) | 4 | 5 | 20 | Pipeline de avaliação (golden set), citação obrigatória de fontes, resposta "não sei" quando confiança baixa, re-ranking |
| R-03 | Sincronização multi-dispositivo com conflitos e perda de dados | 4 | 5 | 20 | Adiar sync para Beta; CRDTs por tipo de dado; log de operações imutável; testes de convergência property-based |
| R-04 | Desempenho de embeddings/indexação em hardware fraco | 4 | 3 | 12 | Modelos de embedding pequenos locais (ex.: bge-small), fila com backpressure, indexação em idle, benchmark contínuo |
| R-05 | Custo de APIs de IA inviabiliza operação | 3 | 4 | 12 | Camada de abstração com roteamento por custo, cache de respostas/embeddings, Ollama como fallback, orçamento por usuário |
| R-06 | Dependência de fornecedor de IA (mudança de preço/política/API) | 4 | 3 | 12 | Abstração `AIProvider` desde o dia 1; testes de contrato por provedor; nenhum recurso exclusivo de um provedor no núcleo |
| R-07 | Vazamento de dados sensíveis (saúde, finanças, documentos) | 2 | 5 | 10 | E2E crypto, criptografia em repouso, threat modeling, pentest antes do beta público, princípio do menor privilégio, dados sensíveis nunca em telemetria |
| R-08 | Segurança do sandbox de plugins (plugin malicioso lê tudo) | 3 | 4 | 12 | Processo isolado, manifesto de permissões, API mediada pelo kernel, revisão de plugins no diretório oficial |
| R-09 | Complexidade do Event Bus vira gargalo de debug | 3 | 3 | 9 | Tracing por correlation-id em todo evento, replay de eventos em dev, esquemas versionados (doc 10) |
| R-10 | Open Finance: homologação regulatória e instabilidade de APIs bancárias | 4 | 3 | 12 | Adiar para v1.0 via agregador licenciado (ex.: Pluggy/Belvo); MVP financeiro manual/CSV |
| R-11 | Restrições de iOS/Android para background (alarmes, indexação, proatividade) | 4 | 3 | 12 | Notificações locais agendadas nativamente; push como backup; expectativas de produto ajustadas por plataforma |
| R-12 | Electron: consumo de memória e percepção de lentidão | 3 | 2 | 6 | Processos utilitários separados, virtualização de listas, medir p95 de interações; migração parcial a Tauri é plano B documentado |
| R-13 | Equipe pequena vs. superfície gigante de manutenção | 4 | 4 | 16 | Monorepo, código compartilhado máximo, CI forte, priorizar desktop antes de mobile |
| R-14 | LGPD/GDPR: base legal para processamento de saúde/finanças | 3 | 4 | 12 | Consentimento explícito por categoria, DPO desde o beta, privacy by design documentado (doc 18) |
| R-15 | Knowledge graph cresce sujo (entidades duplicadas, relações erradas) | 4 | 2 | 8 | Resolução de entidades com revisão humana opcional, limiar de confiança, ferramenta de merge/split |

## Top 3 — atenção contínua

**R-01 (escopo)** é tratado como risco existencial: qualquer proposta de feature fora da versão corrente exige ADR.
**R-02 (qualidade RAG)** define o produto: existe um golden set de perguntas/respostas avaliado a cada release.
**R-03 (sync)** só entra quando o modelo de dados estiver estável; offline-first local primeiro.
