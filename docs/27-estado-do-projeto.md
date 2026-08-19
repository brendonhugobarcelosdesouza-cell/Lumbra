# Estado do projeto — Lumbra

*Relatório de situação. O que existe, o que foi provado, o que falta e o que
está pendurado como dívida nomeada.*

---

## 1. Onde estamos

A Lumbra deixou de ser um projeto que se roda e virou um programa que se
abre. Essa é a mudança da última rodada, e é maior que qualquer
funcionalidade: até ontem ela exigia Docker Desktop, dois terminais e um
ambiente virtual Python. Hoje o Nó é um executável de 221 MB que sobe o
próprio PostgreSQL, e o app o inicia sozinho.

O que **está fechado e provado**:

| Épico | Estado | O que entrega |
|---|---|---|
| Fundação (monorepo, Event Bus, Kernel, API) | ✅ | Base hexagonal, 11 migrações, CI com portões duros |
| E1 — Acervo | ✅ | Pipeline de ingestão, RAG híbrido, memória em 5 camadas |
| E2 — Conversa | ✅ | Chat com streaming, citações, anexos, escolha de modelo |
| Fase A — Agentes | ✅ A0→A9, A11 | Capability Model, Orchestrator em camadas, Sandbox, delegação |
| Fase L — Aprendizado | ✅ L1, L2 | Playbooks (memória procedural), fila de aprovações persistente |
| P1 — Plataforma | ✅ | Contrato OpenAPI versionado, dispositivos, cliente Dart gerado |
| P2 — Cliente Desktop | 🟡 quase | App Flutter completo; instalador é o que falta |

Números: **72 ADRs**, 11 migrações, 84 arquivos de teste no Core, 14 no app.

---

## 2. O que a última rodada resolveu

Cinco problemas estruturais, todos encontrados **usando** o produto — nenhum
foi previsto no papel.

**Docker deixou de ser requisito (ADR-069).** O Postgres virou um detalhe do
Nó em vez de um serviço a instalar: `pgserver` traz PostgreSQL 16 com pgvector
dentro do pacote Python. Descartei SQLite de propósito — custaria a busca
full-text em português com pesos, o `pgvector` e as transações que garantem
decisão única na fila de aprovações. Seria mudar o produto para simplificar a
infraestrutura.

**Cada instalação gera a própria chave (ADR-070).** O `lumbra up` se recusava
a subir sem segredo de JWT próprio, e mandava o usuário definir uma variável
de ambiente antes de escrever a primeira anotação. As duas saídas óbvias eram
ruins: afrouxar a checagem deixaria toda instalação com a mesma chave
conhecida (pior que não ter autenticação, porque parece que tem); exigir a
variável transfere ao usuário um trabalho que a máquina faz melhor.

**O app pede que o Nó encerre, em vez de matá-lo (ADR-071).** No Windows não
há sinal para enviar — `kill` vira `TerminateProcess`. O preço já tinha sido
cobrado: o Postgres embutido levou um tiro no meio de um `COMMIT` e o cluster
ficou precisando de recuperação. O canal de despedida passou a ser a entrada
padrão, que funciona nos dois sistemas. A propriedade que decidiu o desenho:
**quando o app morre de repente, o cano fecha do mesmo jeito** — verificado
matando o pai com `SIGKILL`, o Nó encerrou sozinho em 1 segundo.

**`lumbra up` distingue o que impede servir do que só tira uma função
(ADR-072).** Sem Ollama instalado, a Lumbra inteira não abria — embora
documentos, memória e busca não dependam de modelo de conversa.

**O banco sujo voltou a abrir.** A pior descoberta do dia: o `pgserver` dá 10
segundos ao `pg_ctl start`, e a recuperação de um cluster interrompido passa
de 30. Depois da primeira parada suja, **nenhuma partida futura subia** — e o
dono do computador não tinha como sair sozinho.

---

## 3. O que falta para fechar o P2

Em ordem de dependência.

### 3.1. Confirmar o conjunto (imediato)
O app já é montado com o Nó dentro e o script prova que ele sobe do lugar
definitivo. Falta a confirmação humana: abrir o `lumbra_app.exe` por dois
cliques, com o banco precisando de recuperação, e ver a tela "Iniciando o
Nó…" dar lugar à Lumbra.

