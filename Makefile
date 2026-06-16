.PHONY: install dev test lint fmt typecheck clean docker-up docker-down docker-build

install:
	pip install -e ".[dev]"

dev:
	uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

test:
	pytest tests/ -v

lint:
	ruff check .

fmt:
	ruff format .

typecheck:
	mypy backend/ scanners/ memory/ topology/ llm_intelligence/ observability/

check: lint typecheck test

docker-build:
	docker compose build

docker-up:
	docker compose up

docker-down:
	docker compose down

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
