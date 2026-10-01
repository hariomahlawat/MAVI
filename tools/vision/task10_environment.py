#!/usr/bin/env python3
"""Task 10 split-job environment and harness-evidence checks (qualification tooling).

Task 10 runs the S1 qualification harness in its own job, concurrently with the
full-runtime candidate job. The harness imports none of PyTorch, MMCV, MMEngine
or MMDetection, so it does not wait for them. It must, however, run on exactly
what the qualified candidate environment contains. This tool provides three
subcommands:

* ``record``        -- write the Python, platform, distribution and head identity of this job.
* ``check-harness`` -- the retained harness JUnit names this variant, ran tests, has
                       no failure or error, and skips only what the S1 checker approves.
* ``check-mmcv``    -- the candidate's ``mmcv-wheel.json`` is this head's and variant's,
                       and says how the installed MMCV wheel was obtained: built in this
                       run, or reused from a producer GitHub attested as trusted.
* ``compare``       -- the harness environment is a subset of the candidate environment:
                       the same head, variant, Python build and platform, and every
                       distribution in the harness requirements' dependency closure at
                       the version the candidate had.

The comparison covers the closure, not every installed distribution. A hosted
runner's Python comes with tools preinstalled (pipx, platformdirs, filelock...),
and their versions differ between image versions. Two jobs of one workflow run
can land on different image versions, and those tools are not part of what
the harness runs. Every installed distribution is still recorded, and the
runtime graph must be absent from all of them.

See docs/qualification/stage2-s1/2026-10-01-task10-harness-separation-and-mmcv-wheel-reuse.md.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import re
import sys
import sysconfig
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

SCHEMA = "mavi-task10-environment-v1"
HARNESS_STEP = "task10:s1-qualification-harness"
# What the harness must not need: the qualified runtime graph proper. If the
# harness ever imported one of these it would fail in its own job rather than
# silently run outside the environment it is qualified against.
CANDIDATE_ONLY = frozenset({"torch", "torchvision", "mmcv", "mmengine", "mmdet"})


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement_names(path: Path) -> list[str]:
    from packaging.requirements import Requirement  # noqa: PLC0415 - harness/candidate environments only

    names = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            names.append(_normalize(Requirement(line).name))
    return names


def dependency_closure(roots: list[str]) -> list[str]:
    """Installed distributions reachable from ``roots`` through their declared requirements."""
    from packaging.requirements import Requirement  # noqa: PLC0415

    installed = {}
    for dist in importlib.metadata.distributions():
        name = dist.metadata.get("Name")
        if name:
            installed.setdefault(_normalize(name), dist)
    seen: set[str] = set()
    pending = [(_normalize(root), frozenset()) for root in roots]
    expanded: set[tuple[str, frozenset[str]]] = set()
    while pending:
        name, extras = pending.pop()
        if (name, extras) in expanded:
            continue
        expanded.add((name, extras))
        dist = installed.get(name)
        if dist is None:
            raise SystemExit(f"closure_root_or_dependency_not_installed:{name}")
        seen.add(name)
        for text in dist.requires or ():
            requirement = Requirement(text)
            if requirement.marker is not None and not any(
                requirement.marker.evaluate({"extra": extra}) for extra in (extras or {""})
            ):
                continue
            pending.append((_normalize(requirement.name), frozenset(requirement.extras)))
    return sorted(seen)


def environment_record(roots: Path | None = None) -> dict[str, Any]:
    distributions: dict[str, str] = {}
    for dist in importlib.metadata.distributions():
        name = dist.metadata.get("Name")
        if name:
            distributions[_normalize(name)] = dist.version
    return {
        "schema": SCHEMA,
        "headSha": os.environ.get("MAVI_EXPECTED_SOURCE_SHA"),
        "runtimeVariant": os.environ.get("MAVI_RUNTIME_VARIANT"),
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "build": list(platform.python_build()),
            "compiler": platform.python_compiler(),
        },
        "platform": {
            "system": platform.system(),
            "machine": platform.machine(),
            "sysconfigPlatform": sysconfig.get_platform(),
            "runnerImage": os.environ.get("ImageOS"),
        },
        "distributions": dict(sorted(distributions.items())),
        **({"closure": dependency_closure(_requirement_names(roots))} if roots else {}),
    }


def compare(candidate: dict[str, Any], harness: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for record, role in ((candidate, "candidate"), (harness, "harness")):
        if record.get("schema") != SCHEMA:
            problems.append(f"{role}_schema_unknown")
    for field in ("headSha", "runtimeVariant", "python", "platform"):
        if not candidate.get(field) or candidate.get(field) != harness.get(field):
            problems.append(f"{field}_differs")
    have = candidate.get("distributions") or {}
    harness_distributions = harness.get("distributions") or {}
    closure = harness.get("closure")
    if not isinstance(closure, list) or not closure:
        problems.append("harness_closure_missing")
        closure = []
    for name in closure:
        if name not in harness_distributions:
            problems.append(f"harness_closure_not_installed:{name}")
    for name, version in sorted((n, harness_distributions[n]) for n in closure if n in harness_distributions):
        if name not in have:
            problems.append(f"harness_only_distribution:{name}=={version}")
        elif have[name] != version:
            problems.append(f"distribution_version_differs:{name}:{version}!={have[name]}")
    for name in sorted(CANDIDATE_ONLY & set(harness.get("distributions") or {})):
        problems.append(f"harness_has_runtime_graph_distribution:{name}")
    for name in sorted(CANDIDATE_ONLY - set(have)):
        problems.append(f"candidate_lacks_runtime_graph_distribution:{name}")
    return problems


def check_harness(junit: Path, variant: str) -> list[str]:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "qualification"))
    import s1_evidence  # noqa: PLC0415 - the S1 checker's own skip approvals, not a copy

    if not junit.is_file():
        return [f"junit_missing:{junit.as_posix()}"]
    try:
        root = ElementTree.parse(junit).getroot()
    except ElementTree.ParseError as exc:
        return [f"junit_unreadable:{exc}"]
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    problems: list[str] = []
    if not suites:
        problems.append("junit_has_no_testsuite")
    for suite in suites:
        if suite.get("name") != variant:
            problems.append(f"junit_suite_not_this_variant:{suite.get('name')}")
    cases = list(root.iter("testcase"))
    if not cases:
        problems.append("junit_has_no_testcases")
    for case in cases:
        test_id = f"{case.get('classname')}::{case.get('name')}"
        if case.find("failure") is not None or case.find("error") is not None:
            problems.append(f"harness_test_failed:{test_id}")
        if case.find("skipped") is not None and not s1_evidence.is_approved_skip(HARNESS_STEP, variant, test_id):
            problems.append(f"harness_skip_not_approved:{test_id}")
    return problems


REUSE_TRUST = frozenset({"default-branch", "same-head"})


def check_mmcv(record: dict[str, Any], variant: str, head: str, run_id: str) -> list[str]:
    problems: list[str] = []
    if record.get("headSha") != head:
        problems.append("mmcv_record_head_differs")
    if record.get("runtimeVariant") != variant:
        problems.append("mmcv_record_variant_differs")
    if str(record.get("runId")) != str(run_id):
        problems.append("mmcv_record_not_this_run")
    provenance = record.get("provenance") or {}
    wheel = provenance.get("wheel") or {}
    if not provenance.get("identitySha256") or not wheel.get("sha256"):
        problems.append("mmcv_record_provenance_incomplete")
    attestation = record.get("attestation") or {}
    state = record.get("state")
    if state == "build":
        build = provenance.get("build") or {}
        if attestation.get("trust") != "built-in-this-run" or str(build.get("runId")) != str(run_id):
            problems.append("mmcv_build_not_this_run")
        if build.get("sourceSha") != head:
            problems.append("mmcv_build_not_this_head")
    elif state == "reuse":
        if attestation.get("trust") not in REUSE_TRUST:
            problems.append(f"mmcv_reuse_not_attested:{attestation.get('trust')}")
        if str(attestation.get("runId")) != str((provenance.get("build") or {}).get("runId")):
            problems.append("mmcv_reuse_attestation_not_the_producer")
        if attestation.get("trust") == "same-head" and attestation.get("headSha") != head:
            problems.append("mmcv_reuse_same_head_differs")
    else:
        problems.append(f"mmcv_state_unknown:{state}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    rec = sub.add_parser("record")
    rec.add_argument("--out", required=True, type=Path)
    rec.add_argument("--closure-roots", type=Path, help="requirements file whose dependency closure is compared")
    chk = sub.add_parser("check-harness")
    chk.add_argument("--junit", required=True, type=Path)
    chk.add_argument("--variant", required=True)
    mm = sub.add_parser("check-mmcv")
    mm.add_argument("--record", required=True, type=Path)
    mm.add_argument("--variant", required=True)
    mm.add_argument("--head", required=True)
    mm.add_argument("--run-id", required=True)
    cmp_ = sub.add_parser("compare")
    cmp_.add_argument("--candidate", required=True, type=Path)
    cmp_.add_argument("--harness", required=True, type=Path)
    args = parser.parse_args(argv)

    if args.command == "record":
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(environment_record(args.closure_roots), sort_keys=True, indent=1) + "\n", encoding="utf-8")
        return 0
    if args.command == "check-harness":
        problems = check_harness(args.junit, args.variant)
    elif args.command == "check-mmcv":
        if not args.record.is_file():
            problems = [f"mmcv_record_missing:{args.record.as_posix()}"]
        else:
            try:
                record = json.loads(args.record.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                record, problems = None, [f"mmcv_record_unreadable:{exc}"]
            if record is not None:
                problems = check_mmcv(record, args.variant, args.head, args.run_id) if isinstance(record, dict) else ["mmcv_record_unreadable"]
    else:
        problems = []
        for path in (args.candidate, args.harness):
            if not path.is_file():
                problems.append(f"environment_record_missing:{path.as_posix()}")
        if not problems:
            problems = compare(
                json.loads(args.candidate.read_text(encoding="utf-8")),
                json.loads(args.harness.read_text(encoding="utf-8")),
            )
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        return 1
    print(f"task10-{args.command}-ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
