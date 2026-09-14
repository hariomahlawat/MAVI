# Task 15 — React Application Foundation, Cameras, Import and Processing UI

**Status:** Authoritative implementation plan. Task 15 is the active Phase-1 task after Task 14 merged as PR #31.

**Planning baseline:** Phase-1 integration head `3e0382185d6a3a1907870226af3561ff97f2ba8f`.

**Primary objective:** replace the bootstrap-only React screen with a production-quality offline-capable application shell and the first complete operator workflow: Camera setup → MP4 import → processing queue/status → explicit retry after failure.

Task 15 must consume backend semantics rather than recreate them in the browser. It must establish frontend conventions that Task 16 can extend without redesigning routing, API error handling, server-state management, testing, accessibility, or offline asset policy.

---

## 1. Baseline audit

At the Task-15 baseline:

- React 19 + Vite + strict TypeScript already build successfully.
- The frontend has only a bootstrap `App.tsx`, a health/config fetch, and local CSS.
- There is no router, server-state library, page architecture, form/test harness, or stable API error abstraction.
- `package-lock.json` is already committed and remains the dependency reproducibility boundary.
- Camera APIs already support create/list/get.
- Video APIs already support import/list/get/process/processing/content.
- Task 13 provides authoritative completion and retry semantics.
- Task 14 provides Track/evidence read APIs, but Task 15 deliberately does not implement Visual Search or Evidence Review.
- `GET /api/videos/{id}/processing` currently serializes an anonymous response containing an application-layer view type. Before frontend consumption, Task 15 must convert that endpoint to explicit public `Mavi.Contracts` response records. React must not couple itself to anonymous/internal serialization.

This last point is a required pre-implementation contract hardening step, not scope expansion.

---

## 2. Scope

Task 15 shall implement:

1. stable frontend API client and typed API modules;
2. React Router application shell;
3. TanStack Query server-state ownership;
4. Cameras list/create workflow;
5. MP4 import workflow;
6. processing-status page with bounded polling;
7. explicit retry after failed processing;
8. stable public processing-status DTOs in `Mavi.Contracts`;
9. focused component/API/router tests;
10. accessibility and offline-safe styling conventions.

Task 15 shall not implement:

- Track search UI;
- evidence/video review UI;
- trajectory rendering;
- face recognition/ReID/ANPR/embeddings;
- camera edit/delete unless separately planned;
- video delete;
- drag-and-drop upload unless it falls out trivially after the required file-input workflow is complete;
- Redux or another global client-state store;
- WebSockets/SignalR for processing progress;
- optimistic mutation of authoritative processing state;
- authentication/authorization architecture;
- remote fonts, CDN assets, telemetry, or any Internet runtime dependency.

Task 16 owns Visual Search and Evidence Review.

---

## 3. Non-negotiable frontend architecture

### 3.1 React is an API client only

The browser never accesses PostgreSQL, media storage, evidence paths, storage keys, or worker staging.

All data comes from MAVI HTTP APIs.

### 3.2 Server state belongs to TanStack Query

Use TanStack Query for:

- cameras;
- video metadata;
- processing status;
- mutations and invalidation.

Do not mirror query results into ad-hoc global state.

### 3.3 Router owns navigation state

Task 15 routes:

```text
/                         -> redirect to /cameras
/cameras                  -> CamerasPage
/import                   -> VideoImportPage
/processing/:videoAssetId -> ProcessingPage
```

Task 16 will add `/search` and `/review/video/:videoAssetId`.

Do not create fake Task-16 screens merely to fill navigation.

### 3.4 One public API-error model

Create a reusable frontend `ApiError` carrying:

```text
status
code
detail
```

The client shall parse ASP.NET Problem Details and preserve the stable backend `extensions.code` value.

Pages may translate known codes to operator-friendly text, but must retain the code for diagnostics and tests.

### 3.5 No remote presentation dependencies

Use local CSS and system fonts. No CDN, remote icon set, remote font, runtime package fetch, or Internet telemetry.

---

## 4. Required backend contract hardening

