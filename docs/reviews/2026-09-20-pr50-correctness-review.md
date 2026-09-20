# PR #50 — Correctness Review, Fixes and Workflow Evidence

**Date:** 2026-09-20  
**Repository:** `hariomahlawat/MAVI`  
**Pull request:** #50 `feature/visual-intelligence-workspace` → `main@0225779`  
**Reviewed code head:** `63860a4` (the commit adding this document carries documentation and the development harness only)  
**Posture:** each finding below was verified against the code before a regression test was written; every test failed on the pre-fix code and passes after.

## 1. Findings and fixes

| # | Finding (verified) | Fix | Regression tests |
|---|---|---|---|
| 1 | `TrackEvidencePlayer` attached `onStop` (cancel frame loop) to `timeupdate`, and a second `play`/`playing` started a second loop. During playback the overlay degraded to ~250 ms `timeupdate` granularity a moment after play. | One loop per media element: `play`/`playing` restart it (cancelling any previous handle), `pause`/`ended`/`emptied` stop it, `seeked` and `timeupdate` only publish the position, source replacement (keyed `<video>`) and unmount clean up. | `TrackEvidencePlayer.lifecycle.test.tsx` (4 tests: single loop through timeupdate/seek/duplicate play; stop on pause and end; source replacement and unmount; no frames while paused). |
| 2 | The near-end prefetch effect re-fired after every failed `fetchNextPage` (its dependencies flipped), producing unbounded automatic retries; `goNext` also refetched after errors. | Automatic continuation only while `!isFetchNextPageError`. Transient failure → "Retry load more" (explicit); `track_search_invalid` → "Refresh results" (new snapshot). The query's single 5xx retry is the only automatic retry. | `VisualSearchPage.pagination.test.tsx`: "stops automatic pagination after a transient continuation failure" (asserts exactly 3 calls: page 1, page 2, one retry), "requires an explicit refresh after the snapshot expires". |
| 3 | `goNext` past the last row chained `.then` on `fetchNextPage()` and selected the first item of the last page regardless of what changed meanwhile. In practice the path was mostly unreachable (the prefetch was already in flight, so `goNext` returned), meaning "Next" at the end did nothing. | Replaced with a pending-advance record `{fingerprint, fromId}` honoured by an effect only when the page lands for the same committed search with the same selection; discarded on filter change, selection change, inspector close (`selectTrack(null)`), error or unmount. | Same file: "advances onto the next page when it lands" (failed before: nothing happened), plus four guard tests (filters changed, selection changed, inspector closed, unmounted). |
| 4 | Review links carried only `trackId`; "Back to search" rebuilt `/search?videoAssetId=…&track=…`, discarding the committed filters. | Review links carry `from=<canonical committed query>&track=<id>`. `returnToSearchPath` accepts only a value that re-parses as a valid committed search (plus one GUID `track`); otherwise, including direct links and refreshes without it, it falls back to the video scope. The result snapshot is re-run on return, not resumed. | `VideoReviewPage.test.tsx` "return navigation" (exact context, fallback, malformed rejected); `VisualSearchPage.pagination.test.tsx` "carries the committed search context into the full review link and back". |
| 5 | Processing queue described itself as run history ("N videos with processing history", "Queue, running and completed processing runs") while the API returns the latest run per video; a failed per-video status request showed "Loading run…" forever. | Labels now say "Latest run per video … Earlier runs of a video are not listed here". `useVideoProcessing` exposes per-video errors and `retry(id)`; the queue and Videos rows show "Run status unavailable / Live status unavailable" with Retry. Panels no longer say "Loading…" or show zero counts when the inventory request failed. | `ProcessingQueuePage.test.tsx`: label test, per-video failure + retry test, inventory-failure test. |
| 6 | `GetStatusAsync` had only a contract-mapping test with a stub view. | Database-backed tests seed two completed runs and a running run and assert the projection reads `FramesProcessed`/`TracksCreated` from the persisted latest run, and reports zero while a run is running. The mapping test is retained. | `tests/Mavi.IntegrationTests/ProcessingStatusPersistenceTests.cs` (2 tests), `Task15ApiContractTests.ProcessingStatusMapsOnlyThePublicContract` (retained). |
| 7 | When counters become authoritative: `ProcessingRun.MarkCompletedCore` is the only writer of `FramesProcessed`/`TracksCreated`; heartbeats update `VisionJob.ProgressPercent` only. The overnight UI showed frames for `Running` runs as if live. | Counts are shown only for `Completed` runs; otherwise the cell reads "Final count after completion". Live progress remains `progressPercent`. | `ProcessingPage.test.tsx` "shows frame and Track counts only once a run has completed". |

