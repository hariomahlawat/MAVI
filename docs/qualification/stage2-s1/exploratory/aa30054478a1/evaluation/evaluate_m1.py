"""Evaluate F4 exploratory outputs with the checker rules of exact M1, and derive the
F4-C configuration by the merged execution plan §7 (master §10.2, §10.7).

Usage: evaluate_m1.py b3a <output.json> | b3b <output.json> | derive <b3b-output.json>...

Reads outputs only; never writes to them. Everything is computed in seconds for the
derivation (ms / 1000, ticks / stopwatchFrequency), with no intermediate rounding.
"""
import hashlib
import json
import math
import sys
from pathlib import Path

M1 = "aa30054478a13248d8bbfb6e1a228359b7d8645d"
WORKTREE = Path("/tmp/claude-0/-home-user-MAVI/28469bf1-0d06-57ec-a9bc-448aec8e4cc0/scratchpad/m1c")
sys.path.insert(0, str(WORKTREE / "tools/qualification"))
import s1_evidence as e  # noqa: E402  (the M1 checker, from the M1 worktree)

VARIANT = "linux-x86_64-cpu"


def checker() -> "e._Checker":
    record = {"measurements": {}, "hosts": {}, "units": {"B3": {"measurements": []}}, "retainedArtifacts": {}, "runs": {}}
    return e._Checker(record, WORKTREE, verify_git=True)


def header_problems(output: dict, schema: str) -> list[str]:
    """The per-output header rules of `_Checker._b3_output` at M1 (s1_evidence.py
    lines 1725-1736), applied verbatim with measured SHA = M1."""
    env = output["environment"]
    rules = (
        (f"schema is not {schema}", output["schema"] == schema),
        ("status is not complete", output["status"] == "complete"),
        ("the run was not authoritative", output["authoritative"] is True and output["nonAuthoritativeReasons"] == []),
        (f"it ran on {output['variant']}, not {VARIANT}", output["variant"] == VARIANT),
        (f"it measured {env['gitSha']}, not {M1}", env["gitSha"] == M1),
        ("its tree was not clean", env["gitWorkingTreeClean"] == "true"),
        ("its commit object is absent", env["gitCommitObjectPresent"] == "true"),
        ("its database is not qualification grade", env["isQualificationGradeDatabase"] == "true"),
    )
    return [label for label, holds in rules if not holds]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def findings(c) -> list[dict]:
    return [{"unit": f.unit, "code": f.code, "detail": f.detail} for f in c.findings]


def ceil_to(x: float, g: int) -> int:
    return int(g * math.ceil(x / g))


def evaluate_b3a(path: Path) -> dict:
    output = json.loads(path.read_text())
    c = checker()
    c._b3a_content(output, VARIANT)
    default_ms, maximum_ms = e.worker_request_timeout_bounds_ms(c.source_at(M1, e.WORKER_SETTINGS_RELATIVE).decode())
    bound = min(e.HANDOFF_BOUND_MS, default_ms / 2)
    stats = e.timing_stats(output["samples"], "handOffMs")
    replay = e.timing_stats(output["samples"], "replayMs")
    result = {
        "file": str(path), "sha256": sha256(path),
        "headerProblems": header_problems(output, e.HANDOFF_OUTPUT_SCHEMA),
        "contentFindings": findings(c),
        "handOffStats": stats, "replayStats": replay,
        "workerRequestTimeoutMsAtM1": default_ms, "outputWorkerRequestTimeoutMs": output.get("workerRequestTimeoutMs"),
        "handOffBoundMs": bound,
        "boundHolds": stats is not None and stats["max"] <= bound,
        "samples": len(output["samples"]), "warmupSamples": sum(1 for s in output["samples"] if s["warmup"]),
        "shape": output["shape"], "finalizerHostEnabled": output["finalizerHostEnabled"],
        "host": output["host"], "environment": {k: output["environment"][k] for k in sorted(output["environment"])},
    }
    return result


