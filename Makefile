.PHONY: install lint format typecheck test test-cov ci up down

install:            ## instala dependências de dev
	pip install -e .[dev]

lint:               ## ruff (lint + formato)
	ruff check .
	ruff format --check .

format:             ## aplica formatação
	ruff check --fix .
	ruff format .

typecheck:          ## mypy strict
	mypy

test:               ## testes rápidos (sem integração)
	pytest -m "not integration"

test-cov:           ## testes com gate de cobertura (85%)
	pytest --cov --cov-report=term-missing -m "not integration"

ci: lint typecheck test-cov   ## tudo que o CI roda

up:                 ## sobe PG+Redis+API
	docker compose up -d --build

down:               ## derruba e mantém volumes
	docker compose down
