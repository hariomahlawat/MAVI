# Task 14 — Track Search and Evidence Content APIs

**Status:** Approved implementation plan, amended 14 Sep 2026 for monotonic processing visibility. Implementation must follow this baseline unless the plan is deliberately amended first.

**Amendment rationale:** exact-head review exposed two sibling defects in the original wall-clock/advisory-lock pagination barrier: host-clock rollback/skew could move a later completion inside an earlier cursor snapshot, and exclusive first-page locks serialized readers. The authoritative design now uses a PostgreSQL-owned monotonic visibility sequence plus shared-reader/exclusive-completion advisory locking. `CompletedAtUtc` remains audit/display metadata and is no longer the pagination publication boundary or authoritative latest-completed ordering.

**Planning baseline:** Task 13 merged as PR #30 at `928b31b8b947c2da5ab7869f09213c88bc063dc4`.

**Primary objective:** expose durable Task-13 visual intelligence through stable, bounded, read-only APIs for structured Track search, Track detail, source-video playback and accepted-evidence content without exposing storage keys, physical paths, worker staging, mutable artifacts, or ambiguous reprocessing semantics.

---

## 1. Why Task 14 exists

Task 13 made the analytical result authoritative:

- successful worker completion is lease/attempt validated;
- accepted thumbnails/trajectories are sealed into the platform-owned evidence root;
- Tracks, representative Observations, Artifacts and ProcessingRun completion are committed atomically;
- completed results retain immutable runtime provenance.

The platform still lacks a supported read boundary for that intelligence. React must not invent database joins, filesystem paths, historical-run policy, pagination semantics or content-serving rules.

Task 14 therefore owns the complete backend query/read contract consumed later by Task 16.

---

## 2. Scope

Task 14 shall implement:

1. structured Track search;
2. stable cursor pagination;
3. Track detail retrieval;
4. source-video content streaming with HTTP range support;
5. accepted thumbnail/trajectory content streaming;
6. secure evidence-root reads;
7. explicit reprocessing/history semantics;
8. deterministic public DTOs and stable API error codes;
9. query/resource bounds and adversarial tests;
10. any narrowly required persistence index/migration changes.

Task 14 shall not implement:

- React UI;
- face recognition, ReID, ANPR, embeddings or vector search;
- arbitrary SQL/full-text search;
- trajectory visualization or decoding;
- clips/exports;
- evidence mutation, deletion or review workflows;
- authentication/identity architecture not already present in MAVI;
- public storage keys or physical filesystem paths;
- worker staging content endpoints;
- new detector/tracker behavior;
- new processing lifecycle semantics.

The current deployment remains protected-LAN/API-boundary security. Task 14 must not accidentally create a second filesystem or database access path merely because application authentication is deferred.

---

## 3. Architectural rules

### 3.1 PostgreSQL remains authoritative for discoverability

A file existing on disk does not make it API-visible.

Every search/detail/content request must first resolve an authoritative database relationship. A caller may never supply a storage key.

### 3.2 Storage-root separation remains absolute

Source videos remain in `MediaStorage:RootPath`.

Accepted thumbnails/trajectories remain in `MediaStorage:EvidenceRootPath`.

The Python worker must retain no write authority to the evidence root. Task 14 must not collapse these roots or route accepted evidence through worker-writable staging.

### 3.3 Public contracts expose identities and URLs, not paths

Public DTOs may expose durable database IDs and API content URLs.

They must not expose:

- `Artifact.StorageKey`;
- OS paths;
- evidence-root paths;
- source-media paths;
- staging keys;
- worker lease identifiers.

### 3.4 Query APIs are read-only

Use `AsNoTracking()` and projection queries. Search/detail handlers must not materialize domain aggregates merely to serialize them.

### 3.5 No free-form ordering

Task 14 defines one search order:

`Track.StartTimestampUtc DESC, Track.Id DESC`.

No user-supplied column names or arbitrary sort expressions are accepted.

---

## 4. Reprocessing and historical-run semantics

A VideoAsset may have many completed ProcessingRuns after reprocessing. Returning every historical run by default would duplicate the same real-world scene in operator search.

Task 14 therefore defines:

### Default search scope

For each VideoAsset, search only Tracks belonging to its **latest completed ProcessingRun**.

