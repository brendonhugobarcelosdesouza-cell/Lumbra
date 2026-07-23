# 19 — Escalabilidade (1M+ usuários)

## Vantagem estrutural: local-first

A decisão mais importante de escala já foi tomada na arquitetura: **o trabalho pesado (indexação, embeddings, busca, RAG local) roda no dispositivo do usuário**. A nuvem serve sync, web/mobile e conectores — uma fração do custo de uma plataforma 100% cloud. 1M de usuários desktop ≈ 1M de "servidores" que nós não pagamos.

## O que escala na nuvem e como

| Componente | Estratégia |
|---|---|
| API Gateway / FastAPI | Stateless → réplicas horizontais atrás de LB; autoscaling por p95 e RPS |
| Workers Celery | Filas por classe de trabalho (indexação, IA, notificações) com autoscaling independente; prioridade para interativo |
| PostgreSQL | 1º: réplicas de leitura + particionamento (`events_log`, `sync_ops`). 2º: **sharding por `user_id`** (Citus) — dados de usuário nunca cruzam shard, o modelo já é multi-tenant por linha |
| pgvector | Índices HNSW por shard; usuários pesados (web-only) podem migrar para Qdrant dedicado atrás do `VectorStorePort` sem mudança de código |
| Redis | Cluster; streams por shard de usuários; TTL agressivo em cache |
| Object storage | S3: escala gerenciada; CDN para assets |
| Sync | Naturalmente particionável por usuário; blobs opacos E2E = servidor barato (sem processamento de conteúdo) |
| IA cloud | Roteamento por custo + cache de embeddings/respostas + orçamento por usuário; picos → fila com degradação graciosa (aviso de fila em vez de erro) |

## Marcos de capacidade

| Usuários | Arquitetura cloud |
|---|---|
| 0–10k (beta) | 1 região, PG único + réplica, compose→Kubernetes simples |
| 10k–100k | Autoscaling, particionamento de tabelas grandes, réplicas de leitura, CDN |
| 100k–1M | Sharding Citus por user_id, multi-AZ, filas por classe, rate limiting por plano |
| 1M+ | Segunda região (ativo-passivo → ativo-ativo por residência de dados), cell-based architecture: células independentes de ~200k usuários, blast radius limitado |

## Princípios que impedem re-arquitetura futura

1. Todo dado de usuário tem `user_id` na chave → sharding é operação, não refatoração.
2. Serviços stateless; estado só em PG/Redis/S3.
3. Comunicação por eventos → consumidores escalam separadamente.
4. Ports & adapters → trocar pgvector→Qdrant, Redis Streams→Kafka (se necessário >100k eventos/s) sem tocar no domínio.
5. Nenhuma feature depende de "todos os usuários no mesmo banco" (sem JOINs cross-user).

## Custos

Meta: custo cloud por usuário ativo < US$ 0,15/mês no free tier (sync + push + conectores leves), subsidiado pelos planos pagos (IA cloud gerenciada, conectores premium, família/times). Dashboard de custo por feature desde o beta; orçamento de tokens por usuário com corte gracioso.
