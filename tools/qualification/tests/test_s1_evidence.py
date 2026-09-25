"""The S1 evidence checker refuses every incomplete or inconsistent PASS.

Each negative test starts from a record the checker accepts in full, breaks
exactly one thing, and asserts the specific finding, so a checker that rejects
everything, or accepts everything, fails this suite.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
from pathlib import Path

import pytest

import s1_evidence
from s1_evidence import UNIT_REQUIREMENTS, UNITS, check_record, invalidated_units, required_variants, suite_counts_from_junit

SHA = "a" * 40
MERGE = "b" * 40
OTHER = "c" * 40
PROFILE_SHA = "503225be736d9622ed110aa69e49a83dde4ae02c858d5e8fa41e527b1c4b23fb"
# Every retained file of the fixture lies under the measured SHA's evidence folder.
EVIDENCE = f"{s1_evidence.EVIDENCE_ROOT}{SHA[:12]}/"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _value_for(requirement: s1_evidence.MeasurementRequirement) -> float:
    if requirement.limit_op is None:
        return 1024.0
    return {
        "==": requirement.limit_value,
        "<=": requirement.limit_value / 2 if requirement.limit_value else 0.0,
        "<": requirement.limit_value / 2,
        ">=": requirement.limit_value,
        ">": requirement.limit_value + 1,
    }[requirement.limit_op]


def _isolated_probes() -> list:
    return [{"host": host, "port": port, "reachable": False} for host, port in s1_evidence.ISOLATION_PROBE_TARGETS]


def complete_record() -> dict:
    """A record in which every unit is a complete, consistent PASS."""
    record = {
        "schemaVersion": "s1-qualification-evidence-v1",
        "measuredSha": SHA,
        "identity": {
            "profileId": "phase1-detection-tracking-v1",
            "profileVersion": "1.2.0-candidate",
            "profileSha256": PROFILE_SHA,
            "selectorVersion": "evidence-selector-v1-two-tier",
            "scorerVersion": "quality-v2",
            "encoderVersion": "evidence-jpeg-ladder-v1",
            "completionSchemaVersion": "3.0",
            "digestVersion": "3",
        },
        "hosts": {
            "runner-linux": {
                "cpuModel": "AMD EPYC 7763", "physicalCores": 2, "logicalCores": 4, "ramBytes": 16 * 2**30,
                "os": "Ubuntu", "osBuild": "24.04", "stagingFilesystem": "ext4",
                "acceptedEvidenceFilesystem": "ext4", "storageClass": "ssd",
                "storageClassEvidence": "/sys/class/block/sda/queue/rotational=0",
            },
            "runner-windows": {
                "cpuModel": "AMD EPYC 7763", "physicalCores": 2, "logicalCores": 4, "ramBytes": 16 * 2**30,
                "os": "Windows Server", "osBuild": "2022", "stagingFilesystem": "NTFS",
                "acceptedEvidenceFilesystem": "NTFS", "storageClass": "ssd",
                "storageClassEvidence": "Get-PhysicalDisk MediaType=SSD BusType=SATA",
            },
        },
        "runs": {
            "task10": {"kind": "workflow", "workflow": "task10-runtime-qualification.yml", "runId": 1, "headSha": SHA, "conclusion": "success"},
            "quality": {"kind": "workflow", "workflow": "quality-gate.yml", "runId": 2, "headSha": SHA, "conclusion": "success"},
            "host": {"kind": "local", "host": "runner-linux", "command": "python tools/qualification/s1_memory.py", "cleanTree": True, "headSha": SHA, "conclusion": "success"},
        },
        "retainedArtifacts": {},
        "suites": {},
        "pairedVariantSkips": [],
        "measurements": {},
        "units": {},
        "closure": None,
        "frozenConfiguration": _frozen_configuration(),
        "disconnected": {
            "runtimeBundleSourceCommit": SHA,
            "maviVisionWheelSha256": "d" * 64,
            "installProfile": "development",
            "variant": "windows-x86_64-cpu",
            "isolationMethod": "adapter disabled",
            "isolationBefore": {"passed": True, "proxyEnvironmentAbsent": True, "probes": _isolated_probes()},
            "isolationAfter": {"passed": True, "proxyEnvironmentAbsent": True, "probes": _isolated_probes()},
        },
    }
    for name in UNITS:
        required = UNIT_REQUIREMENTS[name]
        unit = {"verdict": "PASS", "suites": [], "measurements": [], "artifacts": [], "nonClaims": []}
        for suite in required.suites:
            for variant in [v or "any" for v in required_variants(required, suite)]:
                suite_id = f"{name}:{suite}:{variant}"
                junit = f"junit:{suite_id}"
                run = "quality" if variant == "any" else "task10"
                path = f"{variant}/junit/{suite.split(':', 1)[1]}.xml" if suite.startswith("task10:") else _result_path(suite, suite_id)
                record["retainedArtifacts"][junit] = {"path": path, "sha256": _sha256(suite_id), "run": run}
                if variant != "any":
                    record["retainedArtifacts"][junit]["variant"] = variant
                record["suites"][suite_id] = {
                    "suite": suite, "variant": variant, "run": run, "junitArtifact": junit,
                    "passed": 1 + len(PROVING_TESTS.get(suite, ())), "skipped": 0, "failed": 0, "errors": 0,
                    "passedTests": [f"{_case_class(suite)}::test_ok", *PROVING_TESTS.get(suite, ())], "skippedTests": [],
                }
                unit["suites"].append(suite_id)
        for requirement in required.measurements:
            measurement_id = f"{name}:{requirement.metric}"
            entry = {"metric": requirement.metric, "value": _value_for(requirement), "unit": requirement.unit, "host": "runner-linux", "run": "host"}
            if requirement.timing:
                entry.update(samples=30, repeats=3, warmupExcluded=True, stats={"min": 10.0, "p50": 20.0, "p95": 30.0, "max": 40.0, "p50RunSpread": 1.0})
            entry["artifact"] = required.artifacts[0]
            for variant in s1_evidence.QUALIFIED_CPU_VARIANTS:
                for base, artifact_base, field in s1_evidence.B3_TIMINGS:
                    if requirement.metric == f"{base}.{variant}":
                        # Every B3 timing is the recomputation of its producer's raw samples.
                        entry["artifact"] = f"{artifact_base}.{variant}"
                        stats = s1_evidence.timing_stats(_b3_derived(artifact_base), field)
                        entry.update(value=stats["max"], samples=stats["n"], repeats=stats["repeats"], warmupExcluded=stats["warmupExcluded"],
                                     stats={key: stats[key] for key in ("min", "p50", "p95", "max", "p50RunSpread")})
                if name == "B2" and requirement.metric.endswith("." + variant):
                    entry["artifact"] = f"{s1_evidence.B2_OUTPUT_ARTIFACT}.{variant}"
                if requirement.metric.endswith("." + variant):
                    entry["host"] = HOST_OF[variant]
            if requirement.metric == "b3.worker-request-timeout-ms":
                entry["value"] = 30000.0
            if requirement.metric.startswith("b2.process-memory-per-live-track-slope."):
                entry["value"] = _live_fit(LIVE_POINTS)["slope"]
            record["measurements"][measurement_id] = entry
            unit["measurements"].append(measurement_id)
        for artifact in required.artifacts:
            record["retainedArtifacts"][artifact] = {"path": f"records/{artifact}.json", "sha256": _sha256(artifact), "run": "host"}
            if artifact.startswith("b6."):
                _, variant, record_name = artifact.split(".", 2)
                record["retainedArtifacts"][artifact] = {"path": f"task10/{variant}/{record_name}", "sha256": _sha256(artifact), "run": "task10", "variant": variant}
            unit["artifacts"].append(artifact)
        record["units"][name] = unit
    # §11 runs on the disconnected Windows host, as the operator.
    record["runs"]["offline"] = {"kind": "local", "host": "runner-windows", "command": "operator path", "cleanTree": True, "headSha": SHA, "conclusion": "success"}
    for artifact in required_disconnected_artifacts():
        record["retainedArtifacts"][artifact]["run"] = "offline"
    for outcome in s1_evidence.DISCONNECTED_OUTCOMES:
        artifact = f"disconnected.{outcome}"
        record["retainedArtifacts"][artifact] = {"path": f"records/{artifact}.log", "sha256": _sha256(artifact), "run": "offline"}
    # Each B3 harness output is its own local run, stamped with the harness run id.
    for variant in s1_evidence.QUALIFIED_CPU_VARIANTS:
        for base in (s1_evidence.HANDOFF_OUTPUT_ARTIFACT, s1_evidence.FINALIZATION_OUTPUT_ARTIFACT, s1_evidence.CRASH_OUTPUT_ARTIFACT):
            run_id = f"{base}.{variant}"
            record["runs"][run_id] = {
                "kind": "local", "host": HOST_OF[variant], "command": f"dotnet test {base}", "cleanTree": True,
                "headSha": SHA, "conclusion": "success", "harnessRunId": f"{run_id}.run",
            }
            record["retainedArtifacts"][run_id]["run"] = run_id
    # A measurement comes from the run that retained its artifact.
    for entry in record["measurements"].values():
        entry["run"] = record["retainedArtifacts"][entry["artifact"]]["run"]
    # Every retained file lives under the measured SHA's evidence folder (F4 plan §22).
    for entry in record["retainedArtifacts"].values():
        entry["path"] = EVIDENCE + entry["path"]
    return record


def required_disconnected_artifacts() -> tuple:
    return UNIT_REQUIREMENTS["DISCONNECTED"].artifacts


def on_main_repo(root: Path) -> str:
    """A git repository at ``root`` whose ``main`` holds one commit; its SHA."""
    root.mkdir(parents=True, exist_ok=True)
    git = lambda *args: subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()  # noqa: E731
    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@example.invalid")
    git("config", "user.name", "t")
    (root / "measured.txt").write_text("measured", encoding="utf-8")
    # The committed sources the checker reads at the measured SHA.
    for relative in MEASURED_SOURCES:
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_bytes((REPO_ROOT / relative).read_bytes())
    git("add", "measured.txt", *MEASURED_SOURCES)
    git("commit", "-qm", "measured")
    return git("rev-parse", "HEAD")


def _proving_sources() -> tuple[str, ...]:
    suites = {suite for mapping in s1_evidence.PROVING_TESTS_BY_UNIT.values() for tests in mapping.values() for suite, _ in tests}
    return tuple(sorted(suite if suite.endswith(".py") else suite + ".cs" for suite in suites))


MEASURED_SOURCES = (
    s1_evidence.WORKER_SETTINGS_RELATIVE,
    s1_evidence.B1_BASELINE_RELATIVE,
    s1_evidence.APPSETTINGS_RELATIVE,
    s1_evidence.BARRIER_SOURCE_RELATIVE,
    *_proving_sources(),
)


def with_sha(record: dict, sha: str) -> dict:
    """The record with every occurrence of the fixture SHA replaced, evidence folder included."""
    return json.loads(json.dumps(record).replace(SHA, sha).replace(EVIDENCE, f"{s1_evidence.EVIDENCE_ROOT}{sha[:12]}/"))


# The B3 proving tests, present in their suites' passed tests.
def _case_class(suite: str) -> str:
    """The class name a suite's results carry: a .NET TRX names the test class
    (``Mavi.IntegrationTests.ClassTests``), JUnit the cited file."""
    return ".".join(suite.split("/")[1:]) if suite.startswith("tests/") else suite


def _result_path(suite: str, suite_id: str) -> str:
    """Where the workflow writes a suite's results (the checker binds the path)."""
    if suite.startswith("task10:"):
        raise AssertionError("per-variant path")
    unique = f"quality/{abs(hash(suite_id))}"
    if suite.startswith("tests/"):
        return f"{unique}/trx/{suite.split('/')[1]}.trx"
    if suite.startswith("src/web/"):
        return f"{unique}/junit/mavi-web.xml"
    return f"{unique}/junit/python.xml"


def _proving_cases() -> dict[str, tuple[str, ...]]:
    """Every proving test of every unit, as the passed case its suite's result names."""
    cases: dict[str, list[str]] = {}
    for mapping in s1_evidence.PROVING_TESTS_BY_UNIT.values():
        for tests in mapping.values():
            for suite, test in tests:
                case = f"{_case_class(suite)}::{test}"
                if case not in cases.setdefault(suite, []):
                    cases[suite].append(case)
    return {suite: tuple(names) for suite, names in cases.items()}


PROVING_TESTS = _proving_cases()
REPO_ROOT = Path(__file__).resolve().parents[3]
HOST_OF = {"linux-x86_64-cpu": "runner-linux", "windows-x86_64-cpu": "runner-windows"}
LIVE_POINTS = [[4, 50_000_000.0], [8, 51_000_000.0], [16, 53_000_000.0], [32, 57_000_000.0], [64, 65_000_000.0]]


def codes(record: dict, **options) -> set[tuple[str, str]]:
    # Rule tests are structural unless they supply a repository to verify against.
    options.setdefault("structural_only", "repo_root" not in options)
    return {(finding.unit, finding.code) for finding in check_record(record, **options)}


def structural(record: dict) -> list:
    return check_record(record, structural_only=True)


TRX_TEST_TYPE = "13cdc9d9-ddb5-4fa4-a97d-d965ccfc6d4b"


def _trx_for(entry: dict) -> str:
    """A TRX as ``dotnet test --logger trx`` writes it (xUnit skips are NotExecuted)."""
    results, definitions = [], []
    tests = [(t, "Passed") for t in entry["passedTests"]] + [(t, "NotExecuted") for t in entry["skippedTests"]]
    for index, (test, outcome) in enumerate(tests):
        classname, name = test.split("::", 1)
        test_id = f"00000000-0000-0000-0000-{index:012d}"
        results.append(f'<UnitTestResult testId="{test_id}" testName="{classname}.{name}" testType="{TRX_TEST_TYPE}" outcome="{outcome}" />')
        definitions.append(
            f'<UnitTest name="{classname}.{name}" id="{test_id}"><Execution id="{index}" />'
            f'<TestMethod adapterTypeName="executor://xunit/VsTestRunner3/netcore/" className="{classname}" name="{name.split("(", 1)[0]}" /></UnitTest>'
        )
    return (
        '<?xml version="1.0" encoding="utf-8"?><TestRun xmlns="http://microsoft.com/schemas/VisualStudio/TeamTest/2010">'
        f'<Results>{"".join(results)}</Results><TestDefinitions>{"".join(definitions)}</TestDefinitions></TestRun>'
    )


def _junit_for(entry: dict) -> str:
    if entry["suite"].startswith("tests/"):
        return _trx_for(entry)
    cases = [f'<testcase classname="{t.split("::")[0]}" name="{t.split("::", 1)[1]}"/>' for t in entry["passedTests"]]
    cases += [f'<testcase classname="{t.split("::")[0]}" name="{t.split("::", 1)[1]}"><skipped/></testcase>' for t in entry["skippedTests"]]
    name = "" if entry["variant"] == "any" else f' name="{entry["variant"]}"'
    return f'<?xml version="1.0"?><testsuites><testsuite{name}>' + "".join(cases) + "</testsuite></testsuites>"


def _live_fit(points: list) -> dict:
    xs = [float(level) for level, _ in points]
    ys = [float(mean) for _, mean in points]
    x_mean, y_mean = sum(xs) / len(xs), sum(ys) / len(ys)
    slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)) / sum((x - x_mean) ** 2 for x in xs)
    return {"points": points, "slope": slope, "intercept": y_mean - slope * x_mean, "r2": 0.99, "stderr": 1.0}


def _b2_output(record: dict, variant: str) -> str:
    suffix = "." + variant
    values = {}
    for mid in record["units"]["B2"]["measurements"]:
        entry = record["measurements"][mid]
        if entry["metric"].endswith(suffix):
            values[entry["metric"][: -len(suffix)]] = {"value": entry["value"], "unit": entry["unit"]}
    fit = _live_fit(LIVE_POINTS)
    slope = values.get("b2.process-memory-per-live-track-slope", {}).get("value", fit["slope"])
    held = 100_000
    return json.dumps({
        "schema": "s1-b2-memory-derived-v1",
        "identity": {"sourceSha": record["units"]["B2"].get("measuredSha", record["measuredSha"]), "cleanTree": True},
        "runtime": {"runtimeVariant": variant},
        "host": {key: record["hosts"][HOST_OF[variant]][key] for key in s1_evidence.MEASURED_HOST_FIELDS},
        "measurements": values,
        "liveLevelFit": fit,
        "boundOneReconciliation": {
            "perLiveProcessSlopeBytes": slope,
            "accountedEncodedEvidenceBytesMax": held,
            "encodedEvidenceBoundBytes": 544 * 1024,
            "accountedTrajectoryPointsMax": 150,
            "trajectoryChunkPoints": 4096,
            "unaccountedPerLiveBytes": slope - held,
        },
    })


def _lifecycle_output(record: dict, variant: str) -> str:
    return json.dumps({
        "schema": "s1-b2-staging-lifecycle-v1",
        "identity": {"sourceSha": record["units"]["B2"].get("measuredSha", record["measuredSha"]), "cleanTree": True},
        "runtime": {"runtimeVariant": variant},
        "workload": {"tracker": "bytetrack"},
        "checks": {check: True for check in s1_evidence.STAGING_LIFECYCLE_CHECKS},
    })


def _disconnected_run(record: dict) -> str:
    return json.dumps({
        "schema": s1_evidence.DISCONNECTED_RUN_SCHEMA,
        "activation": dict(s1_evidence.DISCONNECTED_ACTIVATION),
        "sourceCommit": record["units"]["DISCONNECTED"].get("measuredSha", record["measuredSha"]),
        "variant": record["disconnected"]["variant"],
        "installProfile": "development",
        "outboundConnectionAttempts": [],
        "outcomes": {name: {"passed": True, "evidence": f"disconnected.{name}"} for name in s1_evidence.DISCONNECTED_OUTCOMES},
    })


# --------------------------------------------------------------------------- B3 outputs (F4 plan §8, §9, §11)
FREQUENCY = 1_000_000  # the fixture's Stopwatch.Frequency: microsecond ticks


def _committed_configuration() -> dict:
    return json.loads((REPO_ROOT / s1_evidence.APPSETTINGS_RELATIVE).read_text(encoding="utf-8"))["VisionFinalization"]


def _barrier_sql() -> str:
    text = (REPO_ROOT / s1_evidence.BARRIER_SOURCE_RELATIVE).read_text(encoding="utf-8")
    return re.search(r'PublicationExclusiveSql\s*=\s*"([^"]+)"', text).group(1)


def _frozen_configuration() -> dict:
    committed = _committed_configuration()
    return {
        "values": {key: committed[key] for key in s1_evidence.FROZEN_CONFIGURATION_KEYS},
        "effectiveBoundSeconds": committed["MaximumFinalizationDurationSeconds"] + committed["ClaimSeconds"] + committed["PollIntervalSeconds"],
        "activationDefault": committed["Enabled"],
        "freezeDecision": "docs/qualification/stage2-s1/f4-configuration-freeze.md",
    }


def _repeats(per_repeat: int = 10):
    """Three repeats, each one excluded warm-up then ``per_repeat`` measured samples."""
    for repeat in range(3):
        for index in range(per_repeat + 1):
            yield repeat, index, index == 0


def _b3a_samples() -> list:
    return [
        {
            "repeat": repeat, "index": index, "warmup": warmup,
            "handOffMs": 9000.0 if warmup else 2000.0 + repeat * 10 + index * 7.5,
            "replayMs": 800.0 if warmup else 300.0 + index,
            "httpStatus": 200, "state": "finalizing", "tracksSubmitted": 10_000, "jobStatus": "Finalizing",
            "payloadRows": 1, "publishedRows": 0, "acceptedEvidenceFiles": 0, "acceptedAtPresent": True,
            "claimTripleNull": True, "stagedObjects": 50_000, "replayState": "finalizing",
            "requestBodyBytes": 25_000_000, "payloadBytes": 24_000_000, "apiRssDeltaBytes": 50_000_000,
            "submissionTimings": {"validationMs": 900.0, "payloadEncodingMs": 300.0, "persistenceMs": 500.0},
        }
        for repeat, index, warmup in _repeats()
    ]


