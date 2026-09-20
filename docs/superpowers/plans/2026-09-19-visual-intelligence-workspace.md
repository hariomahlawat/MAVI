# Visual Intelligence Search & Review Workspace

**Date:** 2026-09-19  
**Base:** `main@0225779` (PR #48 merge)  
**Branch:** `feature/visual-intelligence-workspace`  
**Objective:** turn the Task-15/16 React foundation into a complete operator workflow: know what media exists and where it is in processing, search authoritative Tracks, and review the evidence for a Track without leaving the search context.

This is product-feature work on the operator plane. It consumes the Task-14/15 APIs as published and does not change qualification semantics, checkpoint validation, device policy or anything on the Windows CUDA qualification branch (PR #49), which remains frozen and intact.

## Delivered capability

### Shell and navigation

- Collapsible left sidebar (Overview, Cameras, Videos, Import, Processing, Search) with a compact top bar and an API health indicator. Collapse state is a per-browser preference.
- Routes: `/` Overview, `/cameras`, `/videos`, `/import`, `/processing` (queue), `/processing/:videoAssetId` (per-video detail), `/search`, `/review/video/:videoAssetId?trackId=…`, and a not-found page.

### Processing workflow

- **Overview** answers "what do we have" at a glance: counts by processing status, the newest Tracks, and a media-by-status breakdown, all linking into the relevant page.
- **Videos** is the media inventory: every imported video with camera, recording time in the configured display zone, duration, status, live progress for active runs, the failure code for failed runs, and one action per state (Results for processed, Process/Retry for not-queued/failed, processing detail for all). Filters (`q`, `cameraId`, `status`) live in the URL.
- **Processing** lists the **latest run of every video that has one**, in queue order (active, failed, completed) with progress, worker, attempt and, for completed runs, the final Track count. Earlier runs of a video are not listed; a paginated historical-runs endpoint is a separate task. A per-video status failure is shown as "Run status unavailable" with Retry. The per-video page shows the same numbers and keeps diagnostics (identifiers, pipeline version) behind a disclosure.
- The processing status API now carries `framesProcessed` and `tracksCreated` from the persisted run (`ProcessingRunStatusResponse`). The domain sets both only in `ProcessingRun.MarkCompleted`, so the UI shows them for completed runs only ("Final count after completion" otherwise); live progress is `progressPercent` from the vision job heartbeat.

### Search workspace (`/search`)

- Three panes: committed filters (camera, video, object class, from/to in the configured display zone, minimum duration, minimum confidence), the result snapshot as a dense list or thumbnail grid, and an in-place inspector for the selected Track.
- Filter semantics are unchanged from Task 16: the URL is the source of truth, filters are canonicalised on commit, cursor pagination stays inside one backend snapshot, and unknown parameters are dropped on commit.
- Selection is the `track` URL parameter, so a deep link reopens the same view. Committing new filters clears the selection.
- Review links carry the canonical committed search as `from`; the Review page's "Back to search" returns to exactly that search with the Track selected, falls back to the Track's video scope on a direct link or refresh, and rejects a malformed value. The committed filters are restored exactly; the result snapshot is re-run, not resumed.
- Keyboard: `j`/`k` or arrow keys step through results, `Enter` opens the full review (also when the selected row's button has focus), `Esc` closes the inspector. Stepping past the last loaded row requests the next page of the same snapshot and advances onto it only if the same search and selection are still current when it lands; the page ahead is prefetched while continuation succeeds. After a failed continuation nothing retries automatically: a transient failure offers "Retry load more", an expired snapshot offers "Refresh results".

### Evidence review

- `TrackEvidencePlayer` is shared by the inspector and the Review page: the source video seeks to one second before Track start, a timeline shows the Track interval, the representative frame marker and the playhead, and Start/Evidence/End controls jump the playhead. Exactly one frame loop tracks the playhead while playing; pause, end, source replacement and unmount stop it, and seeks or `timeupdate` only publish the position.
- An SVG overlay draws the persisted representative bounding box (only within 400 ms of its frame, because that is the only frame the detector asserted it for) and the persisted trajectory polyline with the interpolated current centre. Geometry follows `object-fit: contain` letterboxing.
- Trajectory artefacts are fetched through `/api/artifacts/{id}/content` (8 MiB cap) and decoded by a small in-repo MessagePack reader that accepts only the value types the worker emits. The parser mirrors the worker's validation (version 1, strictly increasing offsets).
- Provenance (run, pipeline, detector, tracker) moved to secondary details; the runtime attestation of the producing run loads lazily from `/api/processing/runs/{id}/attestation`.

### Design system

- Tokens in `src/web/mavi-web/src/styles/tokens.css` (surfaces, text, accent, semantic status colours, evidence overlay colours, 4 px spacing scale, radii, control heights, type scale) with `base`, `layout`, `components` and `features` stylesheets. No UI framework was added.
- Shared primitives: `Button`/`ButtonLink`, `Icon`, `Panel`, `StatusBadge`, `Alert`, `EmptyState`, `KeyValue`, `Progress`, `Tabs`, `LoadingState`, `PageHeader`. One status vocabulary (`shared/status/status.ts`) decides tone and label for video, run and review statuses.
- Accessibility: result rows are list items with a select button and a review link as sibling controls (no nested interactive content), icon-only controls carry accessible names, status is never colour-only, muted text and primary buttons meet WCAG AA contrast, focus rings are explicit, reduced motion is honoured. An axe-core scan (wcag2a/aa + best-practice) of every page reports no violations.

## Decisions

- **No new npm dependency.** The offline dependency kit pins `package-lock.json`; a ~150-line MessagePack decoder was cheaper than re-qualifying the kit.
- **Selection in the URL, not component state.** Deep links and back-navigation from Review work without warm cache, in line with the Task-16 reconstruction rule.
- **Bounding box shown only near its frame.** Drawing the representative box across the whole Track would claim positions the detector never asserted; the trajectory carries the motion instead.
- **Frames/Tracks counts come from the API.** The UI does not infer processing progress from anything but the persisted run.

## Limitations

- Review status (Unreviewed/Confirmed/Rejected) is display-only; there is no mutation API yet.
- Search filters are exactly the Task-14 public contract; there is no free-text or semantic search.
- The Processing queue shows the latest run per video by reading the per-video status endpoint (shared cache with the Videos page); a paginated historical-runs endpoint would both list earlier runs and remove the fan-out when the inventory grows large.
- The fixture worker harness under `tools/vision/dev/` is a Development convenience for hosts without the runtime bundle; it produces no model or qualification evidence.

## Validation

- `npm test` (161 tests), `npm run typecheck`, `npm run build` in `src/web/mavi-web`.
- `dotnet build MAVI.sln -c Release`, `dotnet test tests/Mavi.Application.Tests`, `dotnet test tests/Mavi.Domain.Tests`; `dotnet test tests/Mavi.IntegrationTests` against PostgreSQL (CI: PostgreSQL 18; locally here: PostgreSQL 16, where only the intentional version-gate tests fail).
- `python tools/verify_repo.py` (project virtualenv).
- Mocked-API screenshots and an axe-core scan (no violations) — UI evidence only.
- Real API + PostgreSQL workflow (camera → import → control-plane completion → search → inspector → review → return → outage/recovery) recorded in `docs/reviews/2026-09-20-pr50-correctness-review.md`, with the checks that still need the development laptop listed there.

## Recommended next feature

Review-status mutation: a small `PATCH /api/tracks/{id}/review` with an audit record, surfaced as Confirm/Reject actions in the inspector and Review page, so the search workspace becomes a complete triage loop.
