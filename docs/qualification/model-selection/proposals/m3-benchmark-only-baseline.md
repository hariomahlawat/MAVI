# Proposed MSR method revision M3 — benchmark-only baseline role (supersedes draft "M1-A1")

**Status: PROPOSED — not in force.** It needs independent re-review and owner acceptance, and becomes governing only
when merged after review and exact-head CI (README §14). Until then `README.md` and `candidate-credibility.md` (M1)
govern unchanged.

**Validator changes are specified, not implemented.** The changes in §6 are written precisely with their tests, and
are implemented only after acceptance. Nothing in `tools/qualification/model_selection/` implements this role today.

**Name.** The draft was called "M1-A1". It is renamed **M3**, the next numbered method revision after M2 (README §14:
revisions are additive and numbered).

**Origin.** Stage-4 PR-2 (owner decision 2026-10-14):
- the plan's Tesseract baseline (OC5) computes as `reference-only` under M1, because no first-party task-quality claim exists for its exact `tessdata` bytes;
- M1 forbids shortlisting `reference-only`;
- plan §4.5 defines a Baseline gate against a Tesseract composition.

The revision is general; nothing in it is plate-specific.

## 1. Definitions

- **Benchmark-only baseline (BOB):** a third-party candidate whose computed M1 class is **`reference-only`** and which an event's frozen protocol designates with the disposition `BENCHMARK_BASELINE`. It may be executed and measured solely to define frozen comparative baselines or gates.
- **Gate-only baseline composition:** a composition containing exactly one BOB component together with ranked components, designated in the frozen protocol as the comparison for a named, frozen set of compositions.
- **O2:** the owner's implementation choice among technically ranked, gate-passing, licence-cleared and implementation-eligible candidates or compositions (README §4 "implementation candidate"; plan decision O2).

## 2. Rules

1. **Class restriction (review P1-1).**
   - `BENCHMARK_BASELINE` is allowed **only** for computed class `reference-only`.
   - It is refused for `established` and `emerging`, which take the ordinary shortlist route; demoting a strong candidate by role is impossible.
   - It is refused for `excluded-discovery` and `mavi-owned` (a MAVI-owned baseline keeps its existing route).
   - It requires `reasonClass: "technical"` and a reason naming the comparative purpose and the protocol section that freezes it.
2. **Execution preconditions** (review P2-2), each recorded in the frozen protocol:
   - **Exact bytes per declared host profile.** A byte manifest for every model/data file, executable and runtime library (SHA-256 and size), for each host profile on which the baseline runs (for example Windows CPU, Windows CUDA, Linux CPU CI). Each artefact's offline-dependency-policy classification (benchmark-only, dev/test) is cross-referenced.
   - **Complete configuration and invocation.**
   - **Evaluation permission per artefact** (binary, each runtime library, model data), each with decision-maker, date and primary-source hash (README §2 carve-out).

   These are **review rules** until the validator fields in §6(c) exist.
3. **No selection role.** A BOB:
   - never enters a top-K / finalist cut;
   - is never a composition candidate, frontier member, finalist or ranked row;
   - is never the strongest evaluated technical, the highest task-quality evaluated or a strongest-cleared candidate;
   - is never an implementation candidate or component.

   A gate-only baseline composition inherits all of these restrictions. Its measurements are reported under the label "benchmark-only baseline — not a selectable candidate".
4. **Frozen baseline mapping (review P1-2).** The frozen protocol names exactly which gate-only baseline composition gates which compositions. The mapping is general:
   - it may be one baseline composition for all;
   - or one per component, as an event decides;
   - it is fixed before any candidate sees selection data.
5. **Outcome (review P1-3e).** `BASELINE_SELECTED` can never follow from a BOB. If no ranked candidate passes, the outcome is `NO_QUALIFIABLE_CANDIDATE`.
6. **Credibility.**
   - Restatement of M1 I4 and §8: MAVI measurements never change a credibility class, and implementation eligibility requires `established` (or `mavi-owned`) on the decision date.
   - Proposed new rule: a BOB's measurement is recorded nowhere in its ledger entry.
7. **Timing (review P2-3).** Any method amendment that affects eligibility, roles or the decision rule applies **only to events not yet at `PROTOCOL_FROZEN`**, whatever the motive.
8. **Scope (review P1-3f).** This revision applies to decision summary **v1** (non-S2c events). For decision **v2** (M2/S2c), no BOB is permitted until a separate revision defines its v2 representation.

## 3. Clauses amended (replacement wording; review P2-4)

