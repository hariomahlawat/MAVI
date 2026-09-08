# MAVI Phase 1 — Searchable Visual Intelligence Memory Design

**Status:** Approved design baseline for implementation planning  
**Date:** 08 Sep 2026  
**Product:** MAVI — Mission-Aware Visual Intelligence  
**Phase:** Phase 1 — Searchable Visual Intelligence Memory  

## 1. Purpose

Phase 1 proves the architectural nucleus of MAVI without requiring live CCTV integration, large GPU infrastructure, cross-camera identity reasoning, or autonomous behavioural interpretation.

The capability paper defines MAVI as an intelligence layer over existing surveillance infrastructure, with a structured visual memory that links analytical findings back to source footage. Phase 1 implements the smallest operationally useful vertical slice of that concept:

> **Import a recorded MP4 → detect and track persons/vehicles → persist searchable tracks and selected observations → search by structured criteria → return directly to the source video evidence.**

The purpose is not to demonstrate the largest number of AI models. It is to prove that ordinary video can be transformed into durable, evidence-linked, searchable visual intelligence records.

## 2. Phase-1 Scope

### 2.1 In scope

Phase 1 shall provide:

1. Camera registration.
2. Import of pre-recorded MP4 files.
3. Mandatory camera selection and manual recording start date/time at import.
4. Managed ownership of imported video by MAVI storage.
5. Automatic extraction of video metadata after upload.
6. A durable processing-run and vision-job lifecycle.
7. Python-based video processing.
8. Person and vehicle detection.
9. Single-camera multi-object tracking.
10. Selected observations/keyframes per track.
11. Compact detailed trajectory artifacts outside the relational database.
12. PostgreSQL persistence of searchable visual-memory records.
13. Structured search by camera, object class, date/time, minimum duration and minimum confidence.
14. Representative thumbnails.
15. Evidence-linked source-video playback at the corresponding video offset.
16. Processing status, failure status and retry support.
17. Model/pipeline version traceability.
18. Offline-production compatibility from the beginning.

### 2.2 Explicitly out of scope

Phase 1 shall not implement:

- live RTSP ingestion;
- VMS integration;
- face recognition;
- person re-identification across cameras;
- persistent automatic entity grouping;
- ANPR/OCR;
- natural-language video search;
- LLM/VLM reasoning;
- cross-camera reconstruction;
- mission rules;
- anomaly or pattern-of-life analysis;
- relationship intelligence;
- autonomous suspicious-behaviour classification;
- cloud APIs in the production execution path.

These capabilities must be addable later without redesigning the Phase-1 core.

## 3. Architectural Principles

### 3.1 Raw video remains the evidence

MAVI does not replace the source footage. It builds a structured visual-intelligence index over managed source video. Every accepted Track must resolve to the VideoAsset, Camera, ProcessingRun, timestamps, model versions and source footage that produced it.

### 3.2 Track is the primary searchable unit in Phase 1

A detector may produce hundreds of frame-level boxes for one passage. MAVI shall not create one relational row for every detector output. The durable searchable unit is a **Track** representing one observed passage of a person or vehicle in one video/camera context.

### 3.3 Selected observations, not every frame

Each Track shall retain selected Observations such as track start, best-quality frame, representative frame and track end. The full per-frame bounding-box trajectory shall be retained as a compact managed artifact.

### 3.4 Track and Entity are different concepts

- **Track:** one observed passage in one video/camera context.
- **Entity:** a persistent real-world or pseudonymous person/vehicle that may later be represented by multiple Tracks.

Phase 1 creates the Entity structure but does not automatically create or group Entities. `Track.EntityId` remains nullable.

### 3.5 Python performs analytics; .NET owns durable intelligence

The Python worker may produce detections, tracks, keyframes, attributes and analytical artifacts. It shall not directly create or modify operational intelligence records in PostgreSQL.

The ASP.NET Core platform validates worker results and owns accepted persistence, search, operator-facing state and evidence linkage.

### 3.6 Storage locations are abstracted

Domain and application code shall never depend on `D:\MAVI-Data` or any other physical path. They depend on logical `StorageKey` values and `IMediaStore`.

Phase 1 uses `LocalMediaStore`. Future deployments may use NAS or S3-compatible storage without changing the domain model.

### 3.7 Offline production by design

