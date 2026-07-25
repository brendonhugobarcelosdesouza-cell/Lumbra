# lumbra_api_dart — cliente Dart gerado da Platform API

Cliente Dart/Flutter da Lumbra Platform, **gerado** do contrato OpenAPI
(`core/contracts/platform-api-v1.json`) — nunca escrito à mão. É o que o
cliente Flutter (`clients/app`) importa para falar com o Nó com rotas e
tipos garantidos pelo contrato.

## Gerar

```bash
packages/lumbra_api_dart/generate.sh    # requer Node (npx) + Java 11+
```

O pacote Dart inteiro é escrito em `generated/` (pubspec.yaml, lib/, doc/),
**ignorado pelo git**. Os arquivos autorais (`generate.sh`, este README,
`.gitignore`) ficam de fora e nunca são sobrescritos.

## Por que não commitar o gerado

Mesma filosofia do snapshot do contrato (P1-a): a fonte é o contrato; o
cliente é uma projeção determinística dele. Versionar a projeção só criaria
uma cópia que pode divergir. O que garante a corretude é o pipeline
reproduzível (versão do gerador fixada) + o gate de compilação no CI
(`dart analyze`), não bytes congelados no repo.
