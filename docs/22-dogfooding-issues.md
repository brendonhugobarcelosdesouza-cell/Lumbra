# Backlog de dogfooding

Registro dos problemas encontrados durante o uso real da plataforma. Cada
item nasce de um cenário concreto, não de hipótese — é exatamente o que a
inversão de levas (DX e dogfooding antes de otimização) pretendia gerar.

Estado: ✅ resolvido · 🔧 em andamento · 📋 registrado (a priorizar)

## Formato do registro (fase de dogfooding intensivo)

A partir da fase de dogfooding intensivo, cada problema é registrado com
seis campos, para permitir priorização por impacto e frequência, não por
ordem de descoberta:

```
### [estado] #N — <título curto>
- **Descrição:** o que acontece, no cenário concreto em que apareceu.
- **Impacto para o usuário:** o que ele não consegue fazer, ou faz errado.
- **Frequência:** sempre / frequente / ocasional / raro — e em que situação.
- **Causa provável:** hipótese técnica (confirmar antes de corrigir).
- **Prioridade:** alta / média / baixa (impacto × frequência).
- **Solução sugerida:** caminho de correção, sem comprometer-se cedo demais.
```

Prioridade é derivada, não opinião: alta = impacto alto E frequência alta;
baixa = um dos dois baixo. Todo problema entra aqui antes de virar código —
a correção começa por confirmar a causa provável, nunca por adivinhá-la.

---

## Sessão 1 — 21/07/2026: primeira indexação e busca

Corpus de teste: 6 arquivos numa pasta (2 TXT, 3 PDF, 1 PNG). Resultado
da indexação: 4 `indexed`, 2 `failed` (esperado).

### ✅ #1 — `lumbra doctor`/`init` quebravam no Windows
`check_docker` chamava `create_subprocess_exec` sem `stdin`, gerando
`NotImplementedError` no event loop do Windows. Corrigido: `stdin=DEVNULL`
+ tratamento de exceção. (commit `5f33116`)

### ✅ #2 — Wizard `init` estourava com `KeyError: 'providers'`
Resposta de `/chat/providers` sem tratamento quando não-200. Corrigido:
degrada com aviso em vez de crashar. (commit `0e6994a`)

### ✅ #3 — `/indexar` no chat.ps1 não existia / endpoint errado
O comando não estava registrado, e o caminho usado
(`/dev/skills/.../execute`) não existe. Corrigido: endpoint
`/dev/executions` (assíncrono, com polling do resultado); status e output
vêm aninhados em `execution`. (commits `b663b87`, `6f56e35`)

### ✅ #4 — Uma pergunta ampla só citava um documento
**Sintoma:** "O que tem nos documentos?" trazia 5 trechos, todos do PDF
mais longo, como se os outros 3 documentos não existissem.
**Diagnóstico:** a busca estava correta — buscar "salario" trazia o
`SALARIO.txt` em 1º (similaridade 0,655), com dindin, Projeto e Fatura
logo abaixo. O problema era no `DocumentContextProvider`: pegava os 5
trechos globalmente mais relevantes, sem teto por documento; numa
pergunta genérica, um documento longo levava todas as vagas.
**Correção:** sobrebusca (4× as vagas) + `_diversify` com teto de 2
trechos por documento, afrouxado em rodadas só se faltar material.
Variedade quando há de onde escolher; relevância pura quando não há.
Travado por `tests/unit/test_context_providers.py`. (este commit)

### 📋 #5 — Busca léxica não normaliza acento e maiúscula
Buscar "salario" (sem acento) deu "sem casamento de termos" no componente
léxico, mesmo o documento contendo "SALÁRIO" literalmente. Só o vetorial
salvou o recall. Impacto: recall pior em consultas exatas com acento —
comum em PT-BR. Correção provável: normalizar (casefold + remoção de
diacríticos) na indexação e na consulta do índice léxico (GIN).
Prioridade: média.

