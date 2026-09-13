import json
import re
from typing import Final

import httpx

from mavi_vision.common.analytical import VisionProcessingResult
from mavi_vision.common.control_plane import (
    VisionCompletionArtifact,
    VisionCompletionBoundingBox,
    VisionCompletionRepresentative,
    VisionCompletionTrack,
    VisionGpuIdentity,
    VisionJobComplete,
    VisionJobCompleteResponse,
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


class WorkerApiError(RuntimeError):
    """A sanitized worker control-plane transport or status error."""


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
    ) -> VisionJobCompleteResponse:
        if result.job_id != lease.job_id:
            raise WorkerApiError("vision result does not belong to leased job")
        if processing_duration_ms < 0:
            raise WorkerApiError("vision processing duration is invalid")

        request = VisionJobComplete(
            schemaVersion="2.0",
            jobId=lease.job_id,
            workerId=self._settings.worker_id,
            leaseToken=lease.lease_token,
            attemptCount=lease.attempt_count,
            framesProcessed=result.frames_processed,
            processingDurationMs=processing_duration_ms,
            provenance=self._map_provenance(provenance),
            tracks=tuple(
                VisionCompletionTrack(
                    trackId=track.track_id,
                    objectClass=track.object_class.value,
                    startOffsetMs=track.start_offset_ms,
                    endOffsetMs=track.end_offset_ms,
                    detectionCount=track.detection_count,
                    meanConfidence=track.mean_confidence,
                    maxConfidence=track.max_confidence,
                    representative=VisionCompletionRepresentative(
                        offsetMs=track.representative.offset_ms,
                        sourceFrameNumber=track.representative.source_frame_number,
                        confidence=track.representative.confidence,
                        qualityScore=track.representative.quality_score,
                        boundingBox=VisionCompletionBoundingBox(
                            x=track.representative.bounding_box.x,
                            y=track.representative.bounding_box.y,
                            width=track.representative.bounding_box.width,
                            height=track.representative.bounding_box.height,
                        ),
                        thumbnail=VisionCompletionArtifact(
                            storageKey=track.thumbnail.storage_key,
                            mediaType=track.thumbnail.media_type,
                            sizeBytes=track.thumbnail.size_bytes,
                            sha256=track.thumbnail.sha256,
                        ),
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
        )
        response = await self._post(
            f"/api/vision/jobs/{lease.job_id}/complete",
            request.model_dump_json(by_alias=True),
        )
        self._raise_for_status(response)
        return VisionJobCompleteResponse.model_validate_json(response.content)

    async def aclose(self) -> None:
        await self._http_client.aclose()

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
        raise WorkerApiError(f"worker API returned HTTP {response.status_code}{suffix}")

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
