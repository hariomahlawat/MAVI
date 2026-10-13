# Stage 4 — O5 Human Review and Human-Reviewed Recomputation of E-A/E-B/P3

**Date:** 2026-10-13. **O5 status: COMPLETE.** The labels are now **human-reviewed, AI-assisted**.

**Under the same frozen protocol** (`adequacy-protocol.md` revision 1), with the same denominator rules, thresholds, instruments, association and MAVI evidence: **the verdict is unchanged: INADEQUATE** (C = 53/79 = 0.671 < 0.70).

The original frozen AI-label result and all its hashes are preserved alongside: E-A `cc718922…`, E-B `3db69e53…`, verdict `b740ce45…`, labels `0bc089b1…`, truth `709a560b…`.

## Human review record

**Reviewer:** one independent human reviewer inspected all **125** rows of the O5 audit package: 100 tracks, plus 18 unlabelled evidence frames, plus the 20 illegible rows completed by patch 1.

**Files** (under `E:\MAVI-Controlled\Benchmarks\stage4-bdd-plates\`):

| Item | Value |
|---|---|
| Original audit input, preserved unchanged | `o5\human-audit\audit-form.csv`, `ae40d398…` |
| Human-review record | `o5\human-audit\O5_Human_Review_Completed.xlsx`, `fa336951…` (the workbook is named this, not `human-review-completed.xlsx`) |
| Provenance record | `o5\human-review-record.json`, `cc9d7e8f…` |
| Audit manifest | gains a `humanReview` block |

**Checks:**
- all 125 rows carry a decision;
- the identity columns (item, kind, sequence, track, MAVI Track, frames, strata, label) equal `audit-form.csv` row for row.

**Decisions:** accept 91, correct 6, reject 28. The reviewer agrees with the AI pre-review on **125/125**.

**Effect of each decision:**
- **Rejects** concern illegible tracks whose detector proposal was not a plate, and unlabelled evidence frames confirmed illegible. This is the frozen treatment already, so they change nothing.
- **Corrections:**
  - five tracks previously transcribed illegible now have human-confirmed text (below);
  - A050-E113 confirms FZC4204 at an evidence frame of a track already evidence-readable, so it cannot change E-B. No geometry is added there, because the R8 box at that frame was rejected and the reviewer was not asked about geometry.

**Derived labels (new; `labels.json` `0bc089b1…` is unchanged):**
- **`labels-human-reviewed.json` `4764bb5f…`** (primary).
  - Each corrected track takes the reviewer's text.
  - Its geometry is the annotation-detector proposals the reviewer inspected in the patched package.
- **`labels-human-reviewed-named-frames.json` `71e87f5c…`** (sensitivity). Geometry is restricted to the frames the reviewer's note names.

## Recomputation (same frozen protocol)

**Outputs:** `results-human-reviewed\` (primary).
- Tooling: `tools/benchmarks/plates/cli.py`, unchanged.
- Run script: `E:\MAVI-Working\stage4\o5close\recompute.sh`.

| | Frozen (AI labels) | Human-reviewed |
|---|---|---|
| Truth plates (text-usable) | 488 (485) | 517 (514) |
| E-A `h_min` | 32 px | **32 px** |
| E-A ΔEM, plate-specific (fast-plate-ocr), Representative | 75/77 = 0.97 pp (n = 308) | **200/329 = 0.61 pp** (n = 329) |
| E-A ΔEM, generic (rapidocr), Representative / supplemental | 2.27 / 1.95 pp | 1.82 / 1.52 pp |
| E-B R_oracle | 77 | **79** |
| E-B R_ev | 51 | **53** |
| **C** | 51/77 = **0.662** | 53/79 = **0.671** |
| Verdict | INADEQUATE (`coverage_below_0.70`) | **INADEQUATE** (`coverage_below_0.70`) |

| Result | SHA-256 |
|---|---|
| truth | `8d1d03b2…` |
| ea | `db2656f1…` |
| eb | `b3aa0b4d…` |
| verdict | `6dc95563…` |

ΔEM stays far below the 10 pp limit. The only failing criterion is C < 0.70, as before. The failure breakdown is unchanged: matched-not-readable 12, fragmented 6, unmatched 7, unverified 1.

### Tracks that changed (all 5 are the corrected illegible tracks; no other row changed)

| Track | Human text | Before | After | Why |
|---|---|---|---|---|
| b1d7b3ac-afa57f22/00124432 (A079) | 4350234 | no usable plate | **oracle- and evidence-readable** | read exactly natively at frames 111–112 (38–39 px) and in the Representative, NearView and LateDiverse crops |
| b1f4491b-07b32e8c/00117773 (A085) | T712199C | no usable plate | **oracle- and evidence-readable** | read exactly at frames 4 and 12 (44–45 px) and in the NearView and EarlyDiverse crops |
| b1dce572-c6a8cb5e/00113329 (A035) | VAS1411 | no usable plate | usable, **not oracle-readable** | vertical "VAS" with "1411": neither instrument reads the stacked layout (best `S31411`); outside R_oracle |
| b23b2649-6af03cd5/00119199 (A092) | GFC87A | no usable plate | usable, not oracle-readable | instruments read `GFC8747`; outside R_oracle |
| b1fbf878-b31a8293/00112829 (A044) | NARTEA | no usable plate | usable, not oracle-readable (evidence-readable) | native frames read `NARTFA`; one NearView crop reads `NARTEA` exactly. By the frozen rule it is outside R_oracle, so not in C |

## Sensitivity (named-frame geometry)

This variant keeps geometry only on frames the reviewer's notes name. Output `results-human-reviewed-named-frames\`:

| Result | SHA-256 |
|---|---|
| truth | `161fb9f1…` |
| ea | `55777677…` |
| eb | `58927b20…` |
| verdict | `b74028e4…` |

- E-A: `h_min` 32 px; ΔEM (plate-specific, Representative) 8/13 = 0.62 pp (n = 325).
- E-B: R_oracle **79**, R_ev **53**, C = **0.671**, **INADEQUATE**.
- **No track outcome differs from the primary**, so the geometry choice does not affect the result.

## Statement

- **O5 is complete:** the labels are human-reviewed, AI-assisted.
- **P3 remains INADEQUATE** under the frozen protocol, on both the AI-label result and the human-reviewed recomputation.
- No threshold, rule or denominator changed.
- The frozen AI-label result remains the original record of the verdict. The human-reviewed recomputation is its verified successor.