### ✅ #6 — Extração de PDF de layout complexo vira lixo vertical
A `Fatura_Itau_*.pdf` foi extraída caractere-a-caractere na vertical
(`1\nL\nanç\na\nm\nent\no\ns`). `pypdf.extract_text()` não lida bem com o
layout de duas colunas de fatura de cartão. Os chunks resultantes eram
quase inúteis — e o modelo respondia valores de fatura errados a partir
desse ruído (confirmado no uso: "valor total R$ 105,30", incorreto).
**Correção:** `_pdf_text` agora mede a legibilidade do texto (fração de
tokens que são palavras de 3+ letras) e, quando o pypdf fragmenta,
tenta o `pdfplumber` (extração ciente de layout), ficando com o melhor
dos dois — nunca com o pior. Degrada para pypdf se o pdfplumber não
estiver instalado. Travado por `tests/unit/test_extract_stage.py`.
**Ação do usuário:** reinstalar deps (`pip install -e .`) e **reindexar
forçado** (ver #7) para reextrair — reindexar normal não bastava.

### ✅ #7 — Reindexar não reprocessava arquivos de conteúdo inalterado
Consequência direta do #6: depois de corrigir a extração, rodar
`/indexar` de novo reportava "0 indexado, 6 inalterado" e mantinha os
chunks velhos (lixo). A indexação pula arquivos cujo hash não mudou — o
que é certo para o caso comum, mas errado quando a *máquina* muda (novo
extrator, chunker ou modelo de embedding): o arquivo é o mesmo, mas o
que se extrai dele não é. **Correção:** parâmetro `force` em
`document.index` reprocessa mesmo os inalterados (sem criar versão nova,
pois o conteúdo não mudou); novo comando `/reindexar <pasta>` no
chat.ps1. Travado por `test_force_reprocessa_arquivo_inalterado`.

### Observações que NÃO são bug
- **Acentos "corrompidos" no PowerShell** (`SALÃRIO`, `lÃ©xico`): é o
  PowerShell 5.1 exibindo JSON UTF-8 como Latin-1. Os dados armazenados
  estão corretos — o chat.ps1 (StreamReader UTF-8) renderiza certo.
- **image.png e LANGRAPH.txt (0 KB) como `failed`**: correto. Imagem sem
  OCR não vira texto; arquivo vazio não gera chunk. O estado `failed` com
  motivo é o comportamento esperado.

---

### 🔧 #8 — Fatura de cartão: extração melhorou, mas modelo 7B erra o total
Depois do #6/#7, a extração da fatura do Itaú ficou **legível** — o valor
correto ("Total desta fatura 7.016,60") aparece claramente no texto. Mas
duas coisas ainda atrapalham:
- **Palavras coladas:** o pdfplumber padrão gruda termos
  (`Totaldestafatura`). **Correção parcial:** `_legibilidade` agora
  penaliza os DOIS extremos (fragmentação *e* colagem) e ignora números;
  `_pdf_text` testa também a variante `layout=True` do pdfplumber, que
  separa melhor, e fica com a de maior legibilidade.
- **O modelo local (qwen2.5:7b) se perde:** a fatura tem vários "totais"
  (anterior 6.791,07, desta fatura 7.016,60, a pagar 7.308,03) e dezenas
  de transações. O modelo respondeu R$ 17.333,11 — número que **nem
  existe** no documento (alucinação típica de modelo pequeno sob tabela
  numérica densa).
**Resolvido de vez (extração):** o `layout=True` não separou as palavras
coladas desta fatura. Medimos 9 modos de extração NO PDF REAL (script
`scripts/diag_extract.py`) e o vencedor foi claro: `pdfplumber` com
`x_tolerance=1.5` (legibilidade 0.904, `Total da fatura anterior 6.791,07`)
contra 0.607 do padrão (`Totaldafaturaanterior`). `_pdfplumber_variants`
agora inclui essa tolerância, e o limiar subiu para 0.85 (prosa normal
pontua ~0.9; financeiro colado, 0.4–0.7, merece a segunda tentativa).
Isso conserta a colagem, e por tabela deve reanimar a busca léxica (#5) e
fazer o trecho-resumo ranquear melhor (#9). **Ação do usuário:** reiniciar
e `/reindexar` para reextrair com a tolerância nova.

**Ainda aberto (modelo):** mesmo com extração boa, um 7B erra extração
numérica precisa em documento financeiro denso. O modelo de nuvem (Claude)
se comporta com segurança (não alucina). Configurável via
`LUMBRA_AI__ANTHROPIC_API_KEY` + `/usar anthropic`.

### ✅ #9 — Teto de diversidade cortava o trecho certo de documento denso
O teste decisivo: com o modelo de nuvem (Claude) configurado, ele **também**
não achou o total — mas, em vez de alucinar como o 7B, foi honesto: "só
vejo lançamentos individuais, não o resumo". Isso **provou que o gargalo
era recuperação, não o modelo**. A busca direcionada confirmou: o trecho
do resumo ("Lançamentos atuais 7.016,60") **existe e ranqueia em #3** na
fatura — mas o teto de 2 trechos por documento (criado no #4) o cortava
quando outros documentos competiam por vaga. **Correção:** orçamento de
documentos de 5→8 e teto por documento de 2→3, dando fôlego ao documento
dominante numa pergunta focada sem sufocar a diversidade nas amplas.
Travado por `test_trecho_certo_de_documento_denso_entra`.
**Aprendizado de segurança:** o 7B alucinou um número plausível (17.333,11
— que era o "total para próximas faturas", real mas errado); o Claude
admitiu não saber. Num assistente financeiro, modelo que não inventa vale
mais que modelo que arrisca. Documenta o valor de rotear consultas de
precisão para modelos melhores.

### 📋 #5 (revisado) — Busca léxica morta em PDF financeiro
A busca na fatura mostrou "sem casamento de termos" em TODOS os trechos: as
palavras coladas + acentos zeram o componente léxico, e tudo depende do
vetorial. Reforça a prioridade de normalizar (casefold + diacríticos) e de
resolver a colagem na extração (o `layout=True` do #8 não separou ESTE
PDF). Enquanto o léxico estiver morto, buscas por termo exato ("total",
"7.016,60") não recebem o reforço que deveriam.

### ✅ #10 — Chunking parte o bloco-resumo da fatura
Com a extração corrigida (#8), o Claude passou a ler corretamente "Total
da fatura anterior 6.791,07" — mas ainda não o total ATUAL (7.016,60). A
busca mostrou por quê: o chunk do resumo corta em "...Saldo financiado
0,00 L Lançame[ntos atuais 7.016,60]", separando o valor atual do seu
rótulo. O chunker (`basic.py`, 1600 chars, split por linha em branco) não
tem fronteira semântica: numa fatura sem linhas em branco entre itens, ele
corta no meio do resumo.

**Resolvido (ADR-051).** Escolhido o caminho "chunking ciente de estrutura":
a extração passou a preservar blocos tipados (tabelas, cabeçalhos) e o
chunker faz de cada linha de tabela uma unidade autodescritiva, com a seção
e o cabeçalho junto do valor. Nada de overlap nem chunk maior nem regra de
"total". O golden set ponta a ponta (`tests/rag/golden.json` → `answer_cases`)
trava a correção no CI, provando que a fatura é recuperada nos DOIS sentidos
("total desta fatura" → 7.016,60 e "total financiado" → 6.314,94) — logo não
é viés à palavra "total".

### ✅ #5 — Busca léxica ressuscitada (query tolerante, OR em vez de AND)
Depois da extração corrigida, um teste de termo único ("fatura") no dado
real mostrou que o léxico FUNCIONA — casava "fatura/faturas/faturamento"
com stemming português. O que matava era a semântica: `websearch_to_tsquery`
une os termos com **AND**, exigindo TODOS. "total desta fatura" falhava
porque "desta" não estava no documento, mesmo com "total" e "fatura"
presentes. **Correção:** `_tsquery_or` extrai as palavras e as une por
`|` (OR), passando por `to_tsquery('portuguese', ...)` — qualquer termo
conta, o ts_rank ordena por quantos casam. É o comportamento certo para
recuperação. Golden set de RAG revalidado (sem regressão); 5 testes novos
sobre a construção da query. Aplicado só ao search de documentos — a busca
de memória tem o mesmo AND, mas seu recall foi calibrado com cuidado, então
fica como mudança separada e testada à parte.

### 📋 #5b — Aplicar a mesma tolerância à busca de memória
`memory/postgres.py` ainda usa `websearch_to_tsquery` (AND). Mesma
correção, mas exige recalibrar/revalidar `test_memory_recall.py` para não
mexer no recall afinado. Prioridade: média.

### (histórico) #5 original — Índice léxico não casa termos
Mesmo DEPOIS da extração corrigida (palavras separadas), a busca ainda
reporta "léxico: sem casamento de termos" para a query "total desta
fatura" contra um documento que contém "Total da fatura anterior". Ou
seja, não é mais a colagem — é o índice de texto (tsvector) em si:
provavelmente configuração de idioma/acento errada, ou exigência de todos
os termos. Toda a recuperação hoje depende só do vetorial; ressuscitar o
léxico daria um reforço grande a buscas por termo exato (valores, nomes,
datas). Prioridade: alta — Leva 2.

### ✅ #13 — Wizard (`lumbra init`) indexava por endpoint inexistente

**Sintoma (achado rodando o app):** `lumbra init` falhava na etapa de
indexação com `{"detail":"Not Found"}` (404). O wizard chamava
`/api/v1/dev/skills/document.index/execute` — endpoint que não existe;
o certo é `POST /api/v1/dev/executions` (kind/name/payload), que é
ASSÍNCRONO (devolve execution_id, consulta-se depois).
**Correção:** wizard posta em `/dev/executions` e faz polling em
`/dev/executions/{id}` até `completed`/`failed`, reportando
discovered/queued. Bug de contrato desalinhado que só apareceu no
primeiro uso real do onboarding.

### ✅ #12 — Superfície da API depende do adaptador de persistência

**Sintoma (achado no P1-a):** os routers de chat e memória (e o Developer
Console) só são montados quando `persistence=postgres` — um Nó em modo
memória simplesmente não tem `/api/v1/chat` nem `/api/v1/memory`.
**Por que é defeito:** viola a Regra 1 da plataforma (docs/24): o contrato
é a única porta, e um cliente contra um Nó em modo memória veria uma API
diferente. O contrato (contracts/platform-api-v1.json) foi gerado na
configuração completa justamente para não consagrar a superfície mutilada.
**Correção proposta:** routers sempre montados; quando o store subjacente
não existe, a rota responde 501/503 com mensagem estilo doctor. Entra no
P1-b (que já mexe na composição do app para o modelo de dispositivos).
**Estado:** RESOLVIDO no P1-b.1. Stores in-memory para memória/conversas/
anexos fazem o chat e a memória funcionarem sem Postgres; o Developer
Console saiu do contrato público (include_in_schema=False). Travado pelo
teste `test_contrato_independe_do_adaptador`, que gera o schema nos dois
modos e exige igualdade.

### ✅ #11 — Guardrail contra chute em valores ambíguos (segurança)
Achado mais importante da saga da fatura, e não é sobre a fatura: ao
melhorar a recuperação, o Claude passou de honesto ("não sei o total") para
**confiantemente errado** (afirmou R$ 13.309,37, que é "Demais faturas").
Trazer mais trechos com "total" ao contexto, sem desambiguar, fez um modelo
bom arriscar. **Correção:** regra no `SYSTEM_PROMPT` — quando a pergunta
pede UM valor e o contexto tem vários candidatos parecidos (comum em
documento financeiro), apresentar os candidatos rotulados e citados e pedir
confirmação, em vez de escolher no chute. Geral (vale para todo documento),
barato, e restaura o comportamento seguro. Travado por
`TestSystemPrompt.test_guardrail_de_valores_ambiguos`.

**Fortalecido por evidência (ADR-052).** Com o #10 resolvido, os candidatos
chegam ao contexto ROTULADOS (seção + linha de tabela). O guardrail passou a
apoiar-se nesses rótulos como critério: se o rótulo bate com a pergunta,
responde e cita; se não, apresenta os candidatos com o rótulo exato e a
citação de cada um. É evidência-dirigido, não um grau de confiança inventado.
Travado também por `test_guardrail_ancora_na_evidencia_rotulada`.

**Nota sobre a fatura:** o #10 foi resolvido — o trecho "Total desta fatura
7.016,60" agora É recuperado para a pergunta natural (provado no golden set).
O guardrail deixa de ser rede para o erro e passa a operar sobre evidência
que a estrutura tornou separável.

## A fazer antes da Leva 2
Priorizar #5 e #6 conforme o quanto atrapalharem o uso diário. Ambos
afetam qualidade de recall, que é o coração da plataforma — mas só o uso
continuado dirá se são incômodos frequentes ou casos de borda.

## Entregue nesta leva (RAG + contrato + UX)

* **#10 (chunking ciente de estrutura) — ✅** ADR-051. Extração estruturada
  (blocos tipados) + chunker que faz de cada linha de tabela uma unidade
  autodescritiva. Provado no golden set (`answer_cases`), a fatura
  recuperada nos dois sentidos.
* **#11 (guardrail) — ✅ fortalecido** ADR-052. Agora dirigido pela
  evidência rotulada que a estrutura coloca no contexto, não por confiança
  inventada.
* **Contrato (API First) — ✅** anexos, cancelamento e memória tipados
  (fim do mapa livre que quebrava o cliente Dart). Dev-console tipada nas
  rotas estáveis; segue fora do contrato versionado (P1-b.1).
* **UX do chat — ✅** Markdown na resposta, chips só das fontes citadas,
  título automático na primeira pergunta.

## Evoluções registradas (não bloqueiam)

* Levar o `section_path` também à prosa do bloco de CONTEXTO (hoje só as
  tabelas rotulam explícito; a prosa carrega a seção no metadado, mas não
  renderizada) — se o dogfooding mostrar ambiguidade fora de tabelas.
* Reindexação em lote dos documentos já indexados, para preencherem os
  blocos e o metadado estrutural novos (chunks legados coexistem nulos,
  tratados como sem seção — sem regressão, mas sem o ganho até reindexar).
* Fixar o `pubspec.lock` do app com o `flutter_markdown` resolvido, para
  build reprodutível (o CI resolve, mas o lock versionado fica em dia).
