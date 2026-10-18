"""Stage 4 X4-0 frame selection, exactly as frozen in ``x4-0-rules-v1.json`` (``selectK`` and arm ``P1``).

Development experiment only. This module is deliberately standard-library only: it cannot read ground truth,
the evaluation, the association or any plate output except the per-crop maximum detector score handed to
``select_p1``. ``select_k`` sees only model-neutral per-candidate facts (frame number and logged box area).
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

KS: tuple[int | str, ...] = (4, 8, "all")


def pool(track_rows: Iterable[Mapping], a0_frames: Iterable[int], available: Iterable[int]) -> list[dict]:
    """Pool(T): the Track's logged frames, minus its A0 Observation frames, minus frames without a usable crop.

    Each element is ``{"frame": int, "area": float}``; sorted by frame. Duplicate frames are an input defect.
    """
    a0, ok = set(a0_frames), set(available)
    seen: set[int] = set()
    out = []
    for row in track_rows:
        frame = int(row["frame"])
        if frame in seen:
            raise ValueError("x4_pool_duplicate_frame")
        seen.add(frame)
        if frame in a0 or frame not in ok:
            continue
        out.append({"frame": frame, "area": float(row["area"])})
    return sorted(out, key=lambda r: r["frame"])


def _by_area(rows: Iterable[Mapping]) -> list[Mapping]:
    return sorted(rows, key=lambda r: (-r["area"], r["frame"]))


def select_k(pool_rows: Sequence[Mapping], k: int | str) -> tuple[int, ...]:
    """Temporally spread, largest-area frames: K equal frame-number bins, the largest area per bin, then fill."""
    if k != "all" and (not isinstance(k, int) or isinstance(k, bool) or k < 1):
        raise ValueError("x4_k_invalid")
    frames = [int(r["frame"]) for r in pool_rows]
    if len(set(frames)) != len(frames):
        raise ValueError("x4_pool_duplicate_frame")
    if k == "all" or len(pool_rows) <= k:
        return tuple(sorted(frames))
    f0, f1 = min(frames), max(frames)
    span = f1 - f0 + 1
    bins: dict[int, list[Mapping]] = {}
    for r in pool_rows:
        bins.setdefault((k * (int(r["frame"]) - f0)) // span, []).append(r)
    chosen = {int(_by_area(members)[0]["frame"]) for _, members in sorted(bins.items())}
    for r in _by_area(pool_rows):
        if len(chosen) >= k:
            break
        chosen.add(int(r["frame"]))
    return tuple(sorted(chosen))


def select_p1(a0_scores: Sequence[float | None], pool_scores: Mapping[int, float | None]) -> int | None:
    """P1: the Pool frame whose encoded crop has the highest maximum detector box score, if it beats A0's crops.

    ``a0_scores`` are the A0 crops' maximum detector scores and ``pool_scores`` the scouting crops' (frame ->
    score); ``None`` is a crop without any box. Ties prefer an A0 crop, then the lower frame. Returns the frame to
    add, or ``None`` (P1 = A0).
    """
    best_a0 = max((s for s in a0_scores if s is not None), default=None)
    best_frame, best_score = None, None
    for frame in sorted(pool_scores):
        score = pool_scores[frame]
        if score is not None and (best_score is None or score > best_score):
            best_frame, best_score = frame, score
    if best_score is None or (best_a0 is not None and best_a0 >= best_score):
        return None
    return best_frame
