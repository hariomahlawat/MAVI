"""Stage 4 LRLPR-26 aggregation experiment, phases 3-5: DEV selection, one EVAL scoring, secondary analyses.

Development only; bound to the FROZEN rules and split by SHA-256 (``lrlpr26_read.rules``). Every phase first
re-verifies the inventory, the train archive and manifest SHA-256, the aggregate annotation digest, the parameter
file, the OC1-S files, the committed code, and the three OCR passes (phase 1, phase 2, timing pass 2T), which must
be canonical-equal; any failure stops the run as INVALID with the failure code.

* ``select`` (phase 3) scores DEV tracks only and writes ``selection.json`` (text-free counts).
* ``evaluate`` (phase 4) refuses to run unless ``selection.json`` byte-equals the committed
  ``docs/qualification/stage4/lrlpr-26-selection-v1.json`` and its SHA-256 equals ``--selection-sha``. It is the first
  phase that compares EVAL truth. It writes ``eval.json``; aggregation CPU goes to ``eval-timing.json``.
* ``secondary`` (phase 5) needs ``eval.json``: block-split re-selection and scoring, and the frame budget.
* ``verify`` recomputes selection, evaluation and secondary from the verified inputs and requires byte equality.

    python tools/benchmarks/plates/lrlpr26_eval.py select --inventory INV --reads P1 P2 P2T --out SELECTION
    python tools/benchmarks/plates/lrlpr26_eval.py evaluate --inventory INV --reads P1 P2 P2T --selection SELECTION
        --selection-sha SHA --out EVAL
    python tools/benchmarks/plates/lrlpr26_eval.py secondary --inventory INV --reads P1 P2 P2T --selection SELECTION
        --eval EVAL --out SECONDARY
    python tools/benchmarks/plates/lrlpr26_eval.py verify --inventory INV --reads P1 P2 P2T --selection SELECTION
        --eval EVAL --secondary SECONDARY
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lrlpr26_core as core  # noqa: E402
import lrlpr26_read as rd  # noqa: E402
from lrlpr26_core import require  # noqa: E402

COMMITTED_SELECTION = rd.STAGE4 / "lrlpr-26-selection-v1.json"
KIND_SELECTION, KIND_EVAL, KIND_SECONDARY = "lrlpr26-selection", "lrlpr26-eval", "lrlpr26-secondary"


# verified inputs ----------------------------------------------------------------------------------------------------

def load_inputs(inventory_path: Path, reads: list[Path], need_truth_for: str) -> dict[str, Any]:
    """Every binding re-checked; ``need_truth_for`` is 'DEV' (phase 3) or 'ALL' (phases 4-5)."""
    from tools.benchmarks.datasets import lrlpr26

    inv, inv_sha = rd.load_inventory(inventory_path)
    record, rules_sha = rd.rules()
    split, split_sha = rd.split_document(record)
    git = rd.require_clean_code(inv)
    floor = rd.floor_of(record)
    require(floor == inv["ocrConfidenceFloor"], "lrlpr26_floor_not_inventory")
    require(rd.model_files(record) == inv["models"], "lrlpr26_models_not_inventory")
    require(lrlpr26.sha_file(lrlpr26.TRAIN_ARCHIVE) == inv["dataset"]["trainArchive"]["sha256"]
            == record["data"]["trainArchiveSha256"], "lrlpr26_archive_sha_mismatch")
    require(lrlpr26.sha_file(lrlpr26.TRAIN_MANIFEST) == inv["dataset"]["trainManifest"]["sha256"]
            == record["data"]["trainManifestSha256"], "lrlpr26_manifest_sha_mismatch")
    require(len(reads) == 3, "lrlpr26_three_passes_required")
    verified = [rd.verify(path, inventory_path) for path in reads]
    core.require_repeat_equal([(v["pass"], v["index"]["records"]["canonicalSha256"]) for v in verified])
    tracks = split["tracks"]
    wanted = {t for t, row in tracks.items() if row[0] == "DEV"} if need_truth_for == "DEV" else set(tracks)
    truths = lrlpr26.read_truths(wanted, inv["dataset"]["annotationsDigest"])
    rows = {r["trackId"]: r["frames"] for r in verified[0]["rows"]}
    return {"inventory": inv, "inventorySha256": inv_sha, "rules": record, "rulesSha256": rules_sha, "split": split,
            "splitSha256": split_sha, "git": git, "floor": floor, "readings": rows, "truths": truths,
            "reads": {v["pass"]: {"indexSha256": rd.sha_file(p / "index.json"),
                                  "recordsCanonicalSha256": v["index"]["records"]["canonicalSha256"],
                                  "machine": v["index"]["machine"], "execution": v["index"]["execution"],
                                  "wallSeconds": v["index"]["wallSeconds"]} for v, p in zip(verified, reads)},
            "timings": [rd.load(p / "timings.json") for p in reads]}


def identity(inputs: dict[str, Any]) -> dict[str, Any]:
    return {"rulesSha256": inputs["rulesSha256"], "splitSha256": inputs["splitSha256"],
            "inventorySha256": inputs["inventorySha256"], "parametersSha256": inputs["inventory"]["parametersSha256"],
            "ocrConfidenceFloor": inputs["floor"], "models": inputs["inventory"]["models"],
            "reads": {k: {"indexSha256": v["indexSha256"], "recordsCanonicalSha256": v["recordsCanonicalSha256"]}
                      for k, v in inputs["reads"].items()}}


def by_number(ids) -> list[str]:
    return sorted(ids, key=lambda t: int(t.split("_")[1]))


# phase 3: DEV selection ---------------------------------------------------------------------------------------------

def selection_document(inputs: dict[str, Any], side_index: int, side: str, label: str) -> dict[str, Any]:
    """Select C and A on the tracks whose split column ``side_index`` equals ``side`` (0: main split, 2: block)."""
    ids = by_number(t for t, row in inputs["split"]["tracks"].items() if row[side_index] == side)
    accepted = {t: core.accept_all(inputs["readings"][t], inputs["floor"], include_grid=True) for t in ids}
    names = [n for n in core.config_names() if n != "U-raw"]
    table = {n: core.measures([core.track_outcome(accepted[t][n], inputs["truths"][t]) for t in ids]) for n in names}
    families = {"C": core.select_family("C", {k: table[f"C(k={k})"] for k in core.C_GRID}),
                "A": core.select_family("A", {tau: table[f"A(tau={tau})"] for tau in core.A_GRID})}
    return {"population": {"split": label, "side": side, "tracks": len(ids)}, "families": families,
            "measures": table}


def select(inventory_path: Path, reads: list[Path]) -> dict[str, Any]:
    inputs = load_inputs(inventory_path, reads, "DEV")
    return {"kind": KIND_SELECTION, **identity(inputs), **selection_document(inputs, 0, "DEV", "main")}


def load_selection(path: Path, expected_sha: str, inputs: dict[str, Any]) -> dict[str, Any]:
    require(path.is_file(), "lrlpr26_selection_missing")
    data = path.read_bytes()
    require(core.sha_bytes(data) == expected_sha, "lrlpr26_selection_sha_mismatch")
    require(COMMITTED_SELECTION.exists() and COMMITTED_SELECTION.read_bytes() == data,
            "lrlpr26_selection_not_committed")
    tracked = subprocess.run(["git", "-C", str(rd.ROOT), "ls-files", "--error-unmatch",
                              str(COMMITTED_SELECTION.relative_to(rd.ROOT))], capture_output=True, check=False)
    require(tracked.returncode == 0, "lrlpr26_selection_not_committed")
    selection = json.loads(data)
    require(selection.get("kind") == KIND_SELECTION, "lrlpr26_selection_invalid")
    for key, value in identity(inputs).items():
        require(selection[key] == value, f"lrlpr26_selection_binding:{key}")
    return selection


# phase 4: EVAL ------------------------------------------------------------------------------------------------------

def configuration(selection_families: dict[str, Any]) -> dict[str, Any]:
    return {"C*": {"k": selection_families["C"]["selected"], "status": selection_families["C"]["status"]},
            "A*": {"tau": selection_families["A"]["selected"], "status": selection_families["A"]["status"]}}


def score(inputs: dict[str, Any], ids: list[str], config: dict[str, Any], frames: int = 5) -> dict[str, Any]:
    """Accepted texts → per-track outcomes for S1, SB, U, C*, A*, U-raw."""
    out: dict[str, list[dict[str, int]]] = {}
    for t in ids:
        accepted = core.accept_all(inputs["readings"][t], inputs["floor"], k=config["C*"]["k"],
                                   tau=config["A*"]["tau"], frames=frames)
        for name in ("S1", "SB", "U", "C*", "A*", "U-raw"):
            out.setdefault(name, []).append(core.track_outcome(accepted[name], inputs["truths"][t]))
    return out


def group_index(inputs: dict[str, Any], ids: list[str]) -> tuple[list[int], int]:
    raw = [inputs["split"]["tracks"][t][1] for t in ids]
    mapping = {g: i for i, g in enumerate(sorted(set(raw)))}
    return [mapping[g] for g in raw], len(mapping)


def statistics_block(inputs: dict[str, Any], ids: list[str], outcomes: dict[str, list[dict[str, int]]],
                     comparisons: list[tuple[str, str]]) -> dict[str, Any]:
    groups, count = group_index(inputs, ids)
    weights = core.resample_weights(count)
    sums = {name: core.group_sums(rows, groups, count) for name, rows in outcomes.items()}
    boot = {f"{x} - {y}": core.paired_bootstrap(sums[x], sums[y], weights) for x, y in comparisons}
    mcn = {f"{x} vs {y}": {"correct": core.mcnemar([o["correct"] for o in outcomes[x]], [o["correct"] for o in outcomes[y]]),
                           "incorrect": core.mcnemar([o["incorrect"] for o in outcomes[x]],
                                                     [o["incorrect"] for o in outcomes[y]])}
           for x, y in comparisons}
    return {"groups": count, "resamples": core.BOOTSTRAP_RESAMPLES, "seed": core.BOOTSTRAP_SEED, "bootstrap": boot,
            "mcnemarExploratory": mcn}


def measures_by_stratum(inputs: dict[str, Any], ids: list[str], outcomes: dict[str, list[dict[str, int]]]):
    strata = {t: inputs["inventory"]["tracks"][t]["stratum"] for t in ids}
    out = {"overall": {name: core.measures(rows) for name, rows in outcomes.items()}}
    for stratum in sorted(set(strata.values())):
        mask = [strata[t] == stratum for t in ids]
        out[stratum] = {name: core.measures([o for o, m in zip(rows, mask) if m]) for name, rows in outcomes.items()}
    return out


COMPARISONS = [("C*", "U"), ("A*", "U"), ("S1", "U"), ("SB", "U"), ("U-raw", "U"), ("A*", "C*")]


def costs(inputs: dict[str, Any], ids: list[str], frames: int = 5) -> dict[str, Any]:
    per_pass = []
    for label, timings in zip(rd.PASSES, inputs["timings"]):
        five = [sum(f["readCpuMs"] for f in timings[t]["frames"][:frames]) for t in ids]
        last = [timings[t]["frames"][4]["readCpuMs"] for t in ids]
        decode = [sum(f["decodeCpuMs"] for f in timings[t]["frames"][:frames]) for t in ids]
        per_pass.append({"pass": label, "ocrCpuMsPerTrack": sum(five) / len(ids),
                         "s1OcrCpuMsPerTrack": sum(last) / len(ids), "decodeCpuMsPerTrack": sum(decode) / len(ids)})
    return {"ocrCallsPerTrack": {"S1": 1, "others": frames}, "passes": per_pass,
            "medianOcrCpuMsPerTrack": statistics.median(p["ocrCpuMsPerTrack"] for p in per_pass),
            "medianS1OcrCpuMsPerTrack": statistics.median(p["s1OcrCpuMsPerTrack"] for p in per_pass),
            "medianDecodeCpuMsPerTrack": statistics.median(p["decodeCpuMsPerTrack"] for p in per_pass),
            "machine": inputs["reads"]["phase1"]["machine"], "execution": inputs["reads"]["phase1"]["execution"],
            "passWallSeconds": {k: v["wallSeconds"] for k, v in inputs["reads"].items()}}


def evaluate_document(inputs: dict[str, Any], selection: dict[str, Any], selection_sha: str) -> dict[str, Any]:
    ids = by_number(t for t, row in inputs["split"]["tracks"].items() if row[0] == "EVAL")
    config = configuration(selection["families"])
    outcomes = score(inputs, ids, config)
    stats = statistics_block(inputs, ids, outcomes, COMPARISONS)
    boot = stats["bootstrap"]
    c1 = core.family_step1(config["C*"]["status"], boot["C* - U"])
    a1 = core.family_step1(config["A*"]["status"], boot["A* - U"])
    return {"kind": KIND_EVAL, **identity(inputs), "selectionSha256": selection_sha, "configuration": config,
            "population": {"split": "main", "side": "EVAL", "tracks": len(ids)},
            "measures": measures_by_stratum(inputs, ids, outcomes), "statistics": stats,
            "decision": core.decide(c1, a1, boot["A* - C*"]), "costs": costs(inputs, ids)}


def aggregation_timing(inputs: dict[str, Any], ids: list[str], config: dict[str, Any]) -> dict[str, Any]:
    runs = []
    for _ in range(3):
        cpu = time.process_time()
        score(inputs, ids, config)
        runs.append((time.process_time() - cpu) * 1000 / len(ids))
    return {"note": "CPU ms per track to compute all six policies' accepted texts and outcomes (includes "
                    "normalisation), three repetitions", "runsMsPerTrack": runs,
            "medianMsPerTrack": statistics.median(runs)}


# phase 5: secondary -------------------------------------------------------------------------------------------------

def secondary_document(inputs: dict[str, Any], selection: dict[str, Any], selection_sha: str,
                       eval_sha: str) -> dict[str, Any]:
    block_selection = selection_document(inputs, 2, "DEV", "block")
    block_config = configuration(block_selection["families"])
    block_ids = by_number(t for t, row in inputs["split"]["tracks"].items() if row[2] == "EVAL")
    block_outcomes = score(inputs, block_ids, block_config)
    block_stats = statistics_block(inputs, block_ids, block_outcomes, COMPARISONS)
    boot = block_stats["bootstrap"]
    block_decision = core.decide(core.family_step1(block_config["C*"]["status"], boot["C* - U"]),
                                 core.family_step1(block_config["A*"]["status"], boot["A* - U"]), boot["A* - C*"])
    config = configuration(selection["families"])
    eval_ids = by_number(t for t, row in inputs["split"]["tracks"].items() if row[0] == "EVAL")
    budget = {}
    for frames in (1, 3, 5):
        outcomes = score(inputs, eval_ids, config, frames=frames)
        budget[str(frames)] = {"measures": {name: core.measures(outcomes[name]) for name in ("SB", "U", "C*", "A*")},
                               "costs": costs(inputs, eval_ids, frames=frames)}
    return {"kind": KIND_SECONDARY, **identity(inputs), "selectionSha256": selection_sha, "evalSha256": eval_sha,
            "status": "secondary; reported only; never feeds the decision",
            "blockSplit": {"selection": block_selection, "configuration": block_config,
                           "population": {"split": "block", "side": "EVAL", "tracks": len(block_ids),
                                          "excluded": sum(1 for row in inputs["split"]["tracks"].values()
                                                          if row[2] == "EXCLUDED")},
                           "measures": measures_by_stratum(inputs, block_ids, block_outcomes),
                           "statistics": block_stats, "decisionRuleApplied": block_decision},
            "frameBudget": {"configuration": config, "byFrames": budget}}


# commands -----------------------------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    commands = {}
    for name in ("select", "evaluate", "secondary", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--inventory", type=Path, required=True)
        p.add_argument("--reads", type=Path, nargs=3, required=True)
        commands[name] = p
    commands["select"].add_argument("--out", type=Path, required=True)
    for name in ("evaluate", "secondary", "verify"):
        commands[name].add_argument("--selection", type=Path, required=True)
        commands[name].add_argument("--selection-sha", required=True)
    commands["evaluate"].add_argument("--out", type=Path, required=True)
    commands["secondary"].add_argument("--eval", type=Path, required=True)
    commands["secondary"].add_argument("--out", type=Path, required=True)
    commands["verify"].add_argument("--eval", type=Path, required=True)
    commands["verify"].add_argument("--secondary", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "select":
        require(not args.out.exists(), "lrlpr26_output_exists")
        print(f"{args.out} sha256={rd.dump(args.out, select(args.inventory, args.reads))}")
        return 0
    inputs = load_inputs(args.inventory, args.reads, "ALL")
    selection = load_selection(args.selection, args.selection_sha, inputs)
    if args.command == "evaluate":
        require(not args.out.exists(), "lrlpr26_output_exists")
        document = evaluate_document(inputs, selection, args.selection_sha)
        print(f"{args.out} sha256={rd.dump(args.out, document)} outcome={document['decision']['outcome']}")
        ids = by_number(t for t, row in inputs["split"]["tracks"].items() if row[0] == "EVAL")
        timing = args.out.with_name(args.out.stem + "-timing.json")
        print(f"{timing} sha256={rd.dump(timing, aggregation_timing(inputs, ids, document['configuration']))}")
    elif args.command == "secondary":
        require(not args.out.exists(), "lrlpr26_output_exists")
        eval_data = args.eval.read_bytes()
        require(json.loads(eval_data)["selectionSha256"] == args.selection_sha, "lrlpr26_eval_selection_binding")
        document = secondary_document(inputs, selection, args.selection_sha, core.sha_bytes(eval_data))
        print(f"{args.out} sha256={rd.dump(args.out, document)}")
    else:
        require(core.canonical(select_from_inputs(inputs)) == args.selection.read_bytes(),
                "lrlpr26_verify_selection_differs")
        eval_data = args.eval.read_bytes()
        require(core.canonical(evaluate_document(inputs, selection, args.selection_sha)) == eval_data,
                "lrlpr26_verify_eval_differs")
        require(core.canonical(secondary_document(inputs, selection, args.selection_sha, core.sha_bytes(eval_data)))
                == args.secondary.read_bytes(), "lrlpr26_verify_secondary_differs")
        print(json.dumps({"verified": True, "selectionSha256": args.selection_sha,
                          "evalSha256": core.sha_bytes(eval_data),
                          "secondarySha256": core.sha_bytes(args.secondary.read_bytes())}))
    return 0


def select_from_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    """Phase-3 selection recomputed from already-verified inputs (truth restricted to DEV tracks)."""
    dev = {t for t, row in inputs["split"]["tracks"].items() if row[0] == "DEV"}
    restricted = {**inputs, "truths": {t: v for t, v in inputs["truths"].items() if t in dev}}
    return {"kind": KIND_SELECTION, **identity(restricted), **selection_document(restricted, 0, "DEV", "main")}


if __name__ == "__main__":
    raise SystemExit(main())
