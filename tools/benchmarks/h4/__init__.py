"""Stage-3 H4 domain-diversity campaign tooling: arm completion receipts and the paired 640 -> 1280 comparison.

H4 compares two frozen Development producers (``a2-scale640``, ``a2-scale1280``; ADR-014 2026-10-06 note) on the
same prepared benchmark footage. Execution itself is the ordinary harness (``tools.benchmarks.cli execute`` with
``--development-producer``); this package only checkpoints what an arm produced and compares two arms afterwards,
from retained bytes, never re-running inference.
"""
