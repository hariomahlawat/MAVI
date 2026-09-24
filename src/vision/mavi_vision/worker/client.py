import json
import re
from collections.abc import Callable
from typing import Final

import httpx
from pydantic import ValidationError

from mavi_vision.common.analytical import (
    EvidenceAccounting,
    ObservationDescriptor,
    RoleAccounting,
    VisionProcessingResult,
)
from mavi_vision.common.control_plane import (
    VisionCompletionArtifact,
    VisionCompletionBoundingBox,
    VisionCompletionCrop,
    VisionCompletionObservation,
    VisionCompletionTrackV3,
    VisionContractCapabilities,
    VisionEvidenceAccounting,
    VisionEvidenceRoleAccounting,
    VisionGpuIdentity,
    VisionJobCompleteResponse,
    VisionJobCompleteV3,
    VisionJobFail,
    VisionJobHeartbeat,
    VisionJobHeartbeatResponse,
    VisionJobLease,
    VisionJobLeaseRequest,
    VisionPlatformIdentity,
    VisionRuntimeProvenance,
    VisionTrackerParameters,
)
from mavi_vision.common.settings import WorkerSettings
from mavi_vision.runtime.provenance import RuntimeProvenance


_SAFE_PROBLEM_CODE: Final = re.compile(r"^[a-z][a-z0-9_]{0,63}$", re.ASCII)

# The completion contract this worker emits; the platform must advertise it.
COMPLETION_SCHEMA_VERSION: Final = "3.0"
_CONTRACT_VERSION_UNSUPPORTED: Final = "worker_contract_version_unsupported"


