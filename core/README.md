# Lumbra Core — o engine da plataforma

O **Nó Lumbra**: o motor Python completo (kernel, Event Bus, AI Gateway,
Memory Engine, RAG, Knowledge Graph, identidade de dispositivos) e a
**Platform API** que todo cliente consome. É a única fonte de regra de
negócio da plataforma (docs/24, ADR-042).

## Desenvolvimento

```bash
cd core
pip install -e .[dev]     # ou, da raiz: make install
pytest -m "not integration"   # testes rápidos
mypy && ruff check .          # tipos + lint
python -m lumbra.api.contract # regenera core/contracts/platform-api-v1.json
```

Ou pela raiz do monorepo: `make test`, `make lint`, `make ci`.

## Layout

- `src/lumbra/` — domínio, ports, adapters, kernel, API (hexagonal)
- `tests/` — unit, api, integration
- `contracts/` — o contrato OpenAPI versionado (a porta da plataforma)
- `alembic.ini` + migrações em `src/lumbra/adapters/persistence/migrations/`

Documentação e ADRs no `docs/` da raiz do monorepo.
