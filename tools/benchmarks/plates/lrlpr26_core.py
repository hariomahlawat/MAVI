"""Stage 4 LRLPR-26 aggregation experiment: frozen policy, measure, selection, statistics and decision rules.

Pure functions only (no dataset or model access), so the synthetic tests exercise exactly the code the experiment
runs. The rules are ``docs/qualification/stage4/lrlpr-26-aggregation-rules-v1.json`` (FROZEN; bound by SHA-256 in
``lrlpr26_read``/``lrlpr26_eval``). Development only.

A *reading* is one LR frame's OCR result as phase 1 stores it::

    {"frame": "lr-001", "sha256": ..., "status": "ok"|"empty"|"ocrError"|"outputInvalid",
     "rawText": str|None, "confidence": float|None}

``eligible_readings`` turns a track's readings into its eligible ``(frame index, normalised text, confidence)``
triples: status ``ok`` (one contract-valid reading), confidence >= the floor (inclusive) and ``normalise()`` ok.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import math
from fractions import Fraction
from typing import Any, Sequence

FRAMES = ("lr-001", "lr-002", "lr-003", "lr-004", "lr-005")
C_GRID = (2, 3, 4, 5)
A_GRID = ("0.50", "0.60", "0.70", "0.80", "0.90", "1.00")
PRIMARY = ("S1", "SB", "U")
SECONDARY = ("U-raw",)
MEASURES = ("correctTextRecall", "incorrectTextAcceptance", "predictionPrecision", "coverage", "wrongTextsPerTrack")
HIGHER = frozenset({"correctTextRecall", "predictionPrecision", "coverage"})
LOWER = frozenset({"incorrectTextAcceptance", "wrongTextsPerTrack"})
TARGET_DEV_INCORRECT = Fraction(1, 100)
TARGET_RECALL_LOSS_POINT = 0.030
TARGET_RECALL_LOSS_UPPER = 0.050
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20261018
FEASIBLE, INFEASIBLE = "FEASIBLE", "INFEASIBLE"
SUPPORTED, NOT_SUPPORTED, INCONCLUSIVE = "SUPPORTED", "NOT SUPPORTED", "INCONCLUSIVE"
STATUSES = ("ok", "empty", "ocrError", "outputInvalid")


class Lrlpr26ExperimentError(RuntimeError):
    """An integrity failure: the run is INVALID with this code as its cause."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise Lrlpr26ExperimentError(code)


# canonical records --------------------------------------------------------------------------------------------------

def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(document: Any) -> bytes:
    """The harness canonical JSON (``tools.benchmarks.core.identity.canonical_json`` form)."""
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def canonical_lines(rows: list[dict]) -> bytes:
    return b"".join(canonical(r) + b"\n" for r in rows)


def gzip_bytes(raw: bytes) -> bytes:
    """Deterministic gzip (mtime 0, empty name, level 9): the B1/X4 pattern."""
    buffer = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0, compresslevel=9) as handle:
        handle.write(raw)
    return buffer.getvalue()


def log_entry(rows: list[dict]) -> tuple[bytes, dict[str, Any]]:
    raw = canonical_lines(rows)
    data = gzip_bytes(raw)
    return data, {"rows": len(rows), "canonicalSha256": sha_bytes(raw), "gzipSha256": sha_bytes(data)}


def decode_log(data: bytes, entry: dict[str, Any], name: str) -> list[dict]:
    require(sha_bytes(data) == entry["gzipSha256"], f"lrlpr26_log_gzip_mismatch:{name}")
    raw = gzip.decompress(data)
    require(sha_bytes(raw) == entry["canonicalSha256"], f"lrlpr26_log_canonical_mismatch:{name}")
    rows = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
    require(canonical_lines(rows) == raw, f"lrlpr26_log_not_canonical:{name}")
    require(len(rows) == entry["rows"], f"lrlpr26_log_rowcount_mismatch:{name}")
    return rows


def require_repeat_equal(passes: list[tuple[str, str]]) -> None:
    """Phase 1, phase 2 and the timing pass 2T, as (label, records canonical SHA-256), in that order and equal."""
    require([label for label, _ in passes] == ["phase1", "phase2", "phase2T"], "lrlpr26_pass_order")
    for label, digest in passes[1:]:
        require(digest == passes[0][1], f"lrlpr26_repeat_not_equal:{label}")


# eligibility --------------------------------------------------------------------------------------------------------

def normalised_or_none(raw: str) -> str | None:
    from mavi_vision.plates.normalisation import OK, normalise

    result = normalise(raw)
    return result.normalised if result.outcome == OK else None