Two further defects were found only by exercising the real stack in Chromium (section 3) and fixed in `63860a4`:

| # | Finding | Fix | Tests |
|---|---|---|---|
| 8 | The row select button used `display: contents`; Chromium drops such elements from the accessibility tree, so result rows had no accessible button (jsdom and axe-core did not detect this). | Button is a real grid box inside the row. | Covered by the real-browser run below; existing role-based unit tests continue to pass. |
| 9 | After clicking a row the select button keeps focus, so Enter re-selected the row instead of opening the review as the on-screen hint promises. | Enter on the focused select button of the selected row opens the review; Enter on other controls is untouched. | `VisualSearchPage.pagination.test.tsx`: "opens the full review on Enter while the selected row button still has focus", "leaves Enter alone on other controls". |

Adjacent paths reviewed for the same causes: the Overview recent-track links (no navigation state, unaffected); the per-video Processing page (already surfaces `processing.isError`); the Videos page (now surfaces per-video status errors and no longer says "Loading…" on failure).

## 2. Automated validation (executed here)

| Check | Result |
|---|---|
| `npm test` | 161 passed, 26 files (was 140) |
| `npm run typecheck`, `npm run build` | clean |
| `dotnet build MAVI.sln -c Release` | 0 errors |
| `dotnet test` Application / Domain | 109 / 77 passed |
| `dotnet test tests/Mavi.IntegrationTests` against local PostgreSQL 16 + pgvector 0.6.0 | 260 passed, 2 failed: `DatabaseStartupMigrationTests.*` fail only on the intentional `MAVI requires PostgreSQL 18` gate (environment, not code); these pass in CI, which provisions PostgreSQL 18 |
| `tools/verify_repo.py` (repository virtualenv) | passed |
| CI on `d1e0a4c` | quality, deterministic-validation, windows-script-validation green; CI on `63860a4` pending at time of writing |

## 3. Real API + PostgreSQL workflow evidence (executed here)

This is Development evidence on a Linux container, not Production qualification, and it is distinct from the mocked-API screenshots and axe scan recorded in the workspace document.

Stack: `Mavi.Api` (Release build, `dotnet run`, Development environment) → PostgreSQL 16.15 with pgvector 0.6.0 on `127.0.0.1:5432` → Vite dev server on `127.0.0.1:5173` proxying `/api`. Configuration deviations, all disclosed: `DatabasePrerequisites:RequiredPostgreSqlMajorVersion=16` (no PostgreSQL 18 available here), `MediaProcessing:AllowPathFallbackInDevelopment=true` (system FFmpeg 6.x rather than the bundled kit), media/evidence roots under `/tmp`.

Recorded media: a 12 s, 640×360, 25 fps H.264 MP4 generated with FFmpeg (`testsrc2` background with a white box moving 30 px/s), 300 frames.

Vision processing: the qualified RTMDet/ByteTrack runtime bundle is not available on this host (no Torch), so the run was completed by `tools/vision/dev/fixture_worker_harness.py`, which drives the **real** worker control plane (`WorkerApiClient`/`WorkerRunner`: lease → heartbeat → complete, real completion contract, real evidence staging and sealing) with the repository's deterministic `FixtureDetector`/`FixtureTracker`. Its provenance is labelled `fixture-detector` / `unverified`. The first completion attempt was rejected by the API (`vision_result_invalid`: provenance lacked the mandatory `trackers` dependency version), which is the contract behaving correctly; attempt 2 completed.

