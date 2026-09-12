from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, TypeVar

from mavi_vision.runtime.activity import InferenceActivity
from mavi_vision.runtime.errors import ProcessingDependencyError, RuntimeDisposition
from mavi_vision.runtime.interfaces import DetectorRuntime, RuntimeMetadata
from mavi_vision.runtime.profile import PipelineProfile
from mavi_vision.runtime.provenance import (
    GpuIdentity,
    RuntimeProvenance,
    build_runtime_provenance,
)
from mavi_vision.runtime.qualification import (
    VerifiedReleaseSelection,
    verify_release_selection,
)


_LOGGER = logging.getLogger(__name__)
_T = TypeVar("_T")


class RuntimeState(StrEnum):
    STARTING = "starting"
    READY = "ready"
    RECOVERING = "recovering"
    UNAVAILABLE = "unavailable"
    STOPPING = "stopping"


class RuntimeNotReadyError(RuntimeError):
    """Raised when processing asks for a runtime that is not published."""

    def __init__(self) -> None:
        super().__init__("runtime_not_ready")


class RuntimeLane(Protocol):
    async def run(
        self,
        func: Callable[..., _T],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> _T: ...

    async def close(self) -> None: ...


ReleaseVerifier = Callable[..., VerifiedReleaseSelection]
RuntimeFactory = Callable[..., DetectorRuntime]
ProvenanceBuilder = Callable[..., RuntimeProvenance]
GpuIdentityProvider = Callable[[str], GpuIdentity | None]


_DISPOSITION_SEVERITY = {
    RuntimeDisposition.CONTINUE: 0,
    RuntimeDisposition.RECOVER: 1,
    RuntimeDisposition.UNAVAILABLE: 2,
}


class RuntimeSupervisor:
    """Own one process-scoped detector runtime and its recovery boundary.

    Lifecycle transitions are event-loop-owned. The vision lane can only read
    the atomically published runtime and report a small lock-protected incident
    for later reconciliation.
    """

    def __init__(
        self,
        *,
        lane: RuntimeLane,
        activity: InferenceActivity,
        model_root: Path,
        manifest_path: Path,
        profile_path: Path,
        runtime_profile_path: Path,
        qualification_path: Path | None,
        device_policy: str,
        device_index: int,
        production_mode: bool,
        inference_watchdog_seconds: float,
        build_id: str | None = None,
        commit_sha: str | None = None,
        release_verifier: ReleaseVerifier = verify_release_selection,
        runtime_factory: RuntimeFactory | None = None,
        provenance_builder: ProvenanceBuilder = build_runtime_provenance,
        gpu_identity_provider: GpuIdentityProvider | None = None,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if inference_watchdog_seconds <= 0:
            raise ValueError("inference_watchdog_seconds_must_be_positive")
        if (
            not isinstance(device_index, int)
            or isinstance(device_index, bool)
            or device_index < 0
        ):
            raise ValueError("device_index_invalid")

        self._lane = lane
        self._activity = activity
        self._model_root = model_root
        self._manifest_path = manifest_path
        self._profile_path = profile_path
        self._runtime_profile_path = runtime_profile_path
        self._qualification_path = qualification_path
        self._device_policy = device_policy
        self._device_index = device_index
        self._production_mode = production_mode
        self._inference_watchdog_seconds = inference_watchdog_seconds
        self._build_id = build_id
        self._commit_sha = commit_sha
        self._release_verifier = release_verifier
        self._runtime_factory = runtime_factory or _default_runtime_factory
        self._provenance_builder = provenance_builder
        self._gpu_identity_provider = gpu_identity_provider or _no_gpu_identity
        self._monotonic_clock = monotonic_clock

        self._state = RuntimeState.STARTING
        self._unavailable_reason: str | None = None
        self._restart_required = False
        self._started = False
        self._closed = False

        self._publication_lock = threading.Lock()
        self._runtime: DetectorRuntime | None = None
        self._provenance: RuntimeProvenance | None = None

        self._incident_lock = threading.Lock()
        self._accept_incidents = True
        self._pending_disposition: RuntimeDisposition | None = None
        self._pending_reason: str | None = None
        self._pending_restart_required = False

        self._selection: VerifiedReleaseSelection | None = None
        self._resolved_device: str | None = None

    @property
    def state(self) -> RuntimeState:
        return self._state

    @property
    def runtime(self) -> DetectorRuntime:
        with self._publication_lock:
            runtime = self._runtime
        if runtime is None:
            raise RuntimeNotReadyError()
        return runtime

    @property
    def provenance(self) -> RuntimeProvenance | None:
        with self._publication_lock:
            return self._provenance

    @property
    def unavailable_reason(self) -> str | None:
        return self._unavailable_reason

    @property
    def restart_required(self) -> bool:
        return self._restart_required

    @property
    def profile(self) -> PipelineProfile:
        selection = self._selection
        if selection is None:
            raise RuntimeNotReadyError()
        return selection.profile

    async def start(self) -> None:
        if self._closed or self._state is RuntimeState.STOPPING or self._started:
            return
        self._started = True

        candidate: DetectorRuntime | None = None
        try:
            selection = self._release_verifier(
                model_root=self._model_root,
                manifest_path=self._manifest_path,
                profile_path=self._profile_path,
                runtime_profile_path=self._runtime_profile_path,
                qualification_path=self._qualification_path,
                allow_unverified=not self._production_mode,
            )
            resolved_device = self._resolve_device()
            candidate = await self._lane.run(
                self._runtime_factory,
                selection,
                device=resolved_device,
                activity=self._activity,
            )
            self._validate_runtime_metadata(
                selection,
                candidate.metadata,
                resolved_device,
            )
            await self._lane.run(candidate.warmup)
            provenance = self._build_provenance(selection, candidate.metadata)
        except BaseException as exc:
            if candidate is not None and self._cleanup_is_safe(exc):
                await self._close_candidate_best_effort(candidate)
            if isinstance(exc, asyncio.CancelledError):
                raise
            self._selection = None
            self._resolved_device = None
            self._set_unavailable(
                reason=_failure_reason(exc),
                restart_required=_requires_restart(exc),
            )
            return

        self._selection = selection
        self._resolved_device = resolved_device
        self._publish(candidate, provenance)
        self._unavailable_reason = None
        self._restart_required = False
        self._state = RuntimeState.READY

    def report_processing_failure(self, error: ProcessingDependencyError) -> None:
        """Record an incident only; never perform lifecycle work on the vision lane."""
        try:
            disposition = error.runtime_disposition
            self._record_incident(
                disposition,
                error.failure_code,
                disposition is RuntimeDisposition.UNAVAILABLE,
            )
        except Exception:
            # Reporting must never mask the processing exception already in flight.
            return

    def report_watchdog_expiry(self) -> None:
        try:
            self._record_incident(
                RuntimeDisposition.UNAVAILABLE,
                "vision_inference_watchdog_expired",
                True,
            )
        except Exception:
            return

    def watchdog_expired(self) -> bool:
        return self._activity.is_hung(
            now_monotonic=self._monotonic_clock(),
            threshold_seconds=self._inference_watchdog_seconds,
        )

    async def recover_if_required(self) -> None:
        incident = self._consume_incident()
        if incident is None:
            return

        disposition, reason, restart_required = incident
        if self._state is RuntimeState.STOPPING:
            return
        if self._state is not RuntimeState.READY:
            return
        if disposition is RuntimeDisposition.CONTINUE:
            return

        old_runtime = self._unpublish_runtime()
        if disposition is RuntimeDisposition.UNAVAILABLE:
            # A potentially poisoned CUDA context is contained by process restart.
            # Deliberately do not call runtime.close() in this branch.
            self._set_unavailable(
                reason=reason,
                restart_required=restart_required,
            )
            return

        if old_runtime is None:
            self._set_unavailable(
                reason="runtime_recovery_missing_runtime",
                restart_required=False,
            )
            return

        selection = self._selection
        resolved_device = self._resolved_device
        if selection is None or resolved_device is None:
            self._set_unavailable(
                reason="runtime_recovery_selection_missing",
                restart_required=False,
            )
            return

        self._state = RuntimeState.RECOVERING
        candidate: DetectorRuntime | None = None
        try:
            await self._lane.run(old_runtime.close)
            candidate = await self._lane.run(
                self._runtime_factory,
                selection,
                device=resolved_device,
                activity=self._activity,
            )
            self._validate_runtime_metadata(
                selection,
                candidate.metadata,
                resolved_device,
            )
            await self._lane.run(candidate.warmup)
            provenance = self._build_provenance(selection, candidate.metadata)
        except BaseException as exc:
            if candidate is not None and self._cleanup_is_safe(exc):
                await self._close_candidate_best_effort(candidate)
            if isinstance(exc, asyncio.CancelledError):
                raise
            self._set_unavailable(
                reason=_failure_reason(exc),
                restart_required=_requires_restart(exc),
            )
            return

        self._publish(candidate, provenance)
        self._unavailable_reason = None
        self._restart_required = False
        self._state = RuntimeState.READY

    async def close(self) -> None:
        if self._closed:
            return

        self._closed = True
        self._state = RuntimeState.STOPPING
        with self._incident_lock:
            self._accept_incidents = False
            self._pending_disposition = None
            self._pending_reason = None
            self._pending_restart_required = False

        runtime = self._unpublish_runtime()
        try:
            if runtime is not None and not self._restart_required:
                try:
                    await self._lane.run(runtime.close)
                except Exception:
                    _LOGGER.exception(
                        "Runtime close failed during supervisor shutdown"
                    )
        finally:
            await self._lane.close()

    def _resolve_device(self) -> str:
        if self._device_policy == "cpu":
            return "cpu"
        if self._device_policy == "cuda":
            return f"cuda:{self._device_index}"
        if self._device_policy == "auto":
            if self._production_mode:
                raise ValueError("production_auto_device_forbidden")
            _LOGGER.warning(
                "MAVI_DEVICE_POLICY=auto resolves to CPU in the Task-11 "
                "development baseline"
            )
            return "cpu"
        raise ValueError("device_policy_invalid")

    def _build_provenance(
        self,
        selection: VerifiedReleaseSelection,
        metadata: RuntimeMetadata,
    ) -> RuntimeProvenance:
        gpu = (
            self._gpu_identity_provider(metadata.device)
            if metadata.device.startswith("cuda:")
            else None
        )
        return self._provenance_builder(
            selection=selection,
            runtime_metadata=metadata,
            configured_device_policy=self._device_policy,
            configured_device_index=self._device_index,
            production_mode=self._production_mode,
            mavi_build=self._build_id,
            mavi_commit=self._commit_sha,
            gpu=gpu,
        )

    @staticmethod
    def _validate_runtime_metadata(
        selection: VerifiedReleaseSelection,
        metadata: RuntimeMetadata,
        resolved_device: str,
    ) -> None:
        manifest = selection.manifest
        if metadata.backend != manifest.backend:
            raise ValueError("runtime_backend_manifest_mismatch")
        if metadata.model_id != manifest.model_id:
            raise ValueError("runtime_model_manifest_mismatch")
        if metadata.ordered_class_vocabulary != manifest.class_vocabulary:
            raise ValueError("runtime_vocabulary_manifest_mismatch")
        if metadata.device != resolved_device:
            raise ValueError("runtime_device_mismatch")

    def _publish(
        self,
        runtime: DetectorRuntime,
        provenance: RuntimeProvenance,
    ) -> None:
        with self._publication_lock:
            self._runtime = runtime
            self._provenance = provenance

    def _unpublish_runtime(self) -> DetectorRuntime | None:
        with self._publication_lock:
            runtime = self._runtime
            self._runtime = None
            self._provenance = None
        return runtime

    def _record_incident(
        self,
        disposition: RuntimeDisposition,
        reason: str,
        restart_required: bool,
    ) -> None:
        with self._incident_lock:
            if not self._accept_incidents:
                return

            current = self._pending_disposition
            if (
                current is None
                or _DISPOSITION_SEVERITY[disposition]
                > _DISPOSITION_SEVERITY[current]
            ):
                self._pending_disposition = disposition
                self._pending_reason = reason

            self._pending_restart_required = (
                self._pending_restart_required or restart_required
            )

    def _consume_incident(
        self,
    ) -> tuple[RuntimeDisposition, str, bool] | None:
        with self._incident_lock:
            disposition = self._pending_disposition
            if disposition is None:
                return None

            reason = self._pending_reason or "runtime_incident"
            restart_required = self._pending_restart_required
            self._pending_disposition = None
            self._pending_reason = None
            self._pending_restart_required = False
            return disposition, reason, restart_required

    def _set_unavailable(
        self,
        *,
        reason: str,
        restart_required: bool,
    ) -> None:
        self._unpublish_runtime()
        self._unavailable_reason = reason
        self._restart_required = restart_required
        self._state = RuntimeState.UNAVAILABLE

    async def _close_candidate_best_effort(
        self,
        runtime: DetectorRuntime,
    ) -> None:
        try:
            await self._lane.run(runtime.close)
        except Exception:
            _LOGGER.exception("Candidate runtime cleanup failed")

    @staticmethod
    def _cleanup_is_safe(error: BaseException) -> bool:
        return not (
            isinstance(error, ProcessingDependencyError)
            and error.runtime_disposition is RuntimeDisposition.UNAVAILABLE
        )


def _default_runtime_factory(
    selection: VerifiedReleaseSelection,
    *,
    device: str,
    activity: InferenceActivity,
) -> DetectorRuntime:
    # Keep the optional heavy runtime graph out of supervisor import/collection.
    from mavi_vision.runtime.mmdetection import MMDetectionRuntime

    return MMDetectionRuntime(
        selection,
        device=device,
        activity=activity,
    )


def _no_gpu_identity(device: str) -> None:
    del device
    return None


def _requires_restart(error: BaseException) -> bool:
    return (
        isinstance(error, ProcessingDependencyError)
        and error.runtime_disposition is RuntimeDisposition.UNAVAILABLE
    )


def _failure_reason(error: BaseException) -> str:
    failure_code = getattr(error, "failure_code", None)
    if isinstance(failure_code, str) and failure_code:
        return failure_code

    code = getattr(error, "code", None)
    if isinstance(code, str) and code:
        return code

    message = str(error)
    return message if message else type(error).__name__
