# MAVI Stage 2 — S1.4 U1: truthful Finalizing / failed-finalization UI

**Status:** execution-grade implementation plan. **Planning only:** nothing here is implemented.
**Base:** `main@9f9163f8ed22eb0f42dd90322d09cd711248400b`.
**Governing:**
- F4 execution plan `2026-09-25-s1-4-f4-m1-to-m2-execution-plan.md` §10 (U1), §13 Gate B;
- F4 master plan `2026-09-25-s1-4-b3-f4-qualification-closure-implementation.md` §6, §6.1 (U1 row), §15.3, §24 (U1);
- `docs/architecture/ui-ux-design-specification.md` §8.2, §14, §16, §23, §26;
- the runbook's asynchronous-finalization section.

**Sequence position:**
- M1 exploration is complete (Linux activation gate passed; freeze decision in review).
- U1 lands **before** F4-C, as a separate reviewed web-only PR, merged with a merge commit.
- F4-C's merge commit, whose ancestry contains U1, is M2 (execution plan §14).
- U1 invalidates B5 and DISCONNECTED, which is absorbed because M2 follows it (master §6).

---

## 1. Current-state findings (surveyed at `9f9163f`)

### 1.1 Where the truth enters the frontend

- **Type:** `src/web/mavi-web/src/api/videos.ts`. `ProcessingRunStatus` carries `status` (the run's `ProcessingRunStatus`), `failureCode: string | null` and `phase: ProcessingPhase`, where `PROCESSING_PHASES = ['queued','processing','finalizing','completed','failed']`. The doc comment already states the rule: "the run's own `status` stays `Running` until publication".
- **Fetch:** `getProcessingStatus(id)` returns `ProcessingStatus = { videoStatus, latestRun }`.
- **Detail page:** `ProcessingPage` uses it directly.
- **Ledgers:** `ProcessingQueuePage` and `VideosPage` read it through `features/videos/useVideoProcessing.ts`, one query per video on the shared cache key.
- **Polling:** `isProcessingActive` in `api/videos.ts` polls while `latestRun.status` is `Queued` or `Running`. A Finalizing run is `Running`, so the page keeps polling until publication. **This is correct and must not change.**
- **Nothing in `src/` reads `phase` today.** The field is typed and fetched but unused. Verified: no occurrence of `.phase` outside the type.

### 1.2 Processing detail (`features/processing/ProcessingPage.tsx`)

| Element | Current source | Finalizing run (`status: Running`, `phase: finalizing`, video `Processing`) | Finalization failure (`status: Failed`, `phase: failed`, `vision_finalization_*`) |
|---|---|---|---|
| Context Bar badge (l. 224) | `StatusBadge status={state.videoStatus}` | "Processing" (the video's own status; truthful for the video) | "Failed" |
| Run panel badge (l. 291–293) | shown only if `coarseState(run.status) !== coarseState(videoStatus)` (§16) | hidden (Running ≡ Processing) | hidden (Failed ≡ Failed) |
| Progress (l. 297–301) | `label={isActiveStatus(run.status) ? 'Progress' : run.status}`, tone from `run.status` | **"Progress"** at the worker's last inference percent (often 100 %): Finalizing falls through to generic progress | label "Failed", tone `err` |
| Counts (l. 312–313) | `run.status === 'Completed' ? count : 'Final count after completion'` | "Final count after completion" (correct) | "Final count after completion" (pre-existing wording for every failed run; §9) |
| Failure alert (l. 317–321) | any `failureCode` | — | **"Processing failed with `vision_finalization_…`"**: indistinguishable from an inference failure |
| Retry (l. 185–187, 233–237) | `run.status === 'Failed'` → "Retry processing" | — | "Retry processing". Correct: retry queues a new run (runbook: "reprocessing creates a new run and job as usual"). |

**The only visible "Progress" text in the application** is `ProcessingPage.tsx:299`. `Progress.tsx:38` uses it as an `aria-label` fallback, which is not `innerText`.

### 1.3 Ledgers

- **`ProcessingQueuePage.tsx`, l. 163–187:**
  - the run cell is `StatusBadge status={row.processingStatus}`, an inline `Progress` bar while the video is active, and the `failureCode` in mono;
  - a text line `Run: {run.status}` appears only when `coarse(run.status) !== coarse(row.processingStatus)` (§16).
  - A Finalizing job reads **"Processing" + a moving bar**. A finalization failure reads "Failed" + the code.
- **`VideosPage.tsx`, l. 199–229:** the same cell shape without the divergent line. A Finalizing job reads "Processing" + bar.
- Queue bucket ordering (`bucketFor`) uses the video status: a Finalizing job stays in the active bucket, which is correct.

### 1.4 Shared status seam (`shared/status/status.ts`)

- `toneForStatus` and `labelForStatus` map **mixed** vocabularies (video, run and review statuses) centrally. `StatusBadge` derives tone and label from them, or takes an explicit `tone` plus children.
- UI/UX §8.2: "status meaning is assigned centrally (`shared/status`). A screen MUST NOT map a status string to a tone locally."
- `'Finalizing'` currently falls to `default → 'neutral'`.
- `.badge--active` already carries the pulsing dot, so activity is never colour alone (§8.2, §23).

### 1.5 Fixed visual criteria (F4-A, `tools/web-visual-qa/states.mjs`, **not to be edited**)

| State | Fixture | Route | `expectText` | `forbidText` |
|---|---|---|---|---|
| `processing-finalizing` | `FINALIZING_STATUS`: video `Processing`, run `Running`, `phase: 'finalizing'`, `progressPercent: 100`, counts 0 | `/processing/${LONG_VIDEO}` | `Finalizing`, `Final count after completion` | `Progress` |
| `processing-failed-finalization` | `FAILED_FINALIZATION_STATUS`: video `Failed`, run `Failed`, `phase: 'failed'`, `failureCode: vision_finalization_staging_missing` | `/processing/${FAILED_VIDEO}` | `vision_finalization_staging_missing`, `Finalization failed` | — |

`run.mjs` checks both against `document.body.innerText` of the **real production bundle** in Chromium. Both states fail on `main` today, as the README records.

### 1.6 Existing tests touching this

- `features/processing/ProcessingPage.test.tsx`: `findByText('Progress')` for a `processing` run (l. 394); counts only after completion (l. 369–420); run badge only when divergent (l. 253); retry on a failed run with `worker_watchdog_timeout` (l. 328).
- `features/processing/ProcessingQueuePage.test.tsx`: one badge per row (l. 138); run state only where it disagrees (l. 153).
- `features/videos/VideosPage.test.tsx`: one badge per row (l. 97).
- `shared/status/status.test.ts`: the tone and label tables.
- `api/videos.test.ts`: the polling policy.

---

## 2. Target behaviour

The single source for run phase is **`latestRun.phase`**; `run.status` is never used to infer Finalizing. Failure kind comes from `latestRun.phase === 'failed'` **and** `latestRun.failureCode?.startsWith('vision_finalization_')` (the domain's `VisionJob.FinalizationFailureCodePrefix`).

### 2.1 Processing detail

| Run | Context Bar badge | Run panel badge | Primary line | Counts | Failure alert |
|---|---|---|---|---|---|
| none | video status (unchanged) | — | "Not queued" empty state (unchanged) | — | — |
| `phase: queued` / `processing` | video status (unchanged) | unchanged rule | `Progress` labelled "Progress" (unchanged) | "Final count after completion" (unchanged) | — |
| **`phase: finalizing`** | video status "Processing" (unchanged; it is the video's truthful status) | **`Finalizing`** (tone `active`, pulsing dot): the run's state differs from the video's, which is exactly when §16 states it | **No progress bar.** One sentence: "Inference is complete. The results are being finalized and published; counts appear when publication completes." There is no finalization percentage in the API, so none is shown. | "Final count after completion" (unchanged) | — |
| `phase: completed` | unchanged | unchanged | unchanged (`Progress`, label "Completed", `ok`) | real counts (unchanged) | — |
| **`phase: failed` + `vision_finalization_*`** | video status "Failed" (unchanged) | unchanged (hidden) | `Progress` label **"Finalization failed"**, tone `err` | unchanged | **"Finalization failed after inference completed · `<code>`. Retrying queues a new run for this video."** Operator sentence first, code in mono last (§14). |
| `phase: failed` + any other code | unchanged | unchanged | unchanged (label "Failed") | unchanged | unchanged: "Processing failed with `<code>`. Retrying queues a new run for this video." |

Words: "Finalizing" and "Finalization failed". They are concise and already the F4-A criteria. There is no "sealing", "claim" or "hand-off" jargon in operator copy.

### 2.2 Ledgers (Processing queue, Videos)

This follows the same §16 rule the queue already applies: one badge (the video's), and the run's state as a text line only where it differs.

- **`phase: finalizing`:**
  - the inline progress bar is **not** shown, because it is inference progress, not finalization;
  - the cell carries the text line **`Run: Finalizing`**, in the queue's existing `Run: …` form, used identically on Videos.
- **Finalization failure:** badge "Failed" and code (unchanged), plus the text line **`Run: Finalization failed`**.
- Everything else is unchanged.

**Why the ledgers are in U1.** Master §6.1 states U1's test as "a Processing page **row** for a job with `phase == "finalizing"` shows a Finalizing label that is not Running/Progress". A detail-only change would leave the two ledgers rendering a Finalizing job as "Processing" with a moving bar. They are the same untruthful state on the surfaces operators scan. It is a few lines each through the same helpers.

---

## 3. Implementation sequence

1. **Tests first (red on `main`)**: every §5 test is written and seen failing, except the explicit regression guards, which pass before and after.
2. **Shared seams:**
   - **`api/videos.ts`:**
     - add `FINALIZATION_FAILURE_CODE_PREFIX = 'vision_finalization_'`;
     - add `isFinalizing(run)`: `run?.phase === 'finalizing'`;
     - add `isFinalizationFailure(run)`: `run?.phase === 'failed' && (run.failureCode ?? '').startsWith(prefix)`.

     These are the **only** places the phase string and the prefix are tested. Every surface calls these two predicates, so the matching cannot drift between surfaces.
   - **`shared/status/status.ts`:**
     - `toneForStatus('Finalizing') → 'active'`;
     - `labelForStatus('Finalizing')` stays `'Finalizing'` (default passthrough);
     - one constant `FINALIZATION_FAILED_LABEL = 'Finalization failed'`.

     Meaning stays central (§8.2). No state machine and no new module.
3. **`ProcessingPage.tsx`:**
   - `const finalizing = isFinalizing(run)` and `const finalizationFailed = isFinalizationFailure(run)`;
   - panel `actions`: `finalizing ? <StatusBadge status="Finalizing" /> : <existing divergent rule>`;
   - body: `finalizing ? <p>…sentence…</p> : <Progress … label={finalizationFailed ? FINALIZATION_FAILED_LABEL : isActiveStatus(run.status) ? 'Progress' : run.status} …/>`;
   - alert: `finalizationFailed ? <finalization copy> : <existing copy>`.

   Nothing else on the page changes: Context Bar, retry, counts, analytics panel and polling stay as they are.
4. **`ProcessingQueuePage.tsx` and `VideosPage.tsx`:** suppress the inline bar when `isFinalizing(run)`, and add the `Run: Finalizing` / `Run: Finalization failed` text line. In the queue it slots into the existing `divergent` line.
5. **Validation (§7)**, then the U1 PR: web-only, template sections, and the visual-QA enumeration (§26 "Reporting").

---

## 4. Exact files expected to change

All under `src/web/mavi-web/src/`:

| File | Change |
|---|---|
| `api/videos.ts` | prefix constant, `isFinalizing`, `isFinalizationFailure` |
| `api/videos.test.ts` | predicate truth table; polling guard |
| `shared/status/status.ts` | `'Finalizing' → 'active'`; `FINALIZATION_FAILED_LABEL` |
| `shared/status/status.test.ts` | the two vocabulary entries |
| `features/processing/ProcessingPage.tsx` | panel badge, primary line, failure copy (§3 step 3) |
| `features/processing/ProcessingPage.test.tsx` | §5.3 tests |
| `features/processing/ProcessingQueuePage.tsx` | bar suppression and run text line |
| `features/processing/ProcessingQueuePage.test.tsx` | §5.4 tests |
| `features/videos/VideosPage.tsx` | bar suppression and run text line |
| `features/videos/VideosPage.test.tsx` | §5.4 tests |

Ten files. **Nothing** outside `src/web/mavi-web/src/**` changes: no CSS token, no new component, no dependency, no `tools/web-visual-qa/**`.

---

## 5. Tests

Each test below either fails on `main` (**red**) or is a **guard** that passes before and after, and must keep passing.

### 5.1 `api/videos.test.ts`
1. **red.** `isFinalizing` is true only for `phase: 'finalizing'`. It is false for a `Running` run with `phase: 'processing'` (the discriminator against `run.status`), and false for `null`.
2. **red.** `isFinalizationFailure` is true for `phase: 'failed'` + `vision_finalization_staging_missing` and + `vision_finalization_exhausted`. It is false for:
   - `phase: 'failed'` + `worker_watchdog_timeout`;
   - `phase: 'failed'` + `null`;
   - `phase: 'finalizing'` + a `vision_finalization_*` code (not failed);
   - `phase: 'failed'` + `vision_finalization` (no underscore) and `xvision_finalization_a` (prefix, not substring).
3. **guard.** `isProcessingActive` stays true for the Finalizing fixture (`status: Running`), so polling continues until publication.

### 5.2 `shared/status/status.test.ts`
4. **red.** `toneForStatus('Finalizing') === 'active'`; `labelForStatus('Finalizing') === 'Finalizing'`.

### 5.3 `features/processing/ProcessingPage.test.tsx`

The page is driven with the exact F4-A fixture shapes (§1.5) plus variants.

5. **red. Finalizing is distinct.** Video `Processing`, run `Running`, `phase: 'finalizing'`:
   - `getByText('Finalizing')` is inside the "Processing run" panel;
   - the panel badge has `data-status="Finalizing"`;
   - `queryByText('Progress')` is `null`;
   - `queryByRole('progressbar')` is `null`;
   - `queryByText('Running')` is `null`;
   - "Final count after completion" is shown.
6. **red. Phase, not status, is the source.** The same fixture as 5 with only `phase` changed to `'processing'` renders "Progress" and no "Finalizing". The pair differs in `phase` alone, so a status-based implementation cannot pass both.
7. **red. Finalization failure is distinct.** Video `Failed`, run `Failed`, `phase: 'failed'`, `vision_finalization_staging_missing`:
   - "Finalization failed" appears in the progress label and in the alert;
   - the alert contains the code in `<code>`;
   - `queryByText(/Processing failed/)` is `null`, so no contradictory body copy;
   - "Retry processing" is still offered.
8. **guard. Other failures unchanged.** The existing `worker_watchdog_timeout` fixture still reads "Processing failed with `worker_watchdog_timeout`", and `queryByText(/Finalization failed/)` is `null`.
9. **guard. Completed unchanged.** The existing completed test (counts, Scene analytics panel) passes, and `queryByText('Finalizing')` is `null`.
10. **guard. Queued and inference unchanged.** The existing `processing` fixture test (`findByText('Progress')`) passes. A `queued` run renders its existing state with no "Finalizing".

### 5.4 Ledgers (`ProcessingQueuePage.test.tsx`, `VideosPage.test.tsx`)
11. **red.** A Finalizing row shows the text `Run: Finalizing`, has no `progressbar` in its cell, and still carries **exactly one badge** (the existing one-badge tests pass).
12. **red.** A finalization-failure row shows `Run: Finalization failed` and the code. A `worker_watchdog_timeout` row shows no such line (**guard** for relabelling every failure).
13. **guard.** The existing ordering, bucket and divergence tests pass unchanged.

The tests assert what the operator reads, via Testing Library queries on text, role and `data-status`. They do not assert class names, so a restyle cannot fake them.

---

## 6. Visual QA (§26, the F4-A criteria)

The two F4-A states are the acceptance criteria and are **used unmodified**:

```bash
export MAVI_CHROMIUM=/path/to/chromium            # found automatically at the usual locations
node tools/web-visual-qa/run.mjs --build --states processing-finalizing,processing-failed-finalization
```

1. **Before (on `main`, or the U1 branch before step 3):** both states must **fail**:
   - `processing-finalizing`: "Progress" is present and "Finalizing" is absent;
   - `processing-failed-finalization`: "Finalization failed" is absent.

   The failing output is retained in the PR as the red half.
2. **After:** both states pass at **all four widths** (1366×768, 1440×900, 1920×1080, about 2560×1080) with exit 0. The run exercises the **real production bundle** (`npm run build`) and the real `ProcessingPage` component, with only the API intercepted by the F4-A fixtures. Nothing is fixture-only.
3. **Regression set, same run, all four widths:**
   - `processing-detail-running`, `processing-detail-completed`, `processing-detail-failed`, `processing-detail-unavailable`;
   - `processing-queue`, `processing-queue-dense`, `processing-queue-row-unavailable`;
   - `processing-detail-analytics-ready`, `processing-detail-analytics-stale`, `processing-detail-analytics-failed`;
   - `videos`, `videos-dense`.

   All must pass the automated assertions, which cover overflow, overlap, focus visibility, archetype and expect/forbid text.
4. **Human pass (§26 requires looking):** open the captures for the two F4-A states at 1366 and 2560 and confirm:
   - the Finalizing badge sits in the run panel and the sentence reads cleanly;
   - no progress bar is shown while finalizing;
   - the failure alert leads with the operator sentence and ends with the code;
   - the layout is unchanged otherwise.
5. **Retention:** screenshots are working artefacts and **must not be committed** (§26). The PR states the enumerated states × widths, the before/after results and the human-pass notes. The captures for the two F4-A states may be attached to the PR conversation for the Gate B reviewer. The per-state JSON summaries the harness writes beside each capture are quoted in the PR.

What this proves: the shipped UI, not a fixture, shows the truthful state for exactly the API shapes the platform emits. That is the B5 `finalizingStateDistinct` and `failedFinalizationDistinct` result that M2 will record.

---

## 7. Validation

In `src/web/mavi-web`:
1. `npm run typecheck`;
2. the focused tests: `npx vitest run src/api/videos.test.ts src/shared/status/status.test.ts src/features/processing src/features/videos`;
3. the full suite: `npm test`, all green;
4. `npm run build`.

Then:
5. the visual-QA run of §6: before and after, plus the regression set;
6. `python tools/verify_repo.py`, which confirms no model, secret or dependency drift and a clean docs/release scan;
7. exact-head CI green on the U1 PR (Quality Gate web suite).

No .NET, worker or qualification suite needs to run for U1: it touches none of them. The PR states this and shows the diff is confined to `src/web/mavi-web/src/**`.

---

## 8. Scope exclusions (U1 does not touch)

- Backend, API, contracts, domain lifecycle, finalizer, `ProcessingPhases` / `ProcessingPhaseRule`, the status projection.
- `tools/web-visual-qa/**`, including `states.mjs` and the F4-A states' `expectText`/`forbidText`; the qualification harness; `tools/qualification/**`; the checker; F4-A criteria.
- F4-C: no `appsettings.json`, no worker default, no activation, no frozen values, no runbook activation text.
- The Context Bar video badge, the retry semantics, polling (`isProcessingActive`), the Scene analytics panel, CSS tokens and components.
- **Pre-existing, noted, not changed:** a failed run's counts read "Final count after completion" for **every** failure kind. Changing that alters non-finalization failures, which is outside U1. It is not contradictory with the new copy, since the run did not complete; if wanted, it is a separate UI slice.
- **Pre-existing, noted, not changed:** the progress bar tone for non-finalizing runs is chosen locally from `run.status` (`ProcessingPage.tsx:300`), predating §8.2's centralisation. U1 does not refactor it.

---

## 9. Cold-review checklist (Gate B, P1/P2-oriented)

| # | Attack | How U1 is refuted | Sev if it fails |
|---|---|---|---|
| 1 | Finalizing inferred from `run.status` | only `isFinalizing(run)` reads phase; test 6 differs in `phase` alone | P1 |
| 2 | Finalizing still reads Running or Progress elsewhere on the page | test 5 forbids "Progress", "Running" and the progressbar; the F4-A state forbids "Progress" in `innerText`; the Context Bar keeps the video's truthful "Processing" by design (§2.1) | P2 |
| 3 | Finalization failure changes only a label while the alert still says "Processing failed" | test 7 asserts no "Processing failed" text | P2 |
| 4 | Fixture-only behaviour | visual QA runs the built bundle with API interception only; component tests render the real page | P1 |
| 5 | Visual-QA expectations edited instead of product fixed | diff confined to `src/web/mavi-web/src/**`; `git diff --name-only` in the PR | P1 |
| 6 | Backend or API semantics changed | same diff proof; no contract or type change beyond two predicates on the existing type | P1 |
| 7 | Prefix matching inconsistent across surfaces | one predicate and one constant in `api/videos.ts`; test 2 covers no underscore, a leading character and `null` | P2 |
| 8 | Every failure relabelled | tests 8 and 12 | P2 |
| 9 | Completed, queued or inference regress | tests 9 and 10, plus the regression visual states | P2 |
| 10 | Ledgers still lie | tests 11 and 12 | P2 |
| 11 | A second badge per row (§16) | the existing one-badge tests plus test 11 | P2 |
| 12 | Status tone mapped locally (§8.2) | `'Finalizing'` tone lives in `shared/status` | P3 |
| 13 | Over-engineering | two predicates, one tone entry, one label constant; no module, framework or component | P3 |
| 14 | Polling stops during Finalizing | test 3 | P2 |
| 15 | Leak into F4-C | no config, worker or runbook change; the scope list in the PR | P1 |

---

## 10. Completion criteria

U1 is ready to merge when all of these hold:
1. every §5 red test was seen red before the change, and every test is green after;
2. `typecheck`, the full web suite and `npm run build` are green;
3. the two F4-A visual states fail before and pass after at all four widths, **unmodified**, and the regression set passes, with the enumerated pass in the PR (§26);
4. the diff is confined to the ten files of §4;
5. `verify_repo` passes and exact-head CI is green;
6. an independent Gate B cold review raises no P1/P2;
7. it is merged with a merge commit **before** F4-C opens. Its merge SHA is recorded for the M2 declaration (execution plan §14).

U1 does not produce B5 evidence: B5 is measured at M2 (master §25 step 9).
