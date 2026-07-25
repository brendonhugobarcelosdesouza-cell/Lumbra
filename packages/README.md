# packages/ — SDKs da Lumbra Platform

Bibliotecas reutilizáveis que falam a Platform API. Como tudo na plataforma,
elas consomem **apenas o contrato** (`core/contracts/platform-api-v1.json`) —
são a materialização, por linguagem, da única porta de entrada do Nó.

## `lumbra_api_dart/` — cliente Dart gerado (P1-d)

Gerado automaticamente do OpenAPI. É o que o cliente Flutter (`clients/app`)
importa para chamar o Nó com tipos e rotas garantidos pelo contrato. Nunca
editado à mão: regenera quando o contrato muda.

## Futuro: SDKs e plugins

Plugins (ADR-047) são processos externos que consomem a mesma Platform API,
autenticados pelo modelo de dispositivos (chave Ed25519 + escopos). Um SDK de
plugin — em Dart, Python ou outra linguagem — mora aqui quando existir,
seguindo o mesmo princípio: o contrato é a fronteira, o Core permanece livre
para refatorar por dentro.
