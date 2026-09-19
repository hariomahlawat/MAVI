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
_GPU_DIGEST = "cb70319f" + "0" * 56


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
    codes = declared["expectedFailureCodes"]
    value: dict = {
        "schemaVersion": "mavi-windows-cuda-failure-case-v1",
        "configuredDevicePolicy": declared["configuredDevicePolicy"],
        "outcome": declared["outcome"],
        # Each case declares the codes it can legitimately produce, so the
        # fixture uses one of them rather than a single placeholder shared by
        # every case -- which is how the missing check went unnoticed before.
        "failureCode": codes[0] if codes else "vision_runtime_incompatible",
        "operatorDiagnostic": (
            f"{case_id}: refused as declared; see the worker log for the "
            "stable code above."
        ),
        "actualDevice": None,
        "deviceResolutionReason": None,
        "processingCompleted": False,
    }
    if declared["outcome"] == "auto-fallback-cpu":
        value.update(
            {
                "failureCode": None,
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
    if declared["requiresHardware"]:
        value.update({"gpuUuidSha256": _GPU_DIGEST, "driverVersion": "560.94"})
    value.update(overrides)
    if value.get("failureCode") is None:
        value.pop("failureCode", None)
    return value


def _hardware_evidence(**overrides) -> dict:
    value = {
        "schemaVersion": "mavi-windows-cuda-development-evidence-v2",
        "developmentEvidence": {
            "hostObservationSha256": "ab" * 32,
            "evidenceBundleSha256": "cd" * 32,
            "sourceHeadSha": _SOURCE_HEAD_SHA,
            "capturedAtUtc": "2026-09-18T04:11:52Z",
            "operatorReference": _OPERATOR,
        },
        "corroboration": {"gpuUuidSha256": _GPU_DIGEST},
    }
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
    hardware: dict | None = None,
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
    evidence_path = None
    if scope == "hardware":
        evidence_path = _write(
            tmp_path,
            "hardware.json",
            _hardware_evidence() if hardware is None else hardware,
        )
    return MODULE.build_failure_matrix(
        scope=scope,
        cases={
            case: _write(tmp_path, f"case-{case}.json", record)
            for case, record in records.items()
        },
        source_head_sha=source_head_sha,
        captured_at_utc=captured_at_utc,
        operator_reference=operator_reference,
        development_evidence=evidence_path,
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
        _build(tmp_path, scope="windows-host", cases={case: observation})

    assert _code(excinfo) == "failure_case_not_fail_closed:" + case


def test_a_fail_closed_case_that_completed_processing_is_refused(tmp_path):
    case = "corrupted-lock"
    observation = _observation(case, processingCompleted=True)

    with pytest.raises(MODULE.FailureMatrixError) as excinfo:
        _build(tmp_path, scope="windows-host", cases={case: observation})

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
        _build(tmp_path, scope="windows-host", cases={case: observation})

    assert _code(excinfo) == "failure_case_not_fail_closed:" + case


@pytest.mark.parametrize(
    "case", sorted(MODULE.expected_cases("linux-observable"))
)
def test_no_fail_closed_case_may_carry_a_resolution_reason(tmp_path, case):
    if MODULE.FAILURE_CASES[case]["outcome"] != "fail-closed":
        pytest.skip("not a fail-closed case")
    observation = _observation(case, deviceResolutionReason="cuda_pack_absent")

    with pytest.raises(MODULE.FailureMatrixError) as excinfo:
        _build(tmp_path, scope="windows-host", cases={case: observation})

    assert _code(excinfo) == (
        "failure_case_unexpected_resolution_reason:" + case
    )


def test_a_fallback_for_the_wrong_reason_does_not_satisfy_a_case(tmp_path):
    case = "auto-pack-absent"
    observation = _observation(
        case, deviceResolutionReason="cuda_device_unavailable"
    )

    with pytest.raises(MODULE.FailureMatrixError) as excinfo:
        _build(tmp_path, scope="windows-host", cases={case: observation})

    assert _code(excinfo) == "failure_case_resolution_reason_mismatch:" + case


def test_a_fallback_reason_outside_the_vocabulary_is_refused(tmp_path):
    """Checked against the vocabulary itself, not only against this case."""
    case = "auto-pack-absent"
    observation = _observation(case, deviceResolutionReason="cuda_seemed_off")

    with pytest.raises(MODULE.FailureMatrixError) as excinfo:
        _build(tmp_path, scope="windows-host", cases={case: observation})

    assert _code(excinfo) == "failure_case_resolution_reason_unknown:" + case


def test_an_unlogged_fallback_is_a_silent_fallback(tmp_path):
    case = "auto-pack-absent"
    observation = _observation(case, fallbackLogged=False)

    with pytest.raises(MODULE.FailureMatrixError) as excinfo:
        _build(tmp_path, scope="windows-host", cases={case: observation})

    assert _code(excinfo) == "failure_case_fallback_not_logged:" + case


def test_a_fallback_missing_from_provenance_is_refused(tmp_path):
    case = "auto-pack-absent"
    observation = _observation(case, fallbackPersistedInProvenance=False)

    with pytest.raises(MODULE.FailureMatrixError) as excinfo:
        _build(tmp_path, scope="windows-host", cases={case: observation})

    assert _code(excinfo) == "failure_case_fallback_not_persisted:" + case


def test_a_fallback_that_did_not_land_on_cpu_is_refused(tmp_path):
    case = "auto-pack-absent"
    observation = _observation(case, actualDevice="cuda:0")

    with pytest.raises(MODULE.FailureMatrixError) as excinfo:
        _build(tmp_path, scope="windows-host", cases={case: observation})

    assert _code(excinfo) == "failure_case_fallback_device_invalid:" + case


def test_a_case_claiming_the_wrong_outcome_is_refused(tmp_path):
    case = "corrupted-lock"
    observation = _observation(case, outcome="recovered")

    with pytest.raises(MODULE.FailureMatrixError) as excinfo:
        _build(tmp_path, scope="windows-host", cases={case: observation})

    assert _code(excinfo) == "failure_case_outcome_mismatch:" + case


def test_a_case_run_under_the_wrong_policy_is_refused(tmp_path):
    case = "explicit-cuda-pack-absent"
    observation = _observation(case, configuredDevicePolicy="auto")

    with pytest.raises(MODULE.FailureMatrixError) as excinfo:
        _build(tmp_path, scope="windows-host", cases={case: observation})

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
        _build(tmp_path, scope="windows-host", cases={case: observation})

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
        _build(tmp_path, scope="windows-host", cases={case: observation})

    assert _code(excinfo) == code + ":" + case


def test_an_observation_of_the_wrong_schema_is_refused(tmp_path):
    case = "corrupted-lock"
    observation = _observation(case, schemaVersion="mavi-something-else-v1")

    with pytest.raises(MODULE.FailureMatrixError) as excinfo:
        _build(tmp_path, scope="windows-host", cases={case: observation})

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
                "corrupted-lock", failureCode="offline_lock_hash_invalid"
            )
        },
    )

    assert (
        baseline["failureMatrix"]["evidenceBundleSha256"]
        != altered["failureMatrix"]["evidenceBundleSha256"]
    )


