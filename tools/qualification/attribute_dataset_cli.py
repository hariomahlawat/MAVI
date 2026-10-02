"""Entry point for external dataset release tooling (see docs/superpowers/plans/2026-10-02-stage2-s2c-public-attribute-data-slice.md)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from attributes.datasets.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