Development may use the Internet. The released production system must run without Internet connectivity. Runtime model weights, JS assets, fonts, Python packages, NuGet packages needed for deployment, FFmpeg binaries and other runtime dependencies must be capable of being staged locally.

## 4. Deployment Model

### 4.1 Phase-1 development deployment

All components may run on one Windows development laptop:

```text
React/Vite browser UI
        │
        ▼
ASP.NET Core / .NET 10
        │
        ├── PostgreSQL + pgvector
        ├── LocalMediaStore
        └── Vision Job API
                  │
                  ▼
            Python 3.12 Worker
                  │
        PyAV/FFmpeg → Detector → ByteTrack
```

No Docker, RabbitMQ, Linux server or GPU cluster is required for the first vertical slice.

### 4.2 Final deployment direction preserved

The same logical architecture shall support:

- Windows Server/IIS operational platform;
- PostgreSQL on the protected LAN;
- shared managed media storage;
- one or more Ubuntu/Linux GPU worker nodes;
- later replacement of REST polling with a durable queue;
- 200–500 camera establishments.

## 5. Technology Baseline

### 5.1 .NET platform

- .NET 10 LTS
- ASP.NET Core
- Entity Framework Core 10
- Npgsql EF Core provider
- PostgreSQL 18
- pgvector extension enabled from the first database migration
- SignalR retained for later real-time UI events; Phase 1 may use polling for processing status

### 5.2 Frontend

- React
- TypeScript
- Vite
- React Router
- TanStack Query
- Native HTML5 `<video>` for Phase-1 playback

Redux shall not be introduced in Phase 1.

### 5.3 Vision subsystem

- Python 3.12
- PyAV and FFmpeg/ffprobe for media decoding and authoritative metadata/timing
- PyTorch runtime for the detector implementation
- MMDetection / RTMDet adapter as the selected detector baseline
- ByteTrack for single-camera multi-object tracking
- MessagePack for retained trajectory artifacts
- Pydantic for worker transport-model validation
- httpx for worker-to-platform HTTP
- pytest for Python tests

The detector and tracker are behind internal interfaces so model/runtime implementations can be replaced.

## 6. Identifier, Time and Coordinate Policy

### 6.1 Identifiers

All new Phase-1 aggregate and record IDs shall be UUID v7 generated application-side with `.NET Guid.CreateVersion7()` or an equivalent Python UUIDv7 implementation where a transport-only identifier is needed.

Database type: `uuid`.

### 6.2 Time

All durable real-world timestamps shall be normalized to UTC and stored as `timestamptz`.

C# type: `DateTimeOffset` with UTC offset.  
Worker contract: RFC 3339/ISO 8601 UTC string.

Video-relative positions shall use integer milliseconds (`bigint`) in Phase 1.

### 6.3 Manual recording time

At Phase-1 import, the operator supplies:

- Camera;
- recording local date/time.

The platform obtains the camera's configured IANA timezone and converts the supplied local time to UTC. Invalid or ambiguous local times shall be rejected rather than silently guessed.

Final automated ingestion shall later populate the same fields from trusted VMS/stream/container metadata.

### 6.4 Timestamp source

`TimestampSource`:

```text
Manual
VideoMetadata
FilenamePattern
VmsMetadata
StreamTimestamp
SystemClockDerived
```

Phase 1 creates imported videos with `Manual`.

### 6.5 Bounding boxes

Bounding boxes shall be stored as normalized floating-point values in the interval `[0,1]`:

```text
X
Y
Width
Height
```

The source video width and height remain on `VideoAsset`.

## 7. Core Domain Model

## 7.1 Camera

Represents one physical/logical video source.

```text
Camera
- Id: Guid
- Code: string, required, max 32, unique, immutable after creation
- Name: string, required, max 128
- Description: string?, max 512
- LocationName: string?, max 128
- TimeZoneId: string, required, max 64, IANA identifier
- IsActive: bool
- CreatedAtUtc: DateTimeOffset
- UpdatedAtUtc: DateTimeOffset
```

Indexes:

- unique `Code`;
- `IsActive`.

## 7.2 Artifact

Represents managed binary evidence or analytical output.

```text
Artifact
- Id: Guid
- ArtifactType: ArtifactType
- StorageKey: string, required, max 512, unique
- MimeType: string, required, max 128
- SizeBytes: long
- Sha256: string, required, fixed 64 lowercase hex
- MetadataJson: string? mapped to jsonb
- CreatedAtUtc: DateTimeOffset
```