def _timeline(repeat: int, index: int) -> dict:
    base = 1_000_000_000 * (repeat * 20 + index + 1)
    persistence = 15_000_000 + index * 1_000
    ticks = {
        "transactionBegun": base,
        "rowLockAcquired": base + 1_000,
        "graphPersistenceStart": base + 2_000,
        "graphSavingChanges": base + 2_500_000,
        "graphSavedChanges": base + 2_000 + persistence - 1_000,
        "graphPersistenceEnd": base + 2_000 + persistence,
    }
    end = ticks["graphPersistenceEnd"]
    ticks.update(barrierCommandStarted=end + 100, barrierAcquired=end + 150, commitStarted=end + 1_500_000, commitCompleted=end + 1_700_000 + index * 10)
    return {
        "stopwatchFrequency": FREQUENCY, "ticks": ticks, "transactionId": f"tx-{repeat}-{index}", "connectionId": f"conn-{repeat}",
        "barrierCommandText": _barrier_sql(), "transition": "Published", "committed": True,
        "commitCompletedUtc": f"2026-09-25T08:{2 + repeat:02d}:{index:02d}.500000+00:00",
    }


def _b3b_samples() -> list:
    batch = _committed_configuration()["SealingBatchSize"]
    samples = []
    for repeat, index, warmup in _repeats():
        timeline = _timeline(repeat, index)
        base = timeline["ticks"]["transactionBegun"]
        samples.append({
            "repeat": repeat, "index": index, "warmup": warmup,
            "acceptedAtUtc": "2026-09-25T08:00:00+00:00",
            "publicationTimeline": timeline,
            "graphBuildBracket": {"lastExtensionReturned": base - 400_000, "publishEntered": base - 100},
            "bracketProofs": {proof: True for proof in s1_evidence.BRACKET_PROOFS},
            "publications": 1, "visibilitySequences": 1, "prematureVisibilityObserved": 0,
            "extensionCount": -(-50_000 // batch) + 1, "createdObjects": 50_000, "adoptedObjects": 0,
            "longestCommandMs": 1200.0, "claimAcquisitionMs": 4000.0, "payloadLoadMs": 800.0,
            "payloadRevalidationAndPlanMs": 1500.0, "sealWallMs": 60_000.0, "perBatchWallMs": [240.0, 250.0],
        })
    return samples


def _b3_derived(base: str) -> list:
    """The per-sample values the checker recomputes from a harness output."""
    if base == s1_evidence.HANDOFF_OUTPUT_ARTIFACT:
        return _b3a_samples()
    derived = []
    for sample in _b3b_samples():
        values = s1_evidence.derive_timeline(sample["publicationTimeline"])
        values["totalMs"] = s1_evidence.iso_milliseconds(sample["acceptedAtUtc"], sample["publicationTimeline"]["commitCompletedUtc"])
        derived.append({"repeat": sample["repeat"], "index": sample["index"], "warmup": sample["warmup"], **values})
    return derived


def _b3_common(record: dict, base: str, variant: str, schema: str) -> dict:
    host = record["hosts"][HOST_OF[variant]]
    return {
        "schema": schema, "status": "complete", "authoritative": True, "nonAuthoritativeReasons": [],
        "runId": record["runs"][f"{base}.{variant}"]["harnessRunId"], "variant": variant,
        "environment": {
            "gitSha": record["units"]["B3"].get("measuredSha", record["measuredSha"]), "gitWorkingTreeClean": "true",
            "gitCommitObjectPresent": "true", "isQualificationGradeDatabase": "true", "postgresVersion": "18.6",
        },
        "host": {key: host[key] for key in s1_evidence.B3_HOST_FIELDS},
    }


def _b3a_output(record: dict, variant: str) -> str:
    timeout = next(m for m in record["measurements"].values() if m["metric"] == "b3.worker-request-timeout-ms")
    return json.dumps({
        **_b3_common(record, s1_evidence.HANDOFF_OUTPUT_ARTIFACT, variant, s1_evidence.HANDOFF_OUTPUT_SCHEMA),
        "shape": {"tracks": 10_000, "observations": 40_000, "stagedObjects": 50_000},
        "finalizerHostEnabled": False, "workerRequestTimeoutMs": timeout["value"],
        "samples": _b3a_samples(),
    })


def _b3b_output(record: dict, variant: str) -> str:
    configuration = dict(_committed_configuration(), Enabled=True)
    return json.dumps({
        **_b3_common(record, s1_evidence.FINALIZATION_OUTPUT_ARTIFACT, variant, s1_evidence.FINALIZATION_OUTPUT_SCHEMA),
        "shape": {"tracks": 10_000, "observations": 40_000, "stagedObjects": 50_000},
        "hostedServiceUsed": True, "optionsSource": "appsettings.json", "configuration": configuration,
        "barrierCommandText": _barrier_sql(), "effectiveCommandTimeoutSeconds": 30,
        "rejectedTimelines": [],
        "apiContention": {
            "endpoints": [{"endpoint": "/api/health", "baselineP95Ms": 4.0, "duringP95Ms": 9.0, "errors": 0}],
            "errorsDuringFinalization": 0,
        },
        "apiHostRss": {"samplesBytes": [300_000_000, 410_000_000], "peakBytes": 410_000_000},
        "apiProcessCpuSeconds": 120.5,
        "reference": {"samples": [{"publicationTimeline": _timeline(9, index)} for index in range(5)]},
        "samples": _b3b_samples(),
    })


def _crash_output(record: dict, variant: str) -> str:
    rows = [
        {
            "scenario": scenario, "passed": True, "finalState": "Completed", "publications": 1, "sequenceCount": 1,
            "expectedObjects": 50_000, "createdObjects": 30_000 if scenario == "host-death-mid-seal" else 50_000,
            "adoptedObjects": 20_000 if scenario == "host-death-mid-seal" else 0,
            "killPoint": {"afterSealedObjects": 20_000} if scenario == "host-death-mid-seal" else {"phase": scenario},
            "restartLatencyMs": 2500.0, "orphanBytes": 0,
        }
        for scenario in s1_evidence.CRASH_H_SCENARIOS
    ]
    return json.dumps({**_b3_common(record, s1_evidence.CRASH_OUTPUT_ARTIFACT, variant, s1_evidence.CRASH_OUTPUT_SCHEMA), "rows": rows})


def _dependency_diff(record: dict) -> str:
    sha = record["units"]["DISCONNECTED"].get("measuredSha", record["measuredSha"])
    return json.dumps({"schema": "s1-disconnected-dependency-diff-v1", "fromSha": "d" * 40, "toSha": sha, "addedDependencies": []})


def _connect_trace(record: dict) -> str:
    sha = record["units"]["DISCONNECTED"].get("measuredSha", record["measuredSha"])
    return json.dumps({
        "schema": "s1-disconnected-connect-trace-v1", "sourceCommit": sha, "method": "strace -f -e trace=connect",
        "attempts": [{"address": "127.0.0.1", "port": 5432}, {"address": "::1", "port": 62153}, {"address": "/run/postgresql/.s.PGSQL.5432", "port": None}],
    })


def _runtime_manifests(record: dict) -> str:
    sha = record["units"]["DISCONNECTED"].get("measuredSha", record["measuredSha"])
    return json.dumps({
        "schema": "s1-disconnected-runtime-manifests-v1", "sourceCommit": sha,
        "manifests": [{"path": "models/manifests/rtmdet-m-coco-phase1-v1.json", "sha256": "e" * 64}],
    })

def _bundle_manifest(record: dict) -> str:
    block = record["disconnected"]
    return json.dumps({
        "sourceCommit": block["runtimeBundleSourceCommit"],
        "platformVariant": block["variant"],
        "artifacts": [
            {"relativePath": "wheels/mavi_vision-0.1.0-py3-none-any.whl", "package": "mavi-vision", "sha256": block["maviVisionWheelSha256"]},
            {"relativePath": "wheels/numpy.whl", "package": "numpy", "sha256": "f" * 64},
        ],
    })


def materialize(record: dict, root: Path) -> dict:
    """Write every retained artifact under ``root`` with real content and hashes:
    JUnit XML matching each suite result, and a matching sealing output."""
    by_junit = {entry["junitArtifact"]: entry for entry in record["suites"].values()}
    for artifact_id, entry in record["retainedArtifacts"].items():
        if artifact_id in by_junit:
            content = _junit_for(by_junit[artifact_id])
        elif artifact_id.startswith(s1_evidence.HANDOFF_OUTPUT_ARTIFACT + "."):
            content = _b3a_output(record, artifact_id[len(s1_evidence.HANDOFF_OUTPUT_ARTIFACT) + 1:])
        elif artifact_id.startswith(s1_evidence.FINALIZATION_OUTPUT_ARTIFACT + "."):
            content = _b3b_output(record, artifact_id[len(s1_evidence.FINALIZATION_OUTPUT_ARTIFACT) + 1:])
        elif artifact_id.startswith(s1_evidence.CRASH_OUTPUT_ARTIFACT + "."):
            content = _crash_output(record, artifact_id[len(s1_evidence.CRASH_OUTPUT_ARTIFACT) + 1:])
        elif artifact_id == "disconnected.dependency-diff":
            content = _dependency_diff(record)
        elif artifact_id == "disconnected.connect-trace":
            content = _connect_trace(record)
        elif artifact_id == "disconnected.runtime-manifests":
            content = _runtime_manifests(record)
        elif artifact_id.endswith(".production-composition-qualification.json"):
            sha = record["units"]["B6"].get("measuredSha", record["measuredSha"])
            content = json.dumps({"status": "passed", "headSha": sha, "platform": artifact_id.split(".", 2)[1]})
        elif artifact_id.endswith(".bytetrack-qualification.json"):
            variant = artifact_id.split(".", 2)[1]
            sha = record["units"]["B6"].get("measuredSha", record["measuredSha"])
            content = json.dumps({"status": "passed", "runtimeVariant": variant, "headSha": sha, "testResult": "passed"})
        elif artifact_id in ("disconnected.isolation-before", "disconnected.isolation-after"):
            phase = "isolationBefore" if artifact_id.endswith("before") else "isolationAfter"
            content = json.dumps(record["disconnected"][phase])
        elif artifact_id.startswith(s1_evidence.B2_LIFECYCLE_ARTIFACT + "."):
            content = _lifecycle_output(record, artifact_id[len(s1_evidence.B2_LIFECYCLE_ARTIFACT) + 1:])
        elif artifact_id.startswith(s1_evidence.B2_OUTPUT_ARTIFACT + "."):
            content = _b2_output(record, artifact_id.split(".", 1)[1].split(".", 1)[1])
        elif artifact_id == "disconnected.run-record":
            content = _disconnected_run(record)
        elif artifact_id == "disconnected.runtime-bundle-manifest":
            content = _bundle_manifest(record)
        elif artifact_id == "b5.real-video-record":
            content = _b5_video(record)
        elif artifact_id == "b5.visual-qa-record":
            content = _b5_qa(record)
        elif artifact_id == "b1.cross-variant-comparison":
            continue  # derived from the others, below
        else:
            content = artifact_id
        _write_artifact(root, entry, content)
    # The committed sources the checker reads from the repository (the
    # accepted baseline, the worker settings).
    for relative in MEASURED_SOURCES:
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_bytes((REPO_ROOT / relative).read_bytes())
    baseline = root / s1_evidence.B1_BASELINE_RELATIVE
    if "b1.cross-variant-comparison" in record["retainedArtifacts"]:
        _write_artifact(root, record["retainedArtifacts"]["b1.cross-variant-comparison"], _b1_comparison(record, baseline))
    return record


def _write_artifact(root: Path, entry: dict, content: str) -> None:
    path = root / entry["path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    entry["sha256"] = hashlib.sha256(content.encode("utf-8")).hexdigest()


def _b1_comparison(record: dict, baseline: Path) -> str:
    counts = {
        key: next(m["value"] for m in record["measurements"].values() if m["metric"] == metric)
        for metric, key in s1_evidence.B1_COUNTS.items()
    }
    return json.dumps({
        "schema": "s1-b1-comparison-v1",
        "identity": {"sourceSha": record["units"]["B1"].get("measuredSha", record["measuredSha"]), "cleanTree": True},
        "identityProblems": [],
        "inputs": {
            "linux": {"sha256": record["retainedArtifacts"]["b1.real-clip-measurement"]["sha256"]},
            "baseline": {"sha256": hashlib.sha256(baseline.read_bytes()).hexdigest()},
        },
        "counts": counts,
        "traces": [],
    })


def _b5_video(record: dict) -> str:
    count = int(next(m["value"] for m in record["measurements"].values() if m["metric"] == "b5.real-video-clips"))
    return json.dumps({
        "schema": s1_evidence.B5_VIDEO_SCHEMA,
        "sourceCommit": record["units"]["B5"].get("measuredSha", record["measuredSha"]),
        "clips": [
            {"clip": f"clip-{index}", "sha256": f"{index + 1:064x}", "label": "real-video",
             **{check: True for check in s1_evidence.B5_CLIP_CHECKS}}
            for index in range(count)
        ],
    })


def _b5_qa(record: dict) -> str:
    return json.dumps({
        "schema": s1_evidence.B5_QA_SCHEMA,
        "sourceCommit": record["units"]["B5"].get("measuredSha", record["measuredSha"]),
        "items": [
            {"id": "evidence-set-review", "label": "real-video", "passed": True},
            {"id": "unavailable-crop", "label": "fixture", "passed": True},
            *({"id": item, "label": "fixture", "passed": True} for item in s1_evidence.B5_QA_REQUIRED_ITEMS),
        ],
    })


# --------------------------------------------------------------------------- positive


def test_a_complete_record_passes_with_no_finding() -> None:
    assert structural(complete_record()) == []


def test_open_units_may_be_incomplete_and_are_not_errors() -> None:
    record = complete_record()
    record["units"]["B2"] = {"verdict": "OPEN", "suites": [], "measurements": [], "artifacts": [], "nonClaims": []}
    assert structural(record) == []
    # ... and the checker still reports what a PASS would need.
    missing = s1_evidence.open_requirements(record)["B2"]
    assert any("measurement_missing" in line for line in missing)


def test_the_complete_record_is_schema_valid_and_every_unit_is_required() -> None:
    record = complete_record()
    del record["units"]["DISCONNECTED"]
    assert ("record", "schema_invalid") in codes(record)


# --------------------------------------------------------------------------- identity/structure


@pytest.mark.parametrize("field", ["profileSha256", "selectorVersion", "encoderVersion", "digestVersion"])
def test_missing_identity_field_is_refused(field: str) -> None:
    record = complete_record()
    del record["identity"][field]
    assert ("record", "schema_invalid") in codes(record)


def test_missing_host_identity_field_is_refused() -> None:
    record = complete_record()
    del record["hosts"]["runner-linux"]["acceptedEvidenceFilesystem"]
    assert ("record", "schema_invalid") in codes(record)


def test_a_measurement_on_an_unknown_host_is_refused() -> None:
    record = complete_record()
    record["measurements"]["B2:b2.completion-peak-bytes.linux-x86_64-cpu"]["host"] = "somewhere"
    assert ("B2", "host_missing") in codes(record)


def test_an_invalid_verdict_is_refused() -> None:
    record = complete_record()
    record["units"]["B1"]["verdict"] = "PASSED"
    assert ("record", "schema_invalid") in codes(record)


# --------------------------------------------------------------------------- head_sha binding


def test_a_run_on_another_sha_cannot_carry_a_pass() -> None:
    record = complete_record()
    record["runs"]["task10"]["headSha"] = OTHER
    found = codes(record)
    assert ("B1", "head_sha_mismatch") in found
    assert ("B6", "head_sha_mismatch") in found


def test_a_cancelled_or_failed_run_cannot_carry_a_pass() -> None:
    record = complete_record()
    record["runs"]["task10"]["conclusion"] = "cancelled"
    assert ("B6", "run_not_successful") in codes(record)


def test_a_local_run_must_attest_a_clean_tree_and_a_known_host() -> None:
    record = complete_record()
    record["runs"]["host"]["cleanTree"] = False
    assert ("B2", "run_tree_not_clean") in codes(record)
    record = complete_record()
    record["runs"]["host"]["host"] = "unlisted"
    assert ("B2", "host_missing") in codes(record)


def test_a_unit_measured_on_its_own_sha_binds_to_that_sha() -> None:
    record = complete_record()
    record["units"]["B3"]["measuredSha"] = MERGE
    found = codes(record)
    assert ("B3", "head_sha_mismatch") in found
    assert ("B1", "head_sha_mismatch") not in found


# --------------------------------------------------------------------------- suites and skips


def test_a_failed_or_erroring_suite_cannot_carry_a_pass() -> None:
    record = complete_record()
    suite_id = record["units"]["B1"]["suites"][0]
    record["suites"][suite_id]["failed"] = 1
    assert ("B1", "suite_failed") in codes(record)


def test_a_suite_that_passed_nothing_is_not_evidence() -> None:
    record = complete_record()
    suite_id = record["units"]["B4"]["suites"][0]
    record["suites"][suite_id].update(passed=0, passedTests=[])
    assert ("B4", "suite_empty") in codes(record)


def test_an_unpaired_skip_cannot_carry_a_pass() -> None:
    record = complete_record()
    suite_id = record["units"]["B1"]["suites"][2]
    record["suites"][suite_id].update(skipped=1, skippedTests=["tests.test_evidence_encoder::test_golden"])
    # Not on the §3.1 list at all, so it is refused before pairing is considered.
    assert ("B1", "skip_not_approved") in codes(record)


def _paired_record(counterpart_passed: bool) -> dict:
    record = complete_record()
    windows = next(sid for sid in record["units"]["B2"]["suites"] if "test_track_lifecycle.py:windows" in sid)
    linux = windows.replace("windows-x86_64-cpu", "linux-x86_64-cpu")
    test = "tests.test_track_lifecycle::test_many_live_tracks_need_no_descriptor_each"
    record["suites"][windows].update(skipped=1, skippedTests=[test])
    if counterpart_passed:
        record["suites"][linux].update(passed=2, passedTests=[*record["suites"][linux]["passedTests"], test])
    record["pairedVariantSkips"].append({
        "test": test, "skipsOn": "windows-x86_64-cpu",
        "counterpartSuite": "src/vision/tests/test_track_lifecycle.py",
        "counterpartTest": test, "counterpartVariant": "linux-x86_64-cpu",
    })
    return record


def test_a_paired_variant_skip_passes_only_with_its_counterpart_positively_passing() -> None:
    assert structural(_paired_record(counterpart_passed=True)) == []
    assert ("B2", "skip_not_permitted") in codes(_paired_record(counterpart_passed=False))


def test_a_pair_cannot_name_its_own_variant_as_the_counterpart() -> None:
    record = _paired_record(counterpart_passed=True)
    record["pairedVariantSkips"][0]["counterpartVariant"] = "windows-x86_64-cpu"
    assert ("B2", "skip_not_permitted") in codes(record)


def test_counts_must_match_the_named_tests() -> None:
    record = complete_record()
    suite_id = record["units"]["B1"]["suites"][0]
    record["suites"][suite_id]["passed"] = 5
    assert ("B1", "count_inconsistent") in codes(record)


def test_a_missing_per_variant_result_cannot_carry_a_pass() -> None:
    record = complete_record()
    windows = next(sid for sid in record["units"]["B1"]["suites"] if sid.endswith("windows-x86_64-cpu"))
    record["units"]["B1"]["suites"].remove(windows)
    assert ("B1", "variant_result_missing") in codes(record)


def test_a_cited_suite_must_exist() -> None:
    record = complete_record()
    record["units"]["B5"]["suites"].append("nowhere")
    assert ("B5", "suite_missing") in codes(record)


def test_junit_for_a_suite_must_be_retained() -> None:
    record = complete_record()
    suite_id = record["units"]["B6"]["suites"][0]
    del record["retainedArtifacts"][record["suites"][suite_id]["junitArtifact"]]
    assert ("B6", "junit_not_retained") in codes(record)


# --------------------------------------------------------------------------- measurements


def test_every_plan_metric_is_required_for_a_pass() -> None:
    for name, requirement in UNIT_REQUIREMENTS.items():
        for metric in requirement.measurements:
            record = complete_record()
            record["units"][name]["measurements"].remove(f"{name}:{metric.metric}")
            assert (name, "measurement_missing") in codes(record), metric.metric


@pytest.mark.parametrize(
    ("unit", "metric", "value"),
    [
        ("B2", "b2.per-retired-traced-bytes-slope.linux-x86_64-cpu", 16 * 1024 + 1),
        ("B2", "b2.process-memory-retired-slope.linux-x86_64-cpu", 20_000),
        ("B2", "b2.per-live-held-evidence-bytes-max.linux-x86_64-cpu", 544 * 1024 + 1),
        ("B2", "b2.retired-slope-crop-variation.linux-x86_64-cpu", 0.11),
        ("B1", "b1.real-clip-parameter-note-mismatches", 1),
        ("B3", "b3.python-worst-shape-body-bytes", 40 * 1024 * 1024 + 1),
        ("B5", "b5.real-video-clips", 1),
    ],
)
def test_the_plan_limit_binds_whatever_the_record_declares(unit: str, metric: str, value: float) -> None:
    record = complete_record()
    entry = record["measurements"][f"{unit}:{metric}"]
    entry["value"] = value
    # A record that loosens its own limit to match still fails the plan's.
    entry["limit"] = {"op": "<=", "value": value * 10 + 10, "source": "made up"}
    assert (unit, "limit_violated") in codes(record)


def test_a_declared_limit_is_also_enforced() -> None:
    record = complete_record()
    entry = record["measurements"]["B2:b2.completion-peak-bytes.linux-x86_64-cpu"]
    entry["limit"] = {"op": "<=", "value": 10, "source": "recorded baseline"}
    assert ("B2", "limit_violated") in codes(record)


def test_a_recorded_only_metric_has_no_threshold() -> None:
    record = complete_record()
    record["measurements"]["B2:b2.completion-peak-bytes.linux-x86_64-cpu"]["value"] = 10**12
    assert structural(record) == []


@pytest.mark.parametrize(
    "mutate",
    [
        lambda e: e.update(samples=29),
        lambda e: e.update(repeats=2),
        lambda e: e.update(warmupExcluded=False),
        lambda e: e["stats"].pop("p50RunSpread"),
        lambda e: e.pop("stats"),
        lambda e: e["stats"].update(p95=5.0),
    ],
)
def test_timing_needs_samples_repeats_warmup_percentiles_and_spread(mutate) -> None:
    record = complete_record()
    mutate(record["measurements"]["B3:b3a.hand-off-wall-ms.linux-x86_64-cpu"])
    found = codes(record)
    assert ("B3", "timing_incomplete") in found or ("B3", "timing_inconsistent") in found


def test_b3a_max_hand_off_above_15_s_is_refused() -> None:
    # F4 plan §8.4: the hand-off max is at most 15 s (2x headroom against the 30 s worker timeout).
    for variant in s1_evidence.QUALIFIED_CPU_VARIANTS:
        record = complete_record()
        record["measurements"][f"B3:b3a.hand-off-wall-ms.{variant}"]["stats"]["max"] = 15_001.0
        assert ("B3", "hand_off_bound_violated") in codes(record), variant
        record["measurements"][f"B3:b3a.hand-off-wall-ms.{variant}"]["stats"]["max"] = 15_000.0
        assert ("B3", "hand_off_bound_violated") not in codes(record)


def test_b3b_max_above_half_the_frozen_maximum_duration_is_refused() -> None:
    record = complete_record()
    half = record["frozenConfiguration"]["values"]["MaximumFinalizationDurationSeconds"] * 1000.0 / 2
    entry = record["measurements"]["B3:b3b.total-hand-off-to-publication-ms.windows-x86_64-cpu"]
    entry["stats"]["max"] = half + 1
    assert ("B3", "finalization_bound_violated") in codes(record)
    entry["stats"]["max"] = half
    assert ("B3", "finalization_bound_violated") not in codes(record)


def test_a_measurement_unit_must_match_the_plan() -> None:
    record = complete_record()
    record["measurements"]["B2:b2.per-retired-traced-bytes-slope.linux-x86_64-cpu"]["unit"] = "bytes"
    assert ("B2", "measurement_unit_mismatch") in codes(record)


# --------------------------------------------------------------------------- artifacts


def test_every_required_artifact_is_needed() -> None:
    for name, requirement in UNIT_REQUIREMENTS.items():
        for artifact in requirement.artifacts:
            record = complete_record()
            record["units"][name]["artifacts"].remove(artifact)
            assert (name, "artifact_missing") in codes(record), artifact


def test_an_artifact_without_a_hash_is_refused() -> None:
    record = complete_record()
    del record["retainedArtifacts"]["b2.memory-harness-output.linux-x86_64-cpu"]["sha256"]
    assert ("record", "schema_invalid") in codes(record)


def test_retained_files_are_verified_against_their_hash(tmp_path: Path) -> None:
    record = materialize(complete_record(), tmp_path)
    assert check_record(record, repo_root=tmp_path, verify_git=False) == []
    (tmp_path / record["retainedArtifacts"]["b1.real-clip-measurement"]["path"]).write_bytes(b"edited")
    assert ("B1", "artifact_hash_mismatch") in codes(record, repo_root=tmp_path, verify_git=False)
    (tmp_path / record["retainedArtifacts"]["b1.real-clip-measurement"]["path"]).unlink()
    assert ("B1", "artifact_file_missing") in codes(record, repo_root=tmp_path, verify_git=False)


def test_an_artifact_path_cannot_escape_the_repository(tmp_path: Path) -> None:
    record = complete_record()
    for entry in record["retainedArtifacts"].values():
        path = tmp_path / "repo" / entry["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
        entry["sha256"] = hashlib.sha256(b"x").hexdigest()
    (tmp_path / "outside.json").write_bytes(b"x")
    record["retainedArtifacts"]["b1.real-clip-measurement"]["path"] = "../outside.json"
    assert ("B1", "artifact_file_missing") in codes(record, repo_root=tmp_path / "repo", verify_git=False)


# --------------------------------------------------------------------------- disconnected


def test_the_disconnected_run_must_use_a_bundle_of_the_measured_code() -> None:
    record = complete_record()
    record["disconnected"]["runtimeBundleSourceCommit"] = OTHER
    assert ("DISCONNECTED", "runtime_bundle_not_measured_code") in codes(record)


@pytest.mark.parametrize("phase", ["isolationBefore", "isolationAfter"])
def test_isolation_must_be_evidenced_before_and_after(phase: str) -> None:
    record = complete_record()
    record["disconnected"][phase]["probes"][0]["reachable"] = True
    assert ("DISCONNECTED", "isolation_not_evidenced") in codes(record)


def test_a_production_install_is_not_the_s1_disconnected_run() -> None:
    record = complete_record()
    record["disconnected"]["installProfile"] = "production"
    assert ("record", "schema_invalid") in codes(record)


def test_the_disconnected_block_is_required_for_its_pass() -> None:
    record = complete_record()
    del record["disconnected"]
    assert ("DISCONNECTED", "disconnected_record_missing") in codes(record)


# --------------------------------------------------------------------------- §2.1 / §2.2 / §2.3


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("src/vision/mavi_vision/evidence/selector.py", {"B1", "B2", "B3", "B5", "B6", "DISCONNECTED"}),
        ("src/vision/mavi_vision/worker/client.py", {"B3", "B4", "B5", "B6", "DISCONNECTED"}),
        ("src/vision/mavi_vision/common/control_plane.py", {"B3", "B4", "B5", "B6", "DISCONNECTED"}),
        ("src/platform/Mavi.Infrastructure/Storage/AcceptedEvidenceStore.cs", {"B3", "B4", "B5", "DISCONNECTED"}),
        ("src/web/mavi-web/src/features/video-review/TrackEvidenceSet.tsx", {"B5", "DISCONNECTED"}),
        ("src/vision/runtime/mmdetection-phase1-v1.json", {"B1", "B6", "DISCONNECTED"}),
        ("src/vision/config/pipelines/phase1-detection-tracking-v1.json", {"B1", "B2", "B3", "B5", "B6", "DISCONNECTED"}),
        # A behavior-bearing path the table does not map invalidates everything.
        ("src/vision/mavi_vision/embeddings/__init__.py", set(UNITS)),
        ("tools/phase1/promote_phase1_release.py", set(UNITS)),
        (".github/workflows/task10-runtime-qualification.yml", set(UNITS)),
        ("tests/fixtures/scene-analytics/scripted-corpus-v1.json", {"B1"}),
    ],
)
def test_the_invalidation_map_follows_the_plan(path: str, expected: set[str]) -> None:
    assert invalidated_units([path], {}) == {path: expected}


@pytest.mark.parametrize("path", ["docs/qualification/stage2-s1/summary.md", "README.md", "src/vision/tests/test_unrelated.py", ".github/workflows/other.yml"])
def test_documentation_and_uncited_tests_invalidate_nothing(path: str) -> None:
    assert invalidated_units([path], {}) == {}


def test_a_cited_test_invalidates_the_units_that_cite_it() -> None:
    cited = {"B1": {"src/vision/tests/test_evidence_encoder.py"}, "B3": {"src/vision/tests/test_evidence_encoder.py"}}
    assert invalidated_units(["src/vision/tests/test_evidence_encoder.py"], cited) == {
        "src/vision/tests/test_evidence_encoder.py": {"B1", "B3"},
    }
    tree = {"B2": {"tools/qualification/tests"}}
    assert invalidated_units(["tools/qualification/tests/test_s1_memory.py"], tree)["tools/qualification/tests/test_s1_memory.py"] >= {"B2"}


def test_a_closure_diff_on_the_surface_requires_the_affected_units_rerun() -> None:
    record = complete_record()
    record["closure"] = {"mergeSha": MERGE, "changedPaths": ["src/platform/Mavi.Api/Program.cs"]}
    found = codes(record)
    for unit in ("B3", "B4", "B5", "DISCONNECTED"):
        assert (unit, "closure_rerun_required") in found
    for unit in ("B1", "B2", "B6"):
        assert (unit, "closure_rerun_required") not in found


def test_a_closure_diff_touching_nothing_behavior_bearing_is_clean() -> None:
    record = complete_record()
    record["closure"] = {"mergeSha": MERGE, "changedPaths": ["docs/qualification/stage2-s1/s1-qualification-summary.md"]}
    assert structural(record) == []


def test_units_rerun_on_the_merge_sha_satisfy_the_closure_rule() -> None:
    record = complete_record()
    record["closure"] = {"mergeSha": MERGE, "changedPaths": ["src/web/mavi-web/src/App.tsx"]}
    record["runs"]["rerun"] = {"kind": "workflow", "workflow": "quality-gate.yml", "runId": 9, "headSha": MERGE, "conclusion": "success"}
    record["runs"]["rerun-host"] = {**record["runs"]["host"], "headSha": MERGE}
    for name in ("B5", "DISCONNECTED"):
        record["units"][name]["measuredSha"] = MERGE
    for suite_id in record["units"]["B5"]["suites"]:
        record["suites"][suite_id]["run"] = "rerun"
        record["retainedArtifacts"][record["suites"][suite_id]["junitArtifact"]]["run"] = "rerun"
    for artifact in record["units"]["B5"]["artifacts"] + record["units"]["DISCONNECTED"]["artifacts"]:
        record["retainedArtifacts"][artifact]["run"] = "rerun-host"
    for measurement_id in record["units"]["B5"]["measurements"]:
        record["measurements"][measurement_id]["run"] = "rerun-host"
    record["disconnected"]["runtimeBundleSourceCommit"] = MERGE
    assert structural(record) == []


def test_s1_closed_needs_every_unit_pass_and_a_closure() -> None:
    record = complete_record()
    record["s1Closed"] = True
    assert ("record", "closure_missing") in codes(record)
    record["closure"] = {"mergeSha": MERGE, "changedPaths": []}
    for index, workflow in enumerate(s1_evidence.POST_MERGE_WORKFLOWS):
        record["runs"][f"post-merge-{index}"] = {"kind": "workflow", "workflow": workflow, "runId": 100 + index, "headSha": MERGE, "conclusion": "success"}
    assert structural(record) == []
    record["units"]["B6"]["verdict"] = "OPEN"
    assert ("record", "closure_units_open") in codes(record)


def test_the_recorded_closure_diff_must_be_the_real_git_diff(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git = lambda *args: subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()  # noqa: E731
    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@example.invalid")
    git("config", "user.name", "t")
    (repo / "a.txt").write_text("a")
    git("add", ".")
    git("commit", "-qm", "measured")
    measured = git("rev-parse", "HEAD")
    (repo / "src" / "platform").mkdir(parents=True)
    (repo / "src" / "platform" / "x.cs").write_text("x")
    git("add", ".")
    git("commit", "-qm", "merge")
    merge = git("rev-parse", "HEAD")

    record = complete_record()
    record["measuredSha"] = measured
    for run in record["runs"].values():
        run["headSha"] = measured
    record["disconnected"]["runtimeBundleSourceCommit"] = measured
    record["closure"] = {"mergeSha": merge, "changedPaths": []}
    # Hiding the platform change from the recorded diff is caught...
    checker_findings = {(f.unit, f.code) for f in _check_with_git(record, repo)}
    assert ("record", "closure_diff_mismatch") in checker_findings
    # ... and the honest diff then demands the platform-affected reruns.
    record["closure"]["changedPaths"] = ["src/platform/x.cs"]
    honest = {(f.unit, f.code) for f in _check_with_git(record, repo)}
    assert ("record", "closure_diff_mismatch") not in honest
    assert ("B4", "closure_rerun_required") in honest


def _check_with_git(record: dict, repo: Path):
    checker = s1_evidence._Checker(record, repo)
    assert checker.schema()
    for name in UNITS:
        checker.unit(name)
    checker.closure()
    checker.verify_git_diff()
    # Artifact file verification is not under test here.
    return [f for f in checker.findings if not f.code.startswith("artifact_file")]


# --------------------------------------------------------------------------- JUnit


JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="5">
<testcase classname="tests.test_evidence_encoder" name="test_a" file="tests/test_evidence_encoder.py"/>
<testcase classname="tests.test_evidence_encoder" name="test_b"><skipped message="x"/></testcase>
<testcase classname="tests.test_evidence_selector" name="test_c"><failure message="boom"/></testcase>
<testcase classname="tests.test_evidence_selector" name="test_d"><error message="boom"/></testcase>
<testcase classname="tests.test_evidence_selector" name="test_e"/>
</testsuite></testsuites>
"""


def test_junit_counts_come_from_the_test_cases(tmp_path: Path) -> None:
    path = tmp_path / "j.xml"
    path.write_text(JUNIT)
    everything = suite_counts_from_junit(path)
    assert {k: everything[k] for k in ("passed", "skipped", "failed", "errors")} == {"passed": 2, "skipped": 1, "failed": 1, "errors": 1}
    encoder = suite_counts_from_junit(path, "src/vision/tests/test_evidence_encoder.py")
    assert encoder["passedTests"] == ["tests.test_evidence_encoder::test_a"]
    assert encoder["skippedTests"] == ["tests.test_evidence_encoder::test_b"]
    with pytest.raises(ValueError, match="junit_no_matching_testcases"):
        suite_counts_from_junit(path, "src/vision/tests/test_nothing.py")


def test_the_cli_exits_nonzero_on_a_finding(tmp_path: Path, capsys) -> None:
    # A closure-free record needs the measured commit on main and the retained files.
    root = tmp_path / "repo"
    sha = on_main_repo(root)
    good = tmp_path / "good.json"
    good.write_text(json.dumps(materialize(with_sha(complete_record(), sha), root)))
    assert s1_evidence.main(["check", str(good), "--repo-root", str(root)]) == 0
    # Without --repo-root the default is this repository, where the files do not
    # exist: it is verified (and refused), not skipped.
    capsys.readouterr()
    assert s1_evidence.main(["check", str(good)]) == 1
    output = capsys.readouterr().out
    assert "artifact_file_missing" in output and "repository_not_verified" not in output
    bad_record = materialize(with_sha(complete_record(), sha), root)
    bad_record["runs"]["task10"]["headSha"] = OTHER
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(bad_record))
    assert s1_evidence.main(["check", str(bad), "--repo-root", str(root)]) == 1
    assert "head_sha_mismatch" in capsys.readouterr().out


def test_the_schema_file_is_the_one_the_checker_loads() -> None:
    schema = json.loads(s1_evidence.SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["properties"]["schemaVersion"]["const"] == "s1-qualification-evidence-v1"
    assert set(schema["properties"]["units"]["required"]) == set(UNITS)
    assert copy.deepcopy(UNITS) == ("B1", "B2", "B3", "B4", "B5", "B6", "DISCONNECTED")


def test_platform_suites_are_required_once_and_worker_suites_on_every_variant() -> None:
    b3 = UNIT_REQUIREMENTS["B3"]
    assert required_variants(b3, "tests/Mavi.IntegrationTests/S1BoundAgreementTests") == (None,)
    assert required_variants(b3, "src/vision/tests/test_s1_bound_agreement.py") == s1_evidence.QUALIFIED_CPU_VARIANTS
    assert required_variants(UNIT_REQUIREMENTS["B4"], "src/vision/tests/test_worker_completion_v3.py") == (None,)


def test_a_worker_suite_missing_on_one_variant_blocks_its_unit() -> None:
    record = complete_record()
    suite_id = "B3:src/vision/tests/test_s1_bound_agreement.py:windows-x86_64-cpu"
    del record["suites"][suite_id]
    record["units"]["B3"]["suites"].remove(suite_id)
    failures = structural(record)
    assert ("B3", "variant_result_missing") in {(f.unit, f.code) for f in failures}


# --------------------------------------------------------------------------- review round 1


def test_a_pass_is_refused_without_repository_verification() -> None:
    assert ("record", "repository_not_verified") in {(f.unit, f.code) for f in check_record(complete_record())}
    record = complete_record()
    for unit in record["units"].values():
        unit["verdict"] = "OPEN"
    assert check_record(record) == []  # nothing claimed, nothing to verify


def test_a_fully_verified_record_passes(tmp_path: Path) -> None:
    record = materialize(complete_record(), tmp_path)
    assert check_record(record, repo_root=tmp_path, verify_git=False) == []


def test_suite_counts_must_be_the_retained_junit_counts(tmp_path: Path) -> None:
    record = materialize(complete_record(), tmp_path)
    suite_id = next(iter(record["units"]["B1"]["suites"]))
    entry = record["suites"][suite_id]
    entry.update(passed=2, passedTests=[*entry["passedTests"], "invented::test_never_run"])
    assert ("B1", "junit_count_mismatch") in codes(record, repo_root=tmp_path, verify_git=False)


def test_a_tampered_or_missing_junit_file_is_refused(tmp_path: Path) -> None:
    record = materialize(complete_record(), tmp_path)
    suite_id = next(iter(record["units"]["B1"]["suites"]))
    junit = record["retainedArtifacts"][record["suites"][suite_id]["junitArtifact"]]
    (tmp_path / junit["path"]).write_text("<testsuites/>", encoding="utf-8")
    assert ("B1", "artifact_hash_mismatch") in codes(record, repo_root=tmp_path, verify_git=False)
    (tmp_path / junit["path"]).unlink()
    assert ("B1", "artifact_file_missing") in codes(record, repo_root=tmp_path, verify_git=False)


def test_junit_must_come_from_the_run_the_result_cites() -> None:
    record = complete_record()
    suite_id = next(iter(record["units"]["B1"]["suites"]))
    record["retainedArtifacts"][record["suites"][suite_id]["junitArtifact"]]["run"] = "quality"
    assert ("B1", "junit_run_mismatch") in codes(record)


def test_a_paired_counterpart_must_be_cited_by_the_same_unit() -> None:
    record = _paired_record(counterpart_passed=True)
    linux = next(sid for sid in record["units"]["B2"]["suites"] if "test_track_lifecycle.py:linux" in sid)
    record["units"]["B2"]["suites"].remove(linux)
    record["suites"]["stale-counterpart"] = dict(record["suites"][linux])
    assert ("B2", "skip_not_permitted") in codes(record)


def test_a_paired_counterpart_from_a_stale_run_does_not_excuse_a_skip() -> None:
    record = _paired_record(counterpart_passed=True)
    linux = next(sid for sid in record["units"]["B2"]["suites"] if "test_track_lifecycle.py:linux" in sid)
    record["runs"]["stale"] = {**record["runs"]["task10"], "headSha": OTHER, "runId": 99}
    record["suites"][linux]["run"] = "stale"
    assert ("B2", "skip_not_permitted") in codes(record)


def test_the_worker_timeout_is_bound_to_the_worker_default() -> None:
    default_ms, maximum_ms = s1_evidence.worker_request_timeout_bounds_ms()
    assert (default_ms, maximum_ms) == (30_000.0, 120_000.0)
    record = complete_record()
    timeout = next(m for m in record["measurements"].values() if m["metric"] == "b3.worker-request-timeout-ms")
    timeout["value"] = 90_000.0
    # Citing a harness output (or any artifact but the install configuration) is not a binding.
    assert timeout["artifact"] == "b3a.hand-off-output.linux-x86_64-cpu"
    assert ("B3", "worker_timeout_unbound") in codes(record)
    timeout["value"] = 600_000.0
    assert ("B3", "worker_timeout_out_of_range") in codes(record)


def test_a_non_default_timeout_is_refused_even_with_a_cited_configuration(tmp_path: Path) -> None:
    # No install path configures the worker timeout, so a cited file cannot
    # stand in for the value the qualified worker actually uses.
    record = complete_record()
    timeout = next(m for m in record["measurements"].values() if m["metric"] == "b3.worker-request-timeout-ms")
    timeout.update(value=120_000.0, artifact="b3.worker-configuration")
    record["retainedArtifacts"]["b3.worker-configuration"] = {"path": "records/worker.env", "sha256": "e" * 64, "run": "host"}
    record["units"]["B3"]["artifacts"].append("b3.worker-configuration")
    record = materialize(record, tmp_path)
    assert ("B3", "worker_timeout_unbound") in _verified_codes(record, tmp_path)


@pytest.mark.parametrize(
    ("mutate", "detail"),
    [
        (lambda o: o.update(status="smoke"), "status"),
        (lambda o: o.update(authoritative=False), "authoritative"),
        (lambda o: o.update(nonAuthoritativeReasons=["tracks 200"]), "authoritative"),
        (lambda o: o["shape"].update(tracks=200), "shape"),
        (lambda o: o["shape"].update(stagedObjects=0), "shape"),
        (lambda o: o.update(workerRequestTimeoutMs=120_000), "worker timeout"),
        (lambda o: o.update(finalizerHostEnabled=True), "finalizer host was enabled"),
        (lambda o: o.update(samples=[]), "no raw samples"),
        (lambda o: o["samples"][3].update(stagedObjects=0), "fewer objects were staged"),
        (lambda o: o["samples"][3].update(state="completed"), "state is not finalizing"),
        (lambda o: o["samples"][3].update(jobStatus="Completed"), "not Finalizing"),
        (lambda o: o["samples"][3].update(publishedRows=40_001), "publication rows exist"),
        (lambda o: o["samples"][3].update(acceptedEvidenceFiles=1), "accepted-evidence files exist"),
        (lambda o: o["samples"][3].update(payloadRows=0), "payload row"),
        (lambda o: o["samples"][3].update(claimTripleNull=False), "claim triple"),
        (lambda o: o["samples"][3].update(tracksSubmitted=1), "tracksSubmitted"),
        (lambda o: o["samples"][3].update(httpStatus=409), "HTTP status"),
        (lambda o: o["samples"][3].update(acceptedAtPresent=False), "accepted timestamp"),
        (lambda o: o["samples"][3].update(replayState="completed"), "replay"),
    ],
)
def test_the_b3a_output_must_be_an_authoritative_worst_shape_hand_off(tmp_path: Path, mutate, detail: str) -> None:
    record = materialize(complete_record(), tmp_path)
    _rewrite_json(record, tmp_path, "b3a.hand-off-output.linux-x86_64-cpu", mutate)
    findings = [f for f in check_record(record, repo_root=tmp_path, verify_git=False) if f.code == "b3a_output_mismatch"]
    assert findings and any(detail in f.detail for f in findings), findings


def test_a_b3_timing_must_cite_its_producer() -> None:
    record = complete_record()
    wall = record["measurements"]["B3:b3a.hand-off-wall-ms.linux-x86_64-cpu"]
    del wall["artifact"]
    assert ("B3", "measurement_unbound") in codes(record)


def test_a_b3_timing_cited_from_another_output_is_refused(tmp_path: Path) -> None:
    record = materialize(complete_record(), tmp_path)
    record["measurements"]["B3:b3a.hand-off-wall-ms.linux-x86_64-cpu"]["artifact"] = "b3b.finalization-output.linux-x86_64-cpu"
    assert ("B3", "metric_without_producer") in _verified_codes(record, tmp_path)


@pytest.mark.parametrize("key", ["max", "min", "p50", "p95", "p50RunSpread"])
def test_a_b3_statistic_that_is_not_the_recomputation_is_refused(tmp_path: Path, key: str) -> None:
    for metric in ("b3a.hand-off-wall-ms", "b3b.visibility-barrier-hold-ms", "b3b.graph-persistence-ms"):
        record = materialize(complete_record(), tmp_path / metric / key)
        record["measurements"][f"B3:{metric}.linux-x86_64-cpu"]["stats"][key] += 1.0
        assert ("B3", "metric_without_producer") in _verified_codes(record, tmp_path / metric / key), metric


def test_a_b3_sample_count_or_value_that_is_not_the_recomputation_is_refused(tmp_path: Path) -> None:
    for change in ({"samples": 31}, {"repeats": 4}, {"value": 1.0}, {"warmupExcluded": False}):
        record = materialize(complete_record(), tmp_path / str(len(str(change))) / next(iter(change)))
        record["measurements"]["B3:b3b.total-hand-off-to-publication-ms.windows-x86_64-cpu"].update(change)
        found = _verified_codes(record, tmp_path / str(len(str(change))) / next(iter(change)))
        assert ("B3", "metric_without_producer") in found or ("B3", "timing_incomplete") in found, change


def _rewrite_junit(record: dict, root: Path, suite_id: str, xml: str) -> None:
    artifact = record["retainedArtifacts"][record["suites"][suite_id]["junitArtifact"]]
    (root / artifact["path"]).write_text(xml, encoding="utf-8")
    artifact["sha256"] = hashlib.sha256(xml.encode("utf-8")).hexdigest()


def test_junit_counts_are_compared_even_when_the_named_tests_agree(tmp_path: Path) -> None:
    record = materialize(complete_record(), tmp_path)
    suite_id = next(iter(record["units"]["B1"]["suites"]))
    classname = record["suites"][suite_id]["passedTests"][0].split("::")[0]
    xml = _junit_for(record["suites"][suite_id]).replace("</testsuite>", f'<testcase classname="{classname}" name="y"><error/></testcase></testsuite>')
    _rewrite_junit(record, tmp_path, suite_id, xml)
    findings = [f for f in check_record(record, repo_root=tmp_path, verify_git=False) if f.code == "junit_count_mismatch"]
    assert findings and all("errors" in f.detail for f in findings)


def test_junit_test_names_are_compared_even_when_the_counts_agree(tmp_path: Path) -> None:
    record = materialize(complete_record(), tmp_path)
    suite_id = next(iter(record["units"]["B1"]["suites"]))
    xml = _junit_for(record["suites"][suite_id]).replace('name="test_ok"', 'name="test_other"')
    _rewrite_junit(record, tmp_path, suite_id, xml)
    findings = [f for f in check_record(record, repo_root=tmp_path, verify_git=False) if f.code == "junit_count_mismatch"]
    assert findings and all("passedTests" in f.detail for f in findings)


# --------------------------------------------------------------------------- review round 2


def _rewrite_json(record: dict, root: Path, artifact_id: str, mutate) -> None:
    entry = record["retainedArtifacts"][artifact_id]
    data = json.loads((root / entry["path"]).read_text(encoding="utf-8"))
    mutate(data)
    content = json.dumps(data)
    (root / entry["path"]).write_text(content, encoding="utf-8")
    entry["sha256"] = hashlib.sha256(content.encode("utf-8")).hexdigest()


def _verified_codes(record: dict, root: Path) -> set[tuple[str, str]]:
    return codes(record, repo_root=root, verify_git=False)


def test_b2_values_must_be_the_retained_harness_output(tmp_path: Path) -> None:
    record = materialize(complete_record(), tmp_path)
    slope = next(m for m in record["measurements"].values() if m["metric"] == "b2.per-retired-traced-bytes-slope.linux-x86_64-cpu")
    # The harness measured an over-limit slope; the record shows a low one.
    _rewrite_json(record, tmp_path, "b2.memory-harness-output.linux-x86_64-cpu",
                  lambda d: d["measurements"]["b2.per-retired-traced-bytes-slope"].update(value=40_000.0))
    assert slope["value"] <= 16 * 1024
    assert ("B2", "b2_output_mismatch") in _verified_codes(record, tmp_path)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(schema="other"),
        lambda d: d["identity"].update(sourceSha="c" * 40),
        lambda d: d["identity"].update(cleanTree=False),
        lambda d: d["measurements"].pop("b2.staging-peak-bytes"),
        lambda d: d["measurements"]["b2.completion-peak-bytes"].update(unit="ms"),
    ],
)
def test_the_b2_harness_output_must_be_complete_and_from_the_measured_clean_source(tmp_path: Path, mutate) -> None:
    record = materialize(complete_record(), tmp_path)
    _rewrite_json(record, tmp_path, "b2.memory-harness-output.linux-x86_64-cpu", mutate)
    assert ("B2", "b2_output_mismatch") in _verified_codes(record, tmp_path)


def _variant_suite(record: dict, variant: str) -> str:
    return next(sid for sid in record["units"]["B2"]["suites"] if sid.endswith(":" + variant) and "test_track_lifecycle" in sid)


def test_a_linux_junit_relabelled_as_windows_is_refused(tmp_path: Path) -> None:
    record = materialize(complete_record(), tmp_path)
    linux, windows = _variant_suite(record, "linux-x86_64-cpu"), _variant_suite(record, "windows-x86_64-cpu")
    # Cite the Linux XML for the Windows result as well.
    record["suites"][windows]["junitArtifact"] = record["suites"][linux]["junitArtifact"]
    found = _verified_codes(record, tmp_path)
    assert {("B2", "junit_variant_unbound"), ("B2", "junit_variant_reused"), ("B2", "junit_variant_mismatch")} <= found


def test_a_copied_junit_file_is_refused_even_under_its_own_artifact_id(tmp_path: Path) -> None:
    record = materialize(complete_record(), tmp_path)
    linux, windows = _variant_suite(record, "linux-x86_64-cpu"), _variant_suite(record, "windows-x86_64-cpu")
    source = record["retainedArtifacts"][record["suites"][linux]["junitArtifact"]]
    target = record["retainedArtifacts"][record["suites"][windows]["junitArtifact"]]
    (tmp_path / target["path"]).write_bytes((tmp_path / source["path"]).read_bytes())
    target["sha256"] = source["sha256"]
    found = _verified_codes(record, tmp_path)
    assert ("B2", "junit_variant_reused") in found and ("B2", "junit_variant_mismatch") in found


def test_a_variant_junit_must_name_its_variant_in_the_xml(tmp_path: Path) -> None:
    record = materialize(complete_record(), tmp_path)
    windows = _variant_suite(record, "windows-x86_64-cpu")
    xml = _junit_for(record["suites"][windows]).replace('name="windows-x86_64-cpu"', 'name="pytest"')
    _rewrite_junit(record, tmp_path, windows, xml)
    assert ("B2", "junit_variant_mismatch") in _verified_codes(record, tmp_path)


def test_a_variant_junit_artifact_must_declare_its_variant() -> None:
    record = complete_record()
    windows = _variant_suite(record, "windows-x86_64-cpu")
    del record["retainedArtifacts"][record["suites"][windows]["junitArtifact"]]["variant"]
    assert ("B2", "junit_variant_unbound") in codes(record)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(schema="other"),
        lambda d: d.update(sourceCommit="c" * 40),
        lambda d: d.update(variant="linux-x86_64-cpu"),
        lambda d: d.update(installProfile="production"),
        lambda d: d.update(outboundConnectionAttempts=["10.0.0.5:443"]),
        lambda d: d["outcomes"].pop("completionV3"),
        lambda d: d["outcomes"]["reviewInvestigationEvidenceSet"].update(passed=False),
        lambda d: d["outcomes"]["sealedTrackEvidence"].update(evidence=""),
        lambda d: d["outcomes"]["sealedTrackEvidence"].update(evidence="records/not-retained.log"),
        lambda d: d.pop("outcomes"),
    ],
)
def test_disconnected_pass_needs_every_evidenced_outcome_on_the_measured_code(tmp_path: Path, mutate) -> None:
    record = materialize(complete_record(), tmp_path)
    _rewrite_json(record, tmp_path, "disconnected.run-record", mutate)
    assert ("DISCONNECTED", "disconnected_run_incomplete") in _verified_codes(record, tmp_path)


def test_a_changed_dotnet_evidence_test_invalidates_its_unit() -> None:
    cited = {"B3": {"tests/Mavi.IntegrationTests/S1BoundAgreementTests"}, "B4": {"tests/Mavi.Application.Tests/CompletionDigestGoldenTests"}}
    assert invalidated_units(["tests/Mavi.IntegrationTests/S1BoundAgreementTests.cs"], cited) == {
        "tests/Mavi.IntegrationTests/S1BoundAgreementTests.cs": {"B3"}
    }
    assert invalidated_units(["tests/Mavi.Application.Tests/CompletionDigestGoldenTests.Vectors.cs"], cited) == {
        "tests/Mavi.Application.Tests/CompletionDigestGoldenTests.Vectors.cs": {"B4"}
    }
    # Any file of a cited .NET project is shared support (helpers are test classes there).
    assert invalidated_units(["tests/Mavi.IntegrationTests/S1BoundAgreementTestsExtra.cs"], cited) == {
        "tests/Mavi.IntegrationTests/S1BoundAgreementTestsExtra.cs": {"B3"}
    }
    # A project no unit cites invalidates nothing.
    assert invalidated_units(["tests/Mavi.Domain.Tests/AnythingTests.cs"], cited) == {}
    assert s1_evidence.suite_covers("tests/Mavi.IntegrationTests/S1BoundAgreementTests", "tests/Mavi.IntegrationTests/S1BoundAgreementTests.cs")
    assert not s1_evidence.suite_covers("tests/Mavi.IntegrationTests/S1BoundAgreementTests", "tests/Mavi.IntegrationTests/S1BoundAgreementTestsExtra.cs")
    assert not s1_evidence.suite_covers("tests/Mavi.IntegrationTests/S1BoundAgreementTests", "tests/Mavi.IntegrationTests/S1BoundAgreementTests.json")


def test_a_closure_diff_touching_a_cited_dotnet_suite_requires_a_rerun() -> None:
    record = complete_record()
    record["closure"] = {"mergeSha": MERGE, "changedPaths": ["tests/Mavi.IntegrationTests/S1BoundAgreementTests.cs"]}
    assert ("B3", "closure_rerun_required") in codes(record)


# --------------------------------------------------------------------------- cold review before push


def test_junit_membership_is_by_component_not_substring(tmp_path: Path) -> None:
    path = tmp_path / "j.xml"
    path.write_text(JUNIT)
    selector = suite_counts_from_junit(path, "src/vision/tests/test_evidence_selector.py")
    assert (selector["passed"], selector["failed"], selector["errors"]) == (1, 1, 1)
    # A prefix of a module name is not that module.
    with pytest.raises(ValueError, match="junit_no_matching_testcases"):
        suite_counts_from_junit(path, "src/vision/tests/test_evidence.py")
    assert s1_evidence.suite_key("tests/Mavi.IntegrationTests/S1BoundAgreementTests") == ("IntegrationTests", "S1BoundAgreementTests")
    assert s1_evidence.suite_key("tools/qualification/tests") == ("qualification", "tests")
    assert s1_evidence.suite_key("src/web/mavi-web") is None
    assert s1_evidence.case_belongs("tools.qualification.tests.test_s1_memory", ("qualification", "tests"))
    assert s1_evidence.case_belongs("Mavi.IntegrationTests.S1BoundAgreementTests", ("IntegrationTests", "S1BoundAgreementTests"))
    assert not s1_evidence.case_belongs("Mavi.IntegrationTests.S1BoundAgreementTestsExtra", ("IntegrationTests", "S1BoundAgreementTests"))
    # The classnames pytest actually writes in Task 10: the boundary step runs
    # from src/vision, the harness step from the repository root.
    assert s1_evidence.case_belongs("tests.test_s1_bound_agreement", s1_evidence.suite_key("src/vision/tests/test_s1_bound_agreement.py"))
    assert s1_evidence.case_belongs("tools.qualification.tests.test_s1_memory", s1_evidence.suite_key("tools/qualification/tests"))


def test_a_suite_result_cannot_be_backed_by_another_suites_xml(tmp_path: Path) -> None:
    record = materialize(complete_record(), tmp_path)
    b2 = record["units"]["B2"]["suites"]
    lifecycle = next(sid for sid in b2 if "test_track_lifecycle.py:linux" in sid)
    spool = next(sid for sid in b2 if "test_trajectory_spool.py:linux" in sid)
    # The spool result points at the lifecycle suite's XML, with the lifecycle
    # suite's counts and names copied in.
    record["suites"][spool]["junitArtifact"] = record["suites"][lifecycle]["junitArtifact"]
    record["suites"][spool]["passedTests"] = list(record["suites"][lifecycle]["passedTests"])
    assert ("B2", "junit_unreadable") in _verified_codes(record, tmp_path)


def test_every_measurement_cites_a_retained_artifact_of_its_unit() -> None:
    record = complete_record()
    slope = next(m for m in record["measurements"].values() if m["metric"] == "b2.per-retired-traced-bytes-slope.linux-x86_64-cpu")
    del slope["artifact"]
    assert ("B2", "measurement_unbound") in codes(record)
    slope["artifact"] = "b1.real-clip-measurement"  # retained, but another unit's
    assert ("B2", "measurement_unbound") in codes(record)
    slope["artifact"] = "not-retained"
    assert ("B2", "measurement_unbound") in codes(record)


def test_a_unit_measured_off_the_diffed_shas_is_refused() -> None:
    record = complete_record()
    record["runs"]["older"] = {**record["runs"]["task10"], "headSha": OTHER, "runId": 7}
    record["units"]["B6"]["measuredSha"] = OTHER
    for suite_id in record["units"]["B6"]["suites"]:
        record["suites"][suite_id]["run"] = "older"
        record["retainedArtifacts"][record["suites"][suite_id]["junitArtifact"]]["run"] = "older"
    assert ("B6", "unit_sha_unbound") in codes(record)
    # Re-measured on the closure merge SHA is the one other permitted SHA.
    record["closure"] = {"mergeSha": OTHER, "changedPaths": []}
    assert ("B6", "unit_sha_unbound") not in codes(record)


# --------------------------------------------------------------------------- review round 3


def test_an_unapproved_skip_is_refused_even_with_a_passing_counterpart() -> None:
    # The golden-byte test may no longer skip anywhere (§3.1, §5).
    record = complete_record()
    windows = next(sid for sid in record["units"]["B1"]["suites"] if "test_evidence_encoder.py:windows" in sid)
    linux = windows.replace("windows-x86_64-cpu", "linux-x86_64-cpu")
    test = "tests.test_evidence_encoder::test_golden_bytes_per_runtime_variant[smooth]"
    record["suites"][windows].update(skipped=1, skippedTests=[test])
    record["suites"][linux].update(passed=2, passedTests=[*record["suites"][linux]["passedTests"], test])
    record["pairedVariantSkips"].append({
        "test": test, "skipsOn": "windows-x86_64-cpu", "counterpartSuite": "src/vision/tests/test_evidence_encoder.py",
        "counterpartTest": test, "counterpartVariant": "linux-x86_64-cpu",
    })
    assert ("B1", "skip_not_approved") in codes(record)


def test_an_approved_skip_is_approved_only_on_its_own_variant() -> None:
    record = _paired_record(counterpart_passed=True)
    windows = next(sid for sid in record["units"]["B2"]["suites"] if "test_track_lifecycle.py:windows" in sid)
    linux = windows.replace("windows-x86_64-cpu", "linux-x86_64-cpu")
    test = record["suites"][windows]["skippedTests"][0]
    # The POSIX case skipping on Linux is not an approved skip.
    record["suites"][linux].update(skipped=1, skippedTests=[test], passed=1, passedTests=[record["suites"][linux]["passedTests"][0]])
    assert ("B2", "skip_not_approved") in codes(record)


def test_a_pair_must_name_the_same_test_of_the_same_suite() -> None:
    # A genuinely passing but different test on the other variant does not excuse the skip.
    record = _paired_record(counterpart_passed=True)
    linux = next(sid for sid in record["units"]["B2"]["suites"] if "test_track_lifecycle.py:linux" in sid)
    record["pairedVariantSkips"][0]["counterpartTest"] = record["suites"][linux]["passedTests"][0]
    assert ("B2", "skip_not_permitted") in codes(record)
    # Nor does the same-named test passing in a different suite.
    record = _paired_record(counterpart_passed=True)
    spool = next(sid for sid in record["units"]["B2"]["suites"] if "test_trajectory_spool.py:linux" in sid)
    borrowed = "tests.test_trajectory_spool::test_many_live_tracks_need_no_descriptor_each"
    record["suites"][spool].update(passed=2, passedTests=[*record["suites"][spool]["passedTests"], borrowed])
    record["pairedVariantSkips"][0].update(counterpartSuite="src/vision/tests/test_trajectory_spool.py", counterpartTest=borrowed)
    assert ("B2", "skip_not_permitted") in codes(record)


# OS-conditional tests whose condition is false on both qualified platforms, so
# they never skip in Task 10 and need no approval.
NEVER_SKIPS_ON_A_QUALIFIED_VARIANT = {
    ("tools/qualification/tests", "test_a_process_mode_run_fits_the_platform_metric"),
}
_OS_CONDITION = ("os.name", "sys.platform", "hasattr(os", "platform.system")


def _os_conditional_tests(repo: Path, suite: str) -> set[str]:
    import ast

    root = repo / suite
    files = sorted(root.glob("test_*.py")) if root.is_dir() else [root]
    found: set[str] = set()
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        module_skip = any(
            isinstance(node, ast.Assign)
            and any(getattr(t, "id", "") == "pytestmark" for t in node.targets)
            and any(token in ast.unparse(node.value) for token in _OS_CONDITION)
            for node in tree.body
        )
        def os_skip(node: ast.AST) -> bool:
            return any(
                "skipif" in ast.unparse(d) and any(token in ast.unparse(d) for token in _OS_CONDITION)
                for d in getattr(node, "decorator_list", ())
            )

        functions = (ast.FunctionDef, ast.AsyncFunctionDef)
        # Module-level tests, and the methods of ``Test*`` classes (a class
        # ``skipif`` applies to every method).
        candidates = [(node, False) for node in tree.body if isinstance(node, functions)]
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                candidates += [(method, os_skip(node)) for method in node.body if isinstance(method, functions)]
        for node, class_skip in candidates:
            if node.name.startswith("test") and (module_skip or class_skip or os_skip(node)):
                found.add(node.name)
    return found


def test_approved_paired_skips_are_the_os_conditional_tests() -> None:
    """Every OS-conditional test in every required worker suite is approved on
    exactly the variant it skips on, and nothing else is approved."""
    repo = Path(__file__).resolve().parents[3]
    worker_suites = {
        suite
        for requirement in UNIT_REQUIREMENTS.values()
        for suite in requirement.suites
        if suite.startswith(("src/vision/", "tools/qualification/"))
    }
    discovered = {
        (suite, name)
        for suite in worker_suites
        for name in _os_conditional_tests(repo, suite)
    } - NEVER_SKIPS_ON_A_QUALIFIED_VARIANT
    approved = {(suite, name) for (suite, _), names in s1_evidence.APPROVED_PAIRED_SKIPS.items() for name in names}
    assert approved == discovered
    # Each approved test is approved on one variant only.
    variants = {}
    for (suite, variant), names in s1_evidence.APPROVED_PAIRED_SKIPS.items():
        for name in names:
            assert (suite, name) not in variants, (suite, name)
            variants[(suite, name)] = variant


def test_the_drift_scan_sees_a_new_os_conditional_test(tmp_path: Path) -> None:
    suite = tmp_path / "tests"
    suite.mkdir()
    (suite / "test_new.py").write_text(
        "import os, pytest\n@pytest.mark.skipif(os.name != 'nt', reason='x')\ndef test_only_windows():\n    pass\n"
        "@pytest.mark.skipif(True, reason='not OS')\ndef test_other():\n    pass\n",
        encoding="utf-8",
    )
    assert _os_conditional_tests(tmp_path, "tests") == {"test_only_windows"}
    (suite / "test_classes.py").write_text(
        "import os, sys, pytest\n"
        "class TestPosix:\n"
        "    @pytest.mark.skipif(sys.platform == 'win32', reason='x')\n"
        "    def test_method_only_posix(self):\n        pass\n"
        "    def test_unconditional(self):\n        pass\n"
        "@pytest.mark.skipif(os.name == 'nt', reason='x')\n"
        "class TestWholeClass:\n"
        "    async def test_async_in_skipped_class(self):\n        pass\n",
        encoding="utf-8",
    )
    assert _os_conditional_tests(tmp_path, "tests") == {"test_only_windows", "test_method_only_posix", "test_async_in_skipped_class"}


@pytest.mark.parametrize("artifact", ["b3a.hand-off-output", "b3b.finalization-output", "b3.crash-matrix-output"])
def test_every_b3_output_must_measure_the_b3_sha_on_a_clean_qualified_database(tmp_path: Path, artifact: str) -> None:
    for index, mutate in enumerate((
        lambda d: d["environment"].update(gitSha="c" * 40),
        lambda d: d["environment"].update(gitWorkingTreeClean="false"),
        lambda d: d["environment"].update(gitCommitObjectPresent="false"),
        lambda d: d["environment"].update(isQualificationGradeDatabase="false"),
        lambda d: d.update(schema="s1-b3-sealing-scale-v1"),
    )):
        record = materialize(complete_record(), tmp_path / str(index))
        _rewrite_json(record, tmp_path / str(index), f"{artifact}.linux-x86_64-cpu", mutate)
        found = {c for u, c in _verified_codes(record, tmp_path / str(index)) if u == "B3"}
        assert found & {"b3a_output_mismatch", "b3b_output_mismatch", "crash_matrix_incomplete"}, (artifact, index)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(sourceCommit="c" * 40),
        lambda d: d.update(platformVariant="linux-x86_64-cpu"),
        lambda d: d["artifacts"][0].update(sha256="0" * 64),
        lambda d: d["artifacts"].pop(0),
        lambda d: d["artifacts"].append(dict(d["artifacts"][0], relativePath="wheels/other.whl")),  # a second, same-hash wheel
        lambda d: d.pop("artifacts"),
    ],
)
def test_the_disconnected_bundle_manifest_must_be_the_measured_code(tmp_path: Path, mutate) -> None:
    record = materialize(complete_record(), tmp_path)
    _rewrite_json(record, tmp_path, "disconnected.runtime-bundle-manifest", mutate)
    assert ("DISCONNECTED", "bundle_manifest_mismatch") in _verified_codes(record, tmp_path)


def test_a_closure_needs_every_post_merge_workflow_on_the_merge_sha() -> None:
    record = complete_record()
    record["s1Closed"] = True
    record["closure"] = {"mergeSha": MERGE, "changedPaths": []}
    for index, workflow in enumerate(s1_evidence.POST_MERGE_WORKFLOWS):
        record["runs"][f"post-merge-{index}"] = {"kind": "workflow", "workflow": workflow, "runId": 100 + index, "headSha": MERGE, "conclusion": "success"}
    assert ("record", "post_merge_verification_missing") not in codes(record)
    for index in range(len(s1_evidence.POST_MERGE_WORKFLOWS)):
        broken = copy.deepcopy(record)
        broken["runs"][f"post-merge-{index}"]["headSha"] = SHA  # an ancestor's green run
        assert ("record", "post_merge_verification_missing") in codes(broken)
        broken = copy.deepcopy(record)
        broken["runs"][f"post-merge-{index}"]["conclusion"] = "failure"
        assert ("record", "post_merge_verification_missing") in codes(broken)


@pytest.mark.parametrize(
    "harness",
    [
        "tests/Mavi.IntegrationTests/Qualification/S1SealingScaleTests.cs",
        "tests/Mavi.IntegrationTests/Qualification/QualificationGate.cs",
        "tests/Mavi.IntegrationTests/Qualification/S1HandOffScaleTests.cs",
        "tests/Mavi.IntegrationTests/Qualification/S1FinalizationEnvelopeTests.cs",
        "tests/Mavi.IntegrationTests/Qualification/S1FinalizationRecoveryTests.cs",
        "tests/Mavi.IntegrationTests/Qualification/PublicationTimeline.cs",
        "tests/Mavi.IntegrationTests/Qualification/FinalizationTimingDecorator.cs",
    ],
)
def test_a_change_to_a_b3_harness_invalidates_b3_even_uncited(harness: str) -> None:
    assert "B3" in invalidated_units([harness], {})[harness]


def test_every_b3_harness_file_is_mapped_to_b3() -> None:
    harness_root = REPO_ROOT / "tests/Mavi.IntegrationTests/Qualification"
    for name in ("S1HandOffScaleTests.cs", "S1FinalizationEnvelopeTests.cs", "S1FinalizationRecoveryTests.cs", "PublicationTimeline.cs", "FinalizationTimingDecorator.cs"):
        if (harness_root / name).exists():
            assert f"tests/Mavi.IntegrationTests/Qualification/{name}" in s1_evidence.ALWAYS_EVIDENCE, name


# --------------------------------------------------------------------------- independent review


def test_a_duplicate_metric_cannot_hide_a_failing_value() -> None:
    record = complete_record()
    good = next(mid for mid in record["units"]["B1"]["measurements"])
    bad = dict(record["measurements"][good], value=7.0)
    bad.pop("limit", None)
    record["measurements"]["B1:duplicate"] = bad
    record["units"]["B1"]["measurements"].insert(0, "B1:duplicate")
    assert ("B1", "measurement_duplicate") in codes(record)


def _closure_repo(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git = lambda *args: subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()  # noqa: E731
    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@example.invalid")
    git("config", "user.name", "t")
    selector = repo / "src/vision/mavi_vision/evidence/selector.py"
    selector.parent.mkdir(parents=True)
    selector.write_text("selector")
    git("add", ".")
    git("commit", "-qm", "measured")
    return repo, git, git("rev-parse", "HEAD")


def _closure_record(measured: str, merge: str, changed: list[str]) -> dict:
    record = complete_record()
    record["measuredSha"] = measured
    for run in record["runs"].values():
        run["headSha"] = measured
    record["disconnected"]["runtimeBundleSourceCommit"] = measured
    record["closure"] = {"mergeSha": merge, "changedPaths": changed}
    return record


def test_a_moved_behavior_bearing_file_is_seen_under_its_old_path(tmp_path: Path) -> None:
    repo, git, measured = _closure_repo(tmp_path)
    (repo / "docs").mkdir()
    git("mv", "src/vision/mavi_vision/evidence/selector.py", "docs/selector.py")
    git("commit", "-qm", "move")
    merge = git("rev-parse", "HEAD")
    # Recording only the new path (what rename detection shows) is refused...
    assert ("record", "closure_diff_mismatch") in {(f.unit, f.code) for f in _check_with_git(_closure_record(measured, merge, ["docs/selector.py"]), repo)}
    # ...and the honest, rename-free diff invalidates the selector's units.
    honest = _closure_record(measured, merge, ["docs/selector.py", "src/vision/mavi_vision/evidence/selector.py"])
    found = {(f.unit, f.code) for f in _check_with_git(honest, repo)}
    assert ("record", "closure_diff_mismatch") not in found
    assert ("B1", "closure_rerun_required") in found


def test_a_closure_must_be_a_later_commit_on_main(tmp_path: Path) -> None:
    repo, git, measured = _closure_repo(tmp_path)
    same = {(f.unit, f.code) for f in _check_with_git(_closure_record(measured, measured, []), repo)}
    assert ("record", "closure_not_a_merge") in same
    # A commit on a side branch that never reached main.
    git("checkout", "-qb", "side")
    (repo / "notes.md").write_text("n")
    git("add", ".")
    git("commit", "-qm", "side")
    side = git("rev-parse", "HEAD")
    git("checkout", "-q", "main")
    assert ("record", "closure_not_on_main") in {(f.unit, f.code) for f in _check_with_git(_closure_record(measured, side, ["notes.md"]), repo)}
    # A merge SHA that does not descend from the measured SHA.
    git("checkout", "-q", "--orphan", "unrelated")
    (repo / "other.md").write_text("o")
    git("add", "other.md")
    git("commit", "-qm", "unrelated")
    unrelated = git("rev-parse", "HEAD")
    git("checkout", "-q", "main")
    assert ("record", "closure_not_a_merge") in {(f.unit, f.code) for f in _check_with_git(_closure_record(measured, unrelated, []), repo)}


def test_shared_test_support_invalidates_the_units_citing_its_project() -> None:
    cited = {
        "B2": {"src/vision/tests/test_track_lifecycle.py"},
        "B4": {"tests/Mavi.IntegrationTests/VisionFinalizationSubmissionApiTests"},
        "B5": {"src/web/mavi-web"},
    }
    assert invalidated_units(["src/vision/tests/conftest.py"], cited)["src/vision/tests/conftest.py"] == {"B2"}
    assert invalidated_units(["src/vision/tests/profile_fixtures.py"], cited)["src/vision/tests/profile_fixtures.py"] == {"B2"}
    assert invalidated_units(["tests/Mavi.IntegrationTests/ApiTestFactory.cs"], cited)["tests/Mavi.IntegrationTests/ApiTestFactory.cs"] == {"B4"}
    # An uncited Python test module stays free (§2.1).
    assert invalidated_units(["src/vision/tests/test_unrelated.py"], cited) == {}
    # A cited suite's non-surface file still invalidates its unit.
    assert invalidated_units(["src/web/mavi-web/vite.config.ts"], cited) == {"src/web/mavi-web/vite.config.ts": {"B5"}}


def test_a_suite_of_only_approved_skips_is_not_empty_but_other_empty_suites_are() -> None:
    record = complete_record()
    linux = next(sid for sid in record["units"]["B2"]["suites"] if "test_artifact_store_windows.py:linux" in sid)
    windows = linux.replace("linux-x86_64-cpu", "windows-x86_64-cpu")
    names = sorted(s1_evidence.APPROVED_PAIRED_SKIPS[("src/vision/tests/test_artifact_store_windows.py", "linux-x86_64-cpu")])
    tests = [f"tests.test_artifact_store_windows::{n}" for n in names]
    record["suites"][linux].update(passed=0, passedTests=[], skipped=len(tests), skippedTests=tests)
    record["suites"][windows].update(passed=len(tests), passedTests=tests)
    for test in tests:
        record["pairedVariantSkips"].append({
            "test": test, "skipsOn": "linux-x86_64-cpu", "counterpartSuite": "src/vision/tests/test_artifact_store_windows.py",
            "counterpartTest": test, "counterpartVariant": "windows-x86_64-cpu",
        })
    assert structural(record) == []
    spool = next(sid for sid in record["units"]["B2"]["suites"] if "test_trajectory_spool.py:linux" in sid)
    record["suites"][spool].update(passed=0, passedTests=[])
    assert ("B2", "suite_empty") in codes(record)


# --------------------------------------------------------------------------- independent review (2)


def _variant_suite_id(record: dict, unit: str, fragment: str, variant: str) -> str:
    return next(sid for sid in record["units"][unit]["suites"] if fragment in sid and sid.endswith(":" + variant))


def test_a_variant_suite_from_a_local_run_is_refused() -> None:
    record = complete_record()
    sid = _variant_suite_id(record, "B1", "test_evidence_selector.py", "windows-x86_64-cpu")
    record["runs"]["laptop"] = {"kind": "local", "host": "runner-linux", "command": "pytest -k one", "cleanTree": True, "headSha": SHA, "conclusion": "success"}
    record["suites"][sid]["run"] = "laptop"
    record["retainedArtifacts"][record["suites"][sid]["junitArtifact"]]["run"] = "laptop"
    assert ("B1", "suite_provenance_invalid") in codes(record)


def test_a_variant_suite_from_the_quality_gate_is_refused() -> None:
    record = complete_record()
    sid = _variant_suite_id(record, "B1", "test_evidence_selector.py", "linux-x86_64-cpu")
    record["suites"][sid]["run"] = "quality"
    record["retainedArtifacts"][record["suites"][sid]["junitArtifact"]]["run"] = "quality"
    assert ("B1", "suite_provenance_invalid") in codes(record)


def test_a_dotnet_suite_must_come_from_the_quality_gate() -> None:
    record = complete_record()
    sid = next(sid for sid in record["units"]["B4"]["suites"] if "CompletionDigestGoldenTests" in sid)
    record["suites"][sid]["run"] = "task10"
    record["retainedArtifacts"][record["suites"][sid]["junitArtifact"]]["run"] = "task10"
    assert ("B4", "suite_provenance_invalid") in codes(record)


def test_a_task10_step_must_be_backed_by_its_own_junit_file() -> None:
    record = complete_record()
    boundary = _variant_suite_id(record, "B6", "task10:s1-boundary", "linux-x86_64-cpu")
    probe = _variant_suite_id(record, "B6", "task10:runtime-probe-real-torch", "linux-x86_64-cpu")
    # The one-test real-torch XML standing in for the boundary step.
    record["retainedArtifacts"][record["suites"][boundary]["junitArtifact"]]["path"] = record["retainedArtifacts"][record["suites"][probe]["junitArtifact"]]["path"]
    assert ("B6", "suite_provenance_invalid") in codes(record)


def test_b6_needs_every_task10_step_and_record_per_variant() -> None:
    record = complete_record()
    sid = _variant_suite_id(record, "B6", "task10:bytetrack-runtime", "windows-x86_64-cpu")
    record["units"]["B6"]["suites"].remove(sid)
    assert ("B6", "variant_result_missing") in codes(record)
    record = complete_record()
    record["units"]["B6"]["artifacts"].remove("b6.windows-x86_64-cpu.bytetrack-qualification.json")
    assert ("B6", "artifact_missing") in codes(record)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda a: a.update(run="host"),
        lambda a: a.update(variant="linux-x86_64-cpu"),
        lambda a: a.update(path="task10/windows-x86_64-cpu/runtime.json"),
        lambda a: a.update(path="task10/linux-x86_64-cpu/bytetrack-qualification.json"),
        lambda a: a.update(path="bytetrack-qualification.json"),
    ],
)
def test_a_task10_record_must_come_from_its_variants_task10_run(mutate) -> None:
    record = complete_record()
    mutate(record["retainedArtifacts"]["b6.windows-x86_64-cpu.bytetrack-qualification.json"])
    assert ("B6", "task10_record_invalid") in codes(record)


def test_a_failed_production_composition_record_blocks_b6(tmp_path: Path) -> None:
    record = materialize(complete_record(), tmp_path)
    _rewrite_json(record, tmp_path, "b6.linux-x86_64-cpu.production-composition-qualification.json", lambda d: d.update(status="failed"))
    assert ("B6", "task10_record_invalid") in _verified_codes(record, tmp_path)
    record = materialize(complete_record(), tmp_path)
    _rewrite_json(record, tmp_path, "b6.linux-x86_64-cpu.production-composition-qualification.json", lambda d: d.update(headSha="c" * 40))
    assert ("B6", "task10_record_invalid") in _verified_codes(record, tmp_path)


def test_disconnected_outcome_evidence_must_come_from_a_measured_successful_run(tmp_path: Path) -> None:
    record = complete_record()
    record["runs"]["failed-elsewhere"] = {**record["runs"]["host"], "headSha": OTHER, "conclusion": "failure"}
    record["retainedArtifacts"]["disconnected.realVideoProcessing"]["run"] = "failed-elsewhere"
    record = materialize(record, tmp_path)
    found = _verified_codes(record, tmp_path)
    assert ("DISCONNECTED", "head_sha_mismatch") in found and ("DISCONNECTED", "run_not_successful") in found


@pytest.mark.parametrize("reused", ["disconnected.workerStartup", "disconnected.run-record", "disconnected.runtime-bundle-manifest"])
def test_disconnected_outcomes_need_distinct_evidence_other_than_the_record_itself(tmp_path: Path, reused: str) -> None:
    record = materialize(complete_record(), tmp_path)
    _rewrite_json(record, tmp_path, "disconnected.run-record", lambda d: d["outcomes"]["completionV3"].update(evidence=reused))
    assert ("DISCONNECTED", "disconnected_run_incomplete") in _verified_codes(record, tmp_path)


def test_isolation_probes_must_be_the_retained_probe_output(tmp_path: Path) -> None:
    record = materialize(complete_record(), tmp_path)
    # The retained probe saw a reachable host; the record says isolated.
    _rewrite_json(record, tmp_path, "disconnected.isolation-after", lambda d: d["probes"][0].update(reachable=True))
    assert ("DISCONNECTED", "isolation_not_evidenced") in _verified_codes(record, tmp_path)


def test_b2_output_must_come_from_a_qualified_variant_on_the_recorded_host(tmp_path: Path) -> None:
    record = materialize(complete_record(), tmp_path)
    _rewrite_json(record, tmp_path, "b2.memory-harness-output.linux-x86_64-cpu", lambda d: d["runtime"].update(runtimeVariant=None))
    assert ("B2", "b2_output_mismatch") in _verified_codes(record, tmp_path)
    record = materialize(complete_record(), tmp_path / "2")
    _rewrite_json(record, tmp_path / "2", "b2.memory-harness-output.linux-x86_64-cpu", lambda d: d["host"].update(cpuModel="a laptop"))
    assert ("B2", "host_identity_mismatch") in _verified_codes(record, tmp_path / "2")


@pytest.mark.parametrize(("base", "_artifact", "_field"), s1_evidence.B3_TIMINGS)
def test_b3_needs_every_timing_on_each_supported_os(base: str, _artifact: str, _field: str) -> None:
    for variant in s1_evidence.QUALIFIED_CPU_VARIANTS:
        record = complete_record()
        record["units"]["B3"]["measurements"].remove(f"B3:{base}.{variant}")
        assert ("B3", "measurement_missing") in codes(record), (base, variant)


@pytest.mark.parametrize("artifact", ["b3a.hand-off-output", "b3b.finalization-output", "b3.crash-matrix-output"])
def test_b3_needs_every_output_on_each_supported_os(artifact: str) -> None:
    # B3-A alone, B3-B alone, or one OS never passes B3 (B3 plan §17 guard).
    for variant in s1_evidence.QUALIFIED_CPU_VARIANTS:
        record = complete_record()
        record["units"]["B3"]["artifacts"].remove(f"{artifact}.{variant}")
        assert ("B3", "artifact_missing") in codes(record), (artifact, variant)


@pytest.mark.parametrize("artifact", ["b3a.hand-off-output", "b3b.finalization-output", "b3.crash-matrix-output"])
def test_a_linux_b3_output_relabelled_as_windows_is_refused(tmp_path: Path, artifact: str) -> None:
    record = materialize(complete_record(), tmp_path)
    linux = record["retainedArtifacts"][f"{artifact}.linux-x86_64-cpu"]
    windows = record["retainedArtifacts"][f"{artifact}.windows-x86_64-cpu"]
    # The Linux bytes copied under the Windows id: its own variant field betrays it...
    (tmp_path / windows["path"]).write_bytes((tmp_path / linux["path"]).read_bytes())
    windows["sha256"] = linux["sha256"]
    found = _verified_codes(record, tmp_path)
    assert {c for u, c in found if u == "B3"} & {"b3a_output_mismatch", "b3b_output_mismatch", "crash_matrix_incomplete"}
    # ... and so do the identical bytes, even with the field rewritten.
    record = materialize(complete_record(), tmp_path / "2")
    _rewrite_json(record, tmp_path / "2", f"{artifact}.windows-x86_64-cpu", lambda d: d.update(json.loads((tmp_path / "2" / record["retainedArtifacts"][f"{artifact}.linux-x86_64-cpu"]["path"]).read_text()), variant="windows-x86_64-cpu"))
    windows = record["retainedArtifacts"][f"{artifact}.windows-x86_64-cpu"]
    linux = record["retainedArtifacts"][f"{artifact}.linux-x86_64-cpu"]
    content = (tmp_path / "2" / windows["path"]).read_text()
    (tmp_path / "2" / linux["path"]).write_text(content)
    linux["sha256"] = windows["sha256"]
    findings = [f for f in check_record(record, repo_root=tmp_path / "2", verify_git=False) if "other variant" in f.detail]
    assert findings


def test_the_task10_steps_are_every_junit_file_task10_writes() -> None:
    import re as _re

    workflow = (Path(__file__).resolve().parents[3] / ".github/workflows/task10-runtime-qualification.yml").read_text(encoding="utf-8")
    written = set(_re.findall(r"--junitxml=\S*?junit/([A-Za-z0-9_-]+)\.xml", workflow))
    assert written == set(s1_evidence.TASK10_JUNIT_STEPS)
    records = set(_re.findall(r'"([a-z-]+\.json)",\n', workflow))
    assert set(s1_evidence.TASK10_RECORDS) <= records


def test_tampered_or_unretained_outcome_evidence_is_refused(tmp_path: Path) -> None:
    # Outcome evidence is not among the unit's listed artifacts, so only this
    # rule verifies it: a tampered file must be caught by its hash.
    record = materialize(complete_record(), tmp_path)
    evidence = record["retainedArtifacts"]["disconnected.completionV3"]
    (tmp_path / evidence["path"]).write_text("tampered", encoding="utf-8")
    found = check_record(record, repo_root=tmp_path, verify_git=False)
    assert ("DISCONNECTED", "artifact_hash_mismatch") in {(f.unit, f.code) for f in found}
    assert any("completionV3 does not cite a retained, verified evidence artifact" in f.detail for f in found)
    # An id that names no retained artifact is refused for that reason, not by accident.
    record = materialize(complete_record(), tmp_path / "2")
    _rewrite_json(record, tmp_path / "2", "disconnected.run-record", lambda d: d["outcomes"]["trackDetail"].update(evidence="disconnected.never-retained"))
    found = check_record(record, repo_root=tmp_path / "2", verify_git=False)
    assert any("trackDetail does not cite a retained, verified evidence artifact" in f.detail for f in found)


# --------------------------------------------------------------------------- repair round


def test_a_pass_measured_on_an_unmerged_or_unknown_sha_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    on_main = on_main_repo(root)
    git = lambda *args: subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()  # noqa: E731
    git("checkout", "-qb", "unmerged")
    (root / "branch.txt").write_text("b", encoding="utf-8")
    git("add", "branch.txt")
    git("commit", "-qm", "unmerged")
    unmerged = git("rev-parse", "HEAD")
    git("checkout", "-q", "main")
    assert codes(materialize(with_sha(complete_record(), on_main), root), repo_root=root) == set()
    found = codes(materialize(with_sha(complete_record(), unmerged), root), repo_root=root)
    assert ("B1", "measured_sha_not_on_main") in found
    found = codes(materialize(with_sha(complete_record(), "f" * 40), root), repo_root=root)
    assert ("B1", "measured_sha_unknown") in found


def test_an_aggregate_task10_skip_is_approved_by_its_testcases_source_suite() -> None:
    record = complete_record()
    linux = next(s for s in record["units"]["B6"]["suites"] if "task10:s1-boundary" in s and s.endswith("linux-x86_64-cpu"))
    windows = linux.replace("linux-x86_64-cpu", "windows-x86_64-cpu")
    names = sorted(s1_evidence.APPROVED_PAIRED_SKIPS[("src/vision/tests/test_artifact_store_windows.py", "linux-x86_64-cpu")])
    tests = [f"tests.test_artifact_store_windows::{name}" for name in names]
    record["suites"][linux].update(skipped=len(tests), skippedTests=tests)
    record["suites"][windows].update(passed=1 + len(tests), passedTests=record["suites"][windows]["passedTests"] + tests)
    for test in tests:
        record["pairedVariantSkips"].append({
            "test": test, "skipsOn": "linux-x86_64-cpu", "counterpartSuite": "task10:s1-boundary",
            "counterpartTest": test, "counterpartVariant": "windows-x86_64-cpu",
        })
    assert structural(record) == []
    # The same aggregate may not smuggle in a skip whose source suite does not approve it.
    record["suites"][linux].update(skipped=len(tests) + 1, skippedTests=tests + ["tests.test_evidence_encoder::test_golden_bytes_per_runtime_variant"])
    assert ("B6", "skip_not_approved") in codes(record)
    # Nor a Windows-only name under a classname of another suite.
    assert not s1_evidence.is_approved_skip("task10:s1-boundary", "linux-x86_64-cpu", f"tests.test_track_lifecycle::{names[0]}")
    assert not s1_evidence.is_approved_skip("task10:s1-boundary", "windows-x86_64-cpu", tests[0])


# --------------------------------------------------------------------------- B2 per variant (repair round)


def test_b2_needs_the_memory_evidence_of_both_variants() -> None:
    record = complete_record()
    record["units"]["B2"]["measurements"] = [m for m in record["units"]["B2"]["measurements"] if not m.endswith(".windows-x86_64-cpu")]
    assert ("B2", "measurement_missing") in codes(record)
    record = complete_record()
    record["units"]["B2"]["artifacts"].remove("b2.memory-harness-output.windows-x86_64-cpu")
    assert ("B2", "artifact_missing") in codes(record)


def test_a_variants_b2_output_must_be_that_variants_run(tmp_path: Path) -> None:
    record = materialize(complete_record(), tmp_path)
    # The Linux output relabelled as the Windows evidence.
    _rewrite_json(record, tmp_path, "b2.memory-harness-output.windows-x86_64-cpu", lambda d: d["runtime"].update(runtimeVariant="linux-x86_64-cpu"))
    assert ("B2", "b2_output_mismatch") in _verified_codes(record, tmp_path)


@pytest.mark.parametrize("field", s1_evidence.MEASURED_HOST_FIELDS)
def test_every_host_field_is_measured_and_bound(tmp_path: Path, field: str) -> None:
    record = materialize(complete_record(), tmp_path / "a")
    _rewrite_json(record, tmp_path / "a", "b2.memory-harness-output.windows-x86_64-cpu", lambda d: d["host"].update({field: None}))
    assert ("B2", "host_identity_unmeasured") in _verified_codes(record, tmp_path / "a")
    record = materialize(complete_record(), tmp_path / "b")
    # A typed-in value (a valid enum member for storageClass, so only the binding can refuse it).
    typed = "hdd" if field == "storageClass" else ("typed in" if isinstance(record["hosts"]["runner-windows"][field], str) else 999)
    record["hosts"]["runner-windows"][field] = typed
    assert ("B2", "host_identity_mismatch") in _verified_codes(record, tmp_path / "b")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["liveLevelFit"].update(points=d["liveLevelFit"]["points"][:4]),
        lambda d: d["liveLevelFit"]["points"][4].__setitem__(1, 99_000_000.0),
        lambda d: d["liveLevelFit"].pop("r2"),
        lambda d: d["boundOneReconciliation"].update(unaccountedPerLiveBytes=0.0),
        lambda d: d["boundOneReconciliation"].update(perLiveProcessSlopeBytes=1.0),
        lambda d: d["boundOneReconciliation"].update(accountedEncodedEvidenceBytesMax=10**9, unaccountedPerLiveBytes=d["boundOneReconciliation"]["perLiveProcessSlopeBytes"] - 10**9),
        lambda d: d.pop("boundOneReconciliation"),
    ],
)
def test_the_per_live_slope_is_recomputed_from_its_plateaus_and_reconciled(tmp_path: Path, mutate) -> None:
    record = materialize(complete_record(), tmp_path)
    _rewrite_json(record, tmp_path, "b2.memory-harness-output.linux-x86_64-cpu", mutate)
    assert ("B2", "b2_output_mismatch") in _verified_codes(record, tmp_path)


def test_the_per_live_slope_is_mandatory_but_not_thresholded() -> None:
    requirement = next(r for r in UNIT_REQUIREMENTS["B2"].measurements if r.metric.startswith("b2.process-memory-per-live-track-slope."))
    assert requirement.limit_op is None
    record = complete_record()
    record["units"]["B2"]["measurements"].remove("B2:b2.process-memory-per-live-track-slope.windows-x86_64-cpu")
    assert ("B2", "measurement_missing") in codes(record)


def test_an_undefined_variation_blocks_b2(tmp_path: Path) -> None:
    record = materialize(complete_record(), tmp_path)
    _rewrite_json(record, tmp_path, "b2.memory-harness-output.linux-x86_64-cpu", lambda d: d["measurements"]["b2.retired-slope-duration-variation"].update(value=None, undefined="baseline slope 0.0 B/track is not positive"))
    assert ("B2", "variation_undefined") in _verified_codes(record, tmp_path)


def test_the_staging_peak_must_be_within_the_runs_derived_bound() -> None:
    record = complete_record()
    record["measurements"]["B2:b2.staging-peak-to-derived-bound-ratio.linux-x86_64-cpu"]["value"] = 1.01
    assert ("B2", "limit_violated") in codes(record)


@pytest.mark.parametrize(("field", "value"), [
    ("cpuModel", "another CPU"), ("logicalCores", 128), ("acceptedEvidenceFilesystem", "tmpfs"),
    ("storageClass", "nvme"), ("storageClassEvidence", "typed by hand"),
])
def test_every_b3_output_is_bound_to_its_measured_host(tmp_path: Path, field: str, value) -> None:
    for artifact in ("b3a.hand-off-output", "b3b.finalization-output"):
        record = materialize(complete_record(), tmp_path / artifact)
        _rewrite_json(record, tmp_path / artifact, f"{artifact}.windows-x86_64-cpu", lambda d: d["host"].update({field: value}))
        assert ("B3", "host_identity_mismatch") in _verified_codes(record, tmp_path / artifact), artifact


def test_b3_timing_on_a_hosted_runner_is_refused() -> None:
    record = complete_record()
    record["hosts"]["runner-windows"]["storageClass"] = "hosted-runner"
    assert ("B3", "storage_class_unbound") in codes(record)


def test_a_host_needs_storage_class_evidence() -> None:
    record = complete_record()
    del record["hosts"]["runner-linux"]["storageClassEvidence"]
    assert ("record", "schema_invalid") in codes(record)
    record = complete_record()
    record["hosts"]["runner-linux"]["storageClassEvidence"] = ""
    assert ("record", "schema_invalid") in codes(record)
    record = complete_record()
    record["hosts"]["runner-linux"]["storageClass"] = "fast"
    assert ("record", "schema_invalid") in codes(record)


def test_a_typed_storage_class_that_the_b2_harness_did_not_measure_is_refused(tmp_path: Path) -> None:
    record = materialize(complete_record(), tmp_path)
    _rewrite_json(record, tmp_path, "b2.memory-harness-output.linux-x86_64-cpu", lambda d: d["host"].update(storageClass="unknown"))
    assert ("B2", "host_identity_mismatch") in _verified_codes(record, tmp_path)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["checks"].update(failedAttemptCleaned=False),
        lambda d: d["checks"].pop("supersededAttemptRemoved"),
        lambda d: d["checks"].update(siblingJobUntouched=False),
        lambda d: d["checks"].update(peaksWithinDerivedBound=False),
        lambda d: d["workload"].update(tracker="fixture"),
        lambda d: d["runtime"].update(runtimeVariant="linux-x86_64-cpu"),
        lambda d: d["identity"].update(cleanTree=False),
        lambda d: d.update(schema="other"),
    ],
)
def test_each_variant_needs_a_passed_staging_lifecycle(tmp_path: Path, mutate) -> None:
    record = materialize(complete_record(), tmp_path)
    _rewrite_json(record, tmp_path, "b2.staging-lifecycle.windows-x86_64-cpu", mutate)
    assert ("B2", "staging_lifecycle_invalid") in _verified_codes(record, tmp_path)


def test_b2_cites_the_platform_janitor_suite() -> None:
    assert "tests/Mavi.IntegrationTests/StagingJanitorTests" in UNIT_REQUIREMENTS["B2"].suites


# --------------------------------------------------------------------------- B1 / B3 / B5 content binding


def test_a_b1_count_must_be_the_derived_comparisons(tmp_path: Path) -> None:
    record = materialize(complete_record(), tmp_path)
    _rewrite_json(record, tmp_path, "b1.cross-variant-comparison", lambda d: d["counts"].update(parameterNoteMismatches=3))
    assert ("B1", "b1_comparison_invalid") in _verified_codes(record, tmp_path)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(schema="other"),
        lambda d: d["identity"].update(sourceSha="c" * 40),
        lambda d: d["identity"].update(cleanTree=False),
        lambda d: d.update(identityProblems=["windows: ran on 'linux-x86_64-cpu'"]),
        lambda d: d["inputs"]["linux"].update(sha256="0" * 64),
        lambda d: d["inputs"]["baseline"].update(sha256="0" * 64),
        lambda d: d.update(traces=[{"path": "/combined/tracks", "cause": "x"}]),
    ],
)
def test_the_b1_comparison_must_be_of_the_retained_runs_on_the_measured_code(tmp_path: Path, mutate) -> None:
    record = materialize(complete_record(), tmp_path)
    _rewrite_json(record, tmp_path, "b1.cross-variant-comparison", mutate)
    assert ("B1", "b1_comparison_invalid") in _verified_codes(record, tmp_path)


def test_an_arbitrary_b1_artifact_no_longer_supports_a_pass(tmp_path: Path) -> None:
    # The pre-repair fixture: the comparison artifact's content was just its id.
    record = materialize(complete_record(), tmp_path)
    entry = record["retainedArtifacts"]["b1.cross-variant-comparison"]
    (tmp_path / entry["path"]).write_text("b1.cross-variant-comparison", encoding="utf-8")
    entry["sha256"] = hashlib.sha256(b"b1.cross-variant-comparison").hexdigest()
    assert ("B1", "b1_comparison_invalid") in _verified_codes(record, tmp_path)


def _proving_params():
    return [
        (unit, prop, suite, test)
        for unit, mapping in s1_evidence.PROVING_TESTS_BY_UNIT.items()
        for prop, tests in mapping.items()
        for suite, test in tests
    ]


@pytest.mark.parametrize(("unit", "prop", "suite", "test"), _proving_params())
def test_every_proving_test_must_have_passed_in_its_cited_suite(unit: str, prop: str, suite: str, test: str) -> None:
    record = complete_record()
    for entry in record["suites"].values():
        if entry["suite"] == suite:
            entry["passedTests"] = [t for t in entry["passedTests"] if not t.endswith("::" + test)]
            entry["passed"] = len(entry["passedTests"])
    assert (unit, "proving_test_missing") in codes(record), (prop, test)


@pytest.mark.parametrize(("unit", "prop", "suite", "test"), _proving_params())
def test_every_proving_test_exists_in_the_repository(unit: str, prop: str, suite: str, test: str) -> None:
    relative = suite if suite.endswith(".py") else suite + ".cs"
    text = (REPO_ROOT / relative).read_text(encoding="utf-8")
    assert re.search(rf"\b(?:def\s+|Task\s+|void\s+){re.escape(test)}\s*\(", text), f"{prop}: {relative}::{test}"


def test_every_proving_suite_is_a_required_suite_of_its_unit() -> None:
    for unit, mapping in s1_evidence.PROVING_TESTS_BY_UNIT.items():
        for prop, tests in mapping.items():
            for suite, _ in tests:
                assert suite in UNIT_REQUIREMENTS[unit].suites, (unit, prop, suite)


def test_a_proving_test_absent_at_the_measured_sha_is_refused(tmp_path: Path) -> None:
    # A test renamed or removed after the map was written: its old name may still be
    # present in a stale TRX, but the source at the measured SHA must hold it.
    record = materialize(complete_record(), tmp_path)
    source = tmp_path / "tests/Mavi.IntegrationTests/VisionFinalizationRecoveryTests.cs"
    source.write_text(source.read_text().replace("TwoHostsRacingOneJobProduceExactlyOnePublication(", "TwoHostsRacingRenamed("))
    found = _verified_codes(record, tmp_path)
    assert ("B3", "proving_test_absent_at_sha") in found and ("B4", "proving_test_absent_at_sha") in found


def test_the_b4_proving_map_covers_every_f4_plan_property() -> None:
    assert set(s1_evidence.B4_PROVING_TESTS) == {
        "python-dotnet-agreement", "v2-replay", "v3-replay", "v3-1-replay", "durable-hand-off",
        "ambiguous-submission-commit-succeeded", "ambiguous-submission-commit-failed", "publication-commit-ambiguity",
        "no-duplicate-graph", "no-duplicate-sequence", "no-compensation-deletion", "identical-evidence-adopted",
        "staging-survives-hand-off-and-finalization", "stale-claimant-cannot-publish-or-fail", "final-permitted-claimant-exhaustion",
    }


def test_the_b5_clip_count_is_the_records_verified_real_video_clips(tmp_path: Path) -> None:
    record = materialize(complete_record(), tmp_path)
    assert _verified_codes(record, tmp_path) == set()
    _rewrite_json(record, tmp_path, "b5.real-video-record", lambda d: d["clips"][1].update(label="fixture"))
    assert ("B5", "b5_record_invalid") in _verified_codes(record, tmp_path)


@pytest.mark.parametrize(
    ("artifact", "mutate"),
    [
        ("b5.real-video-record", lambda d: d["clips"][0].update(trackDetailVerified=False)),
        ("b5.real-video-record", lambda d: d["clips"][1].update(sha256=d["clips"][0]["sha256"])),
        ("b5.real-video-record", lambda d: d["clips"][0].update(sha256="not-a-hash")),
        ("b5.real-video-record", lambda d: d.update(sourceCommit="c" * 40)),
        ("b5.real-video-record", lambda d: d.update(schema="other")),
        ("b5.visual-qa-record", lambda d: d["items"][0].update(passed=False)),
        ("b5.visual-qa-record", lambda d: d.update(items=[i for i in d["items"] if i["label"] != "real-video"])),
        ("b5.visual-qa-record", lambda d: d.update(sourceCommit="c" * 40)),
    ],
)
def test_b5_records_must_verify_what_they_count(tmp_path: Path, artifact: str, mutate) -> None:
    record = materialize(complete_record(), tmp_path)
    _rewrite_json(record, tmp_path, artifact, mutate)
    assert ("B5", "b5_record_invalid") in _verified_codes(record, tmp_path)


# --------------------------------------------------------------------------- .NET TRX / web JUnit (finding #4)

REAL_SHAPED_TRX = """﻿<?xml version="1.0" encoding="utf-8"?>
<TestRun id="1" name="@vm" xmlns="http://microsoft.com/schemas/VisualStudio/TeamTest/2010">
  <Results>
    <UnitTestResult executionId="e1" testId="t1" testName="Mavi.IntegrationTests.WorkerContractV3Tests.WorstShapeBodyFitsUnderLimit" outcome="Passed" />
    <UnitTestResult executionId="e2" testId="t2" testName="Mavi.IntegrationTests.WorkerContractV3Tests.Rejects(kind: &quot;a&quot;)" outcome="Passed" />
    <UnitTestResult executionId="e3" testId="t2" testName="Mavi.IntegrationTests.WorkerContractV3Tests.Rejects(kind: &quot;b&quot;)" outcome="NotExecuted" />
    <UnitTestResult executionId="e4" testId="t3" testName="Mavi.IntegrationTests.WorkerContractV3TestsExtra.Other" outcome="Failed" />
    <UnitTestResult executionId="e5" testId="t4" testName="Mavi.IntegrationTests.WorkerContractV3Tests.Hangs" outcome="Timeout" />
    <UnitTestResult executionId="e6" testId="t5" testName="Mavi.IntegrationTests.WorkerContractV3Tests.Broke" outcome="Error" />
  </Results>
  <TestDefinitions>
    <UnitTest name="a" id="t1"><Execution id="e1" /><TestMethod className="Mavi.IntegrationTests.WorkerContractV3Tests" name="WorstShapeBodyFitsUnderLimit" /></UnitTest>
    <UnitTest name="b" id="t2"><Execution id="e2" /><TestMethod className="Mavi.IntegrationTests.WorkerContractV3Tests" name="Rejects" /></UnitTest>
    <UnitTest name="c" id="t3"><Execution id="e4" /><TestMethod className="Mavi.IntegrationTests.WorkerContractV3TestsExtra" name="Other" /></UnitTest>
    <UnitTest name="d" id="t4"><Execution id="e5" /><TestMethod className="Mavi.IntegrationTests.WorkerContractV3Tests" name="Hangs" /></UnitTest>
    <UnitTest name="e" id="t5"><Execution id="e6" /><TestMethod className="Mavi.IntegrationTests.WorkerContractV3Tests" name="Broke" /></UnitTest>
  </TestDefinitions>
</TestRun>
"""


def test_a_trx_is_counted_from_its_results_by_test_class(tmp_path: Path) -> None:
    path = tmp_path / "Mavi.IntegrationTests.trx"
    path.write_text(REAL_SHAPED_TRX, encoding="utf-8")
    counts = s1_evidence.suite_counts_from_junit(path, "tests/Mavi.IntegrationTests/WorkerContractV3Tests")
    assert (counts["passed"], counts["skipped"], counts["failed"], counts["errors"]) == (2, 1, 1, 1)
    assert counts["passedTests"] == [
        "Mavi.IntegrationTests.WorkerContractV3Tests::WorstShapeBodyFitsUnderLimit",
        'Mavi.IntegrationTests.WorkerContractV3Tests::Rejects(kind: "a")',
    ]
    assert counts["skippedTests"] == ['Mavi.IntegrationTests.WorkerContractV3Tests::Rejects(kind: "b")']
    # A class whose name merely extends the suite's is another suite.
    extra = s1_evidence.suite_counts_from_junit(path, "tests/Mavi.IntegrationTests/WorkerContractV3TestsExtra")
    assert (extra["passed"], extra["failed"]) == (0, 1)


def test_a_trx_result_without_its_definition_is_unreadable(tmp_path: Path) -> None:
    path = tmp_path / "x.trx"
    path.write_text(REAL_SHAPED_TRX.replace('id="t5"', 'id="t9"'), encoding="utf-8")
    with pytest.raises(ValueError, match="trx_result_without_definition"):
        s1_evidence.suite_counts_from_junit(path, "tests/Mavi.IntegrationTests/WorkerContractV3Tests")


def test_the_real_dotnet_trx_logger_output_is_readable() -> None:
    # Captured from ``dotnet test --logger trx`` (SDK 10.0.112, xUnit 2.9.3) on
    # Mavi.IntegrationTests, pruned to two classes and with local paths removed.
    # It holds real theory names and the real NotExecuted form of an xUnit skip.
    path = Path(__file__).parent / "fixtures/dotnet-sdk-10.0.112-integration-sample.trx"
    worker = s1_evidence.suite_counts_from_junit(path, "tests/Mavi.IntegrationTests/WorkerContractV3Tests")
    assert worker["failed"] == worker["errors"] == worker["skipped"] == 0 and worker["passed"] > 1
    assert "Mavi.IntegrationTests.WorkerContractV3Tests::WorstShapeBodyFitsUnderLimit" in worker["passedTests"]
    assert 'Mavi.IntegrationTests.WorkerContractV3Tests::CompletionRejectsUnacceptedVersions(version: "3.1")' in worker["passedTests"]
    # xUnit truncates long theory arguments ("···"), so two cases can share a
    # display name. Each result is still counted, and the checker compares the
    # names as sorted lists, so a duplicate can neither vanish nor be invented.
    assert len(worker["passedTests"]) == worker["passed"] > len(set(worker["passedTests"]))
    sealing = s1_evidence.suite_counts_from_junit(path, "tests/Mavi.IntegrationTests/Qualification/S1SealingScaleTests")
    assert sealing["skippedTests"] == [
        "Mavi.IntegrationTests.Qualification.S1SealingScaleTests::RealStoreCompletionWallTimeAtTheWorstCaseObjectCount"
    ]
    assert sealing["passed"] >= 1 and sealing["failed"] == 0


@pytest.mark.parametrize(
    ("suite", "wrong_path"),
    [
        ("tests/Mavi.IntegrationTests/WorkerContractV3Tests", "junit/worker.xml"),
        ("tests/Mavi.IntegrationTests/WorkerContractV3Tests", "trx/Mavi.Application.Tests.trx"),
        ("src/web/mavi-web", "junit/web-local.xml"),
    ],
)
def test_a_quality_gate_suite_is_backed_by_the_file_the_gate_writes(suite: str, wrong_path: str) -> None:
    record = complete_record()
    entry = next(e for e in record["suites"].values() if e["suite"] == suite)
    record["retainedArtifacts"][entry["junitArtifact"]]["path"] = wrong_path
    assert any(code == "suite_provenance_invalid" for _, code in codes(record))


def test_the_quality_gate_retains_a_trx_per_test_project_and_the_web_junit() -> None:
    workflow = (REPO_ROOT / ".github/workflows/quality-gate.yml").read_text(encoding="utf-8")
    # Every test project in the solution, each to its own TRX (built-in logger).
    assert 'dotnet sln MAVI.sln list' in workflow and "grep '^tests/'" in workflow
    assert '--logger "trx;LogFileName=${name}.trx" --results-directory qualification-evidence/trx' in workflow
    assert "--reporter=junit --outputFile.junit=../../../qualification-evidence/junit/mavi-web.xml" in workflow
    upload = workflow[workflow.index("actions/upload-artifact"):]
    assert "path: qualification-evidence/" in upload and "if: always()" in workflow[workflow.index("Retain test results"):]
    assert s1_evidence.quality_gate_result_path("tests/Mavi.Domain.Tests/X") == "trx/Mavi.Domain.Tests.trx"
    assert s1_evidence.quality_gate_result_path("src/web/mavi-web") == "junit/mavi-web.xml"
    projects = sorted(path.parent.name for path in (REPO_ROOT / "tests").glob("*/*.csproj"))
    assert projects == ["Mavi.Application.Tests", "Mavi.Domain.Tests", "Mavi.IntegrationTests"]


def test_a_task10_record_is_not_the_other_variants_bytes() -> None:
    record = complete_record()
    for name in sorted(s1_evidence.TASK10_JOB_RECORDS):
        linux = record["retainedArtifacts"][f"b6.linux-x86_64-cpu.{name}"]
        record["retainedArtifacts"][f"b6.windows-x86_64-cpu.{name}"]["sha256"] = linux["sha256"]
        assert ("B6", "task10_record_invalid") in codes(record)
        record = complete_record()
    # A copied committed file is the same on both variants.
    record["retainedArtifacts"]["b6.windows-x86_64-cpu.runtime.json"]["sha256"] = record["retainedArtifacts"]["b6.linux-x86_64-cpu.runtime.json"]["sha256"]
    assert ("B6", "task10_record_invalid") not in codes(record)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(runtimeVariant="linux-x86_64-cpu"),
        lambda d: d.update(headSha="c" * 40),
        lambda d: d.update(status="failed"),
    ],
)
def test_the_bytetrack_record_names_its_variant_and_the_measured_head(tmp_path: Path, mutate) -> None:
    record = materialize(complete_record(), tmp_path)
    assert _verified_codes(record, tmp_path) == set()
    _rewrite_json(record, tmp_path, "b6.windows-x86_64-cpu.bytetrack-qualification.json", mutate)
    assert ("B6", "task10_record_invalid") in _verified_codes(record, tmp_path)


# --------------------------------------------------------------------------- R2: Task-10 step sources


def _task10_step_commands() -> dict[str, tuple[str, ...]]:
    """Each Task-10 JUnit step's test paths, as the workflow invokes them."""
    import re

    workflow = (REPO_ROOT / ".github/workflows/task10-runtime-qualification.yml").read_text(encoding="utf-8")
    found: dict[str, tuple[str, ...]] = {}
    for step in re.split(r"\n      - (?=name:|uses:)", workflow):
        match = re.search(r"--junitxml=\S*junit/([A-Za-z0-9_-]+)\.xml", step)
        if match is None:
            continue
        prefix = "src/vision/" if re.search(r"^        working-directory: src/vision\s*$", step, re.M) else ""
        step = re.sub(r"--deselect \S+", "", step)  # deselected node ids are not run
        paths = re.findall(r"(?<![\w/])((?:src/vision/)?tests/test_\w+\.py|tools/qualification/tests)(?![\w/])", step)
        found[match.group(1)] = tuple(dict.fromkeys(path if path.startswith(("src/", "tools/")) else prefix + path for path in paths))
    return found


def test_the_task10_step_sources_are_what_the_workflow_runs() -> None:
    commands = _task10_step_commands()
    assert set(commands) == set(s1_evidence.TASK10_JUNIT_STEPS)
    assert commands == s1_evidence.TASK10_STEP_SOURCES


def test_a_task10_step_source_change_invalidates_its_units() -> None:
    cited = {"B6": {"task10:bytetrack-runtime", "task10:s1-boundary"}}
    assert invalidated_units(["src/vision/tests/test_bytetrack_runtime.py"], cited) == {"src/vision/tests/test_bytetrack_runtime.py": {"B6"}}
    assert invalidated_units(["src/vision/tests/test_evidence_selector.py"], cited) == {"src/vision/tests/test_evidence_selector.py": {"B6"}}
    assert invalidated_units(["src/vision/tests/conftest.py"], cited) == {"src/vision/tests/conftest.py": {"B6"}}
    assert invalidated_units(["tools/qualification/tests/test_s1_memory.py"], {"B2": {"task10:s1-qualification-harness"}}) == {
        "tools/qualification/tests/test_s1_memory.py": {"B2"}
    }
    # A test file no step runs invalidates nothing through the steps.
    assert invalidated_units(["src/vision/tests/test_unrelated_thing.py"], cited) == {}


def test_a_repository_fixture_invalidates_every_unit_resting_on_a_suite() -> None:
    cited = {"B3": {"tests/Mavi.IntegrationTests/S1BoundAgreementTests"}, "B5": {"src/web/mavi-web"}, "B6": {"task10:s1-boundary"}}
    assert invalidated_units(["tests/fixtures/contracts/example.json"], cited) == {"tests/fixtures/contracts/example.json": {"B3", "B5", "B6"}}


# --------------------------------------------------------------------------- R4 / R6: disconnected isolation


def test_the_isolation_targets_are_the_reused_probes() -> None:
    import re

    source = (REPO_ROOT / "tools/phase1/qualify_offline_variant.py").read_text(encoding="utf-8")
    body = source[source.index("def assert_outbound_internet_unavailable"):]
    block = body[body.index("probes = ("):body.index("observations = []")]
    targets = tuple((host, int(port)) for host, port in re.findall(r'\("([^"]+)", (\d+)\)', block))
    assert targets == s1_evidence.ISOLATION_PROBE_TARGETS


def test_the_disconnected_variant_must_be_a_qualified_cpu_variant() -> None:
    record = complete_record()
    record["disconnected"]["variant"] = "windows-x86_64-cuda"
    assert ("DISCONNECTED", "disconnected_variant_unqualified") in codes(record)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda probes: probes.pop(),
        lambda probes: probes.append({"host": "example.org", "port": 443, "reachable": False}),
        lambda probes: probes.__setitem__(0, {"host": "127.0.0.1", "port": 443, "reachable": False}),
    ],
)
def test_isolation_probes_are_exactly_the_five_targets(mutate) -> None:
    record = complete_record()
    mutate(record["disconnected"]["isolationAfter"]["probes"])
    assert ("DISCONNECTED", "isolation_not_evidenced") in codes(record)