# --- Guards that an earlier adversarial review proved were unpinned. Each of
# --- these corresponds to a weakening mutation that previously survived.


def test_every_declared_code_is_one_the_system_can_actually_emit():
    """A matrix citing codes nothing raises would certify against fiction."""
    declared = {
        code
        for case in MODULE.FAILURE_CASES.values()
        if case["expectedFailureCodes"]
        for code in case["expectedFailureCodes"]
    }

    assert declared
    assert declared <= MODULE.CITABLE_FAILURE_CODES


def test_declared_launcher_codes_exist_in_the_launcher_contract():
    from mavi_vision.runtime.launch_failures import LAUNCH_FAILURE_CODES

    declared = {
        code
        for case in MODULE.FAILURE_CASES.values()
        if case["expectedFailureCodes"]
        for code in case["expectedFailureCodes"]
        if code.startswith("launch_")
    }

    assert declared
    assert declared <= LAUNCH_FAILURE_CODES


def test_restated_worker_codes_still_exist_at_their_raise_sites():
    """These codes are inline literals, so a restatement needs a tripwire."""
    root = Path(__file__).resolve().parents[1] / "mavi_vision"
    sources = "\n".join(
        path.read_text(encoding="utf-8") for path in root.rglob("*.py")
    )

    for code in MODULE._OFFLINE_LOCK_CODES | MODULE._GPU_IDENTITY_CODES:
        assert f'"{code}"' in sources, code


def test_a_case_may_not_carry_a_code_belonging_to_another_case(tmp_path):
    case = "explicit-cuda-resolved-to-cpu-refused"
    observation = _observation(case, failureCode="offline_lock_hash_invalid")

    with pytest.raises(MODULE.FailureMatrixError) as excinfo:
        _build(tmp_path, scope="windows-host", cases={case: observation})

    assert _code(excinfo) == "failure_case_failure_code_unexpected:" + case


