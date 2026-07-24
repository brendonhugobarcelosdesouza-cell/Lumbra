# Operações canceláveis

Toda operação longa da Lumbra usa o MESMO mecanismo de cancelamento
(ADR-032). Este guia é o que você precisa saber para escrever a próxima —
indexação, OCR, embeddings em lote, busca longa, agente, automação ou
sincronização.

## A regra

Se a sua operação pode demorar mais de um segundo, ela precisa ser
cancelável. Não invente um mecanismo próprio: receba o token e coopere.

## Numa skill

```python
async def indexar(payload: SkillInput, ctx: SkillContext) -> SkillOutput:
    token = ctx.cancellation  # pode ser None

    for i, arquivo in enumerate(arquivos):
        if token:
            token.raise_if_cancelled()  # ponto de verificação
        await processar(arquivo)
        if token:
            token.step(f"{i + 1}/{len(arquivos)} arquivos")  # progresso
```

Duas linhas por laço. `raise_if_cancelled()` interrompe entre etapas;
`step()` registra o que já ficou pronto — é isso que aparece no console e
na explicação quando alguém cancela.

## Chamando IA

```python
resultado = await gateway.chat(request, cancellation=ctx.cancellation)

async for evento in gateway.chat_stream(request, cancellation=ctx.cancellation):
    ...
```

Cancelar fecha a conexão com o provedor: o Ollama **para de gerar** e
libera a GPU. Não passar o token faz a chamada virar um ponto cego —
o usuário cancela e a GPU continua ocupada.

## Envolvendo qualquer coisa demorada

```python
dados = await token.guard(baixar_arquivo(url))  # uma chamada
async for linha in token.guard_stream(ler_stream()):  # um fluxo
    ...
```

`guard_stream` chama `aclose()` na fonte ao cancelar, então conexões e
arquivos fecham na hora, sem esperar coletor de lixo.

## Escopos aninhados

```python
token = ctx.cancellation or kernel.cancellation
etapa = token.child("ocr")  # cancelar o pai cancela o filho
```

O token do kernel é cancelado no desligamento — herdar dele garante que
nada sobrevive ao processo.

## Prazo

```python
tracker.start_skill("document.index", payload, subject=..., user_id=..., timeout_seconds=300)
```

Timeout vira um cancelamento com motivo próprio, e o estado final é
`timeout` — distinguível de alguém que desistiu.

## O que NÃO fazer

* Não use `asyncio.Task.cancel()` direto: mata o handler sem deixá-lo
  salvar o parcial nem explicar o que aconteceu.
* Não trate cancelamento como erro. `OperationCancelledError` não deve
  incrementar métrica de falha nem virar alerta.
* Não descarte trabalho parcial. Se metade dos documentos foi indexada,
  isso vale — registre e informe.
* Não confie só na cooperação para segurança: o `ExecutionTracker` força
  a interrupção após o prazo de cortesia, mas escritas em várias tabelas
  devem estar em transação para não ficarem pela metade.

## Estados finais

| Estado | Significado | É falha? |
|---|---|---|
| `completed` | terminou o trabalho | não |
| `cancelled` | alguém pediu para parar | **não** |
| `timeout` | estourou o prazo | **não** |
| `failed` | quebrou | sim |