def test_retained_probe_output_may_carry_more_than_the_probe_fields(tmp_path: Path) -> None:
    record = materialize(complete_record(), tmp_path)
    _rewrite_json(record, tmp_path, "disconnected.isolation-before", lambda d: d.update(observedAt="2026-10-01T10:00:00Z"))
    assert _verified_codes(record, tmp_path) == set()
    _rewrite_json(record, tmp_path, "disconnected.isolation-before", lambda d: d["probes"][2].update(reachable=True))
    assert ("DISCONNECTED", "isolation_not_evidenced") in _verified_codes(record, tmp_path)


# --------------------------------------------------------------------------- R5: disconnected outcome provenance


def test_outcome_evidence_comes_from_the_disconnected_local_run(tmp_path: Path) -> None:
    record = complete_record()
    record["retainedArtifacts"]["disconnected.trackDetail"]["run"] = "host"
    record = materialize(record, tmp_path)
    assert ("DISCONNECTED", "disconnected_run_incomplete") in _verified_codes(record, tmp_path)


def test_outcome_evidence_is_no_other_units_evidence(tmp_path: Path) -> None:
    record = complete_record()
    record["units"]["B5"]["artifacts"].append("disconnected.trackDetail")
    record = materialize(record, tmp_path)
    assert ("DISCONNECTED", "disconnected_run_incomplete") in _verified_codes(record, tmp_path)


