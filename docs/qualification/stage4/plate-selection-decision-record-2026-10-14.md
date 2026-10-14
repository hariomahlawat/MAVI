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
| N3 (revised) | 2026-10-14 (supersedes the 2026-10-13 wording) | Consistent-wrong uses **rank-0 readings only**. This aligns N3 with the frozen product summary `plate-track-text-rank0` / `distinct-rank0-normalised-text`, and stops a recogniser from evading the gate with varying low-ranked alternatives. For each evaluable GT plate-bearing Track with supported normalised truth:<br>(1) consider only contract-valid rank-0 readings of `Read` plate observations under the ranking profile;<br>(2) normalise each with v1;<br>(3) the Track is eligible only with valid normalised rank-0 readings from ≥ 2 distinct source observations;<br>(4) it is consistent-wrong iff **all** qualifying rank-0 readings from **all** such observations share one normalised text, that text ≠ the truth, and no qualifying rank-0 equals the truth. No favourable subset of observations is chosen.<br>**Lower ranks (rank > 0) never trigger or rescue N3.** They stay in declared diagnostics such as the top-k hit.<br>An observation with no `Read` result, or whose rank-0 does not normalise, gives no support.<br>**Primary rate:** consistent-wrong Tracks / all evaluable GT plate-bearing Tracks with supported truth. **Limit:** ≤ 2 %. **Support:** < 50 ⇒ `INSUFFICIENT_EVIDENCE`.<br>**Conditional rate** (diagnostic only): consistent-wrong Tracks / Tracks with valid rank-0 readings from ≥ 2 observations.<br>A run with a contract violation is `CONTRACT_FAIL` first, and N3 is never computed through it. Code: `_rank0_sources`, `_counts` |
| N4 | 2026-10-13 / 14 | Top-K only from a common, predeclared, **demonstrably independent** population; `unknown` exposure is not independent. **Detector order:** A, then lower false plates per crop, then AP50. Within top-K the lexical id breaks ties. **For PD_BASE, equal rank keys among the passing detectors STOP the event** (N2 addendum and M3; no id tie-break; rule `mavi-plate-detector-rank-v2`). **OCR tie-break:** EM, then lower CER, then lower ECE, then lexical id |
| N5 | 2026-10-13 | P14 tolerance: \|D(PR-2) − D(PR-6 product path)\| ≤ 0.02, with identical semantics and no hard-gate reversal |
| N6 | 2026-10-13 | Profiles: `plates-dev-windows-x86_64-cpu-v1` (required), `plates-dev-linux-x86_64-cpu-v1` (required reproducibility/CI), `plates-dev-windows-x86_64-cuda-sm75-4gb-v1` (informational) |
| N7 | 2026-10-13 | Fine-tuning trigger 0.85 (Indian one-line full-plate EM) preserved, and recorded NOT_MEASURED while support is < 50 |
| N8 | 2026-10-13 | D only on a **fully labelled, closed** population. **Exact recall:** supported, queryable GT plate-bearing Tracks. **Contains recall:** deterministic positive Track–query pairs. **Contains precision:** all returned Track–query pairs. **Truth semantics (owner, 2026-10-14):** `TEXT` = human truth that normalises under v1 (unchanged) AND whose normalised text has at least one `[A-Z]` and one `[0-9]`. Any other non-reserved human text is **retained** as `UNSUPPORTED_TEXT`, never refused (raw text and Track kept; excluded only from the positive-recall denominators; every emitted prediction against it has correctness 0 for precision, ECE, risk–coverage and every other prediction-conditioned metric, and is never dropped from them). `NO_PLATE`, `UNREADABLE` and `NO_GT_VEHICLE` carry no text. An unknown or misspelt **state** fails closed. **Reserved syntax** supplied as text is malformed input and refused: a truth-state name (case, whitespace, `_`, `-` ignored) or `<`…/…`>` control syntax; there is no placeholder-word blacklist. The typed state is authoritative after parsing: no metric re-normalises raw truth |
| N9 | 2026-10-13 | No result-driven stopping. One rerun only, for a proven infrastructure/harness failure with identical bytes and configuration. Contract, offline, determinism, persistent runtime and resource failures are FAIL. If fewer than two non-baseline candidates remain evaluable per capability, the event returns to PLANNED |
| Contract (items 8/11) | 2026-10-14 | **Any** candidate output-contract violation is a **hard CONTRACT_FAIL** for the evaluation run, across A, B, C and D. Harness validators wrap the candidate detector and recogniser (`detector_output_violation`, `recogniser_output_violation`). Covered:<br>- more than 2 proposals; a box that is not a `PlateBox`, not integer, degenerate or outside the crop; a non-finite or out-of-range score;<br>- more than 3 readings; an item that is not a `Reading`; invalid raw text; a confidence outside [0, 1]; a non-strict rank order;<br>- a detector or recogniser exception.<br>The exact evidence is kept (code, observation, item, exception type), and nothing is scored through it, truncated or treated as one bad Track. A runtime exception is a FAIL under N9. The one permitted rerun, for a proven infrastructure fault with identical bytes and configuration, is a recorded procedural decision.<br>**Product vs bake-off (no conflict):** PR-3's product keeps its own rule. For example, a duplicate or non-strict reading sequence is a per-crop `ocr_output_invalid` abstention, and the rest of the run publishes. The harness leaves that product behaviour unchanged (tested). The bake-off separately judges the candidate, and any output outside the contract fails it. The two answer different questions (service availability vs candidate conformance), and a candidate that fails here never reaches the product path, so P14 is unaffected |
| Cluster unit (item 4, C2) | 2026-10-14 | One independent top-level cluster = **one physical capture site**. Sequences, windows, Tracks, repeated visits and clips from a site are nested, not independent. Several cameras at one site are one cluster. A camera moved to a genuinely distinct site may be reused there |
| C1 | 2026-10-14 | Corpus plan: 20 independent sites for A/B selection + `required_clusters` independent sites for protected D. A predeclared extension up to 100 total sites is allowed for corpus reasons fixed before candidate execution only. Stop and return to the owner if the design exceeds 100 sites, ≈ 3,000 labelled vehicle Tracks or ≈ 500 annotation/QA hours |
| C3 | 2026-10-14 | Per site, before annotation or candidate execution: one fixed ROI, one **30-minute** contiguous primary window, and the predeclared schedule rule that chooses it. No choice by traffic, readability, candidate or OCR behaviour. Every qualifying vehicle crossing the ROI in the window is in the closed population. **No small-box exclusion** |
| C4 | 2026-10-14 | Two independent primary annotators, blind to candidate outputs, PR-1 instrument OCR outputs and PD1 labels. Third-person adjudication for text/outcome disagreements. Independent QA of geometry and Track association. Organisational, data-controller and privacy approval before capture. Controlled, non-public data under an explicit retention/access/audit policy |
| Outcomes (item 8) | 2026-10-14 | `TEXT`; `NO_PLATE` (truth = no text); `UNREADABLE` (text not establishable by the frozen human rule: excluded from known-truth scoring terms, its prevalence and returned pairs are counted); `NO_GT_VEHICLE` (a MAVI Track with no GT vehicle: a false Track, never conflated with `NO_PLATE`); `UNSUPPORTED_TEXT` (item 10) |
| Unsupported truth (item 10) | 2026-10-14 | The typed state `UNSUPPORTED_TEXT`: human text outside v1 OR outside the letter-and-digit rule. Kept in the closed population with its raw text and counted. Excluded only from positive-recall denominators (D exact/contains recall; B/C EM, CER and top-k hit). Any prediction against it is wrong: D precision, and B/C ECE and risk–coverage (whose coverage denominator is every plate). The harness DERIVES it from document state `TEXT`; the documents cannot write it |
| Letter-and-digit rule | 2026-10-14 | **ACCEPTED (owner).** A Stage-4 **corpus-level** eligibility rule for `TEXT`: the v1-normalised text must contain at least one `[A-Z]` and one `[0-9]`. It is **not part of Normalisation v1**, which is unchanged (`6e505158…bf935`); it only decides `TEXT` vs `UNSUPPORTED_TEXT` |
| Query binding (item 12) | 2026-10-14 | A query set records the population/partition manifest SHA-256, the generator-configuration SHA-256 and the query-set SHA-256. D queries are generated inside the evaluator from the verified bundle (typed TEXT truths and the committed record's query configuration), bound to the protected-D partition digest; no caller query set is accepted (§4a) |
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

- **ECE:** 10 equal-mass bins over the total order (confidence descending, then plate id): item k of n goes to bin ⌊k·10/n⌋, so bin sizes differ by at most one (empty bins skipped when n < 10). Plate ids must be unique, so the order is total and the input order does not matter.
- **Bootstrap:** percentile 95 % interval at indices ⌊0.025·(R−1)⌋ and ⌈0.975·(R−1)⌉ of the sorted exact replicates.
- **§8.1 coverage tolerance:** the minimum site count at which the zero-difference coverage is ≥ 0.93 (PR-2 protocol §7.1).

## 4a. The trust boundary (owner instruction, 2026-10-14; supersedes the review-6/7 manifest boundary)

**Scope.** #218 is the level-1 A–D / query harness only. The M3 pre-D seal integration (committed baseline seal, Git
chronology and M3's committed Layer-A document) is a **MANDATED follow-up PR** that must merge before PR-2 cold review 1
and `PROTOCOL_FROZEN`.

**Governing invariant (owner, verbatim).** "For fixed frozen canonical protocol/corpus bytes and fixed candidate
outputs, no caller-controlled object, subclass, property, method, iterable, parser ambiguity, configuration value,
ordering, seed, partition representation, or mutable state may alter population membership, eligibility, evidence,
partition assignment, candidate eligibility, or any A/B/C/D result."

**Why the manifest boundary was replaced.** The review-6/7 boundary hashed caller-supplied Python objects through
their own methods and properties (`row()`, `supported_text`). An `isinstance`-passing subclass could keep the digest
while changing D, the seeds, the evidence bytes or the partition (convergence review at `e62b947c`, probes `cold218g`).
Patching each exploit would leave the class of attack open, so the boundary was re-architected.

**One boundary:** canonical bytes → identity verification → strict parse → harness-owned immutable state → A/B/C/D.

1. **Independent identity: a committed freeze record** (`selection_bundle.FREEZE_RECORD_PATH` =
   `config/benchmarks/plates/selection-freeze-v1.json`, a fixed repository path).
   - The loader reads the record itself. It must be tracked by Git and its working-tree bytes must equal the HEAD blob
     (Git's own blob identity), so an uncommitted edit is never the record.
   - The record binds every score-affecting value:
     - the protocol: query parameters and seed, bootstrap seed, R = 1,000, the percentile rule, MPID 4/100, the
       calibration minimum, K = 3, the support floor 50, and one pinned floor per rostered detector;
     - the rosters: the detector and recogniser universes with identity SHA-256s, OC5 benchmark-only (excluded from
       both, no identity under two ids), the ranking rule, the Layer-A gate set, the events and the freeze time;
     - the site-level partition plan;
     - the SHA-256 of each of the four corpus documents (A/B index, A/B truth, D index, D truth).
   - The pinned values are also code constants; any other value is refused.
   - **Choice and trade-off.** A committed file is reproducible and reviewable in Git history. It needs no new
     service or dependency: Git is already a repository prerequisite. The caller cannot pass the content and the digest
     that blesses it side by side. The cost is that `repo_root` is a loader argument, which tests need. In production it
     defaults to the harness's own repository, and every result carries the record SHA-256 and the HEAD commit.
2. **Strict parsing.** A document must match its frozen SHA-256 byte for byte. It is then parsed strictly:
   - ASCII only;
   - duplicate keys refused (`object_pairs_hook`), NaN/Infinity refused;
   - the canonical re-serialisation must reproduce the exact bytes. The canonical form is sorted keys, `,`/`:`
     separators, `\uXXXX` escapes, the shortest round-trip float, and one final LF. So whitespace, key order, number
     forms, escapes, a BOM and CRLF each have no second representation;
   - every object has exactly its schema keys with exact primitive types (`bool` is not an `int`);
   - every array is in canonical order.
3. **Harness-owned state.**
   - Verified primitives become private immutable objects in a private registry. A `Bundle` is a handle: only its
     `bundle_id` string is read.
   - Truth is typed once (`classify_truth`). `TruthState` is authoritative afterwards: B/C/D never re-normalise raw
     truth.
   - **The paired bundle (R2).** The A/B and protected-D partitions are verified together under one plan:
     - sites are mutually exclusive, with case and whitespace aliases refused;
     - Track ids, MAVI uuids, observation ids and content SHA-256s (evidence and B plate images) are unique across
       both partitions.
   - **Stages.**
     - `load_selection_bundle` reads the D *index* (truth-free) for these checks, but never the D truth.
     - `load_protected_d_bundle` also reads the D truth. Loading it ends Stage 2: `resolve_baseline` then refuses
       for that record in the process.
4. **Execution envelopes** (`run_track`, `run_detection`, `run_reading`) take a bundle and an item id, never evidence.
   - The identity must be a roster entry by id AND identity SHA-256 (R3).
   - The image source must return exact `bytes` matching the frozen SHA-256 and size.
   - The candidate's outputs must be exact types (list/tuple, `PlateBox`, `Reading`, `str`); anything else is a
     CONTRACT_FAIL.
   - A protected-D Track runs only from the protected-D bundle.
5. **Results are harness records**, not sealed caller objects.
   - Each run and result is recorded in a private registry. The caller receives a deep copy carrying `result_id`.
   - Metrics and decisions read only that id string and use the registry's own record. So edits, subclasses,
     properties, `object.__setattr__` and mutable fields on a copy are inert, and an unregistered object is refused.
   - Every run/score/result iterable is materialised once at entry (R1).
   - Item ids must equal the bundle projection exactly.
   - Compositions must be in the frozen rosters (R3).
   - A/B/C use only the A/B partition and D only the protected-D partition.
6. **Unchanged semantics:**
   - D-score (N8, with the `UNSUPPORTED_TEXT` clarification above) and silence = 0;
   - CONTRACT_FAIL;
   - MPID 0.04 exact and the superiority rule;
   - N3 rank-0;
   - the single PD_BASE + OC5 gate with two-stage resolution (ambiguous → STOP);
   - the two-stage bootstrap with R = 1,000 and percentile indices (24, 975);
   - queries.

   R, the seed, MPID, K, the support floor and the calibration minimum are no longer parameters anywhere.

**Remaining caller-provided values (complete):**
1. the candidate under test: its callables (so its outputs) and its asserted identity, which must equal a roster entry;
2. the image byte source (verified by SHA-256 and size);
3. the corpus directory (verified against the committed record);
4. the N4 `independent` verdict and Layer-A `gates_passed` (mandated M3 integration);
5. `resolve_baseline`'s self-attested `d_rows_read` and `resolved_at_utc`. Binding them to Git chronology and the
   committed pre-D seal is an M3-chronology integration item; the in-process D-truth-loaded check is an extra guard;
6. `repo_root`, for tests only (default: the harness repository).

The real committed record and corpus documents are an **integration prerequisite before the PR-2 freeze**. The record
path does not exist yet, and the loader refuses (`freeze_record_absent`).

**Disclosed limit.** Code running in the same interpreter can still write the private registries (`_register`,
`_BUNDLES`). The boundary protects reproducibility through the supported API, not against in-process code.

**Layer-A artefact** (`layer_a_result_document`): canonical JSON + LF with M3's per-partner keys and
`evidenceSha256` = the A/B partition digest. M3's event-level fields and per-gate dictionary are reconciled in the
integration PR.

**History (superseded by the boundary above; kept for traceability).** Review 6 added alias-item refusals, frozen
top-K values, C any-violation and `c_minus_b` pairing. Review 7 added site-disjoint partitions, `UNSUPPORTED_TEXT`, the
recogniser universe and P3 validations. All are retained as checks on the verified documents (tests in
`test_plates_selection_harness.py` and `test_plates_selection_boundary.py`). The review-7 "letter-and-digit refusal"
became a classification rule (above). The review-7 placeholder refusals (`NOPLATE0`, `[UNREADABLE]`) are withdrawn:
reserved syntax is defined narrowly.

## 5. Still-open values (required parameters; fixed in the PR-2 protocol before freeze)

- Query interior offset, negatives per plate, query seed.
- The bootstrap seed and query seed values (frozen in the committed freeze record; R is fixed at 1,000).
- `required_clusters`, from the §8.1 calibration on the declared site structure.
- The committed freeze record and the four corpus document SHA-256s (exist only after the corpus is captured,
  labelled and partitioned).
- The Stage-1 baseline freeze (in the record's roster): the eligible detector and recogniser identities, the OC5
  identity and the Layer-A gate-set hash.

**Not a frozen value:** the PD_BASE identity. It is a Stage-2 derived value, sealed after Layer A and before D (§1, N2 resolution).
