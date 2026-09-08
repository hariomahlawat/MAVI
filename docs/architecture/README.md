# MAVI Architecture Index

The approved architectural baseline is defined in `docs/superpowers/specs/2026-09-08-mavi-repository-architecture-design.md`.

## Core boundaries

1. **Operator plane:** React/TypeScript.
2. **Operational plane:** ASP.NET Core modular monolith.
3. **Vision plane:** independently deployable Python AI workers.
4. **Data plane:** PostgreSQL + pgvector and abstracted media storage.
5. **Integration plane:** explicit, versioned contracts between operational and vision components.

## Current maturity

This repository bootstrap intentionally implements only health/shell behavior and architecture contracts. CCTV ingestion, PostgreSQL integration, pgvector, model selection, tracking, ReID, ANPR, mission rules and investigation workflows belong to subsequent specifications.
