"""The Stage 2 S2a.3 fence on Phase-1 release promotion.

S2a.3 moves the Phase-1 tools onto the Component Binding v2 composition
(ADR-014) but deliberately defines no v2 qualification/promotion model: how
gate evidence is bound into a capability-scoped v2 qualification record and
how a v2 Model Pack manifest becomes ``verified`` are open (S2a plan §19
erratum). Every tool path that would write, promote or pre-compute a
qualification record or a verified model manifest therefore fails closed with
the one stable code below, before it reads or writes anything, instead of
silently applying the retired v1 rules. RTMDet stays ``unverified``/``pending``.

This module has no dependencies so that a fenced tool refuses before it
imports, reads or resolves anything.
"""

from __future__ import annotations

from typing import NoReturn

V2_PROMOTION_NOT_SUPPORTED = "v2_promotion_not_supported_by_this_slice"


class V2PromotionNotSupported(ValueError):
    """Raised by every fenced writer; ``code`` is always ``V2_PROMOTION_NOT_SUPPORTED``."""

    def __init__(self) -> None:
        super().__init__(V2_PROMOTION_NOT_SUPPORTED)
        self.code = V2_PROMOTION_NOT_SUPPORTED


def refuse_v2_promotion() -> NoReturn:
    raise V2PromotionNotSupported()


__all__ = [
    "V2_PROMOTION_NOT_SUPPORTED",
    "V2PromotionNotSupported",
    "refuse_v2_promotion",
]
