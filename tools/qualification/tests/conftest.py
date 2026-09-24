from __future__ import annotations

import sys
from pathlib import Path

QUALIFICATION = Path(__file__).resolve().parents[1]
REPO = QUALIFICATION.parents[1]
for path in (QUALIFICATION, REPO / "src" / "vision"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
