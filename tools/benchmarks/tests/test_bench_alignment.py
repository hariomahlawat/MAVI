"""Midpoint-window alignment (S3.2d-1 plan §7.1): exact rationals, half-open windows, no time tolerance."""

from __future__ import annotations

from fractions import Fraction as F

import pytest

from tools.benchmarks.capabilities.vehicle_tracks import alignment as al
from tools.benchmarks.core.identity import S32Error


def test_five_hertz_two_points_give_exactly_two_aligned_instants_never_three():
    # Labels at 0/200/400 ms; MAVI points at 100 and 300 ms (both exactly on a midpoint boundary).
    windows = al.windows([F(0), F(200), F(400)], F(5))
    chosen = al.evaluable_points(windows, [100, 300])
    assert chosen == {1: 0, 2: 1}  # 100 -> instant 200 (the later), 300 -> instant 400; instant 0 has none
    assert len(chosen) == 2


def test_boundary_point_belongs_to_the_later_instant():
    windows = al.windows([F(0), F(200)], F(5))
    assert windows.instant_of(F(99)) == 0 and windows.instant_of(F(100)) == 1
    assert windows.instant_of(F(-100)) == 0 and windows.instant_of(F(-101)) is None
    assert windows.instant_of(F(299)) == 1 and windows.instant_of(F(300)) is None  # last window is half-open


def test_windows_tile_the_span_without_gaps_or_overlaps():
    for instants in ([F(0), F(200), F(400), F(600)], [F(1001 * k, 30) for k in range(20)],
                     [F(0), F(180), F(420), F(450)]):
        windows = al.windows(instants, F(5))
        assert windows.lows[1:] == windows.highs[:-1]
        assert all(low < high for low, high in zip(windows.lows, windows.highs))
        assert all(low <= t < high for t, low, high in zip(instants, windows.lows, windows.highs))


def test_non_integral_thirty_hertz_midpoints_land_in_exactly_one_window():
    # 30 fps labels: 33 1/3 ms apart; a point at every exact midpoint goes to the later instant, none in a gap.
    instants = [F(100 * k, 3) for k in range(10)]
    windows = al.windows(instants, F(30))
    for k in range(9):
        midpoint = (instants[k] + instants[k + 1]) / 2
        assert windows.instant_of(midpoint) == k + 1
        assert windows.instant_of(midpoint - F(1, 10**9)) == k


def test_ntsc_rate_uses_exact_rationals():
    instants = [F(1001 * k, 30) for k in range(4)]  # 30000/1001 fps
    windows = al.windows(instants, F(30000, 1001))
    assert windows.highs[0] == F(1001, 60)
    assert windows.instant_of(17) == 1 and windows.instant_of(16) == 0  # 1001/60 = 16.68…


def test_irregular_timestamps():
    windows = al.windows([F(0), F(180), F(420), F(450)], None)
    assert windows.lows == (F(-90), F(90), F(300), F(435))
    assert windows.highs == (F(90), F(300), F(435), F(465))
    offsets = [89, 90, 299, 300, 434, 435, 464]
    assert [windows.instant_of(o) for o in offsets] == [0, 1, 1, 2, 2, 3, 3]


def test_nearest_point_wins_and_exact_tie_goes_to_the_earlier_offset():
    windows = al.windows([F(0), F(200), F(400)], F(5))
    # Around instant 200: points at 150, 190, 210 -> 190 and 210 tie at 10 ms; the earlier (190) wins.
    assert al.evaluable_points(windows, [150, 190, 210]) == {1: 1}
    assert al.evaluable_points(windows, [150, 205]) == {1: 1}


def test_a_point_supports_at_most_one_instant_and_unlabelled_points_never_count():
    windows = al.windows([F(0), F(200), F(400)], F(5))
    chosen = al.evaluable_points(windows, [-150, 0, 499, 500, 900])
    assert chosen == {0: 1, 2: 2}  # -150, 500 (the last window is [300, 500)) and 900 are outside every window
    assert len(set(chosen.values())) == len(chosen)


def test_high_rate_track_against_sparse_labels():
    windows = al.windows([F(200 * k) for k in range(5)], F(5))
    offsets = [round(1000 * k / 30) for k in range(0, 30)]  # 30 fps points over the first second
    chosen = al.evaluable_points(windows, offsets)
    assert sorted(chosen) == [0, 1, 2, 3, 4]
    assert [offsets[i] for i in chosen.values()] == [0, 200, 400, 600, 800]


def test_single_instant_uses_half_a_declared_period():
    windows = al.windows([F(1000)], F(5))
    assert (windows.lows, windows.highs) == ((F(900),), (F(1100),))
    with pytest.raises(S32Error, match="^alignment_invalid:single_instant_without_rate$"):
        al.windows([F(1000)], None)


def test_unsorted_or_empty_instants_are_refused():
    with pytest.raises(S32Error, match="^alignment_invalid:instants_order$"):
        al.windows([F(0), F(0)], F(5))
    with pytest.raises(S32Error, match="^alignment_invalid:no_instants$"):
        al.windows([], F(5))
