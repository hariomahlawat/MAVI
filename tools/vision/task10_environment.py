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
* ``compare``       -- the harness environment is a subset of the candidate environment:
                       the same head, variant, Python build and platform, and every
                       distribution the harness had at the version the candidate had.

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


def environment_record() -> dict[str, Any]:
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
    for name, version in sorted((harness.get("distributions") or {}).items()):
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    rec = sub.add_parser("record")
    rec.add_argument("--out", required=True, type=Path)
    chk = sub.add_parser("check-harness")
    chk.add_argument("--junit", required=True, type=Path)
    chk.add_argument("--variant", required=True)
    cmp_ = sub.add_parser("compare")
    cmp_.add_argument("--candidate", required=True, type=Path)
    cmp_.add_argument("--harness", required=True, type=Path)
    args = parser.parse_args(argv)

    if args.command == "record":
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(environment_record(), sort_keys=True, indent=1) + "\n", encoding="utf-8")
        return 0
    if args.command == "check-harness":
        problems = check_harness(args.junit, args.variant)
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
