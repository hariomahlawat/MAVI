"""The H4 paired comparison (``h4-paired-comparison-v1``): reference arm ``a2-scale640`` against candidate arm
``a2-scale1280`` on the same prepared footage of one domain, from retained ``evaluate`` results only.

Inputs, per domain: one or more partitions (a dataset split prepared once), each with the derived directory and the
two arms' ``evaluate`` result directories. Every result is re-verified (``run.verify``) and must:

* be bound to that partition's derivation manifest, with the same descriptor, mapping, association policy,
  requirements and harness tooling as the other arm (only the producer may differ);
* name exactly its arm's frozen producer tuple (profile SHA, component-binding SHA, Model Pack id) in its envelope.

Per arm and domain (Observed): the result's Scope A counts summed over partitions (expected-vehicle GT outcomes,
MAVI Vehicle Track states, ignored GT), the association rate, zero-assigned sequences, per-native-class coverage and
the Scope B subclass block per partition (copied, never recomputed).

Paired (Derived): ΔAssigned and Δassociation; a paired, partition-stratified sequence bootstrap of Δassociation
(``draws`` resamples of sequences with replacement within each partition, the same draw for both arms, seed fixed;
95% percentile interval; descriptive, no pass/fail); tracking cost per extra assigned GT (extra Vehicle Tracks,
extra fragmented GT, extra fragment MAVI Tracks; reported only when ΔAssigned > 0); per-GT-track transitions between
the two arms; strata by GT median source height band (H3's bands), native class and, when given, per-sequence
conditions. GT population and outcomes are the result's own: Scope A's expected-vehicle GT (a native class the
evaluator places in the expected population: ``exact``, ``subset`` or ``vehicle-unresolved``) that is not
``ignoredGt``; the per-track reconstruction must reproduce the result's Scope A totals or the comparison refuses.

Usage::

    python -m tools.benchmarks.h4.compare --spec spec.json --out comparison.json
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from pathlib import Path
from typing import Any

from tools.benchmarks import prepare as preparation
from tools.benchmarks import run as runs
from tools.benchmarks.capabilities.vehicle_subclass import evaluate as evaluation
from tools.benchmarks.core._stage3 import artefacts
from tools.benchmarks.core.identity import S32Error, canonical_json, require, sha256_hex

SCHEMA = "h4-paired-comparison-v1"
ARMS = ("reference", "candidate")
STATES = ("assigned", "ambiguous", "merged", "fragmented", "unverified", "unmatched")
LISTS = {"ambiguousGt": "ambiguous", "mergedGt": "merged", "fragmentedGt": "fragmented",
         "unverifiedGt": "unverified", "unmatchedGt": "unmatched"}
GT_KEYS = ("total", *STATES)
MAVI_KEYS = ("total", "assigned", "fragment", "unverified", "ignored", "unmatched")
SAME_TOOLING = ("adapterId", "adapterVersion", "associationPolicySha256", "mappingSha256", "requirementsSha256",
                "runnerVersion", "toolingSha256")
BANDS = ((20, "<20"), (40, "20-40"), (80, "40-80"), (160, "80-160"), (None, ">=160"))


def band(pixels: float) -> str:
    for limit, name in BANDS:
        if limit is None or pixels < limit:
            return name
    raise AssertionError


def _read(path: Path, code: str) -> dict[str, Any]:
    data = artefacts.read_bytes(path, code)
    document = artefacts.parse_json(data, code)
    require(isinstance(document, dict), code)
    return document


def _arm_result(directory: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    runs.verify(Path(directory))  # association, result and report re-checked by the harness's own reader
    return _read(Path(directory) / "result.json", "h4_result_invalid"), _read(Path(directory) / "association.json",
                                                                              "h4_association_invalid")


def _outcomes(association: dict[str, Any], documents: dict[str, dict[str, Any]], exact: set[str]
              ) -> dict[tuple[str, str], dict[str, Any]]:
    """Per expected-vehicle GT track: its state and the facts its strata need."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for sequence in association["sequences"]:
        sid = sequence["sequenceId"]
        gt = documents[sid]
        classes = {track["gtTrackId"]: track for track in gt["tracks"]}
        ignored = {item["gtTrackId"] for item in sequence["ignoredGt"]}
        state = {pair["gtTrackId"]: "assigned" for pair in sequence["pairs"]}
        for key, name in LISTS.items():
            for item in sequence[key]:
                state[item["gtTrackId"]] = name
        for track_id, track in classes.items():
            if track["nativeClass"] not in exact or track_id in ignored:
                continue
            require(track_id in state, f"h4_outcome_missing:{sid}:{track_id}")
            heights = [frame["box"]["height"] * gt["frameSize"]["height"] for frame in track["frames"] if not frame["ignore"]]
            out[(sid, track_id)] = {"state": state[track_id], "nativeClass": track["nativeClass"],
                                    "heightBand": band(statistics.median(heights)) if heights else "none"}
    return out


