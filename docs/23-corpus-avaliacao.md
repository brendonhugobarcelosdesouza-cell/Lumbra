# 23 — Corpus de Avaliação

O principal benchmark de qualidade do RAG da Lumbra. Enquanto o
[golden set](../tests/rag/golden.json) mede **recuperação** (a busca traz o
documento certo?), o Corpus de Avaliação mede a **resposta ponta a ponta**
(o assistente responde certo, com a citação certa?) sobre documentos reais
de várias categorias.

O corpus nasce do dogfooding intensivo e cresce continuamente. Cada
documento que expõe uma limitação vira um caso permanente — a fatura do
Itaú é o primeiro, mas não o único: a evolução do chunking (#10) só será
retomada quando o corpus for representativo, para projetar uma solução
**geral**, não afinada a um único documento.

## Categorias

O corpus busca cobrir a diversidade real de um acervo pessoal e
profissional:

| Categoria | Desafio típico de RAG |
|---|---|
| Documentos financeiros | muitos valores parecidos ("vários totais"), tabelas densas, layout adversarial |
| Normas e legislações | estrutura hierárquica (artigos, incisos), referências cruzadas |
| Documentos técnicos | jargão, diagramas, tabelas, versões |
| REDS (registros/relatórios) | campos estruturados, terminologia específica |
| PDFs digitalizados | camada de texto ausente ou suja → OCR |
| Imagens com OCR | texto em imagem, qualidade variável |
| Planilhas | dados tabulares, relações entre células, fórmulas |
| Markdown | estrutura por cabeçalhos, listas, código inline |
| Código-fonte | blocos por função/classe, símbolos, comentários |
| Documentos pessoais | linguagem informal, dados sensíveis (privacidade) |

## Formato de um caso

Cada documento do corpus é cadastrado com metadados e um conjunto de
perguntas de referência com respostas esperadas:

```json
{
  "id": "fatura-itau-2026-05",
  "categoria": "financeiro",
  "arquivo": "corpus/financeiro/fatura_sintetica_01.pdf",
  "origem": "sintetico",
  "descricao": "Fatura de cartão com vários 'totais' (anterior, desta fatura, a pagar, próximas)",
  "perguntas": [
    {
      "pergunta": "Qual o valor total desta fatura?",
      "resposta_esperada": "R$ 7.016,60",
      "tipo": "valor_exato",
      "fonte_esperada": "fatura_sintetica_01.pdf",
      "armadilha": "não confundir com 'total a pagar', 'anterior' ou 'próximas faturas'"
    }
  ]
}
```

Campos: `tipo` classifica a pergunta (`valor_exato`, `fato`, `resumo`,
`lista`, `nao_tem` — quando a resposta correta é "não está nos
documentos"); `armadilha` documenta o erro comum, para o caso virar
regressão explícita; `origem` distingue documento real de sintético.

## Privacidade — regra inegociável

O corpus é **versionado no Git**. Documentos reais com dados pessoais ou
sensíveis (financeiros, jurídicos, de saúde) **nunca** entram como estão.
Para cada caso real que exponha um problema, cria-se uma versão
**sintética** que reproduz o mesmo desafio estrutural (mesmo layout, mesma
"armadilha") com dados fictícios. A fatura do Itaú, por exemplo, entra no
corpus como uma fatura sintética que preserva o problema dos seis totais,
sem um único número real. `origem: "real"` só para documentos que já são
públicos ou explicitamente não sensíveis.

## Ligação com o golden set

O corpus alimenta o golden set continuamente:

* As **perguntas de recuperação** (qual documento?) viram entradas em
  `tests/rag/golden.json`, medidas por recall@k e MRR no CI.
* As **perguntas de resposta** (qual valor/fato?) formam uma suíte de
  avaliação ponta a ponta — com o modelo local para regressão determinística
  onde possível, e como referência manual onde a resposta depende do modelo.
* A fatura permanece como **benchmark permanente**: qualquer melhoria de
  chunking ou extração deve resolvê-la **sem degradar** os demais casos.

## Como um caso entra no corpus

1. Um documento real, no dogfooding, expõe uma limitação (registrada no
   [backlog](22-dogfooding-issues.md)).
2. Cria-se a versão sintética que preserva o desafio, sem dado sensível.
3. Cadastram-se as perguntas de referência com respostas esperadas e a
   armadilha.
4. As perguntas de recuperação vão para o golden set do CI.
5. O caso passa a ser critério permanente: nenhuma evolução pode regredi-lo.