def test_the_disconnected_run_is_on_a_host_of_its_variant(tmp_path: Path) -> None:
    record = complete_record()
    record["runs"]["offline"]["host"] = "runner-linux"
    record = materialize(record, tmp_path)
    assert ("DISCONNECTED", "disconnected_run_incomplete") in _verified_codes(record, tmp_path)


# --------------------------------------------------------------------------- R8: sources at the measured SHA


def _settings_repo(root: Path, default: str) -> str:
    """A main commit whose settings.py has worker timeout ``default``, then a
    later working-tree edit back to the checkout's own value."""
    sha = on_main_repo(root)
    settings = root / s1_evidence.WORKER_SETTINGS_RELATIVE
    original = settings.read_text(encoding="utf-8")
    edited = re.sub(r"(request_timeout_seconds: float = Field\(default=)[0-9.]+", rf"\g<1>{default}", original)
    assert edited != original
    settings.write_text(edited, encoding="utf-8")
    git = lambda *args: subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()  # noqa: E731
    git("commit", "-qam", "timeout")
    measured = git("rev-parse", "HEAD")
    settings.write_text(original, encoding="utf-8")  # the checkout differs from the measured code
    return measured


def test_the_worker_timeout_is_read_at_the_measured_sha(tmp_path: Path) -> None:
    measured = _settings_repo(tmp_path / "repo", "7.0")
    record = with_sha(complete_record(), measured)
    record["units"] = {name: unit for name, unit in record["units"].items()}
    checker = s1_evidence._Checker(record, tmp_path / "repo", verify_git=True)
    settings = checker.source_at(measured, s1_evidence.WORKER_SETTINGS_RELATIVE)
    assert s1_evidence.worker_request_timeout_bounds_ms(settings.decode())[0] == 7000.0
    # The working tree says otherwise; only the measured commit counts.
    assert s1_evidence.worker_request_timeout_bounds_ms((tmp_path / "repo" / s1_evidence.WORKER_SETTINGS_RELATIVE).read_text())[0] != 7000.0
    checker._b3_bounds({"b3.worker-request-timeout-ms": {"value": s1_evidence.worker_request_timeout_bounds_ms()[0]}}, measured)
    assert any(f.code == "worker_timeout_unbound" for f in checker.findings)


