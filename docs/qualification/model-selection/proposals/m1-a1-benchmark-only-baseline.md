# Proposed MSR method amendment M1-A1 — benchmark-only baseline role

**Status: PROPOSED — not in force.**
- It needs independent review and owner acceptance **before** any event relies on it at `PROTOCOL_FROZEN`.
- Until then, `README.md` and `candidate-credibility.md` (M1) govern unchanged.
- The `license plate` validator correction on this branch is a separate reviewable unit (commit 1).

**Origin:** owner decision 2026-10-13, Stage-4 PR-2. The plan's Tesseract baseline (OC5) computes as `reference-only`
under M1, because no first-party task-quality claim exists for its exact `tessdata` bytes. M1 forbids shortlisting
`reference-only`, yet plan §4.5 defines the Baseline gate against a Tesseract composition. The amendment is general and
narrow; nothing in it is plate-specific.

## 1. The role

A candidate entry may carry the role **`benchmark-only-baseline`** (MSR method §4 roles: baseline / incumbent /
challenger / reference, plus this one). A benchmark-only baseline:

1. **May be executed and measured** in the event, provided all of these are pinned in the frozen protocol:
   - its exact bytes (every model/data file by SHA-256, plus any native executable and its runtime libraries by SHA-256 manifest);
   - its complete configuration and invocation;
   - a recorded human evaluation permission (MSR §2 carve-out).
2. **Keeps its computed credibility class.** Its disposition is never `SHORTLISTED`; the ledger records it as `BENCHMARK_BASELINE` (a new pre-evaluation disposition, §3).
3. **Cannot enter a top-K / finalist cut**, cannot be the strongest evaluated technical candidate, cannot be the technical winner, and cannot be an implementation candidate.
4. **Cannot gain credibility from its measurement.** MAVI's own measurement is never external evidence (M1 §2), so no measurement of a baseline (or of any candidate) changes a credibility class.
5. **Exists only to define frozen comparative baselines or gates.** Examples: a detector-matched baseline composition whose D-score a challenger must clear by the MPID; a floor for an engineering budget.
6. Its results are reported in the record's measurement tables with the label "benchmark-only baseline — not a selectable candidate".

## 2. What it does not change

- The M1 classification rule, the shortlist rule for every other role, and the implementation-eligibility rule (`established` or `mavi-owned` on the decision date) are unchanged.
- Licence/deployment stays a separate axis.
- A `mavi-owned` deterministic baseline (for example PC-B0) keeps its existing route. This role is for third-party baselines only.

## 3. Machine-checked changes required (implemented only after acceptance)

- **Ledger:**
  - new disposition `BENCHMARK_BASELINE`, allowed for classes `established`, `emerging` and `reference-only`, and refused for `excluded-discovery`;
  - it requires `reasonClass: null` and a `reason` naming the baseline's comparative purpose;
  - `emergingShortlistBasis` is not used.
- **Decision summary (v1):**
  - `evaluated` may contain benchmark-only baselines beside the frozen shortlist;
  - such a row may not be `strongestEvaluatedTechnical`, `highestTaskQualityEvaluated`, a `strongestClearedPerProfile` value or an `implementation` component, and `validate_decision` refuses each;
  - the evaluated-set check becomes: frozen shortlist ∪ frozen benchmark-only baselines.
- **Tests:** every refusal above, plus a ledger where a `reference-only` baseline is measured while its class stays `reference-only` after the decision.

## 4. Freeze rules reinforced (apply with or without this role)

- MAVI's bake-off results never promote any candidate's M1 class.
- If the strongest evaluated technical candidate is `emerging`, it is recorded as such, and implementation selection (O2) stays **blocked** until M1 implementation eligibility is genuinely met, or until a separate, independently reviewed method amendment is accepted **before** it is used for selection.
- No M1 amendment may be made after candidate scores exist in order to make a measured winner eligible.

## 5. Review questions for the independent reviewer

1. Does the role create any path by which a `reference-only` candidate influences the technical ranking beyond a frozen gate threshold?
2. Is the evaluation-permission requirement sufficient for third-party native binaries?
3. Are the decision-summary refusals complete (all derived outputs)?
