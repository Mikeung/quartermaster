# Stack Decisions

## Backend
- **Python 3.11** — modern typing, performant, broad ecosystem
- **FastAPI** — async-capable, typed, minimal boilerplate
- **uvicorn** — ASGI server, production-grade

## Config
- **pydantic-settings** — type-safe .env parsing with no custom code

## Storage
- **SQLite** (initial) — zero-config, sufficient for Phase 0–2
- Migration path: PostgreSQL when multi-process writes or scale requires it

## Deployment
- **Docker Compose** — single-node VPS deployment target

## Logging
- **python-json-logger** — structured JSON logs, stdlib-compatible

## Code Quality
- **ruff** — lint + format (replaces black + isort + flake8)
- **mypy (strict)** — full type safety
- **pytest** — test runner

## Explicitly Rejected (with reasons)

| Tool         | Reason                                              |
|--------------|-----------------------------------------------------|
| Redis        | Not needed at this scale                            |
| Celery       | Over-engineered; cron + SQLite is sufficient        |
| LangGraph    | Out of scope; we observe LLM usage, not orchestrate |
| Kubernetes   | Not appropriate for VPS-first solo-dev operation    |
| Neo4j        | Deferred; topology can start as SQLite adjacency    |
| React/Next   | No frontend phase until Phase 5 minimum             |

## Future Consideration
- **PostgreSQL** — when multi-process writes needed
- **Neo4j** — for topology graphs in Phase 5
- **React Flow** — topology visualization in Phase 5