“Latest completed” is selected deterministically by the run's unique PostgreSQL-owned `VisibilitySequence DESC`.

`CompletedAtUtc` remains the real-world completion timestamp returned to clients, but it is deliberately not used to decide publication order because host clocks may skew or move backwards.

A later queued/running/failed run does not hide the last completed intelligence.

### Explicit historical access

`GET /api/tracks/{trackId}` may retrieve a Track from any completed ProcessingRun, including a superseded historical completed run.

Search may accept an optional `processingRunId`. When present:

- the named run must be `Completed`;
- only Tracks from that run are searched;
- latest-completed suppression is not applied.

Task 14 does not add an “all historical runs” search mode. That can be introduced later if an audit/history UI needs it.

---

## 5. Track search HTTP contract

### 5.1 Endpoint

```http
GET /api/tracks
```

Supported query parameters:

```text
cameraId
videoAssetId
processingRunId
objectClass
fromUtc
toUtc
minimumDurationMs
minimumConfidence
cursor
limit
```

Defaults:

- `limit = 50`;
- maximum `limit = 100`;
- no cursor means first page.

### 5.2 Filter validation

Reject with `400 track_search_invalid` when:

- any Guid is empty/invalid;
- `objectClass` is not a supported Phase-1 class;
- `fromUtc` or `toUtc` is not an offset-aware/RFC3339 timestamp accepted by ASP.NET;
- either timestamp is not normalized by application parsing to an unambiguous instant;
- `fromUtc >= toUtc`;
- `minimumDurationMs < 0`;
- `minimumConfidence` is non-finite or outside `[0,1]`;
- `limit < 1 || limit > 100`;
- cursor is malformed, oversized or does not decode to the canonical cursor shape.

Do not silently clamp malformed values.

### 5.3 Time semantics

A search window is the half-open UTC interval:

`[fromUtc, toUtc)`.

A Track matches when its interval overlaps the requested interval:

```text
track.EndTimestampUtc >= fromUtc
AND track.StartTimestampUtc < toUtc
```

When only `fromUtc` is supplied:

`track.EndTimestampUtc >= fromUtc`.

When only `toUtc` is supplied:

`track.StartTimestampUtc < toUtc`.

This is intentionally interval-overlap search, not “track started inside the window.”

### 5.4 Confidence semantics

`minimumConfidence` applies to `Track.MeanConfidence`.

The DTO also returns `MaxConfidence`; it is not the filter unless a future explicit parameter is added.

### 5.5 Camera/video/run filter consistency

If multiple identity filters are supplied, combine them with AND.

Examples:

- a `cameraId` plus `videoAssetId` that do not correspond yields an empty result, not a broadened query;
- a `processingRunId` belonging to another video/camera yields an empty result;
- a non-existent identity filter does not leak whether another unrelated resource exists.

---

## 6. Cursor pagination

Task 14 shall not use page-number/offset pagination for Track search.

Concurrent processing can insert newer Tracks while an operator pages. OFFSET would then duplicate/skip rows.

### 6.1 Sort key

Canonical search ordering:

```text
StartTimestampUtc DESC
Id DESC
```

### 6.2 Cursor shape

Application-internal cursor payload:

```text
version = 2
snapshotUtc
snapshotVisibilitySequence
startTimestampUtc
trackId
filterFingerprint
```

Encode as bounded base64url UTF-8 JSON (or an equivalently deterministic opaque format).

The cursor carries no authorization claim. It is an untrusted pagination position and must be fully validated.

`filterFingerprint` binds the cursor to the semantic search filters (camera/video/run/object class/time window/minimum duration/minimum confidence). Reusing a cursor with changed filters is invalid. Page size is intentionally not part of the fingerprint.

Cursors expire one hour after `snapshotUtc` and snapshots more than one minute in the future are rejected. This prevents stale/forged cursors from becoming an undocumented historical-search mechanism while allowing normal operator pagination.

`snapshotUtc` exists only for cursor lifetime/future-skew validation. The completed-run publication boundary is `snapshotVisibilitySequence`. Every continuation page must evaluate both the candidate run and the “is there a later completed run?” anti-exists predicate using `VisibilitySequence <= snapshotVisibilitySequence`. This prevents reprocessing completed after page 1 from replacing a video's result set midway through pagination even when application clocks skew or step backwards.