def test_unreadable_settings_at_the_measured_sha_refuse_b3(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    sha = on_main_repo(root)
    subprocess.run(["git", "rm", "-q", s1_evidence.WORKER_SETTINGS_RELATIVE], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "rm"], cwd=root, check=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True).stdout.strip()
    checker = s1_evidence._Checker(complete_record(), root, verify_git=True)
    checker._b3_bounds({"b3.worker-request-timeout-ms": {"value": 1.0}}, head)
    assert [f.code for f in checker.findings] == ["worker_timeout_unbound"]
    assert sha != head


def test_every_plan_section_3_host_field_is_measured_and_bound() -> None:
    # §3 host identity, storage class included since F4 (plan §17.2): measured, never typed in.
    assert s1_evidence.MEASURED_HOST_FIELDS == (
        "cpuModel", "physicalCores", "logicalCores", "ramBytes", "os", "osBuild", "stagingFilesystem", "storageClass", "storageClassEvidence",
    )
    assert s1_evidence.B3_HOST_FIELDS == ("cpuModel", "logicalCores", "acceptedEvidenceFilesystem", "storageClass", "storageClassEvidence")


# --------------------------------------------------------------------------- F4: B3-B envelope (plan §9)
B3B = "b3b.finalization-output.linux-x86_64-cpu"