def evaluate_b3b(path: Path) -> dict:
    output = json.loads(path.read_text())
    c = checker()
    committed = json.loads(c.source_at(M1, e.APPSETTINGS_RELATIVE).decode())["VisionFinalization"]
    barrier_sql = c._barrier_sql(M1)
    timeout = c._runtime_command_timeout_seconds(M1)
    derived = c._b3b_content(output, VARIANT, committed, barrier_sql, timeout)
    stats = {field: e.timing_stats(derived, field) for field in ("totalMs", "barrierHoldMs", "barrierWaitMs", "publishTransactionMs", "graphPersistenceMs", "graphSaveChangesMs", "graphBuildBracketMs")}
    samples = output["samples"]
    concurrency = output["concurrency"]
    return {
        "file": str(path), "sha256": sha256(path),
        "headerProblems": header_problems(output, e.FINALIZATION_OUTPUT_SCHEMA),
        "contentFindings": findings(c),
        "committedAtM1": committed, "barrierSqlAtM1": barrier_sql, "runtimeCommandTimeoutSecondsAtM1": timeout,
        "outputConfiguration": output["configuration"], "optionsSource": output["optionsSource"], "hostedServiceUsed": output["hostedServiceUsed"],
        "effectiveCommandTimeoutSeconds": output["effectiveCommandTimeoutSeconds"],
        "samples": len(samples), "warmupSamples": sum(1 for s in samples if s["warmup"]), "shape": output["shape"],
        "stats": stats,
        "halfMaxBoundMs": committed["MaximumFinalizationDurationSeconds"] * 1000 / 2,
        "perSample": [
            {
                "repeat": s["repeat"], "index": s["index"], "warmup": s["warmup"],
                "publications": s["publications"], "sequenceAllocations": s["sequenceAllocations"],
                "extensionCount": s["extensionCount"], "created": s["createdObjects"], "adopted": s["adoptedObjects"],
                "prematureVisibilityObserved": s["prematureVisibilityObserved"],
                "visibilityProbes": s["visibility"]["probes"], "detailProbes": s["visibility"]["detailProbes"],
                "detailAfterPublication": s["visibility"]["detailAfterPublication"],
                "apiErrorsDuringFinalization": s["apiContention"]["errorsDuringFinalization"],
                "rssPeakBytes": s["apiHostRss"]["peakBytes"], "cpuSeconds": s["apiProcessCpuSeconds"],
                "longestCommandMs": s["longestCommandMs"],
            }
            for s in samples
        ],
        "concurrency": {k: concurrency[k] for k in ("maxConcurrentFinalizations", "jobs", "maxLiveClaims", "secondClaimedBeforeFirstPublished", "overlapObserved", "overlapSnapshot", "overlapSnapshots")},
        "concurrencyProblems": e.concurrency_problems(concurrency, committed),
        "referenceSamples": len(output["reference"]["samples"]),
        "rejectedTimelines": len(output["rejectedTimelines"]),
        "host": output["host"],
    }


