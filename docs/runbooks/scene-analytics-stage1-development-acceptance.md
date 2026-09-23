# Scene Analytics Stage 1 — Development-machine acceptance actions

**Purpose:** the exact operator actions that close the Stage-1 exit-gate items which can only be executed on the Development machine (plan `docs/superpowers/plans/2026-09-22-scene-analytics-s7-hardening-acceptance.md` §25 items 4a, 7/12/18, 13 and 14). Each action states its command, what it must show, and where its result is recorded. Nothing here is Production qualification (Task 18).

Run from a clean checkout of the PR #70 head on the Windows Development machine (PostgreSQL 18.6 on the canonical MAVI Development service at port **55433**, live database `mavi_dev`), using the normal `Setup-MAVI-Development.cmd` environment. Every tool used is repository-local and standard-library only; none adds a dependency.

Record each result in `docs/reviews/2026-09-22-scene-analytics-stage1-acceptance.md` under *Development-machine actions*. Do not record a PASS for an action that was not run.

---

## A. Aggregate-materialisation P2 — transcribe the authoritative §T figures (items 7, 12, 18)

The authoritative `plan-qualification.json` (SHA `5f5166628b0c4af04cc8f7efcd40f7022f5095c4`, held outside the repository) already contains every figure the decision needs.

```powershell
python tools\qualification\summarize_aggregate_qualification.py <path>\plan-qualification.json
```

It prints the file's SHA-256, its verdict status, its provenance and the nine §T rows (rows materialised per fact family, database ms, application ms, total ms, allocated MiB, GC collections, database query count) as Markdown. **Exit code 1 means the file is not qualification evidence**; do not transcribe such a file as authoritative.

Paste the output into the performance report §8.3. Then apply the decision rule recorded in the security review (§1, *Decision rule*), which was written before these figures were seen.

## B. Development-corpus analytical-unit duration and rows (item 4a)

After the real-worker units have completed:

```powershell
psql -h 127.0.0.1 -p 55433 -U <user> -d mavi_dev -x -f tools\qualification\development-unit-record.sql
```

One record per analytical unit: identity, attempt, final-attempt duration (claim to fenced commit), analysed/unavailable counts, rows written per fact table and trajectory samples. **Pass criterion:** every Development-corpus unit is `Completed`, `unavailable_track_count` is explained (0 for the scripted videos), and `outcomes = analysed + unavailable`. Record the rows as item 4a.

## C. The three scripted videos through the real worker path (item 14)

Parent plan §Z: three short FFmpeg-scripted videos — line crossing, zone dwell then exit, stationary then depart — through the real worker control plane with the fixture detector, and through the real analytics host, with expected facts derived from the scripted motion.

The single source of truth is `tests/fixtures/scene-analytics/scripted-corpus-v1.json`. Its expected facts are already proved against the real engine by `ScriptedCorpusTests` in the ordinary suite; this action proves the worker path.

1. **Generate and verify the videos** (FFmpeg is a Development prerequisite):

   ```powershell
   python tools\vision\dev\scripted_corpus.py generate <out-dir>
   python tools\vision\dev\scripted_corpus.py verify <out-dir>\scripted-line-crossing.mp4 line-crossing
   python tools\vision\dev\scripted_corpus.py verify <out-dir>\scripted-zone-dwell-exit.mp4 zone-dwell-exit
   python tools\vision\dev\scripted_corpus.py verify <out-dir>\scripted-stationary-then-depart.mp4 stationary-then-depart
   ```

   Each `verify` must print `ok`: every one of 300 frames decoded, and the drawn box exactly at the position model on each detection frame and absent elsewhere. The videos are generated, never committed.

2. **One camera per scenario** — create three cameras (for example `SCR-LINE`, `SCR-ZONE`, `SCR-STILL`) in the UI, then save each scenario's exact geometry through the scene API:

   ```powershell
   python tools\vision\dev\scripted_corpus.py apply-scene http://localhost:<api-port> <camera-id> line-crossing
   ```

   (repeat with `zone-dwell-exit` and `stationary-then-depart` for their cameras).

3. **Import** each video to its camera through the UI.

4. **Process with the fixture detector** — for each queued run, in turn:

   ```powershell
   $env:MAVI_API_BASE_URL = "http://localhost:<api-port>"
   $env:MAVI_WORKER_ID = "fixture-worker-01"
   $env:MAVI_MEDIA_ROOT = "<MediaStorage:RootPath>"
   $env:MAVI_FIXTURE_SCENARIO = "line-crossing"   # the scenario of the run being leased
   python tools\vision\dev\fixture_worker_harness.py
   ```

   Exit code 0 means one job was leased and completed. The provenance is labelled `fixture-detector` / `unverified`, as it must be.

5. **Analyse** — let the analytics host analyse each run, or queue it explicitly from Processing, and wait for **Analysed**.

6. **Check the facts** — take the Track id from Search or Evidence Review:

   ```powershell
   python tools\vision\dev\scripted_corpus.py check http://localhost:<api-port> <track-id> line-crossing
   ```

   Must print `ok`. It reads the Track detail and its pinned scene revision from the API and asserts: status `Analysed` against the scenario's revision, 250 samples, the zone visits with entry/exit/dwell brackets, loitering, the line crossings with direction and offset bracket, the heading, and the stationary intervals.

7. **Look at the evidence** in Evidence Review for each Track: the overlays follow the box, the explanation names the expected zone, line, direction and stationary interval.

## D. Runtime identity and no undeclared fetch (item 14)

1. **Runtime identity** of the real-worker runs:

   ```powershell
   psql -h 127.0.0.1 -p 55433 -U <user> -d mavi_dev -x -f tools\qualification\development-run-identity.sql
   ```

   Prints, per completed run, the detector/tracker identity and the whole persisted runtime-provenance document: model and checkpoint digests, pipeline and runtime profiles, runtime variant, platform lock, qualification identity, configured and actual device with its resolution reason, dependency versions, GPU and the MAVI build and commit. Record the `2min.mp4` run's document as the real-worker runtime identity.

2. **No undeclared Internet fetch** — the Development acceptance must survive with the machine disconnected:

   - disconnect the network (disable the adapters or enable airplane mode);
   - restart `Mavi.Api` and the worker;
   - repeat action C for one scripted video end to end, then open Evidence Review, Analytics Activity and Heatmap for it;
   - with the browser's developer tools open on the Network panel, confirm every request is to the local MAVI origin.

   **Pass criterion:** the whole path completes while disconnected, and the Network panel shows no request to any other origin. Any failure that names a remote host is an undeclared dependency and fails item 14.

## E. The Search → Investigation leg on real data (item 13)

On the Development machine, for the `2min.mp4` camera: open Search, apply an analytics filter that the real facts satisfy (`Zone 1`, relation *Dwelled*), confirm the result list contains the analysed Tracks with coverage *complete*, open one in the Investigation inspector and follow it to Evidence Review. **Pass criterion:** the Track, its facts and its revision identity agree between Search, the inspector and Evidence Review.

## F. PostgreSQL restart and reconnect (plan §11)

With `Mavi.Api` running, restart the PostgreSQL 18 service, wait for it to come back, and repeat an Analytics Activity and a Heatmap request. **Pass criterion:** the requests fail cleanly while the database is down (no partial answer, no leaked detail) and succeed with the same answer once it is back, without restarting `Mavi.Api`.
