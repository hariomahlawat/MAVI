# ADR-002: Modular Monolith with Independent AI Workers

**Status:** Accepted  
**Date:** 2026-09-08

## Decision

Begin with one modular ASP.NET Core operational application and independently deployable Python AI workers. Do not start with full microservices.

## Rationale

A five-person or agentic PoC team needs low coordination overhead while the domain model is still evolving. GPU/video workloads have fundamentally different scaling and runtime requirements, so the AI worker is separated from Day 1.

## Consequence

Operational modules communicate in-process initially. High-load boundaries can be extracted later only when measurements justify doing so. Worker job/result contracts must remain transport-neutral enough to move from HTTP polling to durable messaging later.
