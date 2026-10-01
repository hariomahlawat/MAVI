"""Entry point for recorded, metadata-only S2c B0 discovery (see tools/qualification/source_acquisition/README.md)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from source_acquisition.recorded_discovery import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