def _b3b_codes(tmp_path: Path, mutate) -> set:
    record = materialize(complete_record(), tmp_path)
    _rewrite_json(record, tmp_path, B3B, mutate)
    return {code for unit, code in _verified_codes(record, tmp_path) if unit == "B3"}


def _sample(d: dict, index: int = 3) -> dict:
    return d["samples"][index]


def _ticks(d: dict, index: int = 3) -> dict:
    return d["samples"][index]["publicationTimeline"]["ticks"]


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda d: d.update(hostedServiceUsed=False), "b3b_output_mismatch"),  # cycles driven by hand
        (lambda d: d.update(optionsSource="test injection"), "b3b_output_mismatch"),
        (lambda d: d["shape"].update(stagedObjects=1_000), "b3b_output_mismatch"),
        (lambda d: d["configuration"].update(Enabled=False), "frozen_configuration_mismatch"),
        (lambda d: d["configuration"].update(MaximumFinalizationDurationSeconds=d["configuration"]["MaximumFinalizationDurationSeconds"] * 10), "frozen_configuration_mismatch"),
        (lambda d: d["configuration"].update(ClaimExtensionSeconds=1), "frozen_configuration_mismatch"),
        (lambda d: d["configuration"].update(SealingBatchSize=5_000), "frozen_configuration_mismatch"),
        (lambda d: _sample(d).update(extensionCount=0), "b3b_output_mismatch"),  # extension disabled
        (lambda d: _sample(d).update(extensionCount=_sample(d)["extensionCount"] - 1), "b3b_output_mismatch"),
        (lambda d: _sample(d).update(prematureVisibilityObserved=1), "b3b_output_mismatch"),
        (lambda d: _sample(d).update(publications=2), "b3b_output_mismatch"),  # double publish
        (lambda d: _sample(d).update(visibilitySequences=2), "b3b_output_mismatch"),
        (lambda d: _sample(d).update(createdObjects=1), "b3b_output_mismatch"),
        (lambda d: _sample(d).update(longestCommandMs=30_001.0), "b3b_output_mismatch"),
        (lambda d: d.update(effectiveCommandTimeoutSeconds=0), "b3b_output_mismatch"),
        (lambda d: d.update(samples=[]), "b3b_output_mismatch"),
        (lambda d: d["apiHostRss"].update(samplesBytes=[]), "b3b_output_mismatch"),  # RSS absent but PASS
        (lambda d: d.pop("apiHostRss"), "b3b_output_mismatch"),
        (lambda d: d.update(apiProcessCpuSeconds=None), "b3b_output_mismatch"),
        (lambda d: d["apiContention"].update(endpoints=[]), "api_contention_incomplete"),
        (lambda d: d["apiContention"].update(errorsDuringFinalization=3), "api_contention_incomplete"),
        (lambda d: d["reference"].update(samples=d["reference"]["samples"][:4]), "reference_incomplete"),
        (lambda d: d["reference"]["samples"][0]["publicationTimeline"]["ticks"].pop("barrierAcquired"), "reference_incomplete"),
        (lambda d: d.update(rejectedTimelines=[{"reason": "TransactionRolledBack"}]), "publication_timeline_invalid"),
        (lambda d: _sample(d)["bracketProofs"].update(graphPersistenceBracketContainsOnlyAddAsync=False), "publication_timeline_invalid"),
        (lambda d: _sample(d)["bracketProofs"].update(singleBarrierCommand=False), "publication_timeline_invalid"),
        (lambda d: _sample(d)["publicationTimeline"].update(transition="Ambiguous"), "publication_timeline_invalid"),
        (lambda d: _sample(d)["publicationTimeline"].update(committed=False), "publication_timeline_invalid"),
        (lambda d: _sample(d)["publicationTimeline"].update(transactionId=""), "publication_timeline_invalid"),
        (lambda d: _ticks(d).pop("commitCompleted"), "publication_timeline_invalid"),  # raw timestamps absent
    ],
)
def test_the_b3b_output_must_be_the_real_hosted_worst_shape_envelope(tmp_path: Path, mutate, code: str) -> None:
    assert code in _b3b_codes(tmp_path, mutate)


