"""The one bridge to the Stage-3 tooling the harness reuses (plan §4 reuse decisions).

``tools/stage3`` and ``tools/phase1`` are script directories imported as top-level modules (their own tests do
the same), so the harness imports them the same way: one ``artefacts`` module object, one ``S32Error`` class and
one canonical form for every tool. Nothing is copied.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for _directory in (ROOT / "tools" / "phase1", ROOT / "tools" / "stage3"):
    if str(_directory) not in sys.path:
        sys.path.insert(0, str(_directory))

import artefacts  # noqa: E402

__all__ = ["ROOT", "artefacts"]
