"""Track Evidence Set: model-neutral role selection, encoding and admission.

ADR-013 §4–§6; S1.2 implementation plan §4–§6. Everything here depends only on
MAVI-owned value types (frames, detections, Track candidates, the staging
store's typed interface) and on the ``EvidencePolicy`` built from the pipeline
profile. Nothing imports a detector or tracker backend.
"""