### 4.1 Problem

`GET /api/videos/{id}/processing` currently returns:

```csharp
new { videoStatus = result.VideoStatus, latestRun = result.LatestRun }
```

where `LatestRun` is an application-layer `ProcessingRunStatusView`.

That is not an appropriate long-term frontend contract.

### 4.2 Public contracts

Add to `Mavi.Contracts.Api.Processing`:

```text
ProcessingStatusResponse
- videoStatus
- latestRun

ProcessingRunStatusResponse
- processingRunId
- status
- pipeline
- pipelineVersion
- workerId
- queuedAtUtc
- startedAtUtc
- completedAtUtc
- progressPercent
- attemptCount
- failureCode
```

Keep names and JSON casing consistent with the existing ASP.NET JSON policy.

Do not expose:

- lease token/hash;
- configuration JSON;
- runtime provenance JSON;
- worker filesystem/staging information;
- failure details that may contain operational internals.

### 4.3 Endpoint mapping

`VideoEndpoints.ProcessingAsync` explicitly maps the application view to the public response type.

Add an integration/contract test proving the stable response shape for:

- never queued video;
- queued/running video;
- completed video;
- failed video;
- unknown video -> `404 video_not_found`.

The public DTO shall be complete before React types are written.

---

## 5. Dependency and test-tooling policy

Add:

- `react-router-dom`;
- `@tanstack/react-query`.

Add development dependencies:

- `@testing-library/react`;
- `@testing-library/jest-dom`;
- `@testing-library/user-event`;
- `jsdom`.

Vitest already exists.

Rules:

1. install through npm so `package.json` and `package-lock.json` move together;
2. do not hand-edit transitive lock data;
3. dependency versions used by implementation are frozen by the committed lockfile;
4. no package may introduce a production online-service dependency;
5. add a dedicated Vitest setup file for jest-dom and shared DOM setup.

Add/retain scripts:

```json
"test": "vitest run",
"test:watch": "vitest"
```

Quality gate remains:

```text
npm test
npm run typecheck
npm run build
```

---

## 6. Proposed frontend structure

```text
src/web/mavi-web/src/
  app/
    AppProviders.tsx
    AppShell.tsx
    router.tsx
    queryClient.ts
  api/
    client.ts
    cameras.ts
    videos.ts
    platform.ts
    system.ts
  features/
    cameras/
      CamerasPage.tsx
      CamerasPage.test.tsx
    video-import/
      VideoImportPage.tsx
      VideoImportPage.test.tsx
    processing/
      ProcessingPage.tsx
      ProcessingPage.test.tsx
  shared/
    components/
      Alert.tsx
      LoadingState.tsx
      PageHeader.tsx
    format/
      dateTime.ts
      duration.ts
  test/
    setup.ts
    renderWithApp.tsx
  App.tsx
  app.css
  main.tsx
```

Keep the component inventory deliberately small. Do not build a design-system framework in Task 15.

---

## 7. Shared API client

Create `api/client.ts`.

Required behavior:

- use relative `/api/...` URLs;
- accept `AbortSignal`;
- parse JSON only when appropriate;
- throw `ApiError` for non-2xx responses;
- parse Problem Details defensively;
- fall back to a stable generic detail when a malformed error body is returned;
- never log request bodies or uploaded file contents;
- never retry POST mutations inside the client;
- leave retry policy to TanStack Query/mutation callers.

For multipart upload:

- create `FormData`;
- append `cameraId`, `recordingStartLocal`, and `file`;
- do **not** manually set `Content-Type`; the browser must generate the multipart boundary.

No API module may expose backend storage keys.

---

## 8. Camera API and page

### 8.1 API types

Frontend type mirrors:

```text
Camera
- id
- code
- name
- description
- locationName
- timeZoneId
- isActive
- createdAtUtc
- updatedAtUtc

CreateCameraInput
- code
- name
- timeZoneId
```

Functions:

```text
listCameras(signal?)
createCamera(input, signal?)
getCamera(id, signal?)   // useful to direct-route workflows; optional page use
```

