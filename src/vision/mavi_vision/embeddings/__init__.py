"""The ``embeddings`` role: SigLIP 2 appearance embeddings over sealed Track evidence (PoC S4; ADR-021).

A post-Track role (ADR-013 §8–§12) on the ``mavi-embedding-control-v1`` plane. It is its own process and
failure domain: accepted evidence is read only through the lease-scoped evidence endpoint and verified by size
and SHA-256 before decoding, and the only output is the completion body (no sealed artefact, ADR-021 §3).
A second, concurrent loop serves appearance text queries from the same Model Pack.

Development only: the role refuses production mode, and its Model Pack is ``unverified`` (ADR-020).

Import boundary: nothing in this package may import torch, torchvision, mmcv, mmdet or mmengine, directly or
through another ``mavi_vision`` module; ``onnxruntime`` and ``sentencepiece`` are imported lazily by the ONNX
adapter only, so the contracts, runner and fixture model run without them.
``tests/test_embedding_import_boundary.py`` enforces it.
"""
