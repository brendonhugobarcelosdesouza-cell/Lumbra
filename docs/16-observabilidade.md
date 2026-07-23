# 16 — Observabilidade

Stack: OpenTelemetry em tudo (API, workers, agentes) → Prometheus (métricas), Loki (logs), Tempo (traces), Grafana (visualização), Alertmanager. Sentry para erros de cliente (desktop/mobile/web).

## Logs

Estruturados (JSON) com campos obrigatórios: `timestamp`, `level`, `service`, `user_id` (hash), `correlation_id`, `event_type`. **Nunca logar**: conteúdo de memórias, documentos, mensagens, payloads de saúde/finanças — apenas IDs e metadados. Retenção: 30 dias quente, 1 ano frio (auditoria de segurança: 2 anos).

## Métricas principais

| Domínio | Métrica | SLO/alerta |
|---|---|---|
| API | latência p50/p95/p99 por rota; taxa de erro | p95 < 500 ms; erro < 0,5% |
| Busca | latência de busca híbrida | p95 < 300 ms |
| Chat | tempo até primeiro token; tokens/s; custo por conversa | 1º token < 2 s (cloud) |
| Indexação | docs/min, fila, taxa de falha por tipo de arquivo | fila > 1 h → alerta |
| Event Bus | lag por consumidor, DLQ depth, replays | DLQ > 0 sustentado → alerta |
| Agentes | execuções, falhas, restarts, timeout de plano | restart em loop → alerta |
| RAG | recall@k do golden set (por release), groundedness | regressão > 2 pts bloqueia |
| Sync | conflitos/dia, divergência detectada | divergência = incidente |
| Notificações | entregues, ignoradas, escalonadas | dose crítica não entregue = P1 |

## Tracing

Trace distribuído por `correlation_id` atravessando: request HTTP → comando → eventos → workers → chamadas de IA. Spans de IA anotam modelo, tokens e custo (sem conteúdo). Amostragem: 100% de erros, 10% do restante.

## Telemetria do desktop (privacy-first)

Opt-in explícito no onboarding. Somente métricas agregadas e anônimas (versão, plataforma, latências, falhas). Zero conteúdo, zero identificadores pessoais. Documento público descrevendo cada campo enviado. Modo 100% offline = zero telemetria.

## Alertas e plantão

Severidades: P1 (perda de dados, vazamento, notificação crítica de saúde falhou) — page imediato; P2 (SLO violado) — horário comercial; P3 — backlog. Runbooks versionados junto do código em `infra/runbooks/`. Postmortem sem culpados para todo P1/P2.
