from __future__ import annotations

import pytest
from pydantic import TypeAdapter

from mavi_vision.common.control_plane import FailureCode
from mavi_vision.runtime.errors import (
    GpuOutOfMemoryError,
    GpuRuntimeError,
    InferenceContractError,
    ProcessingDependencyError,
    RuntimeDisposition,
    TrackerError,
)


@pytest.mark.parametrize(
    ("error_type", "code", "disposition"),
    [
        (
            GpuOutOfMemoryError,
            "vision_gpu_out_of_memory",
            RuntimeDisposition.RECOVER,
        ),
        (
            GpuRuntimeError,
            "vision_gpu_runtime_failed",
            RuntimeDisposition.UNAVAILABLE,
        ),
        (
            InferenceContractError,
            "vision_inference_contract_failed",
            RuntimeDisposition.RECOVER,
        ),
        (
            TrackerError,
            "vision_tracker_failed",
            RuntimeDisposition.CONTINUE,
        ),
    ],
)
def test_typed_runtime_failures_use_stable_control_plane_codes(
    error_type: type[ProcessingDependencyError],
    code: str,
    disposition: RuntimeDisposition,
) -> None:
    error = error_type()

    assert error.code == code
    assert error.failure_code == code
    assert error.disposition is disposition
    assert error.runtime_disposition is disposition
    assert str(error) == code
    assert TypeAdapter(FailureCode).validate_python(code, strict=True) == code


def test_typed_runtime_failure_can_carry_local_diagnostic_message() -> None:
    error = GpuRuntimeError("CUDA device-side assert")

    assert str(error) == "CUDA device-side assert"
    assert error.code == "vision_gpu_runtime_failed"


@pytest.mark.parametrize(
    "code",
    [
        "Vision_Bad",
        "1bad",
        "bad-code",
        "x" * 65,
    ],
)
def test_processing_dependency_error_rejects_noncanonical_failure_code(
    code: str,
) -> None:
    with pytest.raises(
        ValueError,
        match="processing_dependency_failure_code_invalid",
    ):
        ProcessingDependencyError(code, RuntimeDisposition.RECOVER)


def test_processing_dependency_error_requires_declared_disposition() -> None:
    with pytest.raises(
        TypeError,
        match="processing_dependency_disposition_invalid",
    ):
        ProcessingDependencyError(
            "vision_runtime_failed",
            "recover",  # type: ignore[arg-type]
        )