def test_the_b3b_output_must_time_the_exclusive_barrier_command(tmp_path: Path) -> None:
    shared = _barrier_sql().replace("pg_advisory_xact_lock(", "pg_advisory_xact_lock_shared(")
    assert "barrier_hold_unbound" in _b3b_codes(tmp_path / "a", lambda d: d.update(barrierCommandText=shared))
    assert "publication_timeline_invalid" in _b3b_codes(tmp_path / "b", lambda d: _sample(d)["publicationTimeline"].update(barrierCommandText=shared))


def test_the_barrier_sql_is_read_from_the_measured_source(tmp_path: Path) -> None:
    # A changed lock key in the source makes every timing of the old key unbound.
    record = materialize(complete_record(), tmp_path)
    source = tmp_path / s1_evidence.BARRIER_SOURCE_RELATIVE
    source.write_text(source.read_text().replace("1296127561, 1412505908", "1, 2", 1))
    assert ("B3", "barrier_hold_unbound") in _verified_codes(record, tmp_path)


def test_the_barrier_hold_starts_at_barrier_acquisition_not_the_row_lock(tmp_path: Path) -> None:
    # Mutant: the harness reports the hold from the job row lock (it would include graph persistence).
    def from_row_lock(d):
        timeline = _sample(d)["publicationTimeline"]
        ticks = timeline["ticks"]
        _sample(d)["barrierHoldMs"] = (ticks["commitCompleted"] - ticks["rowLockAcquired"]) * 1000.0 / timeline["stopwatchFrequency"]
    assert "metric_without_producer" in _b3b_codes(tmp_path / "typed", from_row_lock)
    # Mutant: the barrier-acquired timestamp is the row-lock timestamp.
    assert "publication_timeline_invalid" in _b3b_codes(tmp_path / "ticks", lambda d: _ticks(d).update(barrierAcquired=_ticks(d)["rowLockAcquired"]))
    # Mutant: the barrier is acquired before graph persistence ended.
    assert "publication_timeline_invalid" in _b3b_codes(tmp_path / "early", lambda d: _ticks(d).update(barrierCommandStarted=_ticks(d)["graphPersistenceStart"]))


