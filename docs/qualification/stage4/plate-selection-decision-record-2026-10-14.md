# Stage 4 — Plate selection: authoritative pre-freeze decision record (2026-10-14)

**Purpose.** This is the written source of the rules that the A–D evaluators and the query generator
(`tools/benchmarks/capabilities/plates/{evaluator,queries}.py`) and the PR-2 protocol rely on.

**Status.** Pre-freeze. No candidate has been scored and no selection data has been read. Owner decisions here may
change only by a dated owner decision recorded here, before the PR-2 protocol is frozen, and never because of a
candidate result.

**Scope.** This record does not change PR-1's frozen evidence, hashes, thresholds, calculations or INADEQUATE verdict.
It does not change PR-3/PR-4 product semantics or the frozen plate normalisation (`6e505158…bf935`).

## 1. Owner decisions

| Id | Date | Decision |
|---|---|---|
| D6 | 2026-10-13 | PR-3 bounds: ≤ 2 detector proposals per crop, ≤ 1 accepted plate, ≤ 3 readings. **Ranking OCR confidence floor = 0**, enforced in code (`ranking_parameters`; the ranking path refuses any other floor). {0.3, 0.5, 0.7} are **diagnostic only** (`diagnostic_*`) and cannot affect D, gates, top-K or selection. Each candidate's preprocessing and detector defaults are pinned before scoring |
| D7a | 2026-10-14 | **MPID = 0.04** on D-score, compared exactly (`Fraction(4, 100)`) |
| D7b / P-80 | 2026-10-14 | `required_clusters = max(60, the candidate-blind MSR §8.1 coverage/sufficiency-calibration minimum)`. 60 is an absolute floor and is never called "adequately powered". The earlier requirement of "80 % power at a true difference equal to the MPID" is **withdrawn** (incompatible with the observed-difference rule). Power curves for the complete rule at ΔD = 0.04, 0.06 and 0.08, plus "interval excludes zero" as a diagnostic, are reported for transparency only and never change the MPID, the rule, the cluster count, thresholds or an outcome |
| Superiority | 2026-10-14 | A is `superior` to B iff (1) observed ΔD = D_A − D_B ≥ 0.04; (2) the paired hierarchical 95 % interval for ΔD excludes zero in A's favour; (3) the frozen required independent-cluster count is met. The lower bound is **not** required to reach 0.04. A pair failing the rule is simply not demonstrated superior |
| D10b | 2026-10-13 | D uses exactly PR-3/PR-4 product semantics: Track texts = `plate-track-text-rank0`; literal `exact`/`contains` on normalised text; queries 3–15 `[A-Z0-9]`. D binds to PR-4 as merged |
| Silence (item 1) | 2026-10-14 | On a valid closed population, a composition returning nothing has exact recall 0, contains recall 0 and contains precision 0, so D is defined. `INSUFFICIENT_EVIDENCE` is reserved for corpus deficiency (no queryable plate-bearing Track, no positive Track–query pair, no contains query). A silent OC5 baseline scores 0 |
| N2 (revised) | 2026-10-14 (supersedes the 2026-10-13 detector-matched rule) | **One hard Tesseract baseline.** PD_BASE + OC5 is the single gate-only baseline composition. Every ordinary D composition, whatever its detector, passes only if the **observed** D − D(PD_BASE + OC5) ≥ 0.04 (exact). Detector-matched PDx + OC5 runs are **diagnostic only** (OCR uplift at a fixed detector): they never pass or fail a composition, enter top-K or the ranking, or change the MPID. If PD_BASE + OC5 violates the contract or cannot be evaluated, the event **stops** and the baseline is never replaced. A silent baseline is a valid measurement scoring 0. This is a rule clarification before freeze, not a plan deviation: plan §4.5's Tesseract gate is kept, with one baseline. Code: `baseline_gate`, `diagnostic_ocr_uplift`, `rankable_compositions` |
| N2 resolution (addendum) | 2026-10-14 | **Two-stage baseline resolution.** PD_BASE comes from Layer-A results, so its identity cannot be known at PROTOCOL_FROZEN; no detector is chosen manually and OC5 stays immutable before D. **Stage 1, at PROTOCOL_FROZEN, freezes:** the exact identities/hashes of every detector eligible to become PD_BASE; the complete OC5 benchmark-only identity; all Layer-A gates; the detector ranking and tie-break (N4; `DETECTOR_RANKING_RULE`, hashed); the rule "PD_BASE = the highest-ranked detector among those passing every frozen Layer-A gate"; that the one hard D baseline is PD_BASE + OC5; and that it gates every ordinary D composition (`BaselineFreeze`). **Stage 2, after Layer A and before any protected D data is read:** PD_BASE is derived mechanically (`resolve_baseline`) into an immutable, self-hashing baseline-resolution record. It holds the resolved detector id and identity hash, OC5's identity hash, the Layer-A result artefact hash, the ranking-rule hash, the baseline-composition hash, the resolution time, and the state `D_NOT_STARTED`. The event **stops**, with no baseline and no D ranking, if no detector passes Layer A, if Layer A is ambiguous or inconsistent with the frozen universe/identities, or if any D data was read first. The sealed record cannot change (`verify_resolution`, `assert_resolution_unchanged`). No owner discretion, no substitution. OC5 is never a candidate, finalist or winner, and the gate-only composition never enters ranking, the frontier or implementation |
| N3 | 2026-10-13 | Consistent-wrong. **Numerator:** GT plate-bearing Tracks with valid readings from ≥ 2 distinct source observations, all agreeing on one wrong text. **Denominator:** all evaluable GT plate-bearing Tracks with supported truth. **Limit:** ≤ 2 %. **Support:** < 50 ⇒ `INSUFFICIENT_EVIDENCE`. The conditional rate is a diagnostic |
| N4 | 2026-10-13 / 14 | Top-K only from a common, predeclared, **demonstrably independent** population; `unknown` exposure is not independent. **Detector tie-break:** A, then lower false plates per crop, then AP50, then lexical id. **OCR tie-break:** EM, then lower CER, then lower ECE, then lexical id |
| N5 | 2026-10-13 | P14 tolerance: \|D(PR-2) − D(PR-6 product path)\| ≤ 0.02, with identical semantics and no hard-gate reversal |
| N6 | 2026-10-13 | Profiles: `plates-dev-windows-x86_64-cpu-v1` (required), `plates-dev-linux-x86_64-cpu-v1` (required reproducibility/CI), `plates-dev-windows-x86_64-cuda-sm75-4gb-v1` (informational) |
| N7 | 2026-10-13 | Fine-tuning trigger 0.85 (Indian one-line full-plate EM) preserved, and recorded NOT_MEASURED while support is < 50 |
| N8 | 2026-10-13 | D only on a **fully labelled, closed** population. **Exact recall:** supported, queryable GT plate-bearing Tracks. **Contains recall:** deterministic positive Track–query pairs. **Contains precision:** all returned Track–query pairs |
| N9 | 2026-10-13 | No result-driven stopping. One rerun only, for a proven infrastructure/harness failure with identical bytes and configuration. Contract, offline, determinism, persistent runtime and resource failures are FAIL. If fewer than two non-baseline candidates remain evaluable per capability, the event returns to PLANNED |
| Contract (item 11) | 2026-10-14 | Any PR-3 output-contract violation is a **hard CONTRACT_FAIL** for the evaluation run. The exact failure is kept and nothing is scored through it. This covers more than 2 detector proposals, a recogniser over its bound, and malformed output PR-3 treats as an attempt failure |
| Cluster unit (item 4, C2) | 2026-10-14 | One independent top-level cluster = **one physical capture site**. Sequences, windows, Tracks, repeated visits and clips from a site are nested, not independent. Several cameras at one site are one cluster. A camera moved to a genuinely distinct site may be reused there |
| C1 | 2026-10-14 | Corpus plan: 20 independent sites for A/B selection + `required_clusters` independent sites for protected D. A predeclared extension up to 100 total sites is allowed for corpus reasons fixed before candidate execution only. Stop and return to the owner if the design exceeds 100 sites, ≈ 3,000 labelled vehicle Tracks or ≈ 500 annotation/QA hours |
| C3 | 2026-10-14 | Per site, before annotation or candidate execution: one fixed ROI, one **30-minute** contiguous primary window, and the predeclared schedule rule that chooses it. No choice by traffic, readability, candidate or OCR behaviour. Every qualifying vehicle crossing the ROI in the window is in the closed population. **No small-box exclusion** |
| C4 | 2026-10-14 | Two independent primary annotators, blind to candidate outputs, PR-1 instrument OCR outputs and PD1 labels. Third-person adjudication for text/outcome disagreements. Independent QA of geometry and Track association. Organisational, data-controller and privacy approval before capture. Controlled, non-public data under an explicit retention/access/audit policy |
| Outcomes (item 8) | 2026-10-14 | `TEXT`; `NO_PLATE` (truth = no text); `UNREADABLE` (text not establishable by the frozen human rule: excluded from known-truth scoring terms, its prevalence and returned pairs are counted); `NO_GT_VEHICLE` (a MAVI Track with no GT vehicle: a false Track, never conflated with `NO_PLATE`) |
| Unsupported truth (item 10) | 2026-10-14 | Kept in the closed population and counted. Excluded only from text-recall denominators. Any pair it returns is incorrect, so it cannot improve precision |
| Query binding (item 12) | 2026-10-14 | A query set records the population/partition manifest SHA-256, the generator-configuration SHA-256 and the query-set SHA-256. The evaluator refuses a query set bound to another population |
| De-duplication (item 13) | 2026-10-14 | Each unique (match mode, normalised literal) is scored once. Originating classes are kept as provenance |
| Query lengths (item 18) | 2026-10-14 | Prefix 4; suffix = the **terminal four digits** (of the final digit run); interior 5. These are fixed constants, never fabricated: an absent class is recorded |
| Bootstrap (item 17) | 2026-10-14 | The fast path resamples precomputed per-Track counts. It is mathematically identical to re-evaluation, proven by test under the same seed |
| O1 | 2026-10-14 | Bounded private Indian Development-footage labelling approved (design proposed, not started). IDD-X is not ANPR/OCR evidence |

