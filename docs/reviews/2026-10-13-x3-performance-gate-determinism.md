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