Observed, in order, through the real UI in headless Chromium:

1. Cameras → "Add camera" (CAM-E2E-01, Asia/Kolkata) → "Camera registered."
2. Import → camera, recording local time 2026-09-19 08:30, MP4 upload → redirected to `/processing/<video>`; run `Queued`, attempt 0, counters read "Final count after completion".
3. Worker run: lease 200, heartbeat 200 (`Running`, 1 %), complete 200 → status `Processed`, latest run `Completed`, attempt 2, `framesProcessed` 300, `tracksCreated` 2.
4. Processing detail shows "Frames processed 300"; the queue shows "Latest run per video" with the completed run and Tracks = 2.
5. Videos → `Results` → `/search?videoAssetId=<video>` lists 2 Tracks (Vehicle 4–8 s, 101 detections, 82.0 %; Person 2–10 s, 201 detections, 89.7 %) with representative thumbnails served from `/api/artifacts/{id}/content`.
6. Select row → inspector "Vehicle · Track 2", bounding box and trajectory overlay drawn from persisted evidence; `j` → "Person · Track 1"; `k` back.
7. Enter → `/review/video/<video>?trackId=<track>&from=videoAssetId%3D<video>%26track%3D<track>`; "Back to search" returned to the identical search URL. A direct link without `from` produced the fallback `/search?videoAssetId=<video>&track=<track>`.
8. Error path: PostgreSQL stopped → Processing queue showed the API error alert ("The request could not be completed. (api_error)"), and with the fix in `63860a4` the panel reads "Unavailable" with "—" counts; PostgreSQL restarted → reload showed the table again.
9. `GET /api/videos/<id>/content` → 200 `video/mp4`; with `Range: bytes=0-1023` → 206, 1024 bytes.

Not observed here: in-browser playback of the H.264 source (headless Chromium has no H.264 decoder, so the player showed "Source video could not be loaded from the evidence API." while the range endpoint served correctly); the per-video status failure with retry against the real API (the outage failed the inventory request first; that path is covered by the component test).

## 4. Checks that require the development laptop

One consolidated procedure; each step names what it proves.

1. `Setup-MAVI-Development.cmd` (PostgreSQL 18 + pgvector, bundled FFmpeg). Run `dotnet test tests/Mavi.IntegrationTests` with the machine `MAVI_TEST_DB_CONNECTION`: proves the two `DatabaseStartupMigrationTests` that this container could not (PostgreSQL 18 gate).
2. Start `Mavi.Api` from Visual Studio and `Start-MAVI-Vision-Worker.cmd` with the Task-12 CPU runtime bundle: proves RTMDet/ByteTrack completion of a real recording through the same control plane the harness used.
3. Import a real CCTV MP4 (H.264) via Import; wait for `Processed`; open Videos → Results → select → inspector → Enter → Back to search: proves in-browser H.264 playback, seek to one second before Track start, and overlay alignment on real footage. Toggle the sidebar collapse and the list/grid view while doing so.
4. Stop the MAVI PostgreSQL service while the Processing queue is open with several processed videos, then start it and press Retry on a row: proves the per-video "Run status unavailable → Retry" path against the real API.
5. Optional: run `tools/vision/dev/fixture_worker_harness.py` against the laptop API to reproduce section 3 without the runtime bundle.

## 5. Remaining limitations

- Review status is display-only; there is no mutation API (planned in `docs/superpowers/plans/2026-09-20-audited-review-and-cases-plan.md`).
- The processing status API exposes the latest run per video only; a paginated historical-runs endpoint remains a separate task.
- Returning from Review re-runs the committed search; the previous cursor snapshot is not resumed, and a Track selected from a later page may show position "— / n" until that page loads.
- The fixture harness is a Development convenience and produces no model or qualification evidence.