### 8.2 Cameras page behavior

The page shall:

- list existing cameras;
- clearly show code, name, IANA timezone and Active/Inactive state;
- contain an Add Camera form;
- require code, name and timezone;
- disable submit while mutation is pending;
- prevent duplicate local submits;
- on success clear/reset the form and invalidate the camera-list query;
- on `camera_code_conflict` surface a specific conflict message;
- surface domain validation without hiding the backend error code.

No edit/delete controls are shown because the backend does not support them.

### 8.3 Timezone input

Camera timezone is an IANA timezone identity.

Do not silently infer and persist browser timezone as authoritative camera metadata.

A sensible default may be offered from existing system configuration, but the operator must be able to confirm/change it before submit.

The field label must make the semantics explicit, for example:

`Camera timezone (IANA, e.g. Asia/Kolkata)`.

---

## 9. Video import semantics

### 9.1 Form

Required fields:

- active Camera;
- recording local date/time;
- `.mp4` file.

Use `datetime-local` because the backend contract intentionally accepts timezone-less camera-local wall time. Do not convert this field to UTC in the browser.

The selected camera's `timeZoneId` must be displayed next to the recording-time field so the operator can see which timezone will interpret that local wall time.

Only active cameras are selectable for new import.

### 9.2 Client validation

Perform fast UX validation for:

- camera selected;
- date/time present;
- file present;
- file extension is `.mp4` case-insensitively.

Backend validation remains authoritative. Do not duplicate codec, container, DST ambiguity, file-size, hash, or metadata rules in JavaScript.

### 9.3 Mutation sequence

The workflow is intentionally two authoritative operations:

```text
POST /api/videos/import
        |
        v
201 VideoAsset
        |
        v
POST /api/videos/{id}/process
        |
        v
202 QueueProcessingResponse
        |
        v
navigate /processing/{id}
```

The UI may present this as one operator action, but it must preserve partial-success semantics.

If import succeeds and queueing fails:

- never tell the operator that import failed;
- never automatically upload the file again;
- retain the returned VideoAsset identity;
- for `processing_already_active`, navigate to the processing page because authoritative work already exists;
- for any other queue error, navigate/show the imported video state with a Retry Processing action.

This prevents duplicate imports caused by treating a two-step workflow as one transaction.

### 9.4 Backend error handling

Known import codes shall be mapped to clear messages, including:

- camera not found;
- camera inactive;
- duplicate import;
- invalid/ambiguous recording time;
- unsupported format/container;
- file too large;
- invalid filename;
- metadata invalid.

Do not discard the stable code.

---

## 10. Processing page

### 10.1 Data sources

For `/processing/:videoAssetId`, load:

- `GET /api/videos/{id}`;
- `GET /api/videos/{id}/processing`.

A direct browser refresh must reconstruct the page entirely from the route ID; it must not depend on navigation state from Import.

### 10.2 Polling

Use TanStack Query `refetchInterval`.

Poll every **2 seconds** only while the authoritative state is active:

```text
videoStatus == "Queued" or "Processing"
or
latestRun.status == "Queued" or "Running"
```

Stop polling when:

- Processed/Completed;
- Failed;
- the video is not found;
- the component unmounts.

Do not maintain a parallel `setInterval`.

### 10.3 Status display

Show:

- file name;
- camera context when available from cached/list data;
- video processing status;
- current/latest run status;
- progress percentage;
- attempt count;
- queued/start/completion timestamps;
- pipeline/version;
- failure code when failed.

Do not display worker ID as primary operator information. It may appear in a compact diagnostics section if useful.

Progress must be clamped for presentation only; do not mutate authoritative values.

### 10.4 Retry

Retry is available only after authoritative failure/not-queued states where queueing is permitted.

Retry performs:

`POST /api/videos/{id}/process`.

On success:

- invalidate video + processing status queries;
- resume polling.

If the backend returns `processing_already_active`, treat that as authoritative active work: refetch and resume polling rather than presenting a destructive error.

No automatic infinite retry.

---

## 11. Application shell and navigation