`ArtifactType` Phase-1 values:

```text
SourceVideo
Thumbnail
TrackTrajectory
```

Reserved future values may be added later for clips/exports; do not create unused tables for them.

Storage keys are logical, slash-separated and platform-independent, for example:

```text
source/CAM-0001/2026/09/08/0199....mp4
thumbnails/0199-processing-run/0199-track/best.jpg
trajectories/0199-processing-run/0199-track.msgpack
```

Absolute physical paths must never cross the API or worker contracts.

## 7.3 VideoAsset

Represents one successfully ingested managed video.

```text
VideoAsset
- Id: Guid
- CameraId: Guid FK Camera
- SourceArtifactId: Guid FK Artifact
- OriginalFileName: string, required, max 255
- SourceType: VideoSourceType
- SourceReference: string?, max 512
- RecordingStartUtc: DateTimeOffset
- RecordingEndUtc: DateTimeOffset
- DurationMs: long
- FrameRateNumerator: int
- FrameRateDenominator: int
- Width: int
- Height: int
- Codec: string?, max 64
- TimestampSource: TimestampSource
- TimestampConfidence: double [0,1]
- ProcessingStatus: VideoProcessingStatus
- ImportedAtUtc: DateTimeOffset
```

`VideoSourceType` Phase-1 value: `UploadedFile`.

`VideoProcessingStatus`:

```text
NotQueued
Queued
Processing
Processed
Failed
```

Constraints:

- `DurationMs > 0`;
- `RecordingEndUtc = RecordingStartUtc + DurationMs` within millisecond tolerance;
- width/height > 0;
- frame-rate numerator/denominator > 0;
- source artifact must be `SourceVideo`;
- unique source SHA-256 ingestion shall be detected at application level and returned as a duplicate conflict rather than storing the same binary twice.

Indexes:

- `(CameraId, RecordingStartUtc)`;
- `ProcessingStatus`;
- `ImportedAtUtc`.

## 7.4 ProcessingRun

Represents one analytical processing pass over a VideoAsset.

```text
ProcessingRun
- Id: Guid
- VideoAssetId: Guid FK VideoAsset
- Status: ProcessingRunStatus
- PipelineVersion: string, required, max 64
- DetectorName: string?, max 128
- DetectorVersion: string?, max 128
- TrackerName: string?, max 128
- TrackerVersion: string?, max 128
- ConfigurationJson: string mapped to jsonb
- WorkerId: string?, max 128
- QueuedAtUtc: DateTimeOffset
- StartedAtUtc: DateTimeOffset?
- CompletedAtUtc: DateTimeOffset?
- FramesProcessed: long
- TracksCreated: int
- ProcessingDurationMs: long?
- ErrorCode: string?, max 64
- ErrorDetails: string?, max 4000
```

`ProcessingRunStatus`:

```text
Queued
Running
Completed
Failed
Cancelled
```

A VideoAsset may have many ProcessingRuns. Reprocessing creates a new run; it never rewrites the identity of an older run.

## 7.5 VisionJob

Represents one leasable worker task for a ProcessingRun.

```text
VisionJob
- Id: Guid
- ProcessingRunId: Guid FK ProcessingRun, unique
- Pipeline: string, required, max 64
- Status: VisionJobStatus
- CreatedAtUtc: DateTimeOffset
- AvailableAtUtc: DateTimeOffset
- LeaseOwner: string?, max 128
- LeaseExpiresAtUtc: DateTimeOffset?
- AttemptCount: int
- ProgressPercent: double [0,100]
- LastHeartbeatUtc: DateTimeOffset?
- CompletedAtUtc: DateTimeOffset?
- FailureCode: string?, max 64
- FailureDetails: string?, max 4000
```

`VisionJobStatus`:

```text
Queued
Leased
Completed
Failed
Cancelled
```

Lease rules:

- one job is atomically leased to one worker;
- default lease duration: 120 seconds;
- worker heartbeat interval: 30 seconds;
- heartbeat extends the lease by 120 seconds;
- expired leases may be re-leased while `AttemptCount < 3`;
- after 3 unsuccessful attempts the job and ProcessingRun become `Failed`;
- completion is accepted only from the current lease owner while the lease is valid;
- duplicate completion requests after a successful completion are idempotently acknowledged.

