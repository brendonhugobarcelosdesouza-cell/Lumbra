.PHONY: install lint format typecheck test test-cov ci up down contract

# O engine Python vive em core/; os alvos de código rodam lá. A infra
# (docker compose) orquestra o monorepo e roda da raiz.
CORE = core

install:            ## instala dependências de dev
	cd $(CORE) && pip install -e .[dev]

lint:               ## ruff (lint + formato)
	cd $(CORE) && ruff check . && ruff format --check .

format:             ## aplica formatação
	cd $(CORE) && ruff check --fix . && ruff format .

typecheck:          ## mypy strict
	cd $(CORE) && mypy

test:               ## testes rápidos (sem integração)
	cd $(CORE) && pytest -m "not integration"

test-cov:           ## suíte completa com gate de cobertura
	cd $(CORE) && pytest --cov --cov-report=term-missing

contract:           ## regenera o contrato OpenAPI (core/contracts/)
	cd $(CORE) && python -m lumbra.api.contract

ci: lint typecheck test-cov   ## tudo que o CI roda

up:                 ## sobe PG+Redis+API
	docker compose up -d --build

down:               ## derruba e mantém volumes
	docker compose down
