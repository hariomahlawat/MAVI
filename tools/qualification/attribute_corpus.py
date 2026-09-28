"""Entry point for the S2c.1 attribute corpus tooling (see tools/qualification/attributes/corpus/README.md)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from attributes.corpus.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
