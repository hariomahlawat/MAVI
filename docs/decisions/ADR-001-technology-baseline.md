# ADR-001: Technology Baseline

**Status:** Accepted  
**Date:** 2026-09-08

## Decision

Use C#/.NET 10 for the operational platform, React + TypeScript for the operator UI, Python for computer vision/AI, and PostgreSQL + pgvector as the initial authoritative datastore.

## Rationale

The stack separates long-lived operational workflows from the rapidly changing ML ecosystem while retaining a strong typed backend and a highly interactive browser UI. It also supports fully local deployment.

## Consequence

Cross-language boundaries must be explicit and versioned. Model-specific Python libraries must not leak into the operational domain.