def validate_reading(reading: dict[str, Any]) -> None:
    require(reading.get("status") in STATUSES, "lrlpr26_reading_status_invalid")
    if reading["status"] == "ok":
        confidence = reading.get("confidence")
        require(isinstance(reading.get("rawText"), str) and isinstance(confidence, float)
                and math.isfinite(confidence) and 0.0 <= confidence <= 1.0, "lrlpr26_reading_ok_invalid")
    else:
        require(reading.get("rawText") is None and reading.get("confidence") is None, "lrlpr26_reading_not_ok_invalid")


def eligible_readings(readings: Sequence[dict[str, Any]], floor: float) -> list[tuple[int, str, float]]:
    """(frame index, normalised text, confidence) for each eligible reading, in frame order."""
    out = []
    for index, reading in enumerate(readings):
        validate_reading(reading)
        if reading["status"] != "ok" or not reading["confidence"] >= floor:
            continue
        text = normalised_or_none(reading["rawText"])
        if text is not None:
            out.append((index, text, reading["confidence"]))
    return out


def raw_texts(readings: Sequence[dict[str, Any]]) -> list[str]:
    """U-raw input: every ok-normalised rank-0 text, no floor."""
    out = []
    for reading in readings:
        validate_reading(reading)
        if reading["status"] == "ok":
            text = normalised_or_none(reading["rawText"])
            if text is not None:
                out.append(text)
    return out


# policies (each returns the sorted accepted texts; [] is an abstention) ---------------------------------------------

def policy_s1(eligible: list[tuple[int, str, float]], last_index: int = 4) -> list[str]:
    return [text for index, text, _ in eligible if index == last_index]


def policy_sb(eligible: list[tuple[int, str, float]]) -> list[str]:
    if not eligible:
        return []
    best = min(eligible, key=lambda item: (-item[2], item[0]))
    return [best[1]]


def policy_u(eligible: list[tuple[int, str, float]]) -> list[str]:
    return sorted({text for _, text, _ in eligible})


def policy_u_raw(texts: list[str]) -> list[str]:
    return sorted(set(texts))


def _support(eligible):
    support: dict[str, int] = {}
    for _, text, _ in eligible:
        support[text] = support.get(text, 0) + 1
    return support


def policy_c(eligible: list[tuple[int, str, float]], k: int) -> list[str]:
    support = _support(eligible)
    if not support:
        return []
    top = max(support.values())
    leaders = [t for t, s in support.items() if s == top]
    return leaders if len(leaders) == 1 and top >= k else []


def policy_a(eligible: list[tuple[int, str, float]], tau: str) -> list[str]:
    """Exact: weights are Fractions of the float64 confidences, tau the exact decimal."""
    if not eligible:
        return []
    if not all(math.isfinite(c) for _, _, c in eligible):
        return []
    weight: dict[str, Fraction] = {}
    for _, text, confidence in eligible:
        weight[text] = weight.get(text, Fraction(0)) + Fraction(confidence)
    total = sum(weight.values(), Fraction(0))
    if total <= 0:
        return []  # zero-weight guard
    top = max(weight.values())
    leaders = [t for t, w in weight.items() if w == top]
    if len(leaders) != 1:
        return []
    leader = leaders[0]
    if _support(eligible)[leader] < 2:
        return []
    return [leader] if top / total >= Fraction(tau) else []


def config_names(selection: dict[str, Any] | None = None) -> list[str]:
    if selection is None:
        return [*PRIMARY, *(f"C(k={k})" for k in C_GRID), *(f"A(tau={t})" for t in A_GRID), *SECONDARY]
    return [*PRIMARY, "C*", "A*", *SECONDARY]


def accept_all(readings: Sequence[dict[str, Any]], floor: float, k: int | None = None, tau: str | None = None,
               frames: int = 5, include_grid: bool = False) -> dict[str, list[str]]:
    """Every policy's accepted texts for one track, on its first ``frames`` LR frames."""
    used = list(readings[:frames])
    eligible = eligible_readings(used, floor)
    out = {"S1": policy_s1(eligible) if frames == 5 else [], "SB": policy_sb(eligible), "U": policy_u(eligible),
           "U-raw": policy_u_raw(raw_texts(used))}
    if include_grid:
        for kk in C_GRID:
            out[f"C(k={kk})"] = policy_c(eligible, kk)
        for tt in A_GRID:
            out[f"A(tau={tt})"] = policy_a(eligible, tt)
    if k is not None:
        out["C*"] = policy_c(eligible, k)
    if tau is not None:
        out["A*"] = policy_a(eligible, tau)
    return out


# measures -----------------------------------------------------------------------------------------------------------

def track_outcome(accepted: list[str], truth: str) -> dict[str, int]:
    wrong = sum(1 for t in accepted if t != truth)
    correct = 1 if truth in accepted else 0
    return {"correct": correct, "incorrect": 1 if wrong else 0, "covered": 1 if accepted else 0,
            "pairs": len(accepted), "correctPairs": correct, "wrong": wrong}