### Commit-visibility barrier

Wall-clock timestamps are not suitable publication watermarks: they may be assigned before commit, differ between hosts, or move backwards. Task 14 therefore uses a dedicated PostgreSQL sequence, `processing_visibility_sequence`, as the authoritative monotonic publication order.

Task 14 shares one PostgreSQL transaction-level advisory-lock protocol with Task 13 completion:

- a completion transaction takes the **exclusive** advisory lock immediately before allocating its `VisibilitySequence`, then holds the lock through the final save and commit;
- a first-page Track search starts a transaction and takes the **shared** counterpart, allowing multiple first-page readers to execute concurrently;
- while holding the shared lock, the search allocates its own `snapshotVisibilitySequence` from the same PostgreSQL sequence and executes the first-page query;
- continuation pages reuse the issued `snapshotVisibilitySequence` and do not reacquire the barrier.

Consequently, every completed run visible to page 1 has `VisibilitySequence <= snapshotVisibilitySequence`, while any completion that can commit after that first-page transaction releases its shared lock receives a strictly greater sequence. The invariant is independent of application clocks and does not serialize readers.

The barrier and sequence are infrastructure publication protocols; direct data-repair/import paths that create completed ProcessingRuns must allocate and persist a valid visibility sequence before those rows can become searchable.

Maximum encoded cursor length shall be explicit (maximum 512 encoded characters).

### 6.3 Seek predicate

For a decoded cursor `(timestamp, id)`:

```text
track.StartTimestampUtc < timestamp
OR (
    track.StartTimestampUtc == timestamp
    AND track.Id < id
)
```

Fetch `limit + 1` records:

- emit at most `limit`;
- if one additional record exists, create `nextCursor` from the final emitted item;
- otherwise `nextCursor = null`.

No total-count query is required in Task 14.

---

## 7. Search DTO

Create a compact result contract suitable for Task-16 cards.

Conceptual shape:

```text
TrackSearchResponse
- items[]
- nextCursor

TrackSearchItemResponse
- id
- processingRunId
- videoAssetId
- cameraId
- cameraCode
- cameraName
- objectClass
- startTimestampUtc
- endTimestampUtc
- startOffsetMs
- endOffsetMs
- durationMs
- detectionCount
- meanConfidence
- maxConfidence
- reviewStatus
- thumbnailArtifactId
- thumbnailContentUrl
- videoContentUrl
```

Rules:

- all real-world timestamps are UTC API values;
- `thumbnailArtifactId`/URL may be null only for historical data that genuinely lacks a representative thumbnail;
- Task-13 successful rows are expected to have them;
- no storage key appears.

Content URLs must be generated from durable IDs, not persisted as database text.

---

## 8. Track detail contract

### 8.1 Endpoint

```http
GET /api/tracks/{trackId}
```

A Track is retrievable only when its ProcessingRun is `Completed`.

Return `404 track_not_found` for:

- unknown Track;
- Track whose run is not completed.

Do not expose partial/failed analytical rows.

### 8.2 Detail response

Conceptual shape:

```text
TrackDetailResponse
- id
- processingRunId
- videoAssetId
- camera
    - id
    - code
    - name
- objectClass
- localTrackNumber
- startOffsetMs
- endOffsetMs
- startTimestampUtc
- endTimestampUtc
- durationMs
- detectionCount
- meanConfidence
- maxConfidence
- reviewStatus

- processing
    - pipelineVersion
    - detectorName
    - detectorVersion
    - trackerName
    - trackerVersion
    - completedAtUtc

- video
    - recordingStartUtc
    - recordingEndUtc
    - durationMs
    - width
    - height
    - frameRateNumerator
    - frameRateDenominator
    - videoContentUrl

- representative
    - observationId
    - sourceFrameNumber
    - videoOffsetMs
    - timestampUtc
    - confidence
    - qualityScore
    - boundingBox { x, y, width, height }
    - thumbnailArtifactId
    - thumbnailContentUrl

- trajectoryArtifactId
- trajectoryContentUrl
```

Do not return `RuntimeProvenanceJson` wholesale in Task 14. It is an internal forensic/audit record and would unnecessarily couple the operator API to worker provenance schema. The stable detector/tracker/pipeline identities are sufficient for Phase-1 detail.

