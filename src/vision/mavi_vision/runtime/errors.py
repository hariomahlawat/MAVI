from __future__ import annotations

from enum import StrEnum

from pydantic import TypeAdapter, ValidationError

from mavi_vision.common.control_plane import FailureCode


_FAILURE_CODE_ADAPTER = TypeAdapter(FailureCode)


class RuntimeDisposition(StrEnum):
    CONTINUE = "continue"
    RECOVER = "recover"
    UNAVAILABLE = "unavailable"


class ProcessingDependencyError(RuntimeError):
    """Model-neutral processing failure with a stable worker failure code."""

    def __init__(
        self,
        code: str,
        disposition: RuntimeDisposition,
        message: str | None = None,
    ) -> None:
        try:
            validated_code = _FAILURE_CODE_ADAPTER.validate_python(code, strict=True)
        except ValidationError as exc:
            raise ValueError("processing_dependency_failure_code_invalid") from exc
        if not isinstance(disposition, RuntimeDisposition):
            raise TypeError("processing_dependency_disposition_invalid")

        self.code = validated_code
        self.disposition = disposition
        super().__init__(message or validated_code)

    @property
    def failure_code(self) -> str:
        return self.code

    @property
    def runtime_disposition(self) -> RuntimeDisposition:
        return self.disposition


class GpuOutOfMemoryError(ProcessingDependencyError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            "vision_gpu_out_of_memory",
            RuntimeDisposition.RECOVER,
            message,
        )


class GpuRuntimeError(ProcessingDependencyError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            "vision_gpu_runtime_failed",
            RuntimeDisposition.UNAVAILABLE,
            message,
        )


class InferenceContractError(ProcessingDependencyError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            "vision_inference_contract_failed",
            RuntimeDisposition.RECOVER,
            message,
        )


class TrackerError(ProcessingDependencyError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            "vision_tracker_failed",
            RuntimeDisposition.CONTINUE,
            message,
        )
