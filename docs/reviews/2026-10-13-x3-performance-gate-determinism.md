# X3 performance gate: determinism review (2026-10-13)

**Question.** The Quality Gate's *performance budgets* job failed on heads that
change nothing the product renders (main `cdb72a1a`, PR #213 `a7edc003`,
Markdown only), each time on a different case, and passed on rerun. Is the
measurement nondeterministic, and if so why — runner variance, a harness
defect, or the product?

**Answer (short).** The measurement is nondeterministic on identical bytes, and
runner variance is only the trigger. The CLS failures are **genuine,
order-dependent layout shifts in the product** that the harness samples by
chance; the long-task failures are a **harness batching artefact** (Import) and
**product rendering cost at the 50 ms threshold** (Scene Editor rename). The
budgets themselves were not changed and are not proposed for change here.

Raw evidence (per-repetition, per-case values, scripts) is outside Git at
`E:\MAVI-Working\tmp\perf-gate\` (`summary.md`); this record is the summary.

## Method

- Same bytes: the frontend tree of `06e16ec8`…`a7edc003` is identical
  (`src/web/mavi-web` tree `28311a0b`), and the measurement code
  (`settle.mjs`, `run.mjs`, `cdp.mjs`, `server.mjs`) is unchanged across them;
  every repetition below therefore measured identical frontend bytes. Local
  runs used one build of `cdb72a1a` (sha256 of `dist/` recorded), never rebuilt.
- GitHub: artefacts of every measured run since `88588bb8` were downloaded and
  re-judged with one budget table; the two control runs were rerun three times
  each (38356672232 attempts 2–4, 38357633829 attempts 3–5). Chromium
  154.0.8037.97 and image ubuntu-24.04 20261004.327.1 on every job.
- Local (Windows 11, Chrome 154.0.8037.98): two full ordinary sweeps and two
  long-task lanes; diagnostic runs with (a) a per-frame geometry timeline and
  long-animation-frame (LoAF) attribution, (b) the CI runner's resolved font
  (DejaVu Sans, from a local copy, injected as a font face — a labelled
  approximation of the Linux runner), and (c) fixture responses delayed or
  ordered on purpose (the controlled intervention).

## Observed

| Repetitions (same frontend bytes) | Failed | Failing case (value / limit) | Same case in every other repetition |
| --- | --- | --- | --- |
| 15 GitHub runs (`06e16ec8`…`a7edc003`, incl. 6 reruns) | 4 | `scene-editor-narrow-band@768x900` 0.0199/0.0102; `scene-editor-inactive@1024x768` 0.0126/0.0102; `shell-menu-overlay@761x900` 0.1621/0.0689; `import-long-identity@1366x768` 1×72 ms and `scene-editor-dirty@1366x768` 1×51 ms (class permits 0) | 0 (CLS) / no long task |

Every failing case passed on immediate repetition; the failing class and
surface moved between repetitions. 129 of 1730 navigation-CLS cases vary
across the GitHub repetitions (most within their limits); 100 vary between two
local sweeps of one build.

## Mechanism (controlled intervention, exact reproduction)

The fixture server answers instantly, so whether the page paints an
intermediate layout between two concurrent responses is left to scheduling.
Delaying one response deterministically reproduces each CI value **exactly**:

| CI failure | Intervention | Reproduced | Mechanism (frame timeline) |
| --- | --- | --- | --- |
| `shell-menu-overlay@761x900` 0.1621 | `/api/system/config` answered 150 ms after `/api/videos` | 0.1621, 4/4 | rows first paint with explicit-UTC timestamps (`2026-09-14T03:30:00Z UTC`); the folded cell wraps to two lines and the table is 735 px wide; when the display zone arrives (`14 Sept, 09:00`) row 1 loses a line and rows 2–4 move up 19 px |
| `scene-editor-inactive@1024x768` 0.0126; `scene-editor-narrow-band@768x900` 0.0199 | `/api/videos` answered after the scene | 0.0126 and 0.0199, 3/3 | the reference strip's region paints its 35 px loading line, then the 86 px strip; the inspector below moves down 51 px |

The opposite order gives 0 in every case. Under a pinned request-order
schedule (each data response in its own frame), the full ordinary sweep has
**63** navigation-CLS cases over their current limits (processing queue,
scene editor, videos, search, review, overview; triggers: display-zone config,
per-row processing lookups, camera metadata, the video list); a reversed
schedule adds 5 more. The budgets were calibrated on two Linux samples that
both took the common "everything in one frame" path.

## Long tasks (attribution)

- `import-long-identity` — **harness artefact**. The preparation dispatched
  the camera, time and file inputs back to back, so three operator inputs and
  the harness's own script ran as one task (LoAF: three React handlers in one
  frame, most of the frame unattributed script). Each input now runs in its own
  task a frame apart. Local, same bytes, 10 repetitions × 9 viewports: long
  tasks in 25/90 cases before, 3/90 after; the remaining three are single
  frames of 54–61 ms that are 41–47 ms style and layout (product rendering).
- `scene-editor-dirty` — **product rendering at the threshold**. LoAF: the
  rename's frame is 60–80 % style and layout, scripts 6–11 ms; on the local
  host 8/10 repetitions exceed 50 ms, on the CI lane 1/15. Under CPU
  throttling it scales with the CPU (it is the page's work, not GC or the
  runner).

## Harness changes (branch `fix/web-performance-gate-determinism`)

1. Import preparation: one operator input per task (above).
2. Attribution recorded with every measurement, never judged:
   `cls.responses` (data responses that landed in the window),
   `entries[].moves` (where each shifted source moved), `longTasks.frames`
   (long animation frames: scripts by entry point, style and layout).
3. `MAVI_VQA_RESPONSE_ORDER=forward`: pins the fixture server's data-response
   order (request order, 120 ms apart). Off by default; a pinned-order run
   records `responseOrder` and the gate faults it as evidence. On identical
   bytes, 8 repetitions × 34 cases: **natural** order varied in value for
   18/34 cases and flipped one classification under host load (0/34 when
   idle); **forward** varied in 0/34 classifications, and gave the scene
   editor's real shift (0.0126, 0.0200) every time.

No budget, tolerance or class was changed.

## Decision needed (owner)

Stable classifications on identical bytes need the response order to be fixed;
which order the gate judges is a decision about what the budget measures:

- **A (recommended).** Adopt `forward` in the gate and fix the product's
  order-dependent layouts (hold or reserve zone-dependent timestamps, the
  per-row run lookups, camera metadata and the reference strip). Strictest,
  deterministic, no budget change; the gate fails until the UI work lands.
- **B.** Adopt `forward` and recalibrate the budgets on it — a budget change
  needing quantitative approval (the 63 cases above).
- **C.** Keep `natural`: the gate stays stochastic on these surfaces.

A schedule that delivers all responses in one frame would make the gate
deterministic by hiding the late-data path; it is a relaxation and is not
proposed.

Labels: tables and reproductions are *observed*; "63 cases" is *observed*
under an approximate (Windows + injected DejaVu Sans) environment and is an
estimate of the Linux count; the attribution of residual long frames to
rendering is *derived* from LoAF.

## Owner decision: Option A, implemented

The owner chose **A**: response ordering is deterministic, the `forward` order
is the blocking lane, the product's order-dependent layouts are fixed by
drawing the final layout once (never by hiding the late answer), and a
`reverse` lane is added as the adversarial check. No budget, tolerance or
class was changed.

### Gate and harness

- The sweep shards and the long-task lane run with
  `MAVI_VQA_RESPONSE_ORDER=forward`; `performance.mjs` judges only results of
  that order (`GATE_RESPONSE_ORDER`) and faults any other.
- The sweep's ordinary cases run again in `reverse` order, in their own
  four-shard job (`performance-reverse`, beside the sweep);
  `performance` judges their CLS (`--ordinary-lane --response-order reverse`)
  against the same budgets, after the forward verdict.
- The fixture server answers pinned-order data GETs from a queue, one at a
  time and 120 ms from the previous send; `reverse` answers each burst
  (requests within 100 ms) in the opposite order. A document carries the epoch
  it was served in, and a request from a document the harness has left is
  refused: without this, a previous page's poll took the next case's first
  sequenced answer (`videos-row-degraded` unreached in 17 of 54 forward and 20
  of 54 reverse cases; 0 of 54 each after).

### Method correction (long tasks)

One genuine operator input per browser task: the Import preparation's three
inputs (accepted earlier) and the zone drawing's two vertex clicks, which are
two separate operator clicks (each click's pointerdown and pointerup stay in
one task). Recorded as a correction of the measurement's fidelity, not a
threshold change.

### Product fixes (drawn once, in the final layout)

| Surface | What moved, and why | Fix |
| --- | --- | --- |
| Videos, Processing queue | rows drawn with explicit-UTC timestamps and camera identifiers re-wrapped when the timezone and camera metadata landed | the ledger waits for both (`holdUntilSettled`), then is drawn once; per-row run lookups never hold it: a row whose lookup is out draws at once in its final geometry with unseen placeholders (§37.1; see owner ruling 3 below) |
| Scene Editor | the reference strip's one-line loading row grew to the strip and moved the inspector | the stage waits for the video list |
| Search | committed chips and rail re-wrapped for the timezone, camera and video names | the workspace waits for those answers |
| Processing detail | the run panel, its analytics and the camera-named facts landed in turn | the Record is drawn once per video (the shared layout hold), in its own layout instance |
| Overview | Recent tracks' empty answer pulled the stacked panel up | the panel reserves the skeleton's 8 rows in every state |
| Review | transport and rail re-wrapped for the timezone | evidence drawn once the timezone settles |
| Camera analytics | window band and stage re-wrapped for the timezone (reverse lane) | Workbench drawn once camera and timezone settle; the scene keeps its designed region |

During implementation (earlier heads of this branch; the final head's evidence
is under *Final evidence* below), forward-order full ordinary sweep (local, CI
font approximated): **49 → 0** cases over their limits (before → after); reverse: the five reverse-only
cases of the review's first reverse sweep → **0** (the last,
`analytics-enabled-empty-window@768x1024`, by the analytics fix).

### Scene Editor rename (metric and 50 ms threshold unchanged)

The rename re-rendered the whole stage. `SceneCanvas` is now memoised with a
geometry-stable draft (names and note excluded) and stable props, so a rename
renders no SVG, video or overlay. Traced during implementation (an earlier
head) at 3–4x CPU throttling, the rename
task's React script fell from ~65 ms to ~15–18 ms. Same bytes, 10 repetitions
× 2 viewports: at 3x, cases with a long task **8/20 → 0/20**; at 4x both still
exceed (median 70 → 67 ms at 1366, 65 → 60 ms at 1024): what remains is the
first dirty frame's style, layout and paint (the Context Bar gains its note
field, badges and actions).

## Owner rulings after the cold review

### Accepted trade-offs (only these two)

1. **Reverse lane: ordinary non-CLS findings are recorded, not gating.** The
   reverse shards run with `--keep`; their visual and accessibility findings are
   order-dependent evidence, uploaded, not a verdict. Their CLS is judged
   against the same budgets (`--ordinary-lane --response-order reverse`) and
   blocks; a reverse shard's harness fault, a missing shard, or a head or order
   mismatch fails closed.
2. **Zone drawing: one operator input per browser task.** The two vertex clicks
   are two separate operator clicks, so the long-task measurement runs them in
   two tasks. This corrects the measurement's fidelity to the real action; it
   is not a budget, threshold or class change.

### Fixes (not trade-offs)

3. **No first-load block for per-row lookups.** The ledger's hold covers only
   the camera and timezone answers; the drawn-once latch stays. A row whose run
   lookup is out draws at once with unseen placeholders shaped as its status
   predicts (queue: folded values, Tracks only for Processed; the status line's
   inline value, an active row's progress or a failed row's capped code; the
   Queued cell's dash over a timestamp of this year's shape drawn by CSS).
   Probed column widths and row heights, lookups held vs answered, are
   identical at 390/768/1024/1366/1920 (queue) and 1366/1024/768 (Videos).
   Tests: a slow lookup does not block any other row; the slow row holds its
   placeholders. Not zero everywhere: where a row's final run adds a line its
   status cannot predict, a small deterministic shift remains
   (at the final head: `videos-dense@1024x768` 0.0092 and `@768x1024` 0.0088,
   `videos-row-degraded@768x1024` 0.0088, against a limit of 0.0434; every
   queue row case ≤ 0.0017), the same in every run and inside its limit.
4. **Settle race.** The app registers its query client's activity (fetching,
   mutating) on the harness handle, only when the harness installed it.
   `settle()` treats any query still fetching or waiting out a retry's backoff
   (beyond the requests the server holds open on purpose) as unsettled, so CLS
   after the old `settledAt` is now inside the window. Proof: the
   `review-geometry-unavailable` live-region case and four other retry/failure
   states, forward, all lanes, ×3, at the commit that made the fix (`a9663526`):
   270/270 ok, 0 verdict changes; at the final head see *Final evidence*. Tests: a page
   in a 900 ms backoff with nothing in flight is not settled until its retry
   answers (fails without the fix); a held loading state still settles.
5. **Review media.** Correction: the Review fixtures already declared the clip's
   real duration (4000 ms for the 4 s clips); this record's earlier "declared
   10 min" was wrong (that is the Videos inventory's record). What moved Review
   was artifact content (`/api/artifacts/{id}/content`, trajectories and
   crops), which the harness treated as media: neither counted for settling
   nor ordered. Only a video stream is media now; artifact content is ordered
   like any answer. `EvidencePlayer` lays its timeline out on the declared
   duration (the element's only where none is declared), so the rail never
   re-lays out when media metadata lands. Test: the marker's position is
   unchanged when the element reports another duration (fails without it).

### Known follow-up (not in this change): focus after Process

After **Process** on a Videos row, the button leaves with the row's new status
and focus falls to the document body: a keyboard-accessibility defect that
predates this change. It is left out of #216. No regression: the same probe
(render Videos, Process a NotQueued row, wait for Queued, read
`document.activeElement`) run unchanged on `main@4150f96b` and on this branch (`3daab274`)
gives `BODY` on both.

## Owner direct code review of `991a4aa1`: corrections

| Finding | Disposition |
| --- | --- |
| **P1** — the query-activity hook against UI spec §26 ("MUST NOT require production code to be altered") | Fixed (`45c4570c`). §26 amended narrowly (specification v2.2; ADR-012 Decision 14): a harness-only passive observability hook is permitted only when dormant in normal operation, payload-free (counts and flags), unable to alter rendering, query configuration or scheduling, and activated only by the harness preinstalling its handle. `registerHarnessObservability` (`app/harnessObservability.ts`) is exactly that: one read-only function returning a frozen `{fetching, mutating}`, registered only on a preinstalled `window.__vqa`. A contract test binds the four conditions (dormant without the handle, AppProviders included; counts only; defaults, query state, `queryFn` calls and cache listeners unchanged; same render count with and without the handle; no write call into the client). Not a test API. |
| **P2** — page-local layout latches outlive a same-route identity change | Fixed (`95fde4c6`). One shared primitive (`shared/async/layoutHold.ts`: `useLayoutHold`, `useHeldState`) reads settledness from the normalised AsyncState boundary (`fromQuery`) and resets on the surface's identity. Analytics (per camera), Processing detail (per video), Search, Videos and the Processing queue use it; a guard test fails on any page-local latch. Same-route identity-change tests on Analytics and Processing hold the new record until its own answers settle (both fail on the previous code). |
| **P2** — pinned-response scheduler state survives `resetSequences()` | Fixed (`bf9a0303`). `createResponseScheduler`: one generation per case; a reset cancels every timer of the generation, drops its queue and any burst being gathered (refusing their requests), and opens a fresh generation. Virtual-clock test: pending forward entries and a pending reverse burst (gathering, and released but unsent), reset at once, next case: order and timing equal a fresh server's, no old timer remains (3 of its 4 tests fail with the previous reset). |
| **P2** — CI timeout envelope (sweep and reverse lane in one 45-minute job) | Fixed (`fb7d59f3`). The reverse lane is its own four-shard job, `performance-reverse` (20-minute step in a 45-minute envelope, same shard count as the sweep), in parallel with the sweep, whose job is back to its 25-minute step in 45 minutes. Neither lane's coverage changed. |
| **CI** `python vision`: `test_the_quality_aggregate_accounts_for_every_lane` (`continue-on-error` in `quality-gate.yml`) | Fixed by the restructure (`fb7d59f3`): no `continue-on-error`; a reverse harness fault fails `performance-reverse`, which `quality` requires; `performance` runs `always() &&` its scope with its inputs not cancelled or skipped, and still fails closed on a missing shard, head or order. `test_every_sharded_job_runs_every_shard_index_exactly_once` registers the new sharded job; a new test binds the lane to the sweep's shard count, the judge's count, its order and `--keep`. |
| **CI** `qualification shard 2`: `test_s1_evidence.py` (`assert 4 == 3` evidence uploads) | Fixed (`fb7d59f3`): the reverse shard upload is classified with the performance evidence it is (expiring, outside `qualification-evidence/`), so there are 3 performance uploads and the canonical evidence uploads stay 3. The expectation changed because the structure has one more performance evidence upload, not to silence the test. |

Also in this round (`dfb1f873`): two settle-timing harness tests asserted an
elapsed-time proxy measured from `settle()` that a loaded host breaks (the
backoff and the transition begin while the page loads); they now assert the
property on the page's clock (the confirming probe came after the retry
answered / the transition ended). The retry test still fails with the
query-activity check disabled.

## Final evidence (code head `dfb1f873`)

**Head relationship.** All evidence below was produced from the code head
`dfb1f873aa1721d457e041d5c10cca3a7a42a758`, with a clean working tree. The
commit that adds this section is documentation only (this file): it changes
nothing the evidence measured, and a commit cannot name its own SHA. The sweeps
ran on a measurement copy of that head's `src/web/mavi-web/src` and
`tools/web-visual-qa`, identical to it except for the local CI-font emulation
injected into `run.mjs` (production bundle `d241f7b04105d527`); their result
files therefore carry the copy's own Git head, not `dfb1f873`.

Local, Windows host, CI font approximated (DejaVu Sans injected, a labelled
approximation of the Linux runner). With that emulation every case has a
`typography.resolved-font` finding (the injected face is not the platform's):
the emulation's artefact, excluded from the counts below. No other process ran
beside these runs.

| Run | Order | Scope | Cases (unreached) | CLS over limit | Long tasks | Harness faults | Other blocking findings |
| --- | --- | --- | --- | --- | --- | --- | --- |
| FV2: sweep + long-task lane, judged | forward | full sweep, all lanes; long-task lane | 3800 (0); 417 (0) | 0 of 1836 | 0 of 413 interactions with a long task (413 pass) | 0 | 0 |
| RV5: 4 reverse shards, judged `--ordinary-lane --response-order reverse` | reverse | ordinary sweep | 1847 (0) | 0 of 1836 | — | 0 | 0 |
| F8, F9 | forward | ordinary sweep | 1847 (0) each | 0, 0 | — | 0, 0 | 0, 0 |

Stability, FV2 + F8 + F9 on identical bytes: 1836 case-families measured in
all three; **0 classification changes**, 0 ever over a limit; 9 vary in value,
all inside their limits (largest: `review-long-identity@2560x1440` 0.0065 /
0.0017 / 0.0017 on 0.0085; the other eight move by ≤ 0.0005).

Other checks at `dfb1f873`: frontend tests 1595/1595 (86 files); harness unit
tests 359/359 three times; harness end-to-end 110/110; keyboard journeys 18/18;
`src/vision/tests/test_runtime_metadata.py`,
`tools/qualification/tests/test_s1_evidence.py` and
`tools/ci/tests/test_quality_scope.py` 679/679; `verify_repo` PASSED.
