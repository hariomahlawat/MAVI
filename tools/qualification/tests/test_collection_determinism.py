"""The qualification CI lanes shard this suite by test: each shard collects it
and keeps the tests whose collection index falls in its slice. That is a
partition only if every shard's process collects the same node ids in the
same order, so collection must not depend on hash randomisation (for example
``parametrize`` over a ``set``)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def _collect(seed: str) -> list[str]:
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", "tools/qualification/tests"],
        cwd=REPO,
        env={**os.environ, "PYTHONHASHSEED": seed},
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in completed.stdout.splitlines() if "::" in line]


def test_collection_order_does_not_depend_on_hash_randomisation() -> None:
    first, second = _collect("1"), _collect("2")
    assert first, "no tests collected"
    assert first == second