## 7.6 Track

Primary searchable unit of Phase 1.

```text
Track
- Id: Guid
- ProcessingRunId: Guid FK ProcessingRun
- VideoAssetId: Guid FK VideoAsset
- EntityId: Guid? FK Entity
- LocalTrackNumber: int
- ObjectClass: ObjectClass
- StartOffsetMs: long
- EndOffsetMs: long
- StartTimestampUtc: DateTimeOffset
- EndTimestampUtc: DateTimeOffset
- DurationMs: long
- DetectionCount: int
- MeanConfidence: double [0,1]
- MaxConfidence: double [0,1]
- RepresentativeObservationId: Guid? FK Observation
- TrajectoryArtifactId: Guid? FK Artifact
- ReviewStatus: ReviewStatus
- CreatedAtUtc: DateTimeOffset
```

`ObjectClass` Phase-1 values:

```text
Person
Vehicle
```

`ReviewStatus` Phase-1 values:

```text
Unreviewed
Confirmed
Rejected
```

Unique constraint:

- `(ProcessingRunId, LocalTrackNumber)`.

Indexes:

- `(VideoAssetId, StartTimestampUtc)`;
- `(ObjectClass, StartTimestampUtc)`;
- `(ProcessingRunId)`;
- `(EntityId)`.

Constraints:

- `StartOffsetMs >= 0`;
- `EndOffsetMs >= StartOffsetMs`;
- offsets must fall within VideoAsset duration;
- timestamps must equal video recording start + offsets within one millisecond;
- `DetectionCount > 0`.

## 7.7 Observation

Represents a selected meaningful frame from a Track.

```text
Observation
- Id: Guid
- TrackId: Guid FK Track
- ObservationType: ObservationType
- SourceFrameNumber: long
- VideoOffsetMs: long
- TimestampUtc: DateTimeOffset
- BoundingBoxX: float
- BoundingBoxY: float
- BoundingBoxWidth: float
- BoundingBoxHeight: float
- Confidence: double [0,1]
- QualityScore: double [0,1]
- ThumbnailArtifactId: Guid? FK Artifact
- CreatedAtUtc: DateTimeOffset
```

`ObservationType` Phase-1 values:

```text
TrackStart
Representative
BestQuality
TrackEnd
```

A single physical frame may satisfy more than one semantic role; the worker should avoid duplicate observations when roles resolve to the same or near-identical frame. One observation may therefore be designated `Representative` and separately chosen as the Track's representative observation.

## 7.8 VisualAttribute

Extensible analytical attribute record.

```text
VisualAttribute
- Id: Guid
- TrackId: Guid FK Track
- ObservationId: Guid? FK Observation
- AttributeType: string, required, max 64
- Value: string, required, max 128
- Confidence: double [0,1]
- ModelName: string?, max 128
- ModelVersion: string?, max 128
- CreatedAtUtc: DateTimeOffset
```

Phase 1 does not require any VisualAttribute to be populated. The table exists to avoid later adding dozens of person/vehicle-specific columns to Track.

## 7.9 Entity

Future persistent visual identity, structurally present but dormant in Phase 1.

```text
Entity
- Id: Guid
- EntityType: EntityType
- DisplayCode: string, required, max 64, unique
- IdentityStatus: IdentityStatus
- ReviewStatus: ReviewStatus
- RepresentativeArtifactId: Guid? FK Artifact
- CreatedAtUtc: DateTimeOffset
- UpdatedAtUtc: DateTimeOffset
```

`EntityType`: `Person`, `Vehicle`.  
`IdentityStatus`: `Unknown`, `AuthorisedIdentityLinked`.

Phase-1 processing shall not automatically create an Entity for every Track.

## 8. Relational Shape

```text
Camera 1 ─── * VideoAsset 1 ─── * ProcessingRun 1 ─── 1 VisionJob
                    │                    │
                    │                    └── * Track ─── * Observation
                    │                             │              │
                    │                             │              └── 0..1 Thumbnail Artifact
                    │                             ├── * VisualAttribute
                    │                             ├── 0..1 Trajectory Artifact
                    │                             └── 0..1 Entity
                    │
                    └── 1 SourceVideo Artifact
```

## 9. PostgreSQL and EF Core

### 9.1 Database

Database names for local development:

