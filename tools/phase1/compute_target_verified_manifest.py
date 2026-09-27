#!/usr/bin/env python3
"""Pre-compute the verified model-manifest bytes a promotion would publish: fenced in S2a.3.

Under the retired v1 model the target verified manifest was the candidate with
``verificationStatus`` flipped to ``verified`` and ``qualificationId`` filled in.
A v2 Model Pack manifest's verified form (its licence review, the capability-
scoped qualification record it names, and the identity that follows from them)
is v2 promotion semantics, which S2a.3 does not define. Every entry point
therefore refuses with ``v2_promotion_not_supported_by_this_slice`` before it
parses an argument, reads a manifest or creates an output file.
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
TargetManifestError = V2PromotionNotSupported


def build_target_manifest(candidate: dict[str, Any], qualification_id: str) -> bytes:
    """Refused: the v2 verified-manifest form is undefined in S2a.3."""
    refuse_v2_promotion()


def main(argv: Sequence[str] | None = None) -> int:
    """Refuse every invocation; nothing is read and no output file is created."""
    print(json.dumps({"ok": False, "code": V2_PROMOTION_NOT_SUPPORTED}, sort_keys=True))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
