"""The ``plates`` role: plate detection and OCR over sealed Track evidence (Stage 4).

ADR-013 §8–§13 and its implementation amendment 2026-10-13 (items 11–15); Stage 4 plan §2, §5. This
package is its own process and failure domain. It never touches a platform filesystem: accepted
evidence is read, and the ``PlatePredictions`` artefact uploaded, only through lease-scoped endpoints.

Import boundary: nothing in this package may import torch, torchvision, mmcv, mmdet or mmengine,
directly or through another ``mavi_vision`` module, because the role runs from its own Runtime Pack
family (ADR-013 item 10). ``tests/test_plate_import_boundary.py`` enforces it.
"""