Replace the bootstrap hero with a compact operational shell.

Minimum shell:

- product title/identifier;
- primary navigation: Cameras, Import;
- reserved visual hierarchy that Task 16 can extend with Search without restructuring;
- API availability indicator may remain but must not block normal rendering;
- responsive content container;
- keyboard-visible focus states.

Do not over-design. Task 15 establishes structure and consistency, not a final visual-design system.

Use semantic elements (`nav`, `main`, headings, labels, buttons) and accessible status/error regions.

---

## 12. Query keys and mutation discipline

Use centralized query-key factories, for example:

```text
["cameras"]
["camera", id]
["videos"]
["video", id]
["video-processing", id]
["system-config"]
["platform-health"]
```

Mutation invalidation:

- create camera -> invalidate `["cameras"]`;
- import video -> invalidate `["videos"]`;
- queue/retry -> invalidate `["video", id]` and `["video-processing", id]`.

Global automatic mutation retries: **disabled**.

Query retries should be bounded and conservative; do not turn an offline API outage into a request storm.

---

## 13. Testing strategy

Use behavior-focused tests, not implementation snapshots.

### 13.1 API client tests

Prove:

- 2xx JSON parsing;
- Problem Details -> `ApiError`;
- malformed error payload falls back safely;
- multipart request does not force a Content-Type header;
- abort signal is passed through.

### 13.2 Cameras page tests

At minimum:

1. list renders camera code/name/timezone/status;
2. required fields prevent invalid submit;
3. create sends expected JSON;
4. successful create invalidates/refetches list;
5. duplicate code shows conflict message;
6. submit is protected while pending.

### 13.3 Import page tests

At minimum:

1. only active cameras are selectable;
2. camera/date-time/file are required;
3. non-MP4 client rejection;
4. `recordingStartLocal` is sent as the local wall-time value, not converted to UTC;
5. successful import then process navigates to processing route;
6. import success + `processing_already_active` still navigates to processing;
7. import success + queue failure does not retry upload or claim import failure;
8. backend DST ambiguity/metadata errors render stable messages.

### 13.4 Processing page tests

Use a QueryClient with retries disabled.

At minimum:

1. direct route loads video + status;
2. Queued/Running states poll;
3. Completed/Processed stops polling;
4. Failed stops polling and shows failure code;
5. Retry queues a new run and resumes polling;
6. `processing_already_active` on retry refetches rather than failing terminally;
7. unknown video displays not-found state.

### 13.5 Router/shell test

Prove:

- `/` redirects to `/cameras`;
- navigation reaches Cameras and Import;
- deep link to `/processing/:videoAssetId` renders the processing page.

### 13.6 Backend contract test

Add focused integration coverage for the explicit `ProcessingStatusResponse` contract before writing frontend consumers.

---

## 14. Implementation sequence

The implementation shall proceed in controlled checkpoints.

### Checkpoint A — public processing contract

1. RED integration/contract tests for processing-status response.
2. Add public DTOs.
3. Explicit endpoint mapping.
4. Run focused .NET tests + build.

Do not start React processing-page code until this is green.

### Checkpoint B — frontend foundation

1. install router/query/testing dependencies;
2. add test setup;
3. implement `ApiError` + shared client;
4. add QueryClient/provider/router/shell;
5. migrate existing health/config fetches into query-based APIs;
6. run frontend tests/typecheck/build.

### Checkpoint C — Cameras

1. RED Cameras page tests;
2. implement camera API module;
3. implement list/create page;
4. verify validation/conflict/accessibility behavior;
5. run frontend gate.

### Checkpoint D — Import

1. RED import-flow tests;
2. implement video API module;
3. implement import form;
4. implement exact two-step import → queue flow;
5. prove partial-success handling;
6. run frontend gate.

### Checkpoint E — Processing

1. RED processing polling/retry tests;
2. implement page;
3. prove polling termination and retry semantics;
4. run frontend gate.

### Checkpoint F — subsystem audit

Before Codex review, inspect the complete Task-15 subsystem for sibling defects:

- route/deep-link correctness;
- stale cache behavior;
- duplicate mutation risk;
- POST retry behavior;
- multipart headers;
- local-time/timezone corruption;
- import/queue partial success;
- unbounded polling/retry;
- AbortSignal/unmount handling;
- malformed Problem Details;
- backend-internal field leakage;
- remote runtime assets;
- accessibility regressions;
- responsive layout;
- dependency/lockfile reproducibility.

Fix material defects before asking Codex to find them.

---

## 15. Files expected to change

Backend contract:

```text
src/platform/Mavi.Contracts/Api/Processing/ProcessingContracts.cs
src/platform/Mavi.Api/Endpoints/VideoEndpoints.cs
tests/Mavi.IntegrationTests/...processing-status contract tests...
```

Frontend:

```text
src/web/mavi-web/package.json
src/web/mavi-web/package-lock.json
src/web/mavi-web/src/main.tsx
src/web/mavi-web/src/App.tsx
src/web/mavi-web/src/app.css

src/web/mavi-web/src/app/AppProviders.tsx
src/web/mavi-web/src/app/AppShell.tsx
src/web/mavi-web/src/app/queryClient.ts
src/web/mavi-web/src/app/router.tsx

src/web/mavi-web/src/api/client.ts
src/web/mavi-web/src/api/cameras.ts
src/web/mavi-web/src/api/videos.ts

src/web/mavi-web/src/features/cameras/CamerasPage.tsx
src/web/mavi-web/src/features/video-import/VideoImportPage.tsx
src/web/mavi-web/src/features/processing/ProcessingPage.tsx

src/web/mavi-web/src/test/setup.ts
src/web/mavi-web/src/test/renderWithApp.tsx
focused *.test.ts / *.test.tsx files
```

Exact filenames may be adjusted to fit existing conventions, but responsibilities must remain separated.

---

## 16. Verification gates

Focused development gates:

```powershell
dotnet test tests/Mavi.IntegrationTests/Mavi.IntegrationTests.csproj --filter Processing
dotnet build MAVI.sln

cd src/web/mavi-web
npm test
npm run typecheck
npm run build
cd ../../..

python tools/verify_repo.py
```

Before merge, run the repository's normal MAVI Quality Gate on the exact frozen head.

Task 15 changes no vision runtime/model code. No Task-12 runtime lock, offline bundle, model manifest, or qualification metadata rebind is expected unless implementation unexpectedly changes runtime-bound files. If such files change, stop and apply the controlled freeze → generate → rebind → attest process rather than silently broadening Task 15.

---

## 17. Review and merge discipline

1. Branch from exact accepted integration head.
2. Keep backend contract hardening and frontend feature commits cohesive.
3. Do not create multiple competing implementation branches.
4. Run internal subsystem audit before external review.
5. Freeze exact head.
6. Run full quality gate.
7. Request one broad Codex Critical/P1/P2 review of the exact head.
8. Root-cause and remediate any material findings with focused regressions.
9. Re-run exact-head gates after every remediation.
10. Resolve stale review threads with remediation evidence.
11. Mark ready only when exact-head evidence is green and review-clean.
12. Merge with expected-head protection.
13. Verify the integration branch moved to the merge result.

---

## 18. Definition of done

Task 15 is complete only when all of the following are true:

- public processing-status contract is explicit and stable;
- Cameras list/create works from the browser;
- MP4 import preserves camera-local time semantics;
- successful import queues processing and deep-links to status;
- partial import/queue success cannot cause accidental re-upload;
- Processing page polls only while active and stops terminally;
- failed processing can be explicitly retried;
- direct page refresh/deep link works;
- server state is owned by TanStack Query;
- API failures retain stable backend codes;
- no storage/internal worker data leaks to React;
- no runtime Internet dependency is introduced;
- frontend tests, typecheck and build are green;
- .NET contract/integration tests are green;
- repository verification is green;
- exact-head quality gate is green;
- broad exact-head review has no material Critical/P1/P2 blocker.

Only then should the roadmap advance to Task 16.
