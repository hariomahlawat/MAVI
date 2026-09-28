"""The ``attributes`` role: Visual Attribute analysis through the platform's lease plane.

ADR-013 §8–§13; Stage 2 S2b plan. This package is its own process and failure domain. It
never touches a platform filesystem: accepted evidence is read, and the prediction artefact
uploaded, only through lease-scoped HTTP endpoints.
"""
