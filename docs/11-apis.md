# 11 — Contratos de API

## Convenções

Base: `/api/v1`. Auth: `Authorization: Bearer <JWT>` (OAuth2 + refresh; 2FA no login). Erros: RFC 9457 (`application/problem+json`). Paginação por cursor (`?cursor=&limit=`). Idempotência em POSTs críticos via `Idempotency-Key`. Versionamento na URL; breaking → `/v2`. Rate limit por usuário com headers `X-RateLimit-*`. Streaming: SSE para respostas de IA; WebSocket `/ws` para eventos em tempo real na UI.

## Chat

```
POST /chat/conversations                     → cria conversa
GET  /chat/conversations?cursor=             → lista
POST /chat/conversations/{id}/messages       → envia mensagem (JSON completo)
POST /chat/conversations/{id}/messages/stream → envia mensagem (SSE)
GET  /chat/conversations/{id}/messages       → histórico com citações
GET  /chat/providers                         → modelos disponíveis + preço/1M tokens
PATCH /chat/conversations/{id}/policy        → troca provedor/privacidade (E2-04)
POST /chat/conversations/{id}/messages/cancel → cancela a geração em andamento
POST /chat/conversations/{id}/attachments    → anexa arquivo/imagem (multipart, máx 25MB)
GET  /chat/conversations/{id}/attachments    → anexos e seu estado
```

```jsonc
// POST /chat/conversations/{id}/messages
{
  "content": [
    {"type": "text", "text": "Quando vence minha CNH?"},
    {"type": "file", "upload_id": "up_123"}          // multimodal
  ],
  "model_policy": {"provider": "auto", "privacy": "local_only?"}
}
// resposta: text/event-stream
// event: token        {"delta": "Sua CNH"}
// event: sources      {"citations": [{"chunk_id": "...", "title": "CNH.pdf", "score": 0.91}]}
// event: done         {"message_id": "...", "usage": {"in": 812, "out": 96}}
// event: cancelled    {"message_id": "...", "reason": "user|client_gone|timeout", "partial_saved": true}
// event: error        {"detail": "..."}   (erro após o 200: o status já foi enviado)
```

## Busca universal

```
POST /search
{ "query": "contrato do apartamento", 
  "filters": {"kinds": ["document","email"], "after": "2025-01-01", "entity": "Imobiliária X"},
  "mode": "hybrid" }                       // hybrid | vector | lexical
→ { "results": [{"chunk_id","document_id","title","snippet","score","source"}], "next_cursor": null }
```

## Memória

```
GET    /memory?kind=semantic&query=...        → recall (auditável pelo usuário)
POST   /memory                                → gravar memória manual/pinned
PATCH  /memory/{id}                           → editar / fixar (kind=permanent)
DELETE /memory/{id}                           → esquecer (irrevogável, auditado)
```

## Knowledge graph

```
GET  /kg/entities?kind=person&query=jo        → busca entidades
GET  /kg/entities/{id}                        → entidade + relações
POST /kg/entities/{id}/merge {"into": "..."}  → correção humana
GET  /kg/ask?q=...                            → resposta via grafo+RAG com evidências
```

## Indexação

```
GET    /indexing/sources                      → fontes (pastas, e-mail, drives) e status
POST   /indexing/sources                      → conectar fonte {"type":"folder","path":...}
DELETE /indexing/sources/{id}                 → desconectar + expurgo opcional
POST   /uploads                               → multipart; retorna upload_id
GET    /indexing/status                       → fila, progresso, erros
```

## Saúde / medicação

```
POST /health/medications
{ "instruction": "Amoxicilina 500mg por 7 dias de 8 em 8 horas, começando às 8h" }
→ 201 { "medication_id", "schedule": {"doses": 21, "first": "...", "last": "..."},
        "requires_confirmation": true }        // usuário confirma o cronograma interpretado

POST /health/doses/{id}/confirm | /snooze {"minutes": 30}
GET  /health/medications/{id}/history          → doses, atrasos, esquecimentos
```

## Tarefas, lembretes, documentos

```
POST/GET/PATCH/DELETE /tasks                   → CRUD + /tasks/{id}/complete
POST /reminders  {"text","due_at"|"rrule"}     → lembrete simples ou recorrente
GET  /vault/documents?kind=cnh                 → cofre de documentos
POST /vault/documents                          → upload + classificação automática
GET  /vault/expiring?within_days=45            → vencimentos próximos
```

## Automações

```
GET/POST /automations                          → CRUD do fluxo (graph JSON do editor)
POST /automations/{id}/publish                 → valida DAG e ativa
POST /automations/{id}/test                    → execução dry-run com evento sintético
GET  /automations/{id}/runs                    → histórico com passos e erros
```

## Insights (proatividade)

```
GET  /insights?status=active                   → sugestões com explanation e evidence
POST /insights/{id}/accept | /dismiss          → feedback (alimenta memória procedural)
GET/PUT /insights/settings                     → fontes observadas, quiet hours
```

## Consentimento e privacidade

```
GET    /consents                               → tudo que foi concedido, a quem
POST   /consents {"scope","granted_to"}        → conceder
DELETE /consents/{id}                          → revogar (efeito imediato)
POST   /privacy/export                         → exportação completa (LGPD)
POST   /privacy/erase                          → exclusão total com confirmação 2FA
```

## Plugins

```
GET  /plugins/registry?query=                  → diretório
POST /plugins/install {"plugin_id"}            → instala; retorna permissões pedidas
POST /plugins/{id}/enable | /disable | DELETE
```

## Sync (dispositivos)

```
POST /sync/push  {"device_id","ops":[...]}     → ops criptografadas + lamport
GET  /sync/pull?since_lamport=...              → ops de outros dispositivos
```

## WebSocket `/ws`

Servidor → cliente: `notification`, `insight.generated`, `indexing.progress`, `automation.run_completed`, `sync.applied`. Cliente → servidor: `subscribe {topics[]}`, `ping`.

## SDK de plugins (superfície resumida)

```typescript
export interface LumbraPlugin {
  manifest: Manifest;                       // nome, versão, permissões
  activate(ctx: PluginContext): void;
}
interface PluginContext {
  events: { on(type: string, h: Handler): void; emit(evt: DomainEvent): void };
  commands: { register(cmd: Command): void };        // paleta ⌘K
  ui: { addWidget(w: Widget): void; addPage(p: Page): void; addPanel(p: Panel): void };
  agents: { register(a: AgentSpec): void };
  automations: { registerNode(n: NodeSpec): void };  // novos nós no editor
  storage: KVStore;                                  // isolado por plugin
  ai: { complete(req): Promise<Completion> };        // mediado, com orçamento
  // Todo acesso passa pelo Permission Manager; sem permissão no manifesto = erro.
}
```