### 3.2. O instalador propriamente dito
Inno Setup é o candidato: não exige conta de desenvolvedor nem assinatura.
Entrega: atalho no Menu Iniciar, desinstalador, e a pasta `no/` ao lado do
app. **Decisão em aberto:** o `fastembed` baixa o modelo (~120 MB) na
primeira execução. Ou o instalador leva o modelo junto (pacote de ~370 MB,
funciona sem internet), ou a primeira partida exige rede. Não decidi sozinho.

### 3.3. System Health nativo
Está no escopo do P2 e ainda vive só no Developer Console. O `doctor` já
responde em JSON — falta a tela.

---

## 4. Dívidas nomeadas

Coisas que **sei** que estão erradas ou incompletas. Nenhuma é surpresa.

**O leitor SSE do chat não renova token (ADR-068).** Ele fala HTTP por fora do
cliente gerado, então um 401 no meio de um stream ainda aparece como erro na
conversa.

**Órfãos na fila de aprovações (ADR-065).** Um pedido pode envelhecer sem
dono. Falta expirar pendências antigas.

**A chave de assinatura em texto plano (ADR-070).** Coerente com o modelo de
ameaça de um Nó pessoal — quem tem a conta tem os dados —, mas deixa de ser
aceitável quando o Nó for exposto na rede (P4). Deve migrar para o cofre do SO.

**Migrar dados do Docker para o embutido.** Quem já usava a Lumbra tem os
dados no Postgres do compose; a versão instalada nasce vazia. É um `pg_dump`
seguido de `pg_restore`, e provavelmente merece virar `lumbra importar`.

**A prova do `montar.ps1` é mais fraca que a do `construir.ps1`.** Ela só bate
em `/health`, sem perguntar ao `doctor` se pgvector, migrações e índices estão
lá.

**Sem `describe`, a fila de aprovações volta ao texto genérico (ADR-066).** Não
há lint que force skills de risco a explicarem seu próprio pedido.

**`ADR-058` (ciclo de vida de agentes) segue 🚧** e o Learning Loop não tem
gatilho HTTP — `achieve()` é só em processo.

**Títulos de conversa repetidos.** Várias aparecem como "Conversa" na lista.

---

## 5. Depois do P2

| Épico | Escopo |
|---|---|
| **P3 — Sync + Android** | O mais difícil. Log de eventos com HLC, replicação na LAN, pareamento por QR, app Android. Entregável: anotar no celular e encontrar no desktop. |
| **P4 — Modo Pessoal** | O Nó alcançável de fora por overlay WireGuard, sem nuvem de terceiros. |
| **P5 — Proatividade** | Agenda e alarmes em linguagem natural, vencimentos de documentos, resumo diário. A Lumbra deixa de só responder. |
| **P6 — Cloud opcional + Web** | Relay E2E (servidor só vê ciphertext), cliente Web, Linux/macOS como canal oficial. |

Pendente da fase de agentes: **A10 (mobile)**, que depende do P3.

---

## 6. O que aprendi sobre como este projeto falha

Vale registrar, porque o padrão se repetiu quatro vezes em um dia e vai se
repetir de novo.

**Todos os erros graves se apresentaram como sucesso.** O `doctor` dizendo
"tudo pronto para usar" sobre o banco errado. O script de build anunciando
"Nó em dia" enquanto embalava a versão anterior. A verificação batendo em
`/health` e sendo respondida por um Nó que não era o dela. O app declarando o
Nó morto três segundos depois de o ter iniciado com êxito.

Erro que grita é barato. **Erro que elogia é caro** — ele consome a confiança
que se deposita na verificação, e a verificação é o único instrumento que
sobra quando a intuição falha.

**A verificação incompleta engana igual à ausente.** Cobrir `core/src` e
esquecer `core/packaging` deu a mesma confiança de cobrir tudo e não entregou
o mesmo.

**O log em arquivo pagou por si mesmo em uma hora.** Foi adicionado só para
não perder mensagens truncadas na tela; foi ele que revelou o `TimeoutExpired`
do `pg_ctl` — um traceback que, sem ele, teria morrido junto com o processo.
