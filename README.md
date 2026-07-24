# Lumbra — Personal Intelligence Platform

Um "segundo cérebro" que lembra, pesquisa e responde sobre a **sua** vida:
seus documentos, suas memórias, suas decisões. Roda inteiro na sua máquina
— nenhum dado sai dela a menos que você peça explicitamente.

```
você:   Quanto custa o aluguel?
lumbra: O aluguel é R$ 1.800,00 por mês, com vencimento no dia 5 [1].
        fontes: [1] contrato-apartamento.pdf
```

Cada resposta cita a fonte, e cada citação aponta para o trecho exato do
arquivo de onde veio. Sem fonte, o assistente diz que não sabe em vez de
inventar.

---

## Começando

Você precisa de **Python 3.12+**, **Docker** (para Postgres e Redis) e
**[Ollama](https://ollama.com)** (para o modelo local).

```bash
git clone <repo> && cd lumbra
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"

ollama pull qwen2.5:7b     # modelo local (~4,7 GB, uma vez só)

lumbra doctor              # verifica o ambiente e diz como corrigir o que falta
lumbra dev                 # sobe banco, aplica migrações e inicia a API
lumbra init                # assistente de primeira execução (em outro terminal)
```

O `lumbra init` cria sua conta, indexa uma pasta sua, guarda uma primeira
memória e faz uma pergunta de teste — do zero ao primeiro uso real.

### Se algo der errado

```bash
lumbra doctor              # todo problema vem com instrução de correção
```

Esse é o primeiro comando a rodar sempre. Ele verifica Python,
dependências, Docker, PostgreSQL, pgvector, migrações, índices, Redis,
Ollama, modelo baixado, embeddings, portas e permissões — e, para cada
problema, diz exatamente o que fazer.

A mesma informação está em `http://localhost:8000/api/v1/system` (página
**System Health**), útil quando a API está no ar mas algo não responde.

---

## Comandos

| Comando | O que faz |
|---|---|
| `lumbra doctor` | Diagnostica o ambiente. `--json` para uso por scripts. |
| `lumbra dev` | Sobe Postgres e Redis, migra e inicia a API com recarga automática. |
| `lumbra up` | Modo produção local: sem recarga e **recusa subir** se houver falha. |
| `lumbra init` | Assistente de primeira execução. |
| `lumbra version` | Versão da plataforma. |

## Onde as coisas ficam

| Endereço | Para quê |
|---|---|
| `/docs` | API interativa (Swagger) |
| `/api/v1/system` | System Health — estado de cada peça |
| `/api/v1/system/eventbus` | Saúde do Event Bus — throughput, backlog, pendentes, DLQ por consumidor |
| `/api/v1/dev/console` | Developer Console — executar skills, ver eventos, logs, AI Trace |
| `/api/v1/memory` | Auditar e editar o que a plataforma lembra de você |

O `scripts/chat.ps1` (Windows) conversa pelo terminal com streaming,
anexos (`/anexar arquivo`), troca de modelo (`/usar`) e cancelamento (ESC).

---

## Como funciona

Seus arquivos passam por um pipeline (extração → chunking → embeddings →
grafo) e viram trechos pesquisáveis. Quando você pergunta algo, o
**Context Engine** reúne o que é relevante — documentos, memórias, anexos
da conversa — e o modelo responde **citando as fontes numeradas**.

Quatro princípios que explicam a maioria das decisões do código:

- **Privacidade por padrão.** O roteamento de IA é local-first; usar nuvem
  é uma escolha explícita, por conversa. Sem chave configurada, o provedor
  de nuvem sequer existe para o sistema.
- **Tudo explicável.** Toda decisão relevante (o que foi buscado, por que
  aquele modelo, por que aquela memória) fica registrada e consultável.
- **Nada de mágica silenciosa.** Cancelar libera a GPU de verdade; um
  anexo que não pôde ser lido diz isso em vez de sumir; memória duplicada
  é descartada em vez de entulhar o recall.
- **Interromper não descarta trabalho.** Resposta cancelada é salva
  parcial; indexação interrompida guarda o que já processou.

A arquitetura é hexagonal: o domínio não conhece infraestrutura, tudo
entra por *ports* e *adapters*. Trocar Ollama por outro provedor, ou o
sistema de arquivos por S3, é escrever um adaptador — nada mais muda.

## Documentação

Comece pelos [princípios](docs/00-principios.md) e pelas
[decisões arquiteturais](docs/20-adrs.md) — são o mapa mental do projeto.

| # | Documento | Conteúdo |
|---|-----------|----------|
| 00 | [Princípios](docs/00-principios.md) | Regras permanentes e como cada uma vive no código |
| 01 | [Visão do produto](docs/01-visao-produto.md) | Missão, posicionamento, personas |
| 02 | [Requisitos](docs/02-requisitos.md) | Funcionais e não funcionais |
| 03 | [Riscos técnicos](docs/03-riscos.md) | Riscos, impacto, mitigação |
| 04 | [Arquitetura](docs/04-arquitetura.md) | Camadas, Core Intelligence Engine, Event Bus |
| 05 | [Diagramas C4](docs/05-c4.md) | Contexto, contêineres, componentes |
| 06 | [Diagramas UML](docs/06-uml.md) | Classes, sequência, estados |
| 07 | [Multi-agentes](docs/07-agentes.md) | Especificação de cada agente |
| 08 | [Modelo de dados](docs/08-banco-de-dados.md) | PostgreSQL + pgvector, ER, migrações |
| 09 | [Domínio DDD](docs/09-ddd.md) | Bounded contexts, entidades, agregados |
| 10 | [Eventos](docs/10-eventos.md) | Catálogo de eventos |
| 11 | [Contratos de API](docs/11-apis.md) | REST, SSE, convenções |
| 12 | [Backlog](docs/12-backlog.md) | Épicos, histórias e **status real** de cada uma |
| 13 | [Roadmap](docs/13-roadmap.md) | MVP → Beta → v1.0 → v2.0 |
| 14 | [Testes](docs/14-testes.md) | Estratégia e pirâmide |
| 15 | [CI/CD](docs/15-cicd.md) | Pipelines, ambientes, releases |
| 16 | [Observabilidade](docs/16-observabilidade.md) | Logs, métricas, tracing |
| 17 | [Backup e DR](docs/17-backup-dr.md) | Backup e recuperação |
| 18 | [Segurança](docs/18-seguranca.md) | Criptografia, autenticação, LGPD |
| 19 | [Escalabilidade](docs/19-escalabilidade.md) | Plano de crescimento |
| 20 | [ADRs](docs/20-adrs.md) | Cada decisão, com o porquê e o que se perdeu |
| 21 | [Cancelamento](docs/21-cancelamento.md) | Como tornar uma operação longa cancelável |
| 22 | [Backlog de dogfooding](docs/22-dogfooding-issues.md) | Problemas do uso real, com impacto, causa e prioridade |
| 23 | [Corpus de avaliação](docs/23-corpus-avaliacao.md) | Benchmark de qualidade do RAG por categoria de documento |

## Desenvolvimento

```bash
make ci        # lint + mypy strict + testes com gate de cobertura (85%)
make test      # só os testes
make fmt       # formata
```

Os testes de integração sobem um PostgreSQL real (via `pgserver`), então
não precisam de Docker para rodar.

**Estado atual:** épicos E1 (memória e RAG) e E2 (chat assistente)
implementados no backend, mais duas levas de consolidação — Leva 3
(Developer Experience: CLI `lumbra`, System Health, wizard) e Leva 2
(endurecimento do Event Bus: concorrência por chave de partição,
resiliência com backoff e recuperação após crash, observabilidade e testes
de carga). A fase corrente é **dogfooding intensivo** guiado por um
[Corpus de Avaliação](docs/23-corpus-avaliacao.md), com os problemas
registrados no [backlog de dogfooding](docs/22-dogfooding-issues.md). O
status honesto de cada história está no [backlog](docs/12-backlog.md); as
decisões de arquitetura, nos [ADRs](docs/20-adrs.md).

## Stack

Python 3.12, FastAPI, SQLAlchemy, PostgreSQL + pgvector, Redis,
fastembed (embeddings locais), Ollama e Anthropic (chat), Docker.