def derive(paths: list[Path]) -> dict:
    """Execution plan §7.0-§7.9 on every sample (warm-up included) of every output."""
    per_os: dict[str, dict] = {}
    pooled = {"S_batch": [], "G": [], "P": [], "T": []}
    for path in paths:
        output = json.loads(path.read_text())
        os_name = output["variant"]
        inputs = per_os.setdefault(os_name, {"S_batch": [], "G": [], "P": [], "T": [], "files": []})
        inputs["files"].append(str(path))
        for s in output["samples"]:
            timeline = s["publicationTimeline"]
            freq = timeline["stopwatchFrequency"]
            ticks = timeline["ticks"]
            bracket = s["graphBuildBracket"]
            values = {
                "S_batch": [ms / 1000.0 for ms in s["perBatchWallMs"]],
                "G": [(bracket["publishEntered"] - bracket["lastExtensionReturned"]) / freq],
                "P": [(ticks["commitCompleted"] - ticks["transactionBegun"]) / freq],
                "T": [e.iso_milliseconds(s["acceptedAtUtc"], timeline["commitCompletedUtc"]) / 1000.0],
            }
            for key, vs in values.items():
                inputs[key].extend(vs)
                pooled[key].extend(vs)

    def summary(values: list[float]) -> dict:
        return {"n": len(values), "max": max(values), "p95": e.nearest_rank(values, 0.95)}

    table = {os_name: {k: summary(v) for k, v in inputs.items() if k != "files"} | {"files": inputs["files"]} for os_name, inputs in per_os.items()}
    governing = {k: max(per_os, key=lambda o: max(per_os[o][k])) for k in pooled}
    s_batch_max, g_max, p_max, t_max = (max(pooled[k]) for k in ("S_batch", "G", "P", "T"))
    m1 = {"SealingBatchSize": 200, "ClaimExtensionSeconds": 300, "ClaimSeconds": 300, "MaximumFinalizationAttempts": 3,
          "MaximumFinalizationDurationSeconds": 21600, "PollIntervalSeconds": 5, "MaxConcurrentFinalizations": 1, "PayloadCleanupGraceSeconds": 0}
    stops = []
    if s_batch_max > 75:
        stops.append(f"S_batch_max {s_batch_max} s > 75 s (§7.1)")
    e_req = 4 * max(s_batch_max, g_max + p_max)
    extension = max(m1["ClaimExtensionSeconds"], ceil_to(e_req, 30))
    claim = max(m1["ClaimSeconds"], extension, ceil_to(4 * t_max, 60))
    attempts = m1["MaximumFinalizationAttempts"]
    m_req = max(attempts * (claim + 2 * t_max), 2 * t_max)
    m_bound = ceil_to(m_req, 300)
    if m_bound > 21600:
        stops.append(f"M_bound {m_bound} s > 21600 s (§7.5)")
    maximum = m1["MaximumFinalizationDurationSeconds"]
    effective = maximum + claim + m1["PollIntervalSeconds"]
    if effective > 86400:
        stops.append(f"effective bound {effective} s > 86400 s (§7.7)")
    return {
        "inputsSeconds": {"S_batch_max": s_batch_max, "G_max": g_max, "P_max": p_max, "T_max": t_max,
                          "S_batch_p95": e.nearest_rank(pooled["S_batch"], 0.95), "T_p95": e.nearest_rank(pooled["T"], 0.95),
                          "firstClaimInterval": "not retained at M1", "extensionOverhead": "not measured at M1"},
        "perOs": table, "governingOs": governing,
        "arithmetic": {
            "E_req": e_req, "ceilTo(E_req,30)": ceil_to(e_req, 30),
            "4*T_max": 4 * t_max, "ceilTo(4*T_max,60)": ceil_to(4 * t_max, 60),
            "M_req": m_req, "M_bound": m_bound,
        },
        "m1Values": m1,
        "frozen": {"SealingBatchSize": 200, "ClaimExtensionSeconds": extension, "ClaimSeconds": claim,
                   "MaximumFinalizationAttempts": attempts, "MaximumFinalizationDurationSeconds": maximum,
                   "PollIntervalSeconds": 5, "MaxConcurrentFinalizations": 1, "PayloadCleanupGraceSeconds": 0},
        "effectiveBoundSeconds": effective, "effectiveBoundHours": effective / 3600,
        "neverLowered": all((v if k != "SealingBatchSize" else 200) >= m1[k] for k, v in
                            {"SealingBatchSize": 200, "ClaimExtensionSeconds": extension, "ClaimSeconds": claim,
                             "MaximumFinalizationAttempts": attempts, "MaximumFinalizationDurationSeconds": maximum}.items()),
        "stops": stops,
    }


if __name__ == "__main__":
    mode, *files = sys.argv[1:]
    result = {"b3a": lambda: evaluate_b3a(Path(files[0])), "b3b": lambda: evaluate_b3b(Path(files[0])), "derive": lambda: derive([Path(f) for f in files])}[mode]()
    print(json.dumps(result, indent=2, default=str))