OUTCOME_KEYS = ("correct", "incorrect", "covered", "pairs", "correctPairs", "wrong")


def _ratio(numerator: int, denominator: int) -> dict[str, Any]:
    if denominator == 0:
        return {"numerator": numerator, "denominator": 0, "value": None}
    return {"numerator": numerator, "denominator": denominator, "value": numerator / denominator}


def measures(outcomes: list[dict[str, int]]) -> dict[str, Any]:
    n = len(outcomes)
    total = {key: sum(o[key] for o in outcomes) for key in OUTCOME_KEYS}
    return {
        "tracks": n,
        "correctTextRecall": _ratio(total["correct"], n),
        "incorrectTextAcceptance": _ratio(total["incorrect"], n),
        "predictionPrecision": _ratio(total["correctPairs"], total["pairs"]),
        "coverage": _ratio(total["covered"], n),
        "wrongTextsPerTrack": _ratio(total["wrong"], n),
        "wrongTextDistribution": {"0": sum(1 for o in outcomes if o["wrong"] == 0),
                                  "1": sum(1 for o in outcomes if o["wrong"] == 1),
                                  ">=2": sum(1 for o in outcomes if o["wrong"] >= 2)},
        "acceptedPairs": total["pairs"],
    }


# selection ----------------------------------------------------------------------------------------------------------

def select_family(family: str, rows: dict[Any, dict[str, Any]]) -> dict[str, Any]:
    """``rows``: threshold → measures on DEV. Feasible iff 100*incorrect <= tracks; max recall; ties: lower incorrect,
    then stricter. None feasible → INFEASIBLE with the strictest configuration."""
    require(family in ("C", "A"), "lrlpr26_family_invalid")
    grid = list(C_GRID) if family == "C" else list(A_GRID)
    require(sorted(rows, key=str) == sorted(grid, key=str), "lrlpr26_selection_grid_incomplete")
    strictness = {value: position for position, value in enumerate(grid)}  # later in the grid = stricter
    table = []
    for value in grid:
        m = rows[value]
        incorrect, tracks = m["incorrectTextAcceptance"]["numerator"], m["tracks"]
        table.append({"threshold": value, "tracks": tracks, "correct": m["correctTextRecall"]["numerator"],
                      "incorrect": incorrect, "feasible": 100 * incorrect <= tracks})
    feasible = [row for row in table if row["feasible"]]
    if feasible:
        best = max(feasible, key=lambda r: (r["correct"], -r["incorrect"], strictness[r["threshold"]]))
        return {"family": family, "status": FEASIBLE, "selected": best["threshold"], "table": table}
    return {"family": family, "status": INFEASIBLE, "selected": grid[-1], "table": table}


# statistics ---------------------------------------------------------------------------------------------------------

def group_sums(outcomes: list[dict[str, int]], groups: list[int], group_count: int):
    import numpy as np

    sums = np.zeros((group_count, len(OUTCOME_KEYS) + 1), dtype=np.int64)
    for outcome, group in zip(outcomes, groups):
        sums[group, :-1] += [outcome[key] for key in OUTCOME_KEYS]
        sums[group, -1] += 1
    return sums


def resample_weights(group_count: int, resamples: int = BOOTSTRAP_RESAMPLES, seed: int = BOOTSTRAP_SEED):
    """The shared paired resamples: one row of group multiplicities per resample."""
    import numpy as np

    rng = np.random.default_rng(seed)
    weights = np.zeros((resamples, group_count), dtype=np.int64)
    for r in range(resamples):
        weights[r] = np.bincount(rng.integers(0, group_count, size=group_count), minlength=group_count)
    return weights


def _measure_matrix(weights, sums):
    """Per resample: the five measures (NaN where undefined)."""
    import numpy as np

    totals = weights @ sums  # resamples x (keys + tracks)
    k = {key: totals[:, i].astype(np.float64) for i, key in enumerate(OUTCOME_KEYS)}
    n = totals[:, -1].astype(np.float64)
    with np.errstate(invalid="ignore", divide="ignore"):
        precision = np.where(k["pairs"] > 0, k["correctPairs"] / np.where(k["pairs"] > 0, k["pairs"], 1), np.nan)
    return {"correctTextRecall": k["correct"] / n, "incorrectTextAcceptance": k["incorrect"] / n,
            "predictionPrecision": precision, "coverage": k["covered"] / n, "wrongTextsPerTrack": k["wrong"] / n}