```text
mavi_dev
mavi_test
```

Runtime connection string key:

```text
ConnectionStrings:Mavi
```

Integration-test environment variable:

```text
MAVI_TEST_DB_CONNECTION
```

### 9.2 Initial packages

The implementation plan pins:

- `Microsoft.EntityFrameworkCore` 10.0.11
- `Microsoft.EntityFrameworkCore.Design` 10.0.11
- `Npgsql.EntityFrameworkCore.PostgreSQL` 10.0.3
- `Pgvector.EntityFrameworkCore` 0.3.0

The pgvector package is included and the PostgreSQL extension is enabled, but Phase 1 creates no vector columns.

### 9.3 Enum persistence

All Phase-1 domain enums persisted to PostgreSQL shall use stable string values rather than ordinal integers. This keeps operational tables and raw diagnostic queries interpretable and prevents enum reordering from corrupting meaning. EF configurations shall use explicit string conversion with bounded varchar lengths.

### 9.4 Migration policy

- migrations live under `src/platform/Mavi.Infrastructure/Persistence/Migrations`;
- application startup does not silently apply production migrations;
- developers use `dotnet ef database update`;
- offline deployment packages later include an explicit migration/update procedure.

The initial migration enables:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

## 10. Managed Media Storage

### 10.1 Interface

The Application layer consumes an abstraction equivalent to:

```csharp
public interface IMediaStore
{
    Task<MediaWriteResult> WriteAsync(string storageKey, Stream content, CancellationToken cancellationToken);
    Task<Stream> OpenReadAsync(string storageKey, CancellationToken cancellationToken);
    Task<bool> ExistsAsync(string storageKey, CancellationToken cancellationToken);
    Task DeleteAsync(string storageKey, CancellationToken cancellationToken);
    string GetLocalPath(string storageKey);
}
```

`GetLocalPath` is permitted only for internal components that require a seekable local/shared file path such as ffprobe or a worker on a mounted store. It must never be exposed through HTTP contracts.

### 10.2 Phase-1 implementation

`LocalMediaStore` root is configured through:

```text
MediaStorage:RootPath
```

Recommended local value:

```text
D:\MAVI-Data
```

Directory layout:

```text
source/<camera-code>/<yyyy>/<MM>/<dd>/<video-id>.mp4
thumbnails/<processing-run-id>/<track-id>/<observation-id>.jpg
trajectories/<processing-run-id>/<track-id>.msgpack
staging/<job-id>/...
temp/...
```

### 10.3 Worker storage boundary

The job contract passes logical storage keys, not OS paths.

The Python worker resolves storage keys against its own configured media root:

```text
MAVI_MEDIA_ROOT
```

This permits Windows development (`D:\MAVI-Data`) and Linux production (`/mnt/mavi-data`) with the same contract.

## 11. Video Import

### 11.1 API

```http
POST /api/videos/import
Content-Type: multipart/form-data
```

Fields:

```text
cameraId: Guid
recordingStartLocal: yyyy-MM-ddTHH:mm:ss[.fff]
file: MP4
```

The camera's timezone is authoritative for conversion to UTC.

### 11.2 Import processing

1. Verify Camera exists and is active.
2. Reject invalid/ambiguous local recording time.
3. Stream uploaded file to managed temporary storage; never load full video into memory.
4. Validate accepted file extension/container.
5. Compute SHA-256.
6. Run ffprobe and parse duration, dimensions, codec and rational frame rate.
7. Reject unreadable or zero-duration video.
8. Detect duplicate binary by SHA-256; return `409 Conflict` with existing VideoAsset ID if already ingested.
9. Generate VideoAsset UUIDv7 and final storage key.
10. Move/copy from temp to final managed source storage.
11. Create SourceVideo Artifact and VideoAsset in one database transaction.
12. If database persistence fails after media promotion, perform compensating artifact deletion and log the failure.
13. Return `201 Created` with VideoAsset detail.

The browser-provided original path is not trusted or retained because browsers do not provide reliable client filesystem paths.

### 11.3 Upload limits

Phase-1 API configuration shall support files up to 10 GiB without buffering the entire file in memory. Final VMS/live ingestion will bypass browser upload.

## 12. Video Metadata

`IVideoMetadataReader` shall return:

```text
DurationMs
Width
Height
FrameRateNumerator
FrameRateDenominator
Codec
```