---

## 9. Content endpoints

### 9.1 Source video

```http
GET /api/videos/{videoAssetId}/content
```

Resolution:

`VideoAsset -> SourceArtifactId -> Artifact`.

Required conditions:

- VideoAsset exists;
- Artifact exists;
- ArtifactType == `SourceVideo`.

The source file is opened only through `IMediaStore`.

### 9.2 Accepted evidence

```http
GET /api/artifacts/{artifactId}/content
```

Task 14 allows only:

- `Thumbnail`;
- `TrackTrajectory`.

SourceVideo is served through the VideoAsset route so the public API does not create two equivalent source-video identities.

For a Thumbnail, the Artifact must be referenced by an Observation whose Track belongs to a completed ProcessingRun.

For a TrackTrajectory, the Artifact must be referenced by a Track belonging to a completed ProcessingRun.

An arbitrary Artifact row is not sufficient authority for content publication.

Return `404 artifact_not_found` for unknown, unsupported or non-authoritative relationships. Do not reveal storage topology through distinct errors.

---

## 10. Secure accepted-evidence read boundary

Task 13's `IAcceptedEvidenceStore` is a mutation/sealing abstraction. Do not overload its responsibility.

Create a dedicated read abstraction, for example:

```csharp
public interface IAcceptedEvidenceReader
{
    Task<Stream> OpenReadAsync(
        string acceptedStorageKey,
        CancellationToken cancellationToken);
}
```

Infrastructure implementation must:

- accept only canonical `evidence/...` logical keys;
- resolve beneath `EvidenceRootPath`;
- reject `.`, `..`, backslashes, drive syntax and overlong keys;
- re-check existing root/path components for symbolic-link/reparse escape;
- open the leaf through a handle/file descriptor;
- verify the opened leaf identity corresponds to the expected path;
- reject symlink/reparse leaf substitution;
- use read-only sharing appropriate for immutable accepted objects;
- never expose the resolved physical path.

Where practical, extract/share an internal secure-local-file-open primitive with `LocalMediaStore` rather than maintaining two subtly different leaf-safety implementations.

The public content service may receive a storage key only from the authoritative Artifact row, never from HTTP input.

---

## 11. Content response semantics

Both content routes must support byte ranges using ASP.NET Core seekable-stream range processing.

Required behavior:

### Full GET

- `200 OK`;
- authoritative MIME type from Artifact;
- `Content-Length` matching Artifact.SizeBytes;
- `Accept-Ranges: bytes`.

### Valid range

Example:

```http
Range: bytes=0-99
```

Return:

- `206 Partial Content`;
- exactly 100 bytes when the object is >=100 bytes;
- correct `Content-Range`;
- authoritative MIME type.

### Invalid/unsatisfiable range

Return standards-compliant `416 Range Not Satisfiable` through framework range processing.

### Integrity metadata

Set a strong ETag from immutable SHA-256:

```text
"<64-lowercase-sha256>"
```

Task 14 does not need to implement a custom conditional-request state machine. Do not advertise semantics not covered by tests.

### Stream safety

Before returning the stream:

- verify the opened stream is readable;
- verify it is seekable because range processing depends on seeking;
- where length is cheaply available, require `stream.Length == Artifact.SizeBytes`;
- mismatch is a server-side integrity fault and must not stream misleading bytes.

Do not re-hash multi-gigabyte video content on every request. Integrity is established at import/sealing; secure root/leaf identity plus stored length is the read-time boundary.

Dispose streams through ASP.NET result lifecycle.

---

## 12. Application boundaries

Add narrow query/read interfaces.

Recommended shape:

```text
Mavi.Application/Modules/Intelligence/
  TrackSearchQuery.cs
  TrackSearchResult.cs
  ITrackSearchRepository.cs
  TrackSearchService.cs
  TrackCursorCodec.cs

Mavi.Application/Modules/Evidence/
  IContentCatalog.cs
  ContentDescriptor.cs
  ContentReadService.cs

Mavi.Application/Abstractions/Storage/
  IAcceptedEvidenceReader.cs
```

### ITrackSearchRepository

Owns database projection/query execution only.