def _point(sums):
    totals = sums.sum(axis=0)
    t = {key: int(totals[i]) for i, key in enumerate(OUTCOME_KEYS)}
    n = int(totals[-1])
    return {"correctTextRecall": t["correct"] / n, "incorrectTextAcceptance": t["incorrect"] / n,
            "predictionPrecision": (t["correctPairs"] / t["pairs"]) if t["pairs"] else None,
            "coverage": t["covered"] / n, "wrongTextsPerTrack": t["wrong"] / n}


def paired_bootstrap(sums_x, sums_y, weights) -> dict[str, Any]:
    """CI of measure(X) - measure(Y) on each measure, with the recall loss (Y - X) alongside."""
    import numpy as np

    mx, my = _measure_matrix(weights, sums_x), _measure_matrix(weights, sums_y)
    px, py = _point(sums_x), _point(sums_y)
    out: dict[str, Any] = {}
    for measure in MEASURES:
        diff = mx[measure] - my[measure]
        keep = ~np.isnan(diff)
        point = None if px[measure] is None or py[measure] is None else px[measure] - py[measure]
        if keep.sum() == 0:
            out[measure] = {"point": point, "ci95": None, "dropped": int((~keep).sum())}
            continue
        low, high = np.percentile(diff[keep], [2.5, 97.5], method="linear")
        out[measure] = {"point": point, "ci95": [float(low), float(high)], "dropped": int((~keep).sum())}
    loss = my["correctTextRecall"] - mx["correctTextRecall"]
    low, high = np.percentile(loss, [2.5, 97.5], method="linear")
    out["recallLoss"] = {"point": py["correctTextRecall"] - px["correctTextRecall"], "ci95": [float(low), float(high)]}
    return out


def mcnemar(x: list[int], y: list[int]) -> dict[str, Any]:
    """Exact two-sided binomial McNemar on paired 0/1 indicators (exploratory)."""
    require(len(x) == len(y), "lrlpr26_mcnemar_length")
    b = sum(1 for a, c in zip(x, y) if a == 1 and c == 0)
    c = sum(1 for a, cc in zip(x, y) if a == 0 and cc == 1)
    n = b + c
    if n == 0:
        return {"b": b, "c": c, "p": 1.0}
    tail = sum(math.comb(n, i) for i in range(min(b, c) + 1))
    return {"b": b, "c": c, "p": float(min(Fraction(1), Fraction(2 * tail, 2 ** n)))}


# decision -----------------------------------------------------------------------------------------------------------

def favours(measure: str, ci: list[float] | None) -> str | None:
    """Which side of a (first - second) CI excludes 0 in its favour: 'first', 'second' or None."""
    if ci is None:
        return None
    low, high = ci
    if measure in HIGHER:
        return "first" if low > 0 else "second" if high < 0 else None
    return "first" if high < 0 else "second" if low > 0 else None


def family_step1(status: str, vs_u: dict[str, Any]) -> dict[str, Any]:
    incorrect = vs_u["incorrectTextAcceptance"]["ci95"]
    loss = vs_u["recallLoss"]
    supported = (status == FEASIBLE and incorrect[1] < 0 and loss["point"] <= TARGET_RECALL_LOSS_POINT
                 and loss["ci95"][1] <= TARGET_RECALL_LOSS_UPPER)
    negative = {"infeasibleOnDev": status == INFEASIBLE, "doesNotReduceWrongTexts": incorrect[0] >= 0,
                "recallTargetClearlyMissed": loss["ci95"][0] > TARGET_RECALL_LOSS_POINT}
    return {"status": status, "supported": supported, "negativeEvidence": negative,
            "hasNegativeEvidence": any(negative.values())}


def decide(c_step1: dict[str, Any], a_step1: dict[str, Any], a_minus_c: dict[str, Any]) -> dict[str, Any]:
    supported = [name for name, step in (("C*", c_step1), ("A*", a_step1)) if step["supported"]]
    preferred = None
    step2 = None
    if len(supported) == 2:
        favour_a = [m for m in ("correctTextRecall", "incorrectTextAcceptance", "coverage")
                    if favours(m, a_minus_c[m]["ci95"]) == "first"]
        favour_c = [m for m in MEASURES if favours(m, a_minus_c[m]["ci95"]) == "second"]
        preferred = "A*" if favour_a and not favour_c else "C*"
        step2 = {"favoursA": favour_a, "favoursC": favour_c,
                 "rule": "A* only if it is favoured on recall/incorrect/coverage and C* is favoured on no measure"}
    elif len(supported) == 1:
        preferred = supported[0]
    if supported:
        outcome = SUPPORTED
    elif c_step1["hasNegativeEvidence"] and a_step1["hasNegativeEvidence"]:
        outcome = NOT_SUPPORTED
    else:
        outcome = INCONCLUSIVE
    return {"outcome": outcome, "supportedFamilies": supported, "preferred": preferred, "step2": step2,
            "C*": c_step1, "A*": a_step1}