Phase-1 implementation uses `ffprobe` JSON output. ffprobe executable path is configured by:

```text
MediaProcessing:FfprobePath
```

The implementation shall use process argument lists, not shell-concatenated strings.

## 13. Processing Lifecycle

### 13.1 Queue

```http
POST /api/videos/{videoAssetId}/process
```

Creates:

- ProcessingRun status `Queued`;
- VisionJob status `Queued`;
- VideoAsset status `Queued`.

Repeated calls while a run is queued/running return `409 Conflict`.

After a completed/failed run, a new call creates a new ProcessingRun rather than reusing the old one.

### 13.2 Worker lease

```http
POST /api/vision/jobs/lease
```

Request:

```json
{
  "workerId": "dev-worker-01",
  "pipeline": "phase1-detection-tracking"
}
```

Response when work exists contains:

```text
jobId
processingRunId
videoAssetId
cameraId
sourceStorageKey
recordingStartUtc
videoDurationMs
pipeline
leaseExpiresAtUtc
```

No work: `204 No Content`.

### 13.3 Heartbeat/progress

```http
POST /api/vision/jobs/{jobId}/heartbeat
```

Request:

```text
workerId
progressPercent
framesProcessed
```

Extends the lease and updates ProcessingRun/VideoAsset to running/processing.

### 13.4 Completion

```http
POST /api/vision/jobs/{jobId}/complete
```

The result contains structured Track summaries, selected Observations, analytical artifact descriptors and processing metrics. The worker never writes PostgreSQL.

### 13.5 Failure

```http
POST /api/vision/jobs/{jobId}/fail
```

Records structured failure code/details. VideoAsset source media remains intact and can be reprocessed.

## 14. Vision Worker Contract

### 14.1 Pipeline

```text
Source MP4
   ↓
PyAV/FFmpeg decode with PTS-aware timestamps
   ↓
IDetector
   ↓
Person/vehicle detections
   ↓
ITracker / ByteTrack
   ↓
Track candidates
   ↓
Keyframe selection + quality scoring
   ↓
Thumbnail + trajectory staging artifacts
   ↓
VisionProcessingResult
```

### 14.2 Detector abstraction

Conceptual interface:

```python
class Detector(Protocol):
    def detect(self, frame: VideoFrame) -> list[Detection]: ...
```

MAVI domain contracts shall not contain RTMDet-specific class names or MMDetection internals.

Detector mapping for COCO-like models:

```text
person                       -> ObjectClass.Person
car/motorcycle/bus/truck     -> ObjectClass.Vehicle
```

Detector subtype may later be retained as a VisualAttribute.

### 14.3 Tracker abstraction

```python
class Tracker(Protocol):
    def update(self, detections: list[Detection], frame_time_ms: int) -> list[TrackedDetection]: ...
```

Phase-1 implementation uses ByteTrack.

### 14.4 Processing rate

Processing working resolution/frame sampling is configuration-driven. The worker must preserve exact source video offsets derived from PTS/timing so search results return accurately to the source footage.

No Phase-1 acceptance criterion requires real-time processing.

## 15. Keyframe and Quality Policy

For each Track, attempt to retain:

1. Track-start observation.
2. Best-quality observation.
3. Representative observation near the temporal midpoint.
4. Track-end observation.

Near-duplicate candidates shall be de-duplicated.

Initial quality score combines normalized:

- object pixel area;
- image sharpness;
- detector confidence;
- penalty for bounding-box clipping at frame edges.

The formula must be deterministic and versioned as part of the pipeline configuration. Sophisticated face/plate quality models are not part of Phase 1.

## 16. Trajectory Artifact

Phase-1 retained format: MessagePack.

Schema identifier:

```text
mavi.track-trajectory.v1
```

Logical content:

```text
schema
trackLocalNumber
coordinateSpace = normalized
points[]:
  sourceFrameNumber: int64
  videoOffsetMs: int64
  x: float32
  y: float32
  width: float32
  height: float32
  confidence: float32
```

The worker writes trajectory files to its job staging area. Completion descriptors include storage key, size and SHA-256.

## 17. Worker Result Validation and Atomic Persistence

Before accepting a completed result, .NET validates:

