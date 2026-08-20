# Lumbra Core — o engine da plataforma

O **Nó Lumbra**: o motor Python completo (kernel, Event Bus, AI Gateway,
Memory Engine, RAG, Knowledge Graph, identidade de dispositivos) e a
**Platform API** que todo cliente consome. É a única fonte de regra de
negócio da plataforma (docs/24, ADR-042).

## Desenvolvimento

**Rode sempre de dentro de `core/`.** A configuração do pytest — inclusive
`asyncio_mode = "auto"` — vive em `core/pyproject.toml`. Da raiz do monorepo o
pytest não a enxerga e reprova toda função `async def` com "async def functions
are not natively supported": duzentos testes vermelhos e nada quebrado.

```bash
cd core
pip install -e .[dev]                  # ou, da raiz: make install
pytest -m "not integration"            # testes rápidos
mypy                                   # tipos
ruff check . && ruff format --check .  # lint E formatação
python -m lumbra.api.contract          # regenera contracts/platform-api-v1.json
```

O `ruff format --check` não é opcional: o CI roda os **dois** comandos, e um
lint local que só roda o primeiro dá verde no seu terminal e vermelho no
`quality`. Foi o que aconteceu — o portão local era mais fraco que o portão
real, e o resultado foi um CI vermelho depois de oito commits.

O caminho curto e sem pegadinha é o `Makefile` da raiz, onde cada alvo já faz o
`cd` e já roda o par completo:

```bash
make lint       # ruff check + ruff format --check
make typecheck  # mypy
make test       # pytest -m "not integration"
make ci         # tudo que o CI roda
```

## Layout

- `src/lumbra/` — domínio, ports, adapters, kernel, API (hexagonal)
- `tests/` — unit, api, integration
- `contracts/` — o contrato OpenAPI versionado (a porta da plataforma)
- `alembic.ini` + migrações em `src/lumbra/adapters/persistence/migrations/`

Documentação e ADRs no `docs/` da raiz do monorepo.
