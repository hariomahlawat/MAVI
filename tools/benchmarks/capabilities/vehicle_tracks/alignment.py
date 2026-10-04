"""Midpoint-window time alignment (plan §7.1, policy ``alignment: midpoint-windows-v1``).

Each labelled instant ``t_k`` owns the half-open window ``[(t_(k-1) + t_k)/2, (t_k + t_(k+1))/2)``; the first window
starts at ``t_0 - (t_1 - t_0)/2`` and the last ends at ``t_n + (t_n - t_(n-1))/2``; a single instant uses ``±Δ/2`` of
the declared labelled rate. A point exactly on a boundary belongs to the later instant. All boundaries are exact
rationals, so no float rounding decides membership, and the windows tile the labelled span with no gap and no
overlap. Membership is the whole alignment rule: there is no separate time tolerance.

The evaluable point of a Track at an instant is its point in that window nearest the instant (an exact tie goes to
the earlier offset). A point lies in at most one window, so it can support at most one instant; points outside
every window are never evaluable.
"""

from __future__ import annotations

import bisect
from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction

from tools.benchmarks.core.identity import require

CODE = "alignment_invalid"


@dataclass(frozen=True, slots=True)
class Windows:
    instants: tuple[Fraction, ...]
    lows: tuple[Fraction, ...]
    highs: tuple[Fraction, ...]

    def instant_of(self, offset: Fraction | int) -> int | None:
        """The labelled instant whose half-open window holds ``offset``, or ``None`` outside the labelled span."""
        position = bisect.bisect_right(self.lows, offset) - 1
        if position < 0 or not offset < self.highs[position]:
            return None
        return position


def windows(instants: Sequence[Fraction], labelled_rate: Fraction | None) -> Windows:
    """Windows for strictly increasing labelled instants (media ms). ``labelled_rate`` is in frames per second and
    is needed only for a single labelled instant."""
    times = tuple(Fraction(value) for value in instants)
    require(times, f"{CODE}:no_instants")
    require(all(later > earlier for earlier, later in zip(times, times[1:])), f"{CODE}:instants_order")
    if len(times) == 1:
        require(labelled_rate is not None and labelled_rate > 0, f"{CODE}:single_instant_without_rate")
        half = Fraction(1000, 2) / Fraction(labelled_rate)
        return Windows(times, (times[0] - half,), (times[0] + half,))
    midpoints = [(earlier + later) / 2 for earlier, later in zip(times, times[1:])]
    first = times[0] - (times[1] - times[0]) / 2
    last = times[-1] + (times[-1] - times[-2]) / 2
    return Windows(times, (first, *midpoints), (*midpoints, last))


def evaluable_points(windows_: Windows, offsets: Sequence[int]) -> dict[int, int]:
    """For one Track: instant position -> index into ``offsets`` of its evaluable point."""
    chosen: dict[int, tuple[Fraction, int]] = {}
    for index, offset in enumerate(offsets):
        instant = windows_.instant_of(offset)
        if instant is None:
            continue
        distance = abs(Fraction(offset) - windows_.instants[instant])
        held = chosen.get(instant)
        # Offsets are strictly increasing, so on an exact tie the point already held is the earlier one.
        if held is None or distance < held[0]:
            chosen[instant] = (distance, index)
    return {instant: index for instant, (_, index) in sorted(chosen.items())}
