"""C7's output is failures, which is exactly what prose hides.

The matrix is declared as data -- one case per failure the phase must exercise,
each naming the invariant it defends -- and these tests are about the assembler
refusing an observation that does not match its own case. The distinction that
matters most is between a *permitted* fallback and a *silent* one: Development
Auto may resolve to CPU for one of eight declared reasons, logged and persisted;
explicit CUDA may never resolve to CPU at all.

Every record is synthesised in-test; nothing depends on repository state or on
a GPU being present.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from mavi_vision.common.control_plane import (
    AUTO_CPU_DEVICE_RESOLUTION_REASONS,
)


TOOL_PATH = (
    Path(__file__).resolve().parents[3]
    / "tools"
    / "vision"
    / "build_failure_matrix_evidence.py"
)

_SOURCE_HEAD_SHA = "426195d4e1b0a9f2c3d4e5f60718293a4b5c6d7e"
_CAPTURED_AT = "2026-09-18T07:04:11Z"
_OPERATOR = "mavi-dev-workstation-01"


def _load():
    spec = importlib.util.spec_from_file_location(
        "build_failure_matrix_evidence", TOOL_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = _load()


def _observation(case_id: str, **overrides) -> dict:
    declared = MODULE.FAILURE_CASES[case_id]
    value: dict = {
        "schemaVersion": "mavi-windows-cuda-failure-case-v1",
        "configuredDevicePolicy": declared["configuredDevicePolicy"],
        "outcome": declared["outcome"],
        "failureCode": "vision_runtime_unavailable",
        "operatorDiagnostic": (
            f"{case_id}: refused as declared; see the worker log for the "
            "stable code above."
        ),
        "actualDevice": None,
        "deviceResolutionReason": None,
    }
    if declared["outcome"] == "auto-fallback-cpu":
        value.update(
            {
                "actualDevice": "cpu",
                "deviceResolutionReason": declared["deviceResolutionReason"],
                "fallbackLogged": True,
                "fallbackPersistedInProvenance": True,
            }
        )
    if declared["outcome"] == "recovered":
        value.update(
            {
                "actualDevice": "cuda:0",
                "deviceResolutionReason": "explicit_cuda",
                "recovered": True,
                "attemptCount": 2,
            }
        )
    value.update(overrides)
    return value


def _write(root: Path, name: str, value: object) -> Path:
    path = root / name
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def _build(
    tmp_path: Path,
    *,
    scope: str = "linux-observable",
    cases: dict[str, dict] | None = None,
    drop: str | None = None,
    extra: dict[str, dict] | None = None,
    source_head_sha: str = _SOURCE_HEAD_SHA,
    captured_at_utc: str = _CAPTURED_AT,
    operator_reference: str = _OPERATOR,
) -> dict:
    records = {
        case: _observation(case) for case in MODULE.expected_cases(scope)
    }
    if cases:
        records.update(cases)
    if extra:
        records.update(extra)
    if drop is not None:
        records.pop(drop, None)
    return MODULE.build_failure_matrix(
        scope=scope,
        cases={
            case: _write(tmp_path, f"case-{case}.json", record)
            for case, record in records.items()
        },
        source_head_sha=source_head_sha,
        captured_at_utc=captured_at_utc,
        operator_reference=operator_reference,
    )


def _code(excinfo) -> str:
    return excinfo.value.code


def test_the_matrix_covers_every_permitted_auto_fallback_reason():
    """One case per reason, so a reason the runtime emits is never unexercised."""
    exercised = {
        declared["deviceResolutionReason"]
        for declared in MODULE.FAILURE_CASES.values()
        if declared["outcome"] == "auto-fallback-cpu"
    }

    assert exercised == set(AUTO_CPU_DEVICE_RESOLUTION_REASONS)


def test_a_complete_linux_observable_matrix_is_accepted(tmp_path):
    evidence = _build(tmp_path)

    assert evidence["schemaVersion"] == "mavi-windows-cuda-failure-matrix-v1"
    assert evidence["failureMatrix"]["scope"] == "linux-observable"
    assert evidence["failureMatrix"]["caseCount"] == len(
        MODULE.expected_cases("linux-observable")
    )
    assert "not hardware qualification" in evidence["note"]


def test_a_linux_bundle_never_implies_hardware(tmp_path):
    evidence = _build(tmp_path)

    assert all(
        case["requiresHardware"] is False for case in evidence["cases"]
    )
    assert "asserts nothing about any GPU" in evidence["note"]


def test_a_hardware_case_cannot_be_smuggled_into_a_linux_bundle(tmp_path):
    with pytest.raises(MODULE.FailureMatrixError) as excinfo:
        _build(
            tmp_path,
            extra={
                "explicit-cuda-wrong-physical-gpu": _observation(
                    "explicit-cuda-wrong-physical-gpu"
                )
            },
        )

    assert _code(excinfo).startswith(
        "failure_matrix_hardware_case_out_of_scope"
    )


def test_a_hardware_bundle_requires_every_case(tmp_path):
    with pytest.raises(MODULE.FailureMatrixError) as excinfo:
        _build(tmp_path, scope="hardware", drop="explicit-cuda-mmcv-ops-failed")

    assert _code(excinfo) == (
        "failure_matrix_case_missing:explicit-cuda-mmcv-ops-failed"
    )


def test_a_complete_hardware_matrix_is_accepted(tmp_path):
    evidence = _build(tmp_path, scope="hardware")

    assert evidence["failureMatrix"]["caseCount"] == len(MODULE.FAILURE_CASES)


@pytest.mark.parametrize("case", sorted(MODULE.expected_cases("linux-observable")))
def test_every_linux_case_must_be_present(tmp_path, case):
    with pytest.raises(MODULE.FailureMatrixError) as excinfo:
        _build(tmp_path, drop=case)

    assert _code(excinfo) == "failure_matrix_case_missing:" + case


def test_an_unknown_case_is_refused(tmp_path):
    with pytest.raises(MODULE.FailureMatrixError) as excinfo:
        _build(
            tmp_path,
            extra={"it-worked-fine": _observation("corrupted-lock")},
        )

    assert _code(excinfo) == "failure_matrix_unknown_case:it-worked-fine"


def test_a_fail_closed_case_that_reports_a_device_is_refused(tmp_path):
    """If a device resolved, the path did not fail closed."""
    case = "explicit-cuda-pack-absent"
    observation = _observation(case, actualDevice="cuda:0")

    with pytest.raises(MODULE.FailureMatrixError) as excinfo:
        _build(tmp_path, cases={case: observation})

    assert _code(excinfo) == "failure_case_not_fail_closed:" + case


def test_a_fail_closed_case_that_completed_processing_is_refused(tmp_path):
    case = "corrupted-lock"
    observation = _observation(case, processingCompleted=True)

    with pytest.raises(MODULE.FailureMatrixError) as excinfo:
        _build(tmp_path, cases={case: observation})

    assert _code(excinfo) == "failure_case_not_fail_closed:" + case


def test_explicit_cuda_falling_back_to_cpu_is_refused(tmp_path):
    """The forbidden transition, asserted at the case that names it."""
    case = "explicit-cuda-resolved-to-cpu-refused"
    observation = _observation(
        case,
        actualDevice="cpu",
        deviceResolutionReason="cuda_device_unavailable",
    )

    with pytest.raises(MODULE.FailureMatrixError) as excinfo:
        _build(tmp_path, cases={case: observation})

    assert _code(excinfo) == "failure_case_not_fail_closed:" + case


@pytest.mark.parametrize(
    "case", sorted(MODULE.expected_cases("linux-observable"))
)
def test_no_fail_closed_case_may_carry_a_resolution_reason(tmp_path, case):
    if MODULE.FAILURE_CASES[case]["outcome"] != "fail-closed":
        pytest.skip("not a fail-closed case")
    observation = _observation(case, deviceResolutionReason="cuda_pack_absent")

    with pytest.raises(MODULE.FailureMatrixError) as excinfo:
        _build(tmp_path, cases={case: observation})

    assert _code(excinfo) == (
        "failure_case_unexpected_resolution_reason:" + case
    )


def test_a_fallback_for_the_wrong_reason_does_not_satisfy_a_case(tmp_path):
    case = "auto-pack-absent"
    observation = _observation(
        case, deviceResolutionReason="cuda_device_unavailable"
    )

    with pytest.raises(MODULE.FailureMatrixError) as excinfo:
        _build(tmp_path, cases={case: observation})

    assert _code(excinfo) == "failure_case_resolution_reason_mismatch:" + case


def test_a_fallback_reason_outside_the_vocabulary_is_refused(tmp_path):
    case = "auto-pack-absent"
    observation = _observation(case, deviceResolutionReason="cuda_seemed_off")

    with pytest.raises(MODULE.FailureMatrixError) as excinfo:
        _build(tmp_path, cases={case: observation})

    assert _code(excinfo) == "failure_case_resolution_reason_mismatch:" + case


def test_an_unlogged_fallback_is_a_silent_fallback(tmp_path):
    case = "auto-pack-absent"
    observation = _observation(case, fallbackLogged=False)

    with pytest.raises(MODULE.FailureMatrixError) as excinfo:
        _build(tmp_path, cases={case: observation})

    assert _code(excinfo) == "failure_case_fallback_not_logged:" + case


def test_a_fallback_missing_from_provenance_is_refused(tmp_path):
    case = "auto-pack-absent"
    observation = _observation(case, fallbackPersistedInProvenance=False)

    with pytest.raises(MODULE.FailureMatrixError) as excinfo:
        _build(tmp_path, cases={case: observation})

    assert _code(excinfo) == "failure_case_fallback_not_persisted:" + case


def test_a_fallback_that_did_not_land_on_cpu_is_refused(tmp_path):
    case = "auto-pack-absent"
    observation = _observation(case, actualDevice="cuda:0")

    with pytest.raises(MODULE.FailureMatrixError) as excinfo:
        _build(tmp_path, cases={case: observation})

    assert _code(excinfo) == "failure_case_fallback_device_invalid:" + case


def test_a_case_claiming_the_wrong_outcome_is_refused(tmp_path):
    case = "corrupted-lock"
    observation = _observation(case, outcome="recovered")

    with pytest.raises(MODULE.FailureMatrixError) as excinfo:
        _build(tmp_path, cases={case: observation})

    assert _code(excinfo) == "failure_case_outcome_mismatch:" + case


def test_a_case_run_under_the_wrong_policy_is_refused(tmp_path):
    case = "explicit-cuda-pack-absent"
    observation = _observation(case, configuredDevicePolicy="auto")

    with pytest.raises(MODULE.FailureMatrixError) as excinfo:
        _build(tmp_path, cases={case: observation})

    assert _code(excinfo) == "failure_case_device_policy_mismatch:" + case


def test_a_recovery_case_that_never_retried_is_refused(tmp_path):
    case = "cuda-out-of-memory-recovered"
    observation = _observation(case, attemptCount=1)

    with pytest.raises(MODULE.FailureMatrixError) as excinfo:
        _build(tmp_path, scope="hardware", cases={case: observation})

    assert _code(excinfo) == "failure_case_recovery_not_exercised:" + case


def test_a_recovery_case_that_did_not_recover_is_refused(tmp_path):
    case = "worker-restart-recovered"
    observation = _observation(case, recovered=False)

    with pytest.raises(MODULE.FailureMatrixError) as excinfo:
        _build(tmp_path, scope="hardware", cases={case: observation})

    assert _code(excinfo) == "failure_case_not_recovered:" + case


def test_a_fail_closed_case_may_not_claim_recovery(tmp_path):
    case = "corrupted-manifest"
    observation = _observation(case, recovered=True)

    with pytest.raises(MODULE.FailureMatrixError) as excinfo:
        _build(tmp_path, cases={case: observation})

    assert _code(excinfo) == "failure_case_retry_not_permitted:" + case


@pytest.mark.parametrize(
    ("field", "value", "code"),
    (
        ("failureCode", "", "failure_case_failure_code_missing"),
        ("failureCode", "Vision Runtime Broke", "failure_case_failure_code_invalid"),
        ("operatorDiagnostic", "", "failure_case_operator_diagnostic_missing"),
    ),
)
def test_a_case_without_a_usable_diagnostic_is_refused(
    tmp_path, field, value, code
):
    """An operator has to be able to act on what the failure reported."""
    case = "corrupted-lock"
    observation = _observation(case, **{field: value})

    with pytest.raises(MODULE.FailureMatrixError) as excinfo:
        _build(tmp_path, cases={case: observation})

    assert _code(excinfo) == code + ":" + case


def test_an_observation_of_the_wrong_schema_is_refused(tmp_path):
    case = "corrupted-lock"
    observation = _observation(case, schemaVersion="mavi-something-else-v1")

    with pytest.raises(MODULE.FailureMatrixError) as excinfo:
        _build(tmp_path, cases={case: observation})

    assert _code(excinfo) == "failure_case_schema_invalid"


@pytest.mark.parametrize(
    ("kwargs", "code"),
    (
        ({"scope": "whatever"}, "failure_matrix_scope_invalid"),
        ({"source_head_sha": "abc"}, "failure_matrix_source_head_sha_invalid"),
        ({"captured_at_utc": "yesterday"}, "failure_matrix_captured_at_invalid"),
        ({"operator_reference": ""}, "failure_matrix_operator_invalid"),
    ),
)
def test_bundle_metadata_is_validated(tmp_path, kwargs, code):
    with pytest.raises(MODULE.FailureMatrixError) as excinfo:
        _build(tmp_path, **kwargs)

    assert _code(excinfo) == code


def test_the_bundle_digest_can_be_recomputed_from_the_file_alone(tmp_path):
    evidence = _build(tmp_path)

    recomputed = json.loads(json.dumps(evidence))
    recomputed["failureMatrix"]["evidenceBundleSha256"] = ""
    digest = hashlib.sha256(
        json.dumps(
            recomputed, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()

    assert digest == evidence["failureMatrix"]["evidenceBundleSha256"]


def test_the_bundle_digest_covers_every_case(tmp_path):
    second = tmp_path / "again"
    second.mkdir()

    baseline = _build(tmp_path)
    altered = _build(
        second,
        cases={
            "corrupted-lock": _observation(
                "corrupted-lock", failureCode="vision_runtime_incompatible"
            )
        },
    )

    assert (
        baseline["failureMatrix"]["evidenceBundleSha256"]
        != altered["failureMatrix"]["evidenceBundleSha256"]
    )
