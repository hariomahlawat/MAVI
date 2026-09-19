#!/usr/bin/env python3
"""Check that the evidence assemblers' fail-closed guards are actually tested.

A guard no test can distinguish is not a guard: it can be deleted, or quietly
stop firing, and nothing says so. Adversarial review of the C6 and C7 assemblers
found ten such guards at once -- every weakening mutation applied to them left
the suites green -- and the same shape has appeared repeatedly in this
workstream as a check with nothing to say.

So the check is mechanical rather than a matter of remembering: each entry below
names one guard by the exact source line that implements it, neutralises that
line, and requires the suite to fail. A surviving mutation means either the
guard is untested or it is redundant with another check; both are worth knowing,
and neither is visible from a passing test run.

The catalogue is deliberately explicit rather than generated. A mutation tool
that rewrites arbitrary expressions produces equivalent mutants and noise; this
one states the specific weakenings a reviewer would try, so a survivor is always
a real answer to a real question.

Offline, and it restores every file it touches -- including on failure.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VISION = ROOT / "src" / "vision"


@dataclass(frozen=True)
class Mutation:
    """One weakening a reviewer would try, and the guard it neutralises."""

    label: str
    path: str
    original: str
    weakened: str


MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        "C6 accepts reserved memory below allocated",
        "tools/vision/build_development_e2e_evidence.py",
        "    if reserved < allocated:",
        "    if False:",
    ),
    Mutation(
        "C6 accepts any architecture list",
        "tools/vision/build_development_e2e_evidence.py",
        "        if target not in arch_list:",
        "        if False:",
    ),
    Mutation(
        "C6 stops requiring persisted tracks",
        "tools/vision/build_development_e2e_evidence.py",
        '    _positive_int(run.get("trackCount"), "e2e_run_no_tracks:" + case_id)',
        "    pass",
    ),
    Mutation(
        "C6 stops requiring a provenance record",
        "tools/vision/build_development_e2e_evidence.py",
        "    if not isinstance(provenance, dict):",
        "    if False:",
    ),
    Mutation(
        "C6 stops requiring device telemetry",
        "tools/vision/build_development_e2e_evidence.py",
        "    if not isinstance(cuda, dict):",
        "    if False:",
    ),
    Mutation(
        "C6 stops requiring nvidia-smi readings",
        "tools/vision/build_development_e2e_evidence.py",
        "    if not isinstance(smi, dict):",
        "    if False:",
    ),
    Mutation(
        "C6 stops binding the run to the qualified card",
        "tools/vision/build_development_e2e_evidence.py",
        '        if observed_gpu != corroboration.get("gpuUuidSha256"):',
        "        if False:",
    ),
    Mutation(
        "C6 trusts the C4 bundle's own digest",
        "tools/vision/build_development_e2e_evidence.py",
        "    if not isinstance(claimed, str) or claimed != _sha256_bytes(",
        "    if False and claimed != _sha256_bytes(",
    ),
    Mutation(
        "C7 stops checking the reason vocabulary",
        "tools/vision/build_failure_matrix_evidence.py",
        "        if reason not in DEVICE_RESOLUTION_REASONS:",
        "        if False:",
    ),
    Mutation(
        "C7 stops bounding the operator diagnostic",
        "tools/vision/build_failure_matrix_evidence.py",
        "if len(diagnostic) > 2000:",
        "if False:",
    ),
    Mutation(
        "C7 stops redacting a raw GPU UUID",
        "tools/vision/build_failure_matrix_evidence.py",
        'diagnostic = _RAW_GPU_UUID.sub("GPU-<redacted>", diagnostic)',
        "diagnostic = str(diagnostic)",
    ),
    Mutation(
        "C7 accepts any failure code for any case",
        "tools/vision/build_failure_matrix_evidence.py",
        "        if expected_codes is not None and failure_code not in expected_codes:",
        "        if False:",
    ),
    Mutation(
        "C7 stops requiring a stated fail-closed outcome",
        "tools/vision/build_failure_matrix_evidence.py",
        '        if observation.get("processingCompleted") is not False:',
        "        if False:",
    ),
    Mutation(
        "C7 stops requiring a hardware case to name its card",
        "tools/vision/build_failure_matrix_evidence.py",
        "        if not isinstance(observed_gpu, str) or _SHA256.fullmatch(",
        "        if False and _SHA256.fullmatch(",
    ),
    Mutation(
        "C4 stops requiring on-device allocation",
        "tools/vision/build_development_hardware_evidence.py",
        "        or allocated <= 0",
        "        or False",
    ),
    Mutation(
        "C4 stops binding the run to its host observation",
        "tools/vision/build_development_hardware_evidence.py",
        "    ) != host_sha:",
        "    ) != host_sha and False:",
    ),
)

SUITES = (
    "tests/test_development_e2e_evidence.py",
    "tests/test_failure_matrix_evidence.py",
    "tests/test_development_hardware_evidence.py",
)


def _run_suites() -> bool:
    """True when the suites pass."""
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *SUITES],
        cwd=VISION,
        capture_output=True,
        text=True,
    )
    return completed.returncode == 0


def check(selected: str | None = None) -> list[Mutation]:
    """Apply each mutation in turn; return the ones the suites did not catch."""
    survivors: list[Mutation] = []
    for mutation in MUTATIONS:
        if selected is not None and selected not in mutation.label:
            continue
        path = ROOT / mutation.path
        original = path.read_text(encoding="utf-8")
        if original.count(mutation.original) != 1:
            # The guard this entry names is gone or was rewritten. That is a
            # finding in itself: the catalogue must track the code it polices.
            raise SystemExit(
                f"guard no longer found (or is ambiguous): {mutation.label}\n"
                f"  {mutation.path}: {mutation.original!r}"
            )
        try:
            path.write_text(
                original.replace(mutation.original, mutation.weakened, 1),
                encoding="utf-8",
            )
            if _run_suites():
                survivors.append(mutation)
        finally:
            path.write_text(original, encoding="utf-8")
    return survivors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--only",
        help="run only mutations whose label contains this text",
    )
    args = parser.parse_args()

    survivors = check(args.only)
    for mutation in MUTATIONS:
        if args.only is not None and args.only not in mutation.label:
            continue
        caught = mutation not in survivors
        print(f"{'caught  ' if caught else 'SURVIVED'}  {mutation.label}")

    if survivors:
        print(
            f"\n{len(survivors)} guard(s) can be removed without failing a test.",
            file=sys.stderr,
        )
        return 1
    print(f"\nall {len(MUTATIONS)} guards are pinned by at least one test.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