def test_an_unrelated_failure_code_never_satisfies_a_case(tmp_path):
    case = "corrupted-lock"
    observation = _observation(case, failureCode="disk_full")

    with pytest.raises(MODULE.FailureMatrixError) as excinfo:
        _build(tmp_path, cases={case: observation})

    assert _code(excinfo) == "failure_case_failure_code_unexpected:" + case


def test_a_permitted_fallback_is_not_reported_as_a_failure(tmp_path):
    """The run succeeded on CPU; the reason is the record, not a failure code."""
    case = "auto-pack-absent"
    observation = _observation(case, failureCode="vision_runtime_incompatible")

    with pytest.raises(MODULE.FailureMatrixError) as excinfo:
        _build(tmp_path, scope="windows-host", cases={case: observation})

    assert _code(excinfo) == "failure_case_fallback_has_failure_code:" + case


@pytest.mark.parametrize("value", (1, "no", None))
def test_a_fail_closed_case_must_state_that_nothing_ran(tmp_path, value):
    """Silence, and a truthy non-boolean, are both not-False."""
    case = "corrupted-lock"
    observation = _observation(case)
    if value is None:
        del observation["processingCompleted"]
    else:
        observation["processingCompleted"] = value

    with pytest.raises(MODULE.FailureMatrixError) as excinfo:
        _build(tmp_path, cases={case: observation})

    assert _code(excinfo) == "failure_case_not_fail_closed:" + case


def test_a_fail_closed_case_claiming_truthy_recovery_is_refused(tmp_path):
    case = "corrupted-lock"
    observation = _observation(case, recovered=1)

    with pytest.raises(MODULE.FailureMatrixError) as excinfo:
        _build(tmp_path, cases={case: observation})

    assert _code(excinfo) == "failure_case_retry_not_permitted:" + case


def test_a_hardware_bundle_requires_the_c4_evidence_it_was_observed_against(
    tmp_path,
):
    with pytest.raises(MODULE.FailureMatrixError) as excinfo:
        MODULE.build_failure_matrix(
            scope="hardware",
            cases={
                case: _write(tmp_path, f"case-{case}.json", _observation(case))
                for case in MODULE.expected_cases("hardware")
            },
            source_head_sha=_SOURCE_HEAD_SHA,
            captured_at_utc=_CAPTURED_AT,
            operator_reference=_OPERATOR,
        )

    assert _code(excinfo) == "failure_matrix_development_evidence_required"


def test_a_non_hardware_bundle_may_not_cite_hardware_evidence(tmp_path):
    """Citing it would imply exactly what the scope label denies."""
    with pytest.raises(MODULE.FailureMatrixError) as excinfo:
        MODULE.build_failure_matrix(
            scope="linux-observable",
            cases={
                case: _write(tmp_path, f"case-{case}.json", _observation(case))
                for case in MODULE.expected_cases("linux-observable")
            },
            source_head_sha=_SOURCE_HEAD_SHA,
            captured_at_utc=_CAPTURED_AT,
            operator_reference=_OPERATOR,
            development_evidence=_write(
                tmp_path, "hardware.json", _hardware_evidence()
            ),
        )

    assert _code(excinfo) == "failure_matrix_development_evidence_out_of_scope"


@pytest.mark.parametrize(
    "case",
    sorted(
        c
        for c, d in MODULE.FAILURE_CASES.items()
        if d["requiresHardware"]
    ),
)
def test_a_hardware_case_must_name_the_card_it_was_observed_on(tmp_path, case):
    """Otherwise a full hardware bundle assembles on a machine with no GPU."""
    observation = _observation(case)
    del observation["gpuUuidSha256"]

    with pytest.raises(MODULE.FailureMatrixError) as excinfo:
        _build(tmp_path, scope="hardware", cases={case: observation})

    assert _code(excinfo) == "failure_case_gpu_identity_missing:" + case


def test_a_hardware_case_observed_on_another_card_is_refused(tmp_path):
    case = "explicit-cuda-wrong-physical-gpu"
    observation = _observation(case, gpuUuidSha256="ab" * 32)

    with pytest.raises(MODULE.FailureMatrixError) as excinfo:
        _build(tmp_path, scope="hardware", cases={case: observation})

    assert _code(excinfo) == "failure_case_gpu_identity_mismatch:" + case


def test_a_hardware_case_must_state_the_driver_it_ran_under(tmp_path):
    case = "explicit-cuda-device-unavailable"
    observation = _observation(case)
    del observation["driverVersion"]

    with pytest.raises(MODULE.FailureMatrixError) as excinfo:
        _build(tmp_path, scope="hardware", cases={case: observation})

    assert _code(excinfo) == "failure_case_driver_version_missing:" + case