- Job exists and is currently leased to the completing worker.
- ProcessingRun/VideoAsset IDs match the job.
- Each `LocalTrackNumber` is unique within the run.
- Object class is supported.
- Offsets are ordered and within video duration.
- Derived UTC timestamps match recording start + offsets.
- Bounding boxes are finite and within normalized coordinate limits.
- Confidence/quality values are finite and in range.
- Referenced staging artifacts exist.
- Artifact reported size and SHA-256 match actual files.
- Observation IDs belong to their stated Track.
- One representative observation exists per accepted Track.

Persistence rule:

```text
Begin database transaction
  Register analytical Artifacts
  Create Tracks
  Create Observations
  Create VisualAttributes, if any
  Set Track representative/trajectory references
  Mark ProcessingRun Completed
  Mark VisionJob Completed
  Mark VideoAsset Processed
Commit
```

If validation or persistence fails, no accepted Track/Observation rows from that result become visible as intelligence. The run is marked failed through the error path and staging artifacts are retained temporarily for diagnostics, then cleaned by policy.

## 18. Search

### 18.1 API

```http
GET /api/tracks
```

Supported query parameters:

```text
cameraId: Guid?
videoAssetId: Guid?
objectClass: Person|Vehicle?
fromUtc: DateTimeOffset?
toUtc: DateTimeOffset?
minimumDurationMs: long?
minimumConfidence: double?
page: int = 1
pageSize: int = 50, maximum 100
```

Default sort:

```text
StartTimestampUtc descending
```

### 18.2 Result contract

```text
TrackId
ObjectClass
CameraId
CameraCode
CameraName
VideoAssetId
StartTimestampUtc
EndTimestampUtc
StartOffsetMs
DurationMs
MeanConfidence
RepresentativeThumbnailArtifactId
ProcessingRunId
```

Search returns only Tracks from completed ProcessingRuns.

## 19. Evidence Playback

### 19.1 Video content

```http
GET /api/videos/{videoAssetId}/content
```

The endpoint resolves the SourceVideo Artifact through `IMediaStore` and enables HTTP Range processing.

No physical path is exposed.

### 19.2 Artifact content

```http
GET /api/artifacts/{artifactId}/content
```

Phase-1 uses this for thumbnails.

### 19.3 Review route

React route:

```text
/review/video/:videoAssetId?trackId=<id>
```

The UI seeks to:

```text
max(0, Track.StartOffsetMs - 1000 ms)
```

and displays Track metadata. Bounding-box overlays may be added after basic evidence playback works, using the trajectory endpoint/artifact.

## 20. Phase-1 React Workspaces

Only these screens are required:

### 20.1 Cameras

- list cameras;
- add camera;
- show active/inactive state.

### 20.2 Video Import

- camera selector;
- recording local date/time;
- MP4 selector;
- Import & Process action;
- import validation/errors.

The UI may internally call import then process as two API operations.

### 20.3 Processing

- video filename;
- camera;
- queued/running/processed/failed status;
- progress percentage;
- retry action after failure.

### 20.4 Visual Search

- object class;
- camera;
- from/to;
- minimum duration;
- minimum confidence;
- paged track result cards with thumbnail and evidence action.

### 20.5 Video Review

- native HTML5 video;
- track summary;
- seek to selected track;
- representative thumbnail/observation context.

## 21. Error Model

API uses RFC 9457-style Problem Details with stable MAVI error codes.

Initial codes:

```text
camera_not_found
camera_inactive
invalid_recording_time
unsupported_video
video_unreadable
video_duplicate
media_storage_failure
processing_already_active
vision_worker_unavailable
vision_job_lease_conflict
vision_result_invalid
vision_processing_failed
artifact_integrity_failure
```

User-facing messages remain concise; technical details are logged.

## 22. Logging and Audit Baseline

Phase 1 shall use structured application logging and include correlation fields:

```text
RequestId
VideoAssetId
ProcessingRunId
VisionJobId
WorkerId
```

A full operational audit subsystem is later work, but Phase 1 must retain model/pipeline versions and the source/evidence linkage necessary for future audit.

## 23. Testing Strategy

### 23.1 .NET unit tests

Cover:

- domain invariants;
- camera validation;
- timestamp conversion and ambiguous-time rejection;
- processing state transitions;
- job lease rules;
- result validation;
- search filtering logic;
- storage-key validation.

### 23.2 PostgreSQL integration tests

Use dedicated local `mavi_test` PostgreSQL database via `MAVI_TEST_DB_CONNECTION`.