It must not:

- open files;
- generate physical paths;
- parse HTTP query strings;
- return EF entities to the API.

### TrackSearchService

Owns:

- semantic query validation;
- cursor decoding/encoding;
- page-size policy;
- repository orchestration.

### Content catalog/service

Database lookup determines whether a content identity is authoritative and which logical key/store applies.

Storage opening happens only after database authorization succeeds.

Keep DB lookup and filesystem read responsibilities separate.

---

## 13. Persistence query design

### 13.1 Search joins

Search projection requires:

```text
Track
 -> ProcessingRun
 -> VideoAsset
 -> Camera
 -> Representative Observation
 -> Thumbnail Artifact
```

Only `ProcessingRun.Status == Completed`.

### 13.2 Latest-completed-run predicate

For default search, use a SQL-translatable anti-exists/subquery equivalent:

“there is no later completed ProcessingRun for this VideoAsset with a greater `VisibilitySequence` inside the cursor's visibility snapshot.”

Do not load all runs into memory.

### 13.3 Required index review

Current indexes already cover:

- `Track(VideoAssetId, StartTimestampUtc)`;
- `Track(ObjectClass, StartTimestampUtc)`;
- `Track(ProcessingRunId)`;
- `VideoAsset(CameraId, RecordingStartUtc)`;
- `ProcessingRun(VideoAssetId)`.

Task 14 shall benchmark/explain the generated SQL before adding indexes blindly.

A likely narrow migration is a completed-run lookup index such as:

```text
processing_runs(video_asset_id, completed_at_utc DESC, id DESC)
WHERE status = 'Completed'
```

Add it only if the generated latest-run query benefits materially and the Npgsql migration can express the partial index cleanly.

No index is required solely for `minimumDurationMs` or `minimumConfidence` in Phase 1 unless query evidence demonstrates a need.

---

## 14. Error contract

Stable top-level API codes:

```text
track_search_invalid
track_not_found
video_not_found
video_content_unavailable
artifact_not_found
artifact_content_unavailable
```

Mapping:

- malformed search/cursor: 400;
- unknown/non-authoritative resource: 404;
- authoritative DB row whose expected immutable file is absent, unsafe or length-mismatched: 500 with the corresponding `*_content_unavailable` code;
- linked/reparse parent or leaf detection and low-level opened-handle identity failures are normalized by storage infrastructure to I/O-family safety failures so they cannot bypass the stable content error contract;
- existing VideoAsset whose SourceArtifact relationship is missing, wrong-type or otherwise structurally invalid: 500 `video_content_unavailable`, not 404.

Do not convert a platform storage-integrity incident into 404; that would hide operational corruption.

Detailed filesystem paths/exceptions must be logged internally, not returned to clients.

---

## 15. Resource-exhaustion and abuse boundaries

The audit must explicitly test:

- `limit=0`, negative, >100, huge integer;
- overlong cursor;
- invalid base64 cursor;
- cursor JSON with extra fields;
- cursor timestamp/Guid parse failures;
- very broad time range;
- simultaneous filters;
- non-existent identities;
- repeated Range requests;
- suffix ranges and open-ended ranges;
- unsatisfiable ranges;
- request cancellation during search/read;
- evidence/source stream not seekable;
- stored size differing from actual size;
- linked/reparse evidence leaf;
- evidence path replaced between DB lookup and open;
- artifact ID referring to unsupported ArtifactType;
- artifact row not referenced by a completed Track/Observation.

No endpoint accepts a user-controlled storage key, SQL column name, filesystem path, MIME type or filename.

---

## 16. Cross-platform requirements

Task 14 is supported on Windows and Linux.

Tests must cover the secure evidence reader on both OS families through the existing Staging Security workflow or an extended read-security matrix.

Explicitly cover:

- Windows reparse/symlink leaf where test privileges permit;
- Linux symlink leaf;
- case-insensitive/case-sensitive filesystem differences;
- slash-only logical key semantics;
- no path traversal through alternate separators.

Track/Artifact IDs and API behavior must be platform-independent.

---

## 17. Test-first implementation sequence

### Phase A — Contract and query semantics

Create failing tests before repository implementation for:

1. default latest-completed-run search;
2. historical completed run hidden from default results;
3. failed/running run excluded;
4. explicit completed `processingRunId` retrieves historical Tracks;
5. camera + class + video filters compose with AND;
6. interval-overlap time semantics;
7. `minimumDurationMs`;
8. `minimumConfidence` uses mean confidence;
9. stable `StartTimestampUtc DESC, Id DESC` order;
10. deterministic next cursor;
11. second cursor page has no duplicate/omitted boundary row;
12. insertion of a newer Track between page requests does not disturb continuation;
13. completion of a replacement ProcessingRun between page requests does not replace the snapshotted run on continuation pages;
14. cursor reuse with changed filters is rejected;
15. stale/future cursor snapshots are rejected;
16. malformed cursor/query returns `track_search_invalid`.

### Phase B — Detail projection

Tests:

1. complete Track detail returns camera/video/processing/representative data;
2. source/evidence URLs contain durable IDs only;
3. storage keys never appear in serialized JSON;
4. unknown Track -> 404;
5. Track from non-completed run -> 404;
6. historical completed Track detail remains retrievable.

### Phase C — Secure evidence reads

Tests at storage layer:

1. valid accepted key opens expected bytes;
2. traversal/backslash/colon/non-evidence prefix rejected;
3. linked parent rejected;
4. linked/reparse leaf rejected;
5. physical leaf mismatch rejected;
6. missing file reported safely;
7. open stream is seekable/read-only;
8. root remains physically disjoint from worker media root.

### Phase D — Content API

Integration tests:

1. full source-video GET;
2. source-video first-byte range;
3. middle range;
4. suffix range;
5. open-ended range;
6. unsatisfiable range -> 416;
7. correct MIME/Content-Length/Content-Range/ETag;
8. thumbnail content;
9. trajectory content;
10. unsupported SourceVideo through artifact route -> 404;
11. unreferenced evidence Artifact -> 404;
12. completed evidence relation succeeds;
13. DB/file length mismatch -> 500 content-unavailable;
14. no response contains a physical/storage key.

### Phase E — SQL/persistence verification

- inspect generated SQL for search/latest-run query;
- assert all query paths are `AsNoTracking`;
- add only justified index migration;
- migration upgrade test;
- validate no N+1 query behavior in search/detail.

---

## 18. Adversarial invariant matrix

Before the first Codex review, perform an internal read-only audit of the completed Task-14 subsystem against this matrix.

| Area | Required invariant |
|---|---|
| Search scope | default results contain only latest completed intelligence per video |
| Historical integrity | old completed Tracks remain addressable by Track ID |
| Pagination | concurrent newer inserts, uncommitted completion transactions, or later reprocessing cannot duplicate/skip/replace the snapshotted continuation set |
| Time | filters use UTC interval overlap, not local-time guesswork |
| Contracts | no storage key/path escapes API DTOs |
| DB authority | filesystem existence alone never authorizes content |
| Evidence authority | artifact must be referenced by completed intelligence |
| Source authority | video content resolves through VideoAsset.SourceArtifactId |
| Root separation | source media and accepted evidence use distinct read roots |
| Path safety | no link/reparse/path-traversal escape |
| Range | 200/206/416 behavior is deterministic and tested |
| Integrity | stored-vs-opened length mismatch fails closed |
| Resource bounds | cursor/limit/filter parsing is bounded |
| Query safety | no dynamic SQL/sort column/path from client input |
| Reprocessing | queued/failed later run does not hide last completed result |
| Platform parity | Windows/Linux produce equivalent API semantics |

Every discovered bug class must produce a sibling-defect search before it is considered closed.

---

## 19. Internal review before Codex

Task 14 shall use the process learned from Task 13:

1. implement from this plan;
2. run focused tests;
3. perform our own complete subsystem audit;
4. fix all definite Critical/P1/P2-equivalent issues and material invariant gaps;
5. rerun the audit against the modified code;
6. run exact-head Quality and platform security gates;
7. only then request Codex review.

Codex is an independent reviewer, not the primary debugger.

If Codex finds a material issue, identify the failed reasoning class and search for sibling defects before applying the local fix.

---

## 20. Implementation checkpoints

Use small cohesive commits/checkpoints:

### Checkpoint 1 — public contracts + cursor/query validation
- Track DTOs;
- query model;
- cursor codec;
- pure service tests.

