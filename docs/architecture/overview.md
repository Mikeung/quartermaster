# Architecture Overview

## System Boundaries

```
┌─────────────────────────────────────────────┐
│              Quartermaster           │
│                                             │
│  ┌──────────┐   ┌──────────┐   ┌─────────┐ │
│  │ Scanners │──▶│  Memory  │──▶│ Reports │ │
│  └──────────┘   │  Store   │   └─────────┘ │
│                 │ (SQLite) │               │
│  ┌──────────┐   └──────────┘   ┌─────────┐ │
│  │ Topology │◀──────────────── │  LLM    │ │
│  │ Builder  │                  │ Intel.  │ │
│  └──────────┘                  └─────────┘ │
│                                             │
│  ┌──────────────────────────────────────┐   │
│  │         FastAPI HTTP Layer           │   │
│  └──────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
         │ observe only — never modify │
         ▼
   Target Infrastructure
   (repos, processes, containers)
```

## Data Flow

1. Scanners read target systems (never write)
2. Scan results stored in SQLite
3. Memory layer enables historical comparison
4. Topology builder constructs service maps
5. LLM Intelligence analyzes usage patterns
6. Reports layer generates recommendations
7. FastAPI exposes results via HTTP

## Advisory Boundary

All output is advisory. The system has no write path to any external system.