Cover:

- migration applies cleanly;
- pgvector extension exists;
- unique/index constraints;
- camera CRUD;
- job lease atomicity;
- accepted result transaction;
- failed result does not create partial intelligence;
- search query results.

### 23.3 Python unit tests

Cover:

- transport contract parsing;
- storage-key resolution;
- detector/tracker adapters using deterministic fixtures;
- keyframe de-duplication;
- quality scoring;
- trajectory MessagePack round-trip;
- worker lease/heartbeat/complete lifecycle using HTTP mock transport.

### 23.4 Vision runtime acceptance

Use a small controlled MP4 and verify:

- person/vehicle detections are produced;
- tracks have ordered timestamps;
- observations/thumbnails exist;
- trajectory artifacts decode;
- worker completion passes .NET validation.

## 24. Performance Instrumentation

Phase 1 records rather than prematurely mandates throughput.

For each ProcessingRun capture:

```text
source video duration
processing duration
frames processed
effective processing FPS
tracks created
CPU utilisation sample (worker log)
GPU utilisation/VRAM sample where available (worker log)
artifact bytes created
database rows created
```

For search capture API latency in structured logs.

These measurements will inform later GPU/server sizing.

## 25. Controlled PoC Dataset

In addition to public surveillance datasets, Phase 1 shall include a small controlled internal test set with known ground truth.

Minimum controlled scenario:

- at least one 5–15 minute camera recording;
- at least three persons;
- at least two vehicle types;
- repeated passages;
- distractor/background activity;
- a simple ground-truth manifest containing known intervals/object classes.

The purpose is not to establish full scientific model accuracy in Phase 1. It is to measure basic track retrieval, duplicates, misses, evidence linkage and investigation-time improvement.

## 26. Phase-1 Acceptance Criteria

Phase 1 is complete when all of the following can be demonstrated on a clean development machine:

1. MAVI database can be created from migrations.
2. A camera can be registered and remains after restart.
3. A valid MP4 can be imported with camera + recording start time.
4. MAVI owns a managed source-video copy and can play it after the original upload source is removed.
5. The platform can queue a ProcessingRun and a Python worker can lease it.
6. The worker processes the managed video and returns person/vehicle Tracks.
7. .NET validates and atomically persists accepted Tracks/Observations/Artifacts.
8. Search can filter tracks by camera, object class and time range.
9. Each search result has a representative thumbnail.
10. “View Video” opens the managed source video at the correct track time.
11. Processing failures do not create partial accepted intelligence.
12. A failed video can be reprocessed without re-importing the source.
13. The complete Phase-1 test suite passes.
14. The runtime can operate with Internet connectivity disabled once dependencies/model files are locally staged.

## 27. Implementation Increments

Implementation proceeds in this order:

1. Domain model and persistence foundation.
2. Camera CRUD.
3. Managed MP4 ingestion.
4. Processing orchestration and dummy worker.
5. Independent vision pipeline.
6. Worker-result validation and intelligence persistence.
7. Search and evidence playback.
8. React Phase-1 workspaces.
9. PoC hardening, controlled dataset and performance measurement.

Every increment must leave the repository buildable and testable.

## 28. Extension Path After Phase 1

Phase 2 may add:

- track/person/vehicle embeddings using pgvector;
- visual-similarity search;
- operator-assisted same-entity confirmation;
- persistent `Entity` use;
- multiple Tracks per Entity;
- cross-camera candidate association.

No Phase-2 requirement should require replacing the Phase-1 Camera, VideoAsset, ProcessingRun, Track, Observation, Artifact or evidence-linkage concepts.

## 29. Locked Decisions

The following are locked for Phase 1 unless an implementation blocker is demonstrated:

- recorded MP4 only;
- camera and recording start time mandatory at import;
- multiple videos per camera supported;
- MAVI-managed copy of imported video;
- Track is primary searchable unit;
- selected relational Observations plus sidecar trajectory;
- Track can exist without Entity;
- Python never writes operational PostgreSQL data;
- .NET validates and persists worker results;
- logical storage keys, not absolute paths, cross subsystem boundaries;
- REST lease/heartbeat/complete worker transport for PoC;
- PostgreSQL + pgvector as authoritative database foundation;
- structured search before vector/natural-language search;
- source evidence linkage is mandatory for every accepted Track.