class WorkerApiError(RuntimeError):
    """A sanitized worker control-plane transport or status error.

    ``status_code`` and ``code`` are set when the platform answered; ``code`` is
    only ever a validated safe problem code, never free text.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        super().__init__(message)


class PlatformContractUnsupported(WorkerApiError):
    """The platform does not accept the completion contract this worker emits.

    Raised by the capability probe and, defensively, when a completion is
    rejected for its version. It is never answered by falling back to 2.0.
    """


class CompletionPayloadInvalid(ValueError):
    """The worker's own result does not form a valid completion 3.0 body.

    Not a control-plane error: nothing was sent. The attempt is failed
    explicitly instead of being retried into the same result (a poison job).
    """


class WorkerApiClient:
    def __init__(
        self,
        settings: WorkerSettings,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._http_client = http_client or httpx.AsyncClient(
            timeout=settings.request_timeout_seconds,
            verify=str(settings.ca_bundle) if settings.ca_bundle is not None else True,
        )

    async def get_contract_capabilities(self) -> VisionContractCapabilities:
        """``GET /api/vision/contract``; raises unless completion 3.0 is accepted.

        A transport failure is an ordinary ``WorkerApiError`` (the platform may
        be starting); a definite answer that is missing, malformed or lacks
        ``"3.0"`` is ``PlatformContractUnsupported``.
        """
        try:
            response = await self._http_client.get(
                f"{self._settings.api_base_url}/api/vision/contract",
                timeout=self._settings.request_timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise WorkerApiError("worker API request failed") from exc
        if response.status_code in (httpx.codes.NOT_FOUND, httpx.codes.METHOD_NOT_ALLOWED):
            raise PlatformContractUnsupported(
                "platform does not advertise completion capabilities",
                status_code=response.status_code,
            )
        self._raise_for_status(response)
        try:
            capabilities = VisionContractCapabilities.model_validate_json(response.content)
        except ValueError as exc:
            raise PlatformContractUnsupported(
                "platform completion capabilities are malformed",
                status_code=response.status_code,
            ) from exc
        if COMPLETION_SCHEMA_VERSION not in capabilities.completion_schema_versions:
            raise PlatformContractUnsupported(
                "platform does not accept completion 3.0",
                status_code=response.status_code,
            )
        return capabilities

    async def lease(self) -> VisionJobLease | None:
        request = VisionJobLeaseRequest(
            schemaVersion="2.0",
            workerId=self._settings.worker_id,
        )
        response = await self._post(
            "/api/vision/jobs/lease",
            request.model_dump_json(by_alias=True),
        )
        if response.status_code == httpx.codes.NO_CONTENT:
            return None
        self._raise_for_status(response)
        return VisionJobLease.model_validate_json(response.content)

    async def heartbeat(
        self, lease: VisionJobLease, progress_percent: float
    ) -> VisionJobHeartbeatResponse:
        request = VisionJobHeartbeat(
            schemaVersion="2.0",
            workerId=self._settings.worker_id,
            leaseToken=lease.lease_token,
            progressPercent=progress_percent,
        )
        response = await self._post(
            f"/api/vision/jobs/{lease.job_id}/heartbeat",
            request.model_dump_json(by_alias=True),
        )
        self._raise_for_status(response)
        return VisionJobHeartbeatResponse.model_validate_json(response.content)

    async def fail(
        self,
        lease: VisionJobLease,
        failure_code: str,
        failure_message: str | None = None,
    ) -> None:
        request = VisionJobFail(
            schemaVersion="2.0",
            workerId=self._settings.worker_id,
            leaseToken=lease.lease_token,
            failureCode=failure_code,
            failureMessage=failure_message,
        )
        response = await self._post(
            f"/api/vision/jobs/{lease.job_id}/fail",
            request.model_dump_json(by_alias=True),
        )
        self._raise_for_status(response)

    async def complete(
        self,
        lease: VisionJobLease,
        result: VisionProcessingResult,
        processing_duration_ms: int,
        provenance: RuntimeProvenance,
        *,
        authorize_publish: Callable[[], None] | None = None,
    ) -> VisionJobCompleteResponse:
        if result.job_id != lease.job_id:
            raise WorkerApiError("vision result does not belong to leased job")
        if processing_duration_ms < 0:
            raise WorkerApiError("vision processing duration is invalid")

        try:
            request = self._completion_request(lease, result, processing_duration_ms, provenance)
        except ValidationError as exc:
            raise CompletionPayloadInvalid("vision result is not a valid completion 3.0 body") from exc
        body = request.model_dump_json(by_alias=True)
        if authorize_publish is not None:
            authorize_publish()
        return await self._send_completion(lease, body)

    def _completion_request(
        self,
        lease: VisionJobLease,
        result: VisionProcessingResult,
        processing_duration_ms: int,
        provenance: RuntimeProvenance,
    ) -> VisionJobCompleteV3:
        return VisionJobCompleteV3(
            schemaVersion=COMPLETION_SCHEMA_VERSION,
            jobId=lease.job_id,
            workerId=self._settings.worker_id,
            leaseToken=lease.lease_token,
            attemptCount=lease.attempt_count,
            framesProcessed=result.frames_processed,
            processingDurationMs=processing_duration_ms,
            provenance=self._map_provenance(provenance),
            tracks=tuple(
                VisionCompletionTrackV3(
                    trackId=track.track_id,
                    objectClass=track.object_class.value,
                    startOffsetMs=track.start_offset_ms,
                    endOffsetMs=track.end_offset_ms,
                    detectionCount=track.detection_count,
                    meanConfidence=track.mean_confidence,
                    maxConfidence=track.max_confidence,
                    # Canonical order is the Track's own: Representative first,
                    # then supplemental roles, ranks 0..n-1 (already validated).
                    observations=tuple(
                        self._map_observation(observation)
                        for observation in track.observations
                    ),
                    trajectoryArtifact=VisionCompletionArtifact(
                        storageKey=track.trajectory_artifact.storage_key,
                        mediaType=track.trajectory_artifact.media_type,
                        sizeBytes=track.trajectory_artifact.size_bytes,
                        sha256=track.trajectory_artifact.sha256,
                    ),
                )
                for track in result.tracks
            ),
            evidenceAccounting=self._map_accounting(result.evidence_accounting),
        )

    async def _send_completion(self, lease: VisionJobLease, body: str) -> VisionJobCompleteResponse:
        response = await self._post(
            f"/api/vision/jobs/{lease.job_id}/complete",
            body,
        )
        if (
            response.status_code == httpx.codes.BAD_REQUEST
            and self._safe_problem_code(response) == _CONTRACT_VERSION_UNSUPPORTED
        ):
            # Defence in depth behind the startup probe: never retried and
            # never re-sent as 2.0.
            raise PlatformContractUnsupported(
                "platform rejected completion 3.0",
                status_code=response.status_code,
                code=_CONTRACT_VERSION_UNSUPPORTED,
            )
        self._raise_for_status(response)
        completed = VisionJobCompleteResponse.model_validate_json(response.content)
        if completed.schema_version != COMPLETION_SCHEMA_VERSION:
            raise WorkerApiError("platform answered completion with an unexpected version")
        return completed

    async def aclose(self) -> None:
        await self._http_client.aclose()

    @staticmethod
    def _map_observation(observation: ObservationDescriptor) -> VisionCompletionObservation:
        box = observation.bounding_box
        return VisionCompletionObservation(
            role=observation.role.value,
            rank=observation.rank,
            offsetMs=observation.offset_ms,
            sourceFrameNumber=observation.source_frame_number,
            confidence=observation.confidence,
            qualityScore=observation.quality_score,
            selectionScore=observation.selection_score,
            boundingBox=VisionCompletionBoundingBox(
                x=box.x,
                y=box.y,
                width=box.width,
                height=box.height,
            ),
            crop=VisionCompletionCrop(
                storageKey=observation.crop.storage_key,
                mediaType=observation.crop.media_type,
                sizeBytes=observation.crop.size_bytes,
                sha256=observation.crop.sha256,
            ),
        )

    @staticmethod
    def _map_accounting(accounting: EvidenceAccounting) -> VisionEvidenceAccounting:
        def role(value: RoleAccounting) -> VisionEvidenceRoleAccounting:
            return VisionEvidenceRoleAccounting(
                candidates=value.candidates,
                admitted=value.admitted,
                omitted=value.omitted,
                candidateBytes=value.candidate_bytes,
                admittedBytes=value.admitted_bytes,
            )

        return VisionEvidenceAccounting.model_validate(
            {
                "representative": role(accounting.representative),
                "near-view": role(accounting.near_view),
                "early-diverse": role(accounting.early_diverse),
                "late-diverse": role(accounting.late_diverse),
            }
        )

    @staticmethod
    def _map_provenance(provenance: RuntimeProvenance) -> VisionRuntimeProvenance:
        platform = provenance.platform
        gpu = provenance.gpu
        tracker = provenance.tracker_parameters

        return VisionRuntimeProvenance(
            modelId=provenance.model_id,
            modelVersion=provenance.model_version,
            modelManifestSha256=provenance.model_manifest_sha256,
            checkpointSha256=provenance.checkpoint_sha256,
            resolvedConfigSha256=provenance.resolved_config_sha256,
            pipelineProfileId=provenance.pipeline_profile_id,
            pipelineProfileVersion=provenance.pipeline_profile_version,
            pipelineProfileSha256=provenance.pipeline_profile_sha256,
            qualificationId=provenance.qualification_id,
            qualificationSha256=provenance.qualification_sha256,
            verificationStatus=provenance.verification_status,
            runtimeProfileId=provenance.runtime_profile_id,
            runtimeProfileSha256=provenance.runtime_profile_sha256,
            runtimeVariant=provenance.runtime_variant,
            platformLockSha256=provenance.platform_lock_sha256,
            detectorBackend=provenance.detector_backend,
            dependencyVersions=dict(provenance.dependency_versions),
            ffmpegVersion=provenance.ffmpeg_version,
            platform=VisionPlatformIdentity(
                system=platform.system,
                release=platform.release,
                version=platform.version,
                machine=platform.machine,
                processor=platform.processor,
                pythonVersion=platform.python_version,
                pythonImplementation=platform.python_implementation,
                pythonBuild=platform.python_build,
                pythonCompiler=platform.python_compiler,
            ),
            configuredDevicePolicy=provenance.configured_device_policy,
            configuredDeviceIndex=provenance.configured_device_index,
            deviceResolutionReason=provenance.device_resolution_reason,
            actualDevice=provenance.actual_device,
            gpu=(
                None
                if gpu is None
                else VisionGpuIdentity(
                    name=gpu.name,
                    index=gpu.index,
                    vramBytes=gpu.vram_bytes,
                    driverVersion=gpu.driver_version,
                    cudaRuntimeVersion=gpu.cuda_runtime_version,
                    uuid=gpu.uuid,
                    pciBusId=gpu.pci_bus_id,
                    computeCapability=gpu.compute_capability,
                )
            ),
            maviBuild=provenance.mavi_build,
            maviCommit=provenance.mavi_commit,
            framePolicy=provenance.frame_policy,
            trackerParameters=VisionTrackerParameters(
                referenceFrameRate=tracker.reference_frame_rate,
                trackActivationThreshold=tracker.track_activation_threshold,
                highConfidenceThreshold=tracker.high_confidence_threshold,
                minimumIouThreshold=tracker.minimum_iou_threshold,
                minimumConsecutiveFrames=tracker.minimum_consecutive_frames,
                lostTrackBufferSeconds=tracker.lost_track_buffer_seconds,
            ),
            inputColourSpace=provenance.input_colour_space,
        )

    async def _post(self, path: str, body: str) -> httpx.Response:
        try:
            return await self._http_client.post(
                f"{self._settings.api_base_url}{path}",
                content=body.encode("utf-8"),
                headers={"Content-Type": "application/json"},
                timeout=self._settings.request_timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise WorkerApiError("worker API request failed") from exc

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.is_success:
            return
        code = WorkerApiClient._safe_problem_code(response)
        suffix = f" ({code})" if code is not None else ""
        raise WorkerApiError(
            f"worker API returned HTTP {response.status_code}{suffix}",
            status_code=response.status_code,
            code=code,
        )

    @staticmethod
    def _safe_problem_code(response: httpx.Response) -> str | None:
        try:
            payload = json.loads(response.content)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        code = payload.get("code") if isinstance(payload, dict) else None
        if isinstance(code, str) and _SAFE_PROBLEM_CODE.fullmatch(code):
            return code
        return None
