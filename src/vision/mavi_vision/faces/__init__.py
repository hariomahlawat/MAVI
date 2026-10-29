"""The ``faces`` role: YuNet face detection and face embeddings over sealed Person evidence (PoC S6; ADR-022).

A post-Track role (ADR-013 §8–§12) on the ``mavi-face-control-v1`` plane, built like the ``embeddings`` role
(ADR-021 §3). It is its own process and failure domain: accepted evidence is read only through the lease-scoped
evidence endpoint and verified by size and SHA-256 before decoding, and the only outputs are the completion body
and, for a transient query image, its faces. Every result is a *candidate*, never identity (ADR-022 §1); the
platform owns matching, storage, retention and audit.

Development only: the role refuses production mode, and its Model Pack is ``unverified`` (ADR-020, ADR-022 §9).

Import boundary: nothing in this package may import torch, torchvision, mmcv, mmdet or mmengine, directly or
through another ``mavi_vision`` module; ``onnxruntime`` is imported lazily by the ONNX adapter only, so the
contracts, runner and fixture model run without it.
"""