| Clause | Replacement |
|---|---|
| README §4 role list | "**Role:** `baseline`, `incumbent`, `challenger`, `reference`, or `benchmark-only-baseline` (M3: a `reference-only` third-party candidate measured only to define frozen baselines or gates; never selectable)." |
| README §4 disposition diagram | add `DISCOVERED ─→ BENCHMARK_BASELINE (M3; reference-only class; measured, never ranked)` |
| README §3.2 outcomes | after `BASELINE_SELECTED`: "A benchmark-only baseline (M3) can never produce `BASELINE_SELECTED`; with no qualifying ranked candidate the outcome is `NO_QUALIFIABLE_CANDIDATE`." |
| README §5.1 step 2 | replace "Non-packageable baselines never enter a tuple." with "Non-packageable baselines never enter a ranked tuple. A gate-only baseline composition (M3) is measured only as the frozen comparison for the compositions the protocol names; it is never a composition candidate, frontier member, finalist or ranked row." |
| README §9 | add to the outputs: "Benchmark-only baselines are reported separately and never appear in any derived output." |
| M1 §3 class table | `reference-only` allowed dispositions: add `BENCHMARK_BASELINE (M3)` |
| M1 §4 | "admits only the pre-evaluation dispositions `DISCOVERED`, `SHORTLISTED`, `NOT_SHORTLISTED`, `REFERENCE_ONLY`, `DEFERRED` and, under M3, `BENCHMARK_BASELINE`" |
| M1 §8 | "The evaluated set equals the frozen shortlist plus the frozen benchmark-only baselines (M3). No derived output may name a benchmark-only baseline." |
| M1 I1 | append "A benchmark-only baseline (M3) is never shortlisted; it is measured under its pinned manifests and permissions" |
| M1 I6 | "evaluated set equals the frozen shortlist **plus frozen benchmark-only baselines**" |
| M1 I12 | unchanged (S2c.2a); add I13: "A benchmark-only baseline cannot affect any derived output or credibility" |

## 4. What this revision does not do

It does not change:
- the M1 classification rule or the shortlist rule for other classes;
- implementation eligibility;
- the licence axis;
- the technical ranking of any ranked candidate.

## 5. Trade-off (README §14 form)

- **Cost:** one more disposition, decision-summary rules and review items, and per-host manifests for native baselines.
- **Gain:** a plan-mandated comparison floor (for example a Tesseract baseline) can be measured honestly without being misrepresented as a credible, selectable candidate.
- **What changes:** a `reference-only` candidate may be **measured** for a frozen gate. It still can never be ranked, selected or implemented.

## 6. Machine-checked changes (specified; implemented only after acceptance)

**(a) Derivations** (`credibility.py` `validate_decision`, the `_maximal` domains for quality, technical and eligible):
- exclude every evaluated row whose candidate disposition is `BENCHMARK_BASELINE`;
- such a row carries `technicalGates: "n/a"`, `comparativeScore: null` and `taskQualityScore: null`;
- any other value is refused.

*Tests:*
- a BOB with the highest score is not `strongestEvaluatedTechnical`;
- a BOB named in `strongestReported`, `highestTaskQualityEvaluated`, `strongestEvaluatedTechnical`, `strongestClearedPerProfile` or `implementation.components` is refused;
- a BOB row with a numeric score is refused.

**(b) Evolution** (`validate_evolution`):
- after `frozenOn`, the set of `BENCHMARK_BASELINE` entries and each one's identity and configuration hashes are fixed, like the shortlist.

*Tests:* adding, removing or re-pinning a BOB after freeze is refused.

**(c) Pinning** (ledger and `_check_evaluated_artefact`):
- `BENCHMARK_BASELINE` requires provenance High (an immutable revision, every file hashed);
- an `identity.hostManifests` field, `{profileId: [{path, sha256, size}]}`, covering executables and libraries;
- evaluated rows of a BOB must equal those hashes.

*Tests:* unpinned, missing a host manifest, or bytes that differ — each refused.

**(d) Top-K and composition membership:** these are not represented in decision v1. They stay **review rules** (the reviewer confirms no BOB appears in a top-K cut or ranked composition), unless a later revision adds the fields.

**(e) Outcome:** `outcome: "BASELINE_SELECTED"` with only BOB rows passing is refused; `NO_QUALIFIABLE_CANDIDATE` is required. *Test:* included.

**(f) Scope:** a decision v2 document containing a BOB is refused (`m3_v2_unsupported`). *Test:* included.

**Class restriction.** `BENCHMARK_BASELINE` is refused for any class other than `reference-only` (`benchmark_baseline_class`).

*Tests:* `established`, `emerging`, `excluded-discovery` and `mavi-owned` are each refused.
