"""The MAVI benchmark harness (Stage 3 S3.2d-1; ADR-017 §11).

A reusable, deterministic harness that evaluates a MAVI capability against an existing labelled research
dataset: a shared envelope for identity and provenance (``core``), dataset adapters (``datasets``), and
capability-specific ground truth, association and evaluation (``capabilities``, from later slices).

Implementation plan: ``docs/superpowers/plans/2026-10-04-stage3-s3-2d-benchmark-harness.md``. Every result is
Development or reference evidence (ADR-017 §8–§9), never qualification.
"""