def _rate(numerator: int, denominator: int) -> dict[str, Any]:
    return {"numerator": numerator, "denominator": denominator,
            "value": (numerator / denominator) if denominator else None}


def compare(spec: dict[str, Any]) -> dict[str, Any]:
    tuples = spec["producers"]
    require(set(tuples) == set(ARMS), "h4_spec_invalid:producers")
    exact: set[str] | None = None
    sequences: list[dict[str, Any]] = []
    outcomes = {arm: {} for arm in ARMS}
    partitions = []
    for partition in spec["partitions"]:
        manifest, manifest_sha, documents = preparation.load(Path(partition["derived"]))
        loaded = {arm: _arm_result(Path(partition["results"][arm])) for arm in ARMS}
        envelopes = {arm: loaded[arm][0]["envelope"] for arm in ARMS}
        for arm in ARMS:
            envelope = envelopes[arm]
            require(envelope["derivationManifestSha256"] == manifest_sha, f"h4_result_not_this_partition:{arm}")
            producer = envelope["mavi"]["producer"]
            for key in ("pipelineProfileSha256", "componentBindingSha256", "modelPackId"):
                require(producer.get(key) == tuples[arm][key], f"h4_result_wrong_producer:{arm}:{key}")
        require(envelopes["reference"]["dataset"] == envelopes["candidate"]["dataset"], "h4_arms_differ:dataset")
        for key in SAME_TOOLING:
            require(envelopes["reference"]["tooling"][key] == envelopes["candidate"]["tooling"][key],
                    f"h4_arms_differ:{key}")
        mapping = _read(Path(partition["mapping"]), "h4_mapping_invalid")
        require(sha256_hex(artefacts.read_bytes(Path(partition["mapping"]), "h4_mapping_invalid"))
                == envelopes["reference"]["tooling"]["mappingSha256"], "h4_mapping_not_the_evaluated_one")
        # Scope A's expected-vehicle population, by the evaluator's own rule (exact, subset, vehicle-unresolved).
        partition_exact = {row["nativeClass"] for row in mapping["mappings"] if evaluation._population(row) == "expected"}
        require(exact is None or exact == partition_exact, "h4_partitions_differ:mapping")
        exact = partition_exact
        rows = {arm: {row["sequenceId"]: row for row in loaded[arm][0]["scopeA"]["sequences"]} for arm in ARMS}
        require(set(rows["reference"]) == set(rows["candidate"]) == {r["sequenceId"] for r in manifest["sequences"]},
                "h4_arms_differ:sequences")
        for arm in ARMS:
            arm_outcomes = _outcomes(loaded[arm][1], documents, exact)
            totals = loaded[arm][0]["scopeA"]["expectedVehicleGt"]
            for state in STATES:
                require(sum(1 for item in arm_outcomes.values() if item["state"] == state) == totals[state],
                        f"h4_reconstruction_mismatch:{arm}:{state}")
            outcomes[arm].update({(partition["name"], *key): value for key, value in arm_outcomes.items()})
        conditions = partition.get("conditions", {})
        for row in manifest["sequences"]:
            sid = row["sequenceId"]
            gt = documents[sid]
            sequences.append({"partition": partition["name"], "sequenceId": sid, "frames": row["frameCount"],
                              "sourceSize": [gt["frameSize"]["width"], gt["frameSize"]["height"]],
                              "conditions": conditions.get(sid, {}),
                              **{arm: {"gt": rows[arm][sid]["expectedVehicleGt"],
                                       "mavi": rows[arm][sid]["maviTracks"]} for arm in ARMS}})
        partitions.append({"name": partition["name"], "derivationManifestSha256": manifest_sha,
                           "frameRate": manifest["frameRate"], "datasetId": manifest["datasetId"],
                           "split": manifest["split"],
                           **{arm: {"benchmarkRunId": envelopes[arm]["benchmarkRunId"],
                                    "resultSha256": sha256_hex(artefacts.read_bytes(Path(partition["results"][arm]) / "result.json", "x")),
                                    "associationSha256": loaded[arm][0]["associationSha256"],
                                    "scopeB": loaded[arm][0]["scopeB"],
                                    "perNativeClass": loaded[arm][0]["scopeA"]["perNativeClass"],
                                    "ignoredGt": loaded[arm][0]["scopeA"]["ignoredGt"]} for arm in ARMS}})
    require(set(outcomes["reference"]) == set(outcomes["candidate"]), "h4_arms_differ:population")

    arms = {}
    for arm in ARMS:
        gt = {f: sum(s[arm]["gt"][f] for s in sequences) for f in GT_KEYS}
        mavi = {f: sum(s[arm]["mavi"][f] for s in sequences) for f in MAVI_KEYS}
        arms[arm] = {"producer": tuples[arm], "expectedVehicleGt": gt, "vehicleTracks": mavi,
                     "associationRate": _rate(gt["assigned"], gt["total"]),
                     "zeroAssignedSequences": sum(1 for s in sequences if s[arm]["gt"]["total"] and s[arm]["gt"]["assigned"] == 0)}
    delta_assigned = arms["candidate"]["expectedVehicleGt"]["assigned"] - arms["reference"]["expectedVehicleGt"]["assigned"]
    total = arms["reference"]["expectedVehicleGt"]["total"]
    require(total == arms["candidate"]["expectedVehicleGt"]["total"], "h4_arms_differ:gt_total")

    def delta(key: str, field: str) -> int:
        return arms["candidate"][key][field] - arms["reference"][key][field]

    costs = None
    if delta_assigned > 0:
        costs = {"vehicleTracksPerExtraAssigned": delta("vehicleTracks", "total") / delta_assigned,
                 "fragmentedGtPerExtraAssigned": delta("expectedVehicleGt", "fragmented") / delta_assigned,
                 "fragmentMaviPerExtraAssigned": delta("vehicleTracks", "fragment") / delta_assigned}

    # Paired, partition-stratified sequence bootstrap of Δassociation (descriptive).
    rng = random.Random(spec["bootstrap"]["seed"])
    groups = {}
    for index, s in enumerate(sequences):
        groups.setdefault(s["partition"], []).append(index)
    draws = []
    for _ in range(spec["bootstrap"]["draws"]):
        chosen = [rng.choice(members) for members in groups.values() for _ in members]
        totals = sum(sequences[i]["reference"]["gt"]["total"] for i in chosen)
        if totals == 0:
            continue
        draws.append((sum(sequences[i]["candidate"]["gt"]["assigned"] for i in chosen)
                      - sum(sequences[i]["reference"]["gt"]["assigned"] for i in chosen)) / totals)
    draws.sort()
    interval = [draws[int(0.025 * (len(draws) - 1))], draws[int(0.975 * (len(draws) - 1))]] if draws else None

    transitions = {a: {b: 0 for b in STATES} for a in STATES}
    for key, item in outcomes["reference"].items():
        transitions[item["state"]][outcomes["candidate"][key]["state"]] += 1

    def strata(field: str) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, item in outcomes["reference"].items():
            name = item[field]
            entry = out.setdefault(name, {"gt": 0, "reference": 0, "candidate": 0})
            entry["gt"] += 1
            entry["reference"] += item["state"] == "assigned"
            entry["candidate"] += outcomes["candidate"][key]["state"] == "assigned"
        return {name: {**entry, "referenceRate": entry["reference"] / entry["gt"], "candidateRate": entry["candidate"] / entry["gt"]}
                for name, entry in sorted(out.items())}

    condition_strata: dict[str, Any] = {}
    for s in sequences:
        for attribute, value in sorted(s["conditions"].items()):
            entry = condition_strata.setdefault(attribute, {}).setdefault(str(value), {"sequences": 0, "gt": 0, "reference": 0, "candidate": 0})
            entry["sequences"] += 1
            entry["gt"] += s["reference"]["gt"]["total"]
            entry["reference"] += s["reference"]["gt"]["assigned"]
            entry["candidate"] += s["candidate"]["gt"]["assigned"]

    return {"schemaVersion": SCHEMA, "event": spec["event"], "domain": spec["domain"],
            "bootstrap": spec["bootstrap"], "partitions": partitions, "arms": arms,
            "paired": {"deltaAssigned": delta_assigned,
                       "deltaAssociation": (delta_assigned / total) if total else None,
                       "deltaAssociationCI95": interval, "bootstrapDrawsUsed": len(draws),
                       "deltaVehicleTracks": delta("vehicleTracks", "total"),
                       "deltaFragmentedGt": delta("expectedVehicleGt", "fragmented"),
                       "deltaFragmentMavi": delta("vehicleTracks", "fragment"),
                       "deltaUnmatchedMavi": delta("vehicleTracks", "unmatched"),
                       "costPerExtraAssigned": costs, "transitions": transitions},
            "strata": {"heightBand": strata("heightBand"), "nativeClass": strata("nativeClass"),
                       "conditions": condition_strata},
            "sequences": sequences}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="tools.benchmarks.h4.compare")
    p.add_argument("--spec", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)
    try:
        require(not args.out.exists(), "output_exists")
        spec = json.loads(args.spec.read_text(encoding="utf-8"))
        document = compare(spec)
        data = canonical_json(document)
        args.out.write_bytes(data)
        print(sha256_hex(data))
    except S32Error as exc:
        print(f"refused {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