## 2. Plan-derived rules (Stage-4 plan; not owner-changed)

- **A primary:** recall at coverage ≥ 0.95 of the GT plate polygon.
- **D-score:** the unweighted mean of full-plate exact recall, partial-query contains precision and partial-query contains recall.
- **Query classes** (full, state/RTO prefix, last-4-digit suffix, 5-character interior, matched negatives at edit distance 1–2), with negatives counting toward precision only.
- **Consistent-wrong limit:** 2 %. **Budget:** CPU per-Track p95 ≤ 2 s at ≤ 4 crops.
- **Normalisation:** v1 only, no confusable substitution.

## 3. Diagnostic-only values

- OCR floors {0.3, 0.5, 0.7}.
- The interval-excludes-zero power curve.
- Per-stratum results (support < 50 ⇒ INSUFFICIENT_EVIDENCE; this invalidates nothing unless a stratum is a frozen gate).
- C − B, B top-k hit, risk–coverage, per-cluster ΔD and the cluster sign count.
- Detector-matched OCR uplift, D(PDx + OCy) − D(PDx + OC5) (N2 revised).
- Below-floor proposal counts, the conflicting rate, the no-text rate, and the conditional consistent-wrong rate.

## 4. Proposed frozen values (protocol drafting; for cold review 1, not owner-decided)

- **ECE:** 10 equal-mass bins over the total order (confidence descending, then plate id). The input order does not matter.
- **Bootstrap:** percentile 95 % interval at indices ⌊0.025·(R−1)⌋ and ⌈0.975·(R−1)⌉ of the sorted exact replicates.
- **§8.1 coverage tolerance:** the minimum site count at which the zero-difference coverage is ≥ 0.93 (PR-2 protocol §7.1).

## 5. Still-open values (required parameters; fixed in the PR-2 protocol before freeze)

- Query interior offset, negatives per plate, query seed.
- Bootstrap replicates and seed.
- `required_clusters`, from the §8.1 calibration on the declared site structure.
- The population/partition manifest SHA-256 (exists only after the corpus is captured, labelled and partitioned).
- The Stage-1 baseline freeze: the eligible detector identities, the OC5 identity and the Layer-A gate-set hash.

**Not a frozen value:** the PD_BASE identity. It is a Stage-2 derived value, sealed after Layer A and before D (§1, N2 resolution).