### Checkpoint 2 — repository projections + latest-run policy
- search repository;
- detail repository;
- SQL tests;
- optional justified index migration.

### Checkpoint 3 — secure evidence reader
- dedicated read abstraction;
- shared secure leaf-open primitive if appropriate;
- Windows/Linux security tests.

### Checkpoint 4 — content catalog/service
- DB-authoritative content descriptors;
- source/evidence store routing;
- size/seekability validation.

### Checkpoint 5 — endpoints + HTTP range behavior
- `GET /api/tracks`;
- `GET /api/tracks/{id}`;
- `GET /api/videos/{id}/content`;
- `GET /api/artifacts/{id}/content`;
- error/ETag/range semantics.

### Checkpoint 6 — full adversarial audit
- run all Task-14 tests;
- full solution build;
- repository verification;
- internal invariant audit;
- exact-head gates;
- broad Codex review.

Do not mix Task-15 React work into this branch.

---

## 21. Expected files

Expected additions/modifications include:

```text
src/platform/Mavi.Application/Modules/Intelligence/
  ITrackSearchRepository.cs
  TrackSearchQuery.cs
  TrackSearchResult.cs
  TrackSearchService.cs
  TrackCursorCodec.cs

src/platform/Mavi.Application/Modules/Evidence/
  IContentCatalog.cs
  ContentDescriptor.cs
  ContentReadService.cs

src/platform/Mavi.Application/Abstractions/Storage/
  IAcceptedEvidenceReader.cs

src/platform/Mavi.Infrastructure/Persistence/Repositories/
  TrackSearchRepository.cs
  ContentCatalog.cs

src/platform/Mavi.Infrastructure/Storage/
  AcceptedEvidenceReader.cs
  [shared secure-read helper if justified]

src/platform/Mavi.Contracts/Api/Tracks/
  TrackSearchResponse.cs
  TrackDetailResponse.cs

src/platform/Mavi.Api/Endpoints/
  TrackEndpoints.cs
  ArtifactEndpoints.cs

src/platform/Mavi.Api/Endpoints/VideoEndpoints.cs
src/platform/Mavi.Api/Program.cs
src/platform/Mavi.Infrastructure/DependencyInjection.cs

tests/Mavi.Application.Tests/
  TrackSearchServiceTests.cs
  TrackCursorCodecTests.cs

tests/Mavi.IntegrationTests/
  TrackSearchApiTests.cs
  TrackDetailApiTests.cs
  ContentApiTests.cs
  AcceptedEvidenceReaderTests.cs
```

A migration is added only if the completed-run search index is justified.

---

## 22. Definition of done

Task 14 is complete only when all of the following are true:

- search semantics are implemented exactly as this plan defines;
- latest-completed-run behavior is tested;
- historical Track detail remains available;
- cursor pagination is deterministic and insertion-stable;
- content endpoints never accept/expose storage paths;
- source/evidence stores remain physically separate;
- secure evidence reads reject path/link/reparse attacks;
- source video and evidence ranges pass 200/206/416 integration tests;
- stored content-length mismatch fails closed;
- all APIs expose stable error codes;
- all DTOs are verified not to leak storage keys;
- .NET solution/tests are green;
- Windows/Linux storage-security tests are green;
- our internal adversarial audit finds no remaining Critical/P1/P2-equivalent issue;
- one broad independent Codex review finds no material blocker;
- PR is merged with expected-head protection;
- merged target tree is verified.

No deterministic ML runtime rebind is expected for Task 14 because it must not modify packaged Python runtime code. If implementation unexpectedly changes packaged vision/runtime source, stop and reapply the Task-12 release process rather than casually rebinding artifacts.

---

## 23. Task 15/16 handoff contract

Task 15 may use existing camera/video/processing APIs after Task 14 without depending on Track search.

Task 16 Visual Search/Evidence Review must consume only the Task-14 APIs defined here:

- search through `GET /api/tracks`;
- detail through `GET /api/tracks/{id}`;
- playback through `GET /api/videos/{id}/content`;
- thumbnails/trajectory bytes through `GET /api/artifacts/{id}/content`.

React must not reconstruct storage URLs from Artifact storage keys or call the filesystem directly.