def test_a_hardware_bundle_from_another_source_revision_is_refused(tmp_path):
    hardware = _hardware_evidence()
    hardware["developmentEvidence"]["sourceHeadSha"] = "f" * 40

    with pytest.raises(MODULE.FailureMatrixError) as excinfo:
        _build(tmp_path, scope="hardware", hardware=hardware)

    assert _code(excinfo) == "failure_matrix_source_revision_mismatch"


def test_a_raw_gpu_uuid_pasted_by_an_operator_is_redacted(tmp_path):
    """The natural driver message for a wrong-GPU refusal is the UUID itself."""
    case = "explicit-cuda-wrong-physical-gpu"
    observation = _observation(
        case,
        operatorDiagnostic=(
            "explicit CUDA refused: attested "
            "GPU-6c1f0a3e-9b2d-4c7f-a1e5-2b8d4f6a9c01 is not the device at cuda:0"
        ),
    )

    evidence = _build(tmp_path, scope="hardware", cases={case: observation})

    serialised = json.dumps(evidence)
    assert "GPU-6c1f0a3e" not in serialised
    assert "GPU-<redacted>" in serialised
    assert "is not the device at cuda:0" in serialised


def test_the_explicit_cuda_cases_mirror_every_permitted_fallback_reason():
    """Where Auto may legitimately answer CPU, explicit CUDA must refuse.

    Those are the highest-risk places for a silent fallback precisely because a
    legitimate CPU answer exists next door, so each one needs its own refusal
    case rather than only the four that were obvious.
    """
    mirrors = {
        "cuda_pack_absent": "explicit-cuda-pack-absent",
        "cuda_pack_integrity_failed": "explicit-cuda-pack-integrity-failed",
        "cuda_pack_id_mismatch": "explicit-cuda-pack-identity-mismatch",
        "cuda_device_unavailable": "explicit-cuda-device-unavailable",
        "cuda_pack_not_declared": "explicit-cuda-pack-not-declared",
        "cuda_pack_variant_mismatch": "explicit-cuda-pack-variant-mismatch",
        "cuda_driver_probe_unavailable": "explicit-cuda-driver-probe-unavailable",
        "cuda_driver_probe_failed": "explicit-cuda-driver-probe-failed",
    }

    assert set(mirrors) == set(AUTO_CPU_DEVICE_RESOLUTION_REASONS)
    for case_id in mirrors.values():
        assert case_id in MODULE.FAILURE_CASES, case_id
        assert MODULE.FAILURE_CASES[case_id]["outcome"] == "fail-closed"


def test_the_declared_scope_counts_are_pinned():
    """The plan and the operator run sheet quote these numbers."""
    assert len(MODULE.FAILURE_CASES) == 37
    assert len(MODULE.expected_cases("hardware")) == 37
    assert len(MODULE.expected_cases("windows-host")) == 25
    assert len(MODULE.expected_cases("linux-observable")) == 5


def test_a_launcher_stage_case_is_not_claimed_to_be_linux_observable():
    """PowerShell does not run in hosted CI, so launcher cases need a host.

    Two device-resolution cases are the worker's own: `cuda_pack_not_declared`
    is produced by the supervisor's Auto branch, and an unknown reason is
    refused by the worker's contract layer. Those are genuinely observable
    here; everything else at this stage is `Test-CudaRuntimeUsable`.
    """
    worker_resolved = {"auto-pack-not-declared", "auto-unknown-reason-refused"}

    for case_id, declared in MODULE.FAILURE_CASES.items():
        if declared["stage"] != "device-resolution" or case_id in worker_resolved:
            continue
        assert declared["requiresWindowsHost"] is True, case_id

    for case_id in worker_resolved:
        assert MODULE.FAILURE_CASES[case_id]["requiresWindowsHost"] is False


def test_an_unbounded_operator_diagnostic_is_refused(tmp_path):
    """A pasted log dump is not a diagnostic, and it bloats every bundle."""
    case = "corrupted-lock"
    observation = _observation(case, operatorDiagnostic="x" * 2001)

    with pytest.raises(MODULE.FailureMatrixError) as excinfo:
        _build(tmp_path, cases={case: observation})

    assert _code(excinfo) == (
        "failure_case_operator_diagnostic_invalid:" + case
    )


def test_redaction_applies_to_every_case_not_only_hardware_ones(tmp_path):
    case = "corrupted-lock"
    observation = _observation(
        case,
        operatorDiagnostic=(
            "lock refused while GPU-6c1f0a3e-9b2d-4c7f-a1e5-2b8d4f6a9c01 idle"
        ),
    )

    evidence = _build(tmp_path, cases={case: observation})

    assert "GPU-6c1f0a3e" not in json.dumps(evidence)
