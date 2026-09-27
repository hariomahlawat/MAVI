#!/usr/bin/env python3
"""Phase-1 release promotion constructor: fenced in Stage 2 S2a.3.

The Task-17 tool built promoted copies of the v1 model manifest and v1
qualification record from gate evidence keyed by the v1 ``requiredGates``
names, then re-verified them with the v1 release verifier. All of that was
retired at the Component Binding v2 cut-over (ADR-014): v2 records are
capability-scoped with per-variant gates named by the capability gate sets
(plan P-12), and a v2 manifest's verified form is bound to its derived Model
Pack identity. How v1-named gate evidence maps onto v2 gates, how a v2 record's
variants and profile index are advanced, and how a v2 manifest becomes
``verified`` are v2 promotion semantics that S2a.3 deliberately does not define
(plan §19 erratum).

Applying the v1 rules to v2 documents would be a silent, unreviewed promotion
model, so every entry point refuses with ``v2_promotion_not_supported_by_this_slice``
before it parses an argument, reads a release file or creates the output
directory. Read-only checks of the v2 composition live in
``assess_phase1_closure.py`` and ``phase1_e2e_check.py``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Sequence

PHASE1_ROOT = Path(__file__).resolve().parent
if str(PHASE1_ROOT) not in sys.path:
    sys.path.insert(0, str(PHASE1_ROOT))

from v2_promotion_fence import (  # noqa: E402
    V2_PROMOTION_NOT_SUPPORTED,
    V2PromotionNotSupported,
    refuse_v2_promotion,
)

# Kept as the tool's error type so callers keep one ``except`` clause.
PromotionError = V2PromotionNotSupported


def build_promoted_metadata(**_: Any) -> tuple[bytes, bytes]:
    """Refused: would construct promoted v2 manifest/record bytes (undefined in S2a.3)."""
    refuse_v2_promotion()


def validate_promoted_outputs(**_: Any) -> None:
    """Refused: validating promoted outputs presupposes the undefined v2 promotion model."""
    refuse_v2_promotion()


def main(argv: Sequence[str] | None = None) -> int:
    """Refuse every invocation; nothing is read and no output is created."""
    print(json.dumps({"ok": False, "code": V2_PROMOTION_NOT_SUPPORTED}, sort_keys=True))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