def test_the_barrier_hold_ends_at_the_observed_commit(tmp_path: Path) -> None:
    # Mutant: the end is TransactionCommitting (the commit call started), not TransactionCommitted.
    assert "publication_timeline_invalid" in _b3b_codes(tmp_path / "a", lambda d: _ticks(d).update(commitCompleted=_ticks(d)["commitStarted"]))
    # Mutant: the end is the final SaveChanges, before the commit started.
    assert "publication_timeline_invalid" in _b3b_codes(tmp_path / "b", lambda d: _ticks(d).update(commitCompleted=_ticks(d)["barrierAcquired"] + 1))


def test_graph_persistence_must_be_measured_positive_and_recomputed(tmp_path: Path) -> None:
    zero = lambda d: _ticks(d).update(graphPersistenceEnd=_ticks(d)["graphPersistenceStart"], graphSavingChanges=_ticks(d)["graphPersistenceStart"], graphSavedChanges=_ticks(d)["graphPersistenceStart"])  # noqa: E731
    assert "graph_persistence_unbound" in _b3b_codes(tmp_path / "zero", zero)
    assert "publication_timeline_invalid" in _b3b_codes(tmp_path / "missing", lambda d: _ticks(d).pop("graphPersistenceStart"))

    def by_subtraction(d):
        timeline = _sample(d)["publicationTimeline"]
        values = s1_evidence.derive_timeline(timeline)
        _sample(d)["graphPersistenceMs"] = values["publishTransactionMs"] - values["barrierHoldMs"]
    assert "metric_without_producer" in _b3b_codes(tmp_path / "subtraction", by_subtraction)
    # The graph SaveChanges lies inside the persistence bracket.
    assert "publication_timeline_invalid" in _b3b_codes(tmp_path / "outside", lambda d: _ticks(d).update(graphSavedChanges=_ticks(d)["graphPersistenceEnd"] + 10))


def test_every_b3b_interval_is_recomputed_from_two_raw_timestamps() -> None:
    timeline = _timeline(0, 1)
    values = s1_evidence.derive_timeline(timeline)
    ticks = timeline["ticks"]
    assert values["barrierHoldMs"] == (ticks["commitCompleted"] - ticks["barrierAcquired"]) / 1000.0
    assert values["barrierWaitMs"] == (ticks["barrierAcquired"] - ticks["barrierCommandStarted"]) / 1000.0
    assert values["publishTransactionMs"] == (ticks["commitCompleted"] - ticks["transactionBegun"]) / 1000.0
    assert values["graphPersistenceMs"] == (ticks["graphPersistenceEnd"] - ticks["graphPersistenceStart"]) / 1000.0
    assert values["graphSaveChangesMs"] == (ticks["graphSavedChanges"] - ticks["graphSavingChanges"]) / 1000.0
    # The hold never contains graph persistence.
    assert values["barrierHoldMs"] < values["publishTransactionMs"] - values["graphPersistenceMs"]


def test_nearest_rank_matches_the_dotnet_harness() -> None:
    assert s1_evidence.nearest_rank([5.0, 1.0, 3.0, 2.0, 4.0], 0.50) == 3.0
    assert s1_evidence.nearest_rank([5.0, 1.0, 3.0, 2.0, 4.0], 0.95) == 5.0
    assert s1_evidence.nearest_rank([7.0], 0.95) == 7.0


# --------------------------------------------------------------------------- F4: frozen configuration (plan §10)
@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda r: r.pop("frozenConfiguration"), "frozen_configuration_missing"),
        (lambda r: r["frozenConfiguration"]["values"].update(MaximumFinalizationDurationSeconds=1), "frozen_configuration_mismatch"),
        (lambda r: r["frozenConfiguration"]["values"].update(ClaimSeconds=r["frozenConfiguration"]["values"]["ClaimSeconds"] + 1), "frozen_configuration_mismatch"),
        (lambda r: r["frozenConfiguration"].update(effectiveBoundSeconds=1), "frozen_configuration_mismatch"),
        (lambda r: r["frozenConfiguration"].update(activationDefault=not r["frozenConfiguration"]["activationDefault"]), "frozen_configuration_mismatch"),
    ],
)
def test_the_frozen_configuration_is_the_committed_appsettings(mutate, code: str) -> None:
    record = complete_record()
    mutate(record)
    assert ("B3", code) in codes(record)


def test_the_frozen_configuration_is_read_at_the_measured_sha(tmp_path: Path) -> None:
    record = materialize(complete_record(), tmp_path)
    appsettings = tmp_path / s1_evidence.APPSETTINGS_RELATIVE
    document = json.loads(appsettings.read_text())
    document["VisionFinalization"]["SealingBatchSize"] = 17
    appsettings.write_text(json.dumps(document))
    found = _verified_codes(record, tmp_path)
    assert ("B3", "frozen_configuration_mismatch") in found
    appsettings.unlink()
    assert ("B3", "frozen_configuration_unbound") in _verified_codes(record, tmp_path)


# --------------------------------------------------------------------------- F4: crash matrix (plan §11)
CRASH = "b3.crash-matrix-output.windows-x86_64-cpu"


def _row(d: dict, scenario: str) -> dict:
    return next(row for row in d["rows"] if row["scenario"] == scenario)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(rows=[row for row in d["rows"] if row["scenario"] != "two-hosts-racing"]),  # an H row missing
        lambda d: d["rows"].append(dict(d["rows"][0])),  # an H row twice
        lambda d: _row(d, "worker-death-after-hand-off").update(passed=False),
        lambda d: _row(d, "host-death-before-first-claim").update(finalState="Failed"),
        lambda d: _row(d, "two-hosts-racing").update(publications=2),
        lambda d: _row(d, "two-hosts-racing").update(sequenceCount=2),
        lambda d: _row(d, "host-death-mid-seal").update(adoptedObjects=0, createdObjects=50_000),  # recreated, never adopted
        lambda d: _row(d, "host-death-mid-seal").update(createdObjects=10),
        lambda d: _row(d, "host-death-mid-seal").update(killPoint={}),
        lambda d: _row(d, "host-death-before-first-claim").update(restartLatencyMs=None),
        lambda d: _row(d, "host-death-before-first-claim").update(orphanBytes=-1),
    ],
)
def test_every_crash_h_row_must_converge_to_one_publication(tmp_path: Path, mutate) -> None:
    record = materialize(complete_record(), tmp_path)
    _rewrite_json(record, tmp_path, CRASH, mutate)
    assert ("B3", "crash_matrix_incomplete") in _verified_codes(record, tmp_path)


def test_the_crash_h_scenarios_are_the_plans_process_kill_rows() -> None:
    assert s1_evidence.CRASH_H_SCENARIOS == ("worker-death-after-hand-off", "host-death-before-first-claim", "host-death-mid-seal", "two-hosts-racing")


# --------------------------------------------------------------------------- F4: provenance of B3 outputs
def test_a_b3_output_from_another_harness_run_is_refused(tmp_path: Path) -> None:
    record = materialize(complete_record(), tmp_path)
    _rewrite_json(record, tmp_path, "b3a.hand-off-output.windows-x86_64-cpu", lambda d: d.update(runId="another-run"))
    assert ("B3", "artifact_run_mismatch") in _verified_codes(record, tmp_path)
    record = materialize(complete_record(), tmp_path / "2")
    record["measurements"]["B3:b3a.hand-off-wall-ms.windows-x86_64-cpu"]["run"] = "b3b.finalization-output.windows-x86_64-cpu"
    assert ("B3", "artifact_run_mismatch") in _verified_codes(record, tmp_path / "2")


@pytest.mark.parametrize(
    "path",
    [
        "docs/qualification/stage2-s1/evidence/bb331c6/task10/linux-x86_64-cpu/junit/s1-boundary.xml",  # PR #87's superseded evidence
        "docs/qualification/stage2-s1/exploratory/aaaaaaaaaaaa/b3b/s1-b3b-finalization.json",  # the freeze inputs
        "docs/qualification/stage2-s1/history/bb331c6/b3/s1-b3-sealing-scale.linux-x86_64-cpu.json",
        "records/b3b.json",
    ],
)
def test_a_pass_cannot_rest_on_another_shas_historical_or_exploratory_evidence(path: str) -> None:
    record = complete_record()
    record["retainedArtifacts"]["b3b.finalization-output.linux-x86_64-cpu"]["path"] = path
    assert ("B3", "artifact_not_from_measured_sha") in codes(record)
    record = complete_record()
    junit = record["suites"][record["units"]["B4"]["suites"][0]]["junitArtifact"]
    record["retainedArtifacts"][junit]["path"] = path
    assert ("B4", "artifact_not_from_measured_sha") in codes(record)


def test_the_closure_sha_folder_is_accepted_for_units_rerun_on_it() -> None:
    record = complete_record()
    record["closure"] = {"mergeSha": MERGE, "changedPaths": []}
    artifact = record["retainedArtifacts"]["b4.completion-v3-golden"]
    artifact["path"] = artifact["path"].replace(f"/{SHA[:12]}/", f"/{MERGE[:12]}/")
    assert ("B4", "artifact_not_from_measured_sha") not in codes(record)


# --------------------------------------------------------------------------- F4: B5 (plan §15)
@pytest.mark.parametrize("check", ["finalizingObserved", "prematureVisibilityAbsent", "completedAfterAsyncPublication"])
def test_a_real_video_clip_counts_only_if_the_asynchronous_path_was_truthful(tmp_path: Path, check: str) -> None:
    record = materialize(complete_record(), tmp_path)
    _rewrite_json(record, tmp_path, "b5.real-video-record", lambda d: d["clips"][0].update({check: False}))
    assert ("B5", "b5_record_invalid") in _verified_codes(record, tmp_path)


@pytest.mark.parametrize("item", s1_evidence.B5_QA_REQUIRED_ITEMS)
def test_b5_needs_every_finalizing_ui_item_to_pass(tmp_path: Path, item: str) -> None:
    record = materialize(complete_record(), tmp_path / "failed")
    _rewrite_json(record, tmp_path / "failed", "b5.visual-qa-record", lambda d: next(i for i in d["items"] if i["id"] == item).update(passed=False))
    assert ("B5", "b5_record_invalid") in _verified_codes(record, tmp_path / "failed")
    record = materialize(complete_record(), tmp_path / "absent")
    _rewrite_json(record, tmp_path / "absent", "b5.visual-qa-record", lambda d: d.update(items=[i for i in d["items"] if i["id"] != item]))
    assert ("B5", "b5_record_invalid") in _verified_codes(record, tmp_path / "absent")


def test_fixture_only_b5_evidence_is_not_real_video_acceptance(tmp_path: Path) -> None:
    record = materialize(complete_record(), tmp_path)
    _rewrite_json(record, tmp_path, "b5.visual-qa-record", lambda d: [i.update(label="fixture") for i in d["items"]])
    assert ("B5", "b5_record_invalid") in _verified_codes(record, tmp_path)


@pytest.mark.parametrize(("artifact", "schema"), [("b5.real-video-record", "s1-b5-real-video-record-v1"), ("b5.visual-qa-record", "s1-b5-visual-qa-v1")])
def test_a_pre_f4_b5_record_is_refused(tmp_path: Path, artifact: str, schema: str) -> None:
    record = materialize(complete_record(), tmp_path)
    _rewrite_json(record, tmp_path, artifact, lambda d: d.update(schema=schema))
    assert ("B5", "b5_record_invalid") in _verified_codes(record, tmp_path)


# --------------------------------------------------------------------------- F4: disconnected (plan §19)
@pytest.mark.parametrize(
    ("artifact", "mutate"),
    [
        ("disconnected.run-record", lambda d: d.update(activation={"visionFinalizationEnabled": False, "completionSchemaVersion": "3.1"})),
        ("disconnected.run-record", lambda d: d.update(activation={"visionFinalizationEnabled": True, "completionSchemaVersion": "3.0"})),
        ("disconnected.run-record", lambda d: d.pop("activation")),
        ("disconnected.run-record", lambda d: d.update(schema="s1-disconnected-run-v1")),
        ("disconnected.connect-trace", lambda d: d["attempts"].append({"address": "151.101.0.223", "port": 443})),  # pypi
        ("disconnected.connect-trace", lambda d: d["attempts"].append({"address": "10.0.0.5", "port": 3128})),  # a LAN proxy
        ("disconnected.connect-trace", lambda d: d["attempts"].append({"address": "pypi.org", "port": 443})),
        ("disconnected.connect-trace", lambda d: d.update(sourceCommit="c" * 40)),
        ("disconnected.connect-trace", lambda d: d.update(method="")),
        ("disconnected.dependency-diff", lambda d: d.update(addedDependencies=["psutil==6.0"])),
        ("disconnected.dependency-diff", lambda d: d.update(toSha="c" * 40)),
        ("disconnected.runtime-manifests", lambda d: d.update(manifests=[])),
        ("disconnected.runtime-manifests", lambda d: d["manifests"][0].update(sha256="not-a-hash")),
        ("disconnected.runtime-manifests", lambda d: d.update(sourceCommit="c" * 40)),
    ],
)
def test_the_disconnected_run_must_exercise_3_1_with_no_hidden_dependency_or_network(tmp_path: Path, artifact: str, mutate) -> None:
    record = materialize(complete_record(), tmp_path)
    _rewrite_json(record, tmp_path, artifact, mutate)
    assert ("DISCONNECTED", "disconnected_run_incomplete") in _verified_codes(record, tmp_path)


@pytest.mark.parametrize("artifact", ["disconnected.dependency-diff", "disconnected.connect-trace", "disconnected.runtime-manifests"])
def test_the_disconnected_bindings_are_required(artifact: str) -> None:
    record = complete_record()
    record["units"]["DISCONNECTED"]["artifacts"].remove(artifact)
    assert ("DISCONNECTED", "artifact_missing") in codes(record)


@pytest.mark.parametrize(("address", "loopback"), [
    ("127.0.0.1", True), ("127.8.8.8", True), ("::1", True), ("[::1]", True), ("localhost", True), ("/run/postgresql/.s.PGSQL.5432", True),
    ("10.0.0.5", False), ("192.168.1.10", False), ("8.8.8.8", False), ("github.com", False), ("", False),
])
def test_only_loopback_connect_targets_are_local(address: str, loopback: bool) -> None:
    assert s1_evidence.is_loopback_address(address) is loopback


@pytest.mark.parametrize("artifact", ["b3a.hand-off-output", "b3b.finalization-output", "b3.crash-matrix-output"])
def test_a_b3_output_that_names_the_other_variant_is_refused(tmp_path: Path, artifact: str) -> None:
    # Its bytes differ from the Linux output (another host), so only the variant field betrays it.
    record = materialize(complete_record(), tmp_path)
    _rewrite_json(record, tmp_path, f"{artifact}.windows-x86_64-cpu", lambda d: d.update(variant="linux-x86_64-cpu"))
    findings = [f for f in check_record(record, repo_root=tmp_path, verify_git=False) if f.unit == "B3" and "ran on linux-x86_64-cpu" in f.detail]
    assert findings


def test_the_15_s_hand_off_cap_holds_when_half_the_worker_timeout_is_looser(tmp_path: Path) -> None:
    # F4 plan §8.4: the bound is min(15 s, timeout/2). With a 60 s worker default,
    # timeout/2 is 30 s, so only the 15 s cap can refuse a 20 s hand-off.
    assert s1_evidence.HANDOFF_BOUND_MS == 15_000.0
    measured = _settings_repo(tmp_path / "repo", "60.0")
    record = with_sha(complete_record(), measured)
    checker = s1_evidence._Checker(record, tmp_path / "repo", verify_git=True)
    variant = s1_evidence.QUALIFIED_CPU_VARIANTS[0]
    metric = f"{s1_evidence.HANDOFF_WALL_METRIC}.{variant}"
    host = record["measurements"][f"B3:{metric}"]["host"]
    for hand_off_max, refused in ((20_000.0, True), (15_000.0, False)):
        checker.findings.clear()
        checker._b3_bounds(
            {
                "b3.worker-request-timeout-ms": {"value": 60_000.0},
                metric: {"metric": metric, "host": host, "stats": {"max": hand_off_max}},
            },
            measured,
        )
        assert any(f.code == "hand_off_bound_violated" for f in checker.findings) is refused, hand_off_max
        assert not any(f.code in ("worker_timeout_unbound", "worker_timeout_out_of_range") for f in checker.findings)
