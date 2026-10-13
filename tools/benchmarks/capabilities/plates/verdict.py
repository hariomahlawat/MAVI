"""The frozen evidence-adequacy decision rule (Stage 4 plan §3.4; protocol ``adequacy-protocol.md`` §5).

Inputs are exact: the coverage C as a ratio of Track counts, and ΔEM per instrument at the supplemental (NearView)
cap as an exact rational in percentage points. The rule, by precedence:

* **NOT MEASURED** — no C, a C denominator below the support floor, a missing or insufficient ΔEM for any instrument,
  or any instrument with read errors. No data is never ADEQUATE.
* **INADEQUATE** — C < 0.70, or ΔEM > 10 pp for any instrument.
* **MARGINAL** — 0.70 ≤ C < 0.85, or 5 pp < ΔEM ≤ 10 pp for any instrument.
* **ADEQUATE** — C ≥ 0.85 and ΔEM ≤ 5 pp for every instrument.

Strata never change the verdict; they are reported beside it (§3.4: a per-stratum failure under an overall ADEQUATE
is an exposure limit recorded in the register).
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any

ADEQUATE, MARGINAL, INADEQUATE, NOT_MEASURED = "ADEQUATE", "MARGINAL", "INADEQUATE", "NOT_MEASURED"
C_ADEQUATE, C_MARGINAL = Fraction(85, 100), Fraction(70, 100)
LOSS_ADEQUATE, LOSS_MARGINAL = Fraction(5), Fraction(10)


def decide(*, coverage: tuple[int, int] | None, coverage_sufficient: bool,
           losses: dict[str, Fraction | None], losses_sufficient: dict[str, bool],
           instrument_errors: dict[str, int]) -> dict[str, Any]:
    """The verdict and every reason that contributed to it."""
    reasons: list[str] = []
    if coverage is None or coverage[1] == 0:
        reasons.append("coverage_not_measured")
    elif not coverage_sufficient:
        reasons.append("coverage_insufficient_support")
    if not losses:
        reasons.append("encoding_loss_not_measured")
    for instrument_id in sorted(losses):
        if losses[instrument_id] is None:
            reasons.append(f"encoding_loss_not_measured:{instrument_id}")
        elif not losses_sufficient.get(instrument_id, False):
            reasons.append(f"encoding_loss_insufficient_support:{instrument_id}")
    for instrument_id, errors in sorted(instrument_errors.items()):
        if errors:
            reasons.append(f"instrument_errors:{instrument_id}:{errors}")
    if reasons:
        return {"verdict": NOT_MEASURED, "reasons": reasons}
    c = Fraction(coverage[0], coverage[1])  # type: ignore[index]
    inadequate, marginal = [], []
    if c < C_MARGINAL:
        inadequate.append("coverage_below_0.70")
    elif c < C_ADEQUATE:
        marginal.append("coverage_below_0.85")
    for instrument_id in sorted(losses):
        loss = losses[instrument_id]
        assert loss is not None
        if loss > LOSS_MARGINAL:
            inadequate.append(f"encoding_loss_above_10pp:{instrument_id}")
        elif loss > LOSS_ADEQUATE:
            marginal.append(f"encoding_loss_above_5pp:{instrument_id}")
    if inadequate:
        return {"verdict": INADEQUATE, "reasons": inadequate + marginal}
    if marginal:
        return {"verdict": MARGINAL, "reasons": marginal}
    return {"verdict": ADEQUATE, "reasons": []}
