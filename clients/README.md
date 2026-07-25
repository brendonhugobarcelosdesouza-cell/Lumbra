# clients/ — interfaces da Lumbra Platform

Todo cliente aqui consome **exclusivamente a Platform API** (`core/contracts/platform-api-v1.json`).
Nenhum cliente lê banco, arquivos ou filas do Nó diretamente — essa é a
Regra 1 da plataforma (docs/24). Se um cliente precisa de um dado que a API
não expõe, a resposta é evoluir o contrato, nunca abrir um atalho.

## `app/` — o cliente Flutter único

Um **único** código Flutter/Dart compila para as seis plataformas-alvo:
Windows, Linux, macOS, Android, iPhone e Web (ADR-043). Não há projetos
separados por plataforma — a paridade de recursos entre dispositivos é o
padrão, não um esforço. As diferenças por dispositivo (câmera no celular,
IA local no desktop) são capacidades, não aplicativos distintos.

O cliente Dart da API é **gerado** a partir do OpenAPI (P1-d), consumido de
`packages/`. O app nunca escreve requisições HTTP à mão.

Estado: scaffolding a partir do P2.
