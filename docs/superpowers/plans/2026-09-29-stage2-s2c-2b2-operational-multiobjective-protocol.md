# Stage 2 S2c.2b-2 — Operational and Multi-objective Protocol

**Status:** Revised draft implementation plan — updated after independent Astra architecture review and Claude repository-grounded cold review; not governing until final bounded review, acceptance, exact-head CI and merge.  
**Date:** 2026-09-29  
**Starting baseline:** `main@7d97cca565098bf1bef9a48122e01540ec5a37db` (PR #120 merge; S2c.2b-1 governing).  
**Scope:** planning/protocol design only. No model is selected, downloaded, trained, calibrated or benchmarked. No F/G acceptance row changes.  
**Governing authorities:** ADR-013, ADR-014, Stage-2 parent plan, Stage-2 qualification plan including R1/R2/R3, the Stage-2 acceptance register, MSR method v1 + M1, and the governing S2c.2b-1 quality/statistical protocol and machine contract.  
**Independent design input:** Astra architecture review of PR #121 at `03462d4`; Claude cold review of revised PR #121 at `e706b2f`. Their valid findings are reconciled here.

---

## 1. Purpose

S2c.2b-1 defines trustworthy quality evidence but deliberately stops before operational selection. S2c.2b-2 must convert already-frozen measurements into an auditable technical decision without:

- trading failed or unresolved quality for lower cost;
- assuming transitivity of pairwise non-inferiority/equivalence;
- treating Tracks as independently schedulable work;
- hiding person/vehicle runtime coupling;
- using a weighted utility score;
- turning owner preference into statistical evidence;
- overstating a 500-camera projection as qualification.

The governing decision architecture is:

> **freeze complete experiment → pre-screen label-free engineering infeasibility → per-capability absolute gates → MPID filter → direct quality protection against the complete eligible comparison set → joint person×vehicle operational evaluation → constrained deployment selection → preserve genuine ties and unresolved outcomes**

---

## 2. Non-goals

This slice does not:

- choose any real candidate or composition;
- invent event-specific numerical owner targets;
- execute models or expose selection/frozen-test data;
- change the S2b worker/lifecycle/lease plane;
- make CUDA mandatory;
- change b-1 populations, partition authority, statistical outcomes or gate forms;
- promote any acceptance row;
- create a generic optimization or simulation framework.

---

## 3. Authority boundary

### 3.1 b-1 remains authoritative

b-2 consumes but does not redefine:

- S/U/I/A;
- post-aggregation Track calibration;
- training/tuning/selection/frozen-test authority;
- paired cluster-aware comparison;
- support sufficiency;
- practical/non-inferiority/equivalence margins;
- outcomes `superior`, `non-inferior`, `equivalent`, `inconclusive`, `insufficient-evidence`;
- owner quality targets frozen before selection;
- no frozen-test tuning, ranking, replacement or rescue.

### 3.2 Explicit disposition of all fifteen b-1 deferred subjects

| Deferred subject | b-2 disposition |
|---|---|
| operational-performance | **Defined** — §§7–10, 17 |
| whole-job-cpu-host-gates | **Defined** — §§7, 9, 17 |
| composition-resource-accounting | **Defined** — §§10, 16 |
| 10k-track-deadline-mechanics | **Defined** — §§7–8, 17 |
| 500-camera-projection | **Defined** — §§11, 17 |
| pareto-axes | **Retired as governing selection mechanism** — diagnostics only; replaced by §§13–16 |
| pareto-directions | **Retired as governing selection mechanism** |
| pareto-normalization | **Retired** — no normalization/utility score |
| dominance-semantics | **Retired as governing selection mechanism** |
| disabled-attribute-frontier-treatment | **Replaced** — required disabled attribute fails the capability scope before selection (§10.2) |
| non-dominated-set-construction | **Retired as governing selection mechanism** |
| sub-task-finalist-ordering | **Retired** — replaced by predeclared bounded composition manifest (§10.3) |
| final-technical-selection | **Defined** — §§13–18 |
| msr-final-ranking-representation | **Defined** — M2 / decision-v2 in §20 |
| historical-weighted-ordering-reconciliation | **Defined** — §21 |

No deferred subject remains implicit.

---

## 4. Design principles

1. **Direct quality protection.** No candidate reaches deployment selection by eliminating the comparator against which it would fail quality protection.
2. **No transitivity assumption.**
3. **Complete candidates before selection.**
4. **Actual compositions, not component arithmetic.**
5. **Joint runtime reality.** Person and vehicle quality remain separate, but final operational selection is over the pair because the bound identity and worker execute both capability packs in one process.
6. **Operational constraints before optimization.**
7. **One frozen deployment objective.**
8. **Set-valued outcomes are valid.**
9. **Projection is not qualification.**
10. **Owner decisions do not rewrite evidence.**
11. **Licence/credibility remain separate from technical evidence.**

---

## 5. Canonical b-2 machine contract

Implementation creates:

`docs/qualification/model-selection/s2c-operational-selection-contract.json`

with:

- `schema = mavi-s2c-operational-selection-v1`
- `method = s2c-2b2`

Exact top-level sections:

- `schema`
- `method`
- `prerequisite`
- `experimentFreeze`
- `wholeJob`
- `hostProfile`
- `workloadFamily`
- `compositionAccounting`
- `qualityDecisionClaims`
- `mpidExtensionRule`
- `scaleProjection`
- `jointOperationalSelection`
- `finalSelection`
- `msrRepresentation`
- `historicalOrdering`
- `ownerInputs`
- `frozenInvariants`
- `invariantStatements`

The Markdown protocol contains one deterministic protected projection from the contract and is byte-compared like b-1.

### 5.1 Cross-contract enforcement

The validator must load b-1 and prove:

- every current b-1 deferred subject has one explicit disposition;
- no b-2 field redefines b-1 authority;
- `PROTOCOL_FROZEN` requires both b-1 and b-2 ids/hashes;
- no S2c event uses weighted `comparativeScore` as technical authority;
- no frozen-test result enters b-2 selection inputs.

---

## 6. Freeze complete experiment before selection

Before any selection result is read, freeze:

- exact candidate/component identities;
- exact executable configurations;
- target capability scope per event;
- complete person composition manifest;
- host class/profile;
- workload family;
- owner quality gate table and margins;
- **decision-claim set Q_c for each capability**;
- direction of every claim in Q_c;
- one simultaneous-inference family per event covering all ordered candidate pairs × decision claims;
- operational constraints;
- deployment objective;
- MPID claim(s) and margin;
- existing-graph candidate designation;
- **predeclared `MPID_COMPARATOR_UNAVAILABLE` disposition** for each extension route (`exclude-pending-ADR` by default unless an already-governing route explicitly admits it);
- **per-capability fallback operational unit** for the joint stage if `F_c` is empty: either a packageable gate-passing baseline or a predeclared disabled-capability identity/scope with its own valid schema/identity;
- E1/E2/E3 evidence obligations;
- joint person×vehicle operational decision schema;
- licence target profiles;
- revision invalidation rule;
- freeze commit/hash/date bound to the sealed S2c.1 evaluation-view date. Freeze-before-selection-data access remains a reviewed protocol attestation until the S2c.3 harness provides a hash-chained first-selection-read record; if that record is implemented, it becomes the preferred machine evidence.

A result-informed revision that changes candidate inclusion, claims, margins, objective or composition manifest does not become unbiased by rerunning the same exposed selection data. Affected confirmatory evidence needs a fresh evaluation basis or later event.

---

## 7. Whole-job operational-performance contract

### 7.1 Scheduling unit and capability coupling

The S2b scheduling unit is one analysis of one ProcessingRun under one bound attribute identity. The bound identity includes the required person and vehicle capabilities and their Model Pack identities. One worker process holds one unit.

Therefore:

- **quality evaluation remains per capability/event**;
- **final whole-job resource, memory, queueing and fleet selection is over a person×vehicle implementation pair**.

Per-capability operational measurements may be retained as diagnostics/pre-screen evidence, but final host-count or whole-job selection is not computed independently for person and vehicle.

### 7.2 Lifecycle timestamps and their source

Retain/derive:

- `queuedAtUtc` / job available — platform persisted;
- `firstClaimedAtUtc` — platform persisted;
- `attemptClaimedAtUtc` — worker/harness instrumentation, tied to claim response;
- `leaseExpiresAtUtc` — platform persisted;
- `phaseAValidatedAtUtc` — harness/platform instrumentation around successful Phase-A response; not currently a durable platform field;
- `publicationCommittedAtUtc` — harness/platform instrumentation around Phase-C commit;
- `completedAtUtc` — platform persisted;
- `completionAcknowledgedAtUtc` — client/harness instrumentation;
- `readyAtUtc` — worker/supervisor instrumentation;

Every lifecycle instant above is an absolute UTC instant named with the `...Utc` suffix (AGENTS.md time naming); durations are derived from these instants, never from local wall-clock values.
- attempt failures — platform persisted where the current lifecycle records them.

The implementation record must distinguish persisted platform evidence from harness instrumentation.

### 7.3 Exact lifecycle semantics to replay

The replay must match current S2b semantics:

- FIFO claim order by `queued_at_utc, id`;
- retryable requeue preserves original `QueuedAtUtc`;
- one unit per worker process;
- identity fence respected;
- attempt consumed at claim;
- maximum attempts from the frozen lifecycle policy;
- worker/process loss becomes reclaimable only after lease expiry and subsequent claim;
- no claim or reclaim is permitted at or after the first-claim analysis deadline;
- every lease is capped at the first-claim analysis deadline;
- Phase A requires a live lease and therefore must occur before the deadline;
- protected publication window follows successful Phase A and is capped at deadline + one lease duration as currently defined;
- successful Phase-C publication commit and acknowledgement are distinct; for a unit in `Completed`, persisted `CompletedAtUtc` records the Phase-C transaction time, while acknowledgement is client/harness evidence;
- no unimplemented partial-progress/checkpoint reuse is assumed.

### 7.4 Performance views

Report separately:

1. boot-to-READY;
2. claim-to-Phase-A;
3. claim-to-publication;
4. available-to-publication;
5. publication-to-acknowledgement.

A protected publication after D but within the valid publication window remains lifecycle-valid. A stricter owner SLA may still fail separately.

### 7.5 Warm whole-job gate

The primary warm CPU gate is claim-to-publication for frozen workload shapes on the pinned joint runtime topology.

It includes evidence read/verify/decode, admissibility, preprocessing, inference, aggregation, artefact construction/upload, completion and publication.

Per-crop/per-Track latency remains diagnostic.

### 7.6 Recoverability gate

The protocol freezes required failure scenarios. Each required scenario must still satisfy:

- Phase-A before the frozen lifecycle deadline;
- publication inside the valid publication window;
- owner recovery/publication SLA, if stricter;
- attempt bound.

Explicit fail and hard process/host loss are modelled separately where both apply.

---

## 8. Workload family and 10k boundary

Freeze a workload family containing:

- representative typical jobs;
- small-job burst;
- demanding feasible 10k-Track boundary job;
- mixed person/vehicle jobs;
- failure/recovery scenario;
- workloads needed for the 500-camera envelope.

Each definition records:

- job/run count;
- Tracks per job by capability;
- person/vehicle mix;
- crops/Track distribution;
- crop-size/byte distribution;
- release cadence;
- initial backlog;
- any synchronized busy-period trace.

10k remains a hard capacity/resilience boundary, not the sole operational workload.

---

## 9. Host class and topology

The deployment objective is valid only on a frozen host class.

Freeze:

- host class/id;
- CPU model;
- cores;
- RAM;
- OS/build;
- Runtime Pack/lock;
- storage/evidence path;
- detector co-residency state;
- worker-process range allowed for topology search;
- inference/runtime thread settings;
- power/performance policy where material.

Mixed host classes are not allowed in S2c b-2 selection unless the owner explicitly freezes a cost-normalized multi-class objective. Default S2c uses one host class.

Topology search operates only over predeclared worker/process counts and uses **unlabelled engineering evidence**. It does not tune model outputs.

---

## 10. Composition accounting and baselines

### 10.1 Exact compositions

For person attributes, quality/resource evidence refers to exact executable compositions.

Record component identities, shared backbone, heads/training manifests, region component, enabled attributes, Runtime Pack family, service distributions, memory, startup, pack/runtime bytes and failure domain.

### 10.2 Capability scope and disabled attributes

Use the term **capability scope** for the frozen required attribute set, distinct from licence deployment profiles.

A candidate/composition with a disabled required attribute because a b-1 gate failed is ineligible for that capability scope.

A partial capability scope is allowed only if separately predeclared before selection.

### 10.3 Person composition manifest

Freeze a bounded composition manifest before selection.

Preferred rule:

- enumerate every compatible composition from the admitted component shortlist when tractable;
- explicitly include intended shared-backbone combinations;
- train composition-specific/shared heads on training data;
- tune allowed parameters on tuning data;
- freeze exact executable compositions before selection.

K=3 from the parent plan becomes a planning/experiment-budget parameter, not a statistical top-K pruning law. No component is discarded after selection results by standalone rank.

For larger products, the subset is fixed before selection and the search-completeness limitation is recorded.

Label-free operational infeasibility may prune a composition **before selection** only under frozen candidate-independent engineering limits.

### 10.4 Baselines

- **PO-B0** remains a non-packageable statistical floor only. It is never a member of E and cannot be selected.
- **PC-B0** and **VC-B0** are packageable colour baselines and may enter their applicable E sets like any other packageable candidate/composition if they pass applicable gates.
- A packageable baseline selected under the technical rule is represented as the implementation candidate with the MSR outcome `BASELINE_SELECTED` where the methodology requires that outcome.
- Baseline/reference measurements never delete comparison obligations for learned candidates unless the frozen protocol explicitly defines them as non-selectable references.

---

## 11. 500-camera methodology

### 11.1 Level 1 — fluid service-demand screen

Use:

`W[t+1] = max(0, W[t] + A[t] - C[t])`

where A and C are **job-service demand/capacity**, not raw Track counts.

Use only for:

- coarse instability detection;
- initial host lower-bound screening;
- reserve/headroom intuition;
- rough drain bounds.

Never use it as proof of job deadlines.

### 11.2 Level 2 — deterministic analysis-job replay

Implement a bounded standard-library discrete-event helper with fixed event ordering.

For a healthy worker:

`start[j] = max(available[j], workerFree[w])`

`finish[j] = start[j] + service[j,w]`

Extend only for the actual S2b semantics in §7.3:

- FIFO queue;
- claim polling;
- attempt consumption;
- lease expiry/reclaim;
- explicit failure;
- process loss;
- restart/READY;
- host loss;
- lost work;
- Phase A;
- publication.

No generic scheduler/simulator.

### 11.3 Owner workload envelope

Freeze:

- target camera count;
- camera classes/proportions;
- correlated busy periods;
- run duration/release cadence;
- jobs/interval;
- Tracks/job by capability;
- Evidence Set counts/sizes;
- initial backlog;
- burst traces;
- failure timing/duration;
- reserve policy;
- maximum installed hosts;
- memory/IO/API constraints;
- queue-age/backlog/drain limits.

### 11.4 Required measurements

Measure on exact candidate pairs/topologies:

- warm/cold startup;
- service distributions by job shape;
- 10k boundary;
- feasible worker concurrency;
- active co-residency;
- evidence-read demand;
- upload/publication demand;
- heartbeat behaviour;
- explicit-failure recovery;
- process-loss recovery;
- host-loss recovery;
- joint memory including restart transients;
- deployment/storage growth.

Do not derive job p95 by multiplying per-crop p95.

### 11.5 Projection outputs

Report:

- installed/active hosts;
- workers/host;
- completed/failed/retried jobs;
- waiting jobs;
- unfinished Tracks;
- oldest queue age;
- queue-to-publication latency;
- Phase-A deadline misses;
- owner-SLA misses;
- peak backlog;
- peak/post-failure drain;
- memory/IO/API bottlenecks;
- deployment footprint;
- sensitivity to workload/service assumptions.

### 11.6 Validation

Freeze projections before E3 validation.

Use held-out engineering traces distinct from traces used to calibrate the operational model.

Require one-sided protection against dangerous underprediction plus any declared symmetric tolerance.

If validation fails:

- candidate-independent model error → numbered method revision; recompute all admitted pairs consistently from unchanged E2 evidence where valid;
- candidate-specific mismatch → affected pair becomes `TECHNICAL_EVIDENCE_INCOMPLETE` and the event reopens; no silent alternative rescue.

Permitted claim: projected capacity for the declared 500-camera envelope validated at stated executed loads/hardware.

---

## 12. Evidence stages

### E1 — isolated bake-off
Model-quality and diagnostic engineering evidence from the evaluation harness.

### E2 — joint selection-stage operational evidence
For every pair that can still affect the technical decision, run the **real S2b attribute runner against a local/qualification platform path** under the frozen identity/topology sufficiently to measure the service/resource quantities used by the joint operational model.

Before S2c.7 production adapters exist, E2 uses the runner's existing `AttributeInferencer` seam fed by the S2c.3/S2c.4 candidate-runner implementation; this is evaluation plumbing, not a release binding. The parent-plan S2c.3/S2c.4 rows must be reconciled so that this E2 responsibility is explicit.

E2 must not require Production qualification, but it must use the real lease/evidence/upload/completion semantics for quantities that claim whole-job meaning.

### E3 — integrated S2c.9 validation
Selected/tied pair(s) execute multi-worker and, where available, multi-host validation against held-out engineering traces, including projection validation and combined-role deployment.

E2 estimates are never labelled E3 execution.

---

## 13. Per-capability eligibility E_c

For each capability c ∈ {person, vehicle}:

1. begin with the frozen manifest M_c;
2. apply label-free pre-selection engineering exclusions;
3. apply applicable absolute b-1 quality/support gates;
4. apply applicable component/capability engineering gates that do not depend on the final joint pair;
5. apply the MPID extension filter in §14.

The result is E_c.

Rules:

- missing mandatory evidence is not a pass;
- insufficient support remains insufficient evidence;
- disabled required attributes exclude the candidate;
- licence/credibility do not affect E_c;
- PO-B0 is never in E_presence;
- reported evidence cannot satisfy measured gates.

---

## 14. MPID / architectural-extension filter

An extension candidate x enters E_c only if it satisfies the frozen MPID rule **before** F_c is computed.

### 14.1 Comparator chain

1. Let G be the existing-graph candidates in the same frozen manifest that passed the same absolute b-1 SG5/SG6 gates.
2. If any member of G remains technically eligible apart from the extension issue, compare x against every such member on the frozen MPID claim(s).
3. If none remains, use every existing-graph candidate in G that passed the quality gates as the comparator set.
4. If G is empty, outcome = `MPID_COMPARATOR_UNAVAILABLE`. The **predeclared protocol disposition frozen under §6** is applied. Unless an already-governing ADR-013 item 10 / parent §12.7 route explicitly admits the no-comparator case, the default disposition is `exclude-pending-ADR`: x is **not in E_c while pending**. No result-time owner decision may change E_c membership.

### 14.2 MPID pass

x passes only if:

- the frozen MPID claim(s) establish `superior` by at least the MPID requirement against every required comparator;
- all non-MPID required quality dimensions satisfy the same protection rule used elsewhere;
- normal operational/ADR/dependency gates still apply.

An extension candidate that fails MPID is removed before F_c and therefore cannot poison the quality-protection set.

---

## 15. Decision-claim set Q_c and simultaneous inference

### 15.1 Q_c

Each capability freezes a **small finite set of decision claims Q_c** before selection.

Q_c contains only claims that can legitimately block technical selection, for example:

- one declared primary quality claim per required attribute;
- specifically designated robustness-slice claims where owner policy makes them selection-critical.

Everything else remains an absolute gate or diagnostic.

Q_c must not mechanically include every reported metric/value/slice.

### 15.2 Direction

Every claim declares whether higher or lower is better. Lower-is-better quantities such as FPR, unsupported-assertion rates or calibration error are transformed/interpreted consistently before b-1 directional outcomes are recorded.

### 15.3 Simultaneous inference family

The event freezes one multiplicity/simultaneous-inference family covering:

- every ordered candidate pair that can enter E_c;
- every claim in Q_c.

No pair/claim is added after results are seen.

This is the b-2 use of b-1's predeclared multiplicity requirement.

The protocol also declares the intended relationship between the practical-superiority margin and the non-inferiority margin. If the chosen margins permit one candidate to be `superior` while the other is also `non-inferior`, that is treated as an intentional consequence of the frozen margins rather than an implicit tie-break.

---

## 16. Direct quality protection F_c

For every ordered pair a,b in E_c define:

`P_c(a,b) = true`

iff for **every q in Q_c**, the b-1 paired result for a relative to b on q is one of:

- `superior`;
- `non-inferior`;
- `equivalent`;

under the frozen simultaneous family.

Anything else, including `inconclusive` and `insufficient-evidence`, yields false for that q.

Then:

`F_c = { a in E_c : P_c(a,b) for every b in E_c, b != a }`

F_c is computed against the **complete original E_c**. No comparator is peeled away first.

### 16.1 Outcomes

- E_c empty → `NO_TECHNICALLY_ELIGIBLE_CANDIDATE`
- F_c empty → `NO_QUALITY_PROTECTED_TECHNICAL_CHOICE`

When F_c is empty, record whether the cause is:

- genuine supported trade-off;
- inconclusive evidence;
- insufficient evidence;
- mixed causes.

A noisy candidate that passed every absolute gate may legitimately block F_c if direct protection cannot be established. The remedy is adequate power/evidence, not silently deleting the comparator.

---

## 17. Joint person×vehicle operational stage

This replaces the old post-selection “combined-role check.”

### 17.0 Fallback operational units when `F_c` is empty

Each event freezes before selection one fallback operational unit under §6:

- a packageable baseline that passed its own applicable gates; or
- a predeclared **disabled-capability identity/scope** that is valid under the schema/binding rules and produces no false quality claim.

Define `J_c` as:

- `F_c` when `F_c` is non-empty;
- `{fallback_c}` when `F_c` is empty and the frozen fallback is operationally available;
- empty only when no valid fallback exists.

The event's original quality outcome remains unchanged: using a fallback in the joint runtime stage does **not** convert `NO_QUALITY_PROTECTED_TECHNICAL_CHOICE` into a quality pass or winner.

The joint product is evaluated over:

`u = (p,v) in J_person × J_vehicle`

If either `J_c` is empty, the joint outcome is `NO_OPERATIONALLY_COMPLETE_IDENTITY`; the healthy capability's quality/MSR result remains independently recorded.

For every pair in that product, construct the exact bound runtime identity/topology and use E2 measurements plus the frozen workload model to evaluate the pair jointly.

### 17.1 Joint constraints

Each pair must satisfy:

- whole-job warm gate;
- recovery/deadline gate;
- active co-resident memory;
- Runtime Pack compatibility;
- queue-age/backlog/drain limits;
- evidence/API/storage constraints;
- reserve policy;
- maximum host count;
- all owner SLAs;
- any required failure-domain constraint.

### 17.2 Primary deployment objective

The event must explicitly freeze the objective. Default proposed S2c objective:

> minimize supported installed host count on one frozen host class, including the frozen reserve requirement.

This is not silently assumed; it is a required protocol field.

### 17.3 Host-count uncertainty

For each admitted pair u derive:

- `H_lo[u]` — defensible lower bound on required hosts;
- `H_up[u]` — conservative supported upper bound on required hosts;

from the **same deterministic replay** under frozen lower/upper service-demand scenarios. At selection time the bounds use E2 measurement uncertainty plus the frozen error envelope calibrated on the designated calibration engineering traces; E3 held-out validation error is not known or used yet.

A pair is operationally admitted only if H_up is finite and all constraints pass.

Let:

`H* = min(H_up[u])`

over admitted pairs.

Define:

`T = { u : H_lo[u] <= H* }`

This preserves pairs whose supported host requirement overlaps the best conservative requirement.

### 17.4 Joint outcomes

- no admitted pair and required evidence missing → `TECHNICAL_EVIDENCE_INCOMPLETE`
- no admitted pair with complete evidence → `NO_OPERATIONALLY_FEASIBLE_PAIR`
- |T| = 1 → `UNIQUE_TECHNICAL_WINNER`
- otherwise → `TECHNICAL_TIED_SET`

Canonical ids may order presentation only.

---

## 18. Licence/profile filtering and owner boundary

Technical quality sets F_person/F_vehicle are computed **before licence filtering**. Joint runtime selection uses the effective sets `J_person` and `J_vehicle` from §17.0, so a frozen fallback remains available for deployment without altering the empty capability's quality outcome.

For each declared licence deployment profile r:

1. form the cleared pair set:
   `C_r = { (p,v) in J_person × J_vehicle : every required component/fallback unit is CLEARED or otherwise explicitly deployment-admissible for r under the frozen profile rule }`
2. a fallback unit may enter `C_r` only if its own frozen baseline/disabled-capability admissibility rule is satisfied for r; fallback use never changes the originating event's `E_c`, `F_c` or quality outcome;
3. apply the **same joint operational constraints and H_lo/H_up rule** over C_r;
4. derive `T_r`, the strongest supported cleared technical set for profile r.

Do not define strongest-cleared as merely T ∩ cleared; clearance may remove the unconstrained technical minimum.

For implementation, define:

`C_all = intersection over all required profiles r of C_r`

where fallback-containing pairs remain eligible only if every required profile admits that exact fallback unit.

**Implementation eligibility (MSR revision M1 §8, retained by M2).** Credibility is not a technical property: it never changes `E_c`, `F_c`, the quality outcome, `T` or any `T_r`, and an `emerging` member of `T` remains recorded as technically selected. It governs **only** which pairs may be implemented:

A unit is **implementable** when every learned component is `established` or `mavi-owned`, now and in the history entry in force on that event's decision-snapshot date (M1 §8). For a person composition the rule applies to **every** component. A packageable baseline is `mavi-owned`. A disabled-capability fallback has no component and is vacuously implementable. An `emerging` candidate needs a recorded promotion (M1 §7) dated on or before the decision snapshot; until then it is not implementable, however strong it is technically.

Implementation eligibility is decided per capability first, so that one capability's credibility or licence gap cannot block the other (the N1 principle):

`K_c = { x in J_c : x is implementable and CLEARED/admissible for every required profile }` when that set is non-empty; otherwise `K_c = {fallback_c}` if the frozen fallback (§17.0) is itself implementable and admissible for every required profile; otherwise `K_c` is empty.

The fallback is frozen before selection, so using it here is not result-time discretion, and it never changes the capability's `E_c`, `F_c` or quality outcome.

`C_impl = K_person × K_vehicle`

Apply the same §17.3 joint constraints and H_lo/H_up selection rule directly over `C_impl` to derive **`T_impl`**. If either `K_c` is empty, or no pair of `C_impl` is operationally admitted, `T_impl` is empty. `C_all` remains a credibility-blind reporting set: the pairs of `J_person × J_vehicle` cleared for every required profile. Do **not** intersect the separately optimized `T_r` sets, and do not intersect `T` with an implementability filter. As with licence, the filter is applied before the optimum is computed, so the best implementable pair is found rather than lost.

The implementation pair must belong to `T_impl`. The `T_r` sets remain per-profile reporting outputs (credibility-blind, like M1's strongest-cleared field). A pair that is merely absent from one profile's optimum is not disqualified if it is cleared for every required profile, implementation-admissible and supported by the `C_impl` optimization.

**When these sets exist (MSR README §3.2; M1 §8).** `C_r`, `T_r`, `C_all`, `K_c`, `C_impl` and `T_impl` depend on licence determinations and the decision snapshot, so they are computed at `QUALIFICATION_PENDING`, not at `TECHNICAL_DECISION_RECORDED`. An empty `C_r`/`T_impl` while any required licence status is still `NOT_ASSESSED` or `REVIEW_PENDING` is **pending**, not a conclusion. `NO_QUALIFIABLE_CANDIDATE` is recorded only when the event is `CLOSED` and `T_impl` is empty on final determinations (or the applicable MSR §8.2 unresolved action).

Owner may choose among the permitted cleared tied set but may not:

- waive gates;
- choose a pair outside `T_impl` (every unit of `T_impl` comes from `K_c`, which contains only `J_c` members or the frozen fallback; choosing the fallback leaves that capability's quality outcome unchanged);
- implement a non-promoted `emerging` candidate, or relabel it as not technically selected;
- name an implementation before `QUALIFICATION_PENDING`;
- reinterpret inconclusive/insufficient evidence;
- overwrite the technical result.

---

## 19. Revision semantics and E3 contradiction

A numbered revision must state whether it changes:

- candidate/composition manifest;
- Q_c;
- margins/multiplicity;
- operational objective/constraints;
- workload;
- replay semantics;
- E2 calibration model;
- profile definitions.

If a revision can bias selection, affected confirmatory evidence needs a fresh basis; administrative invalidation plus rerunning identical exposed data is insufficient.

For E3 failure:

- candidate-independent modelling error → revise method, retain prior result as superseded, recompute all affected pairs consistently from still-valid E2 evidence;
- candidate-specific mismatch → invalidate that pair's E2 operational evidence, mark evidence incomplete, reopen event; do not silently select the next pair.

---

## 20. MSR method revision M2 and decision schema v2

This plan requires an explicit numbered MSR revision **M2** and a new S2c decision schema:

`mavi-model-selection-decision-v2`

M1/v1 remain valid for non-S2c events.

### 20.1 Unit identity

`evaluated[]` is keyed by `unitId`, representing:

- single candidate; or
- composition with exact `components[]`.

### 20.2 Per-event quality-result artefact

Each S2c capability event creates one immutable machine-readable quality-result artefact before the joint operational decision is built.

- **schema:** `mavi-s2c-quality-result-v1`
- **path:** event-specific under `docs/qualification/model-selection/<capability>/`, indexed by M2; for the planned events the canonical names are `msr-person-attributes-2026-01-quality-result.json` and `msr-vehicle-attributes-2026-01-quality-result.json`;
- **canonical bytes:** UTF-8 JSON, exact-key validated, duplicate-key refused, finite numbers only, deterministic key/order rules defined by the b-2 validator, trailing LF; the SHA-256 is over those canonical bytes;
- **identity:** event id, capability id, frozen ledger hash, b-1/b-2 contract hashes and frozen experiment hash;
- **decision inputs:** `decisionClaimsSha256`, pairwise matrix hash, MPID status/reference evidence hash and all gate-result hashes needed to reconstruct `E_c`;
- **outputs:** exact `E_c`, exact `F_c`, quality outcome and `qualityOutcomeReason`;
- **immutability:** once consumed by the joint decision its bytes are not rewritten; corrections use the numbered revision/addendum mechanism and therefore produce a new hash.

The validator recomputes the stored `E_c`/`F_c` from the referenced event evidence before accepting the artefact. This artefact is the acyclic bridge between the per-capability quality decision and the cross-event joint operational decision.

### 20.3 Joint-decision artefact

S2c creates one checked cross-event artefact:

- **schema:** `mavi-s2c-joint-operational-decision-v1`
- **path:** `docs/qualification/model-selection/s2c-joint-operational-decision.json` for the active S2c event pair, or the event-pair-specific path defined by the M2 index;
- **identity:** both event ids, both **frozen-ledger** hashes, one **`mavi-s2c-quality-result-v1` hash** for each capability, b-1/b-2 contract hashes and the frozen experiment hash;
- **`technicalStage`** (written at `TECHNICAL_DECISION_RECORDED`): `J_person`/`J_vehicle`, every evaluated joint pair with exact person/vehicle `unitId`s, operational evidence hash, `H_lo`, `H_up`, admission/constraint outcomes, `T`, technical outcome and joint evidence hash;
- **`implementationStage`** (`null` until `QUALIFICATION_PENDING`): both events' decision-snapshot hashes, the per-unit licence status per profile, `C_r` and `T_r` per profile, `C_all`, `K_person`, `K_vehicle`, `C_impl` with the per-component credibility class used, `T_impl`, and a `supersedes` hash naming the technical-stage version it extends.

A version with a non-null `implementationStage` is a new document, with a new hash. Its `technicalStage` must be byte-identical to that of the version it supersedes (checked), so licence and credibility can never rewrite the technical result. The supersession chain only points backwards, so it stays acyclic.

The validator dependency is one-way and acyclic: load both event ledgers and their quality-result artefacts first; validate the joint operational document from those immutable inputs; hash the joint document (and, for an implementation-stage version, first the decision snapshots and the superseded technical-stage version); then load/validate each event decision-v2, which may cite `jointOperationalDecisionSha256`. The joint document does **not** cite full event decision hashes. Any S2c person/vehicle event still using decision-v1 is refused; decision-v1 remains accepted for non-S2c events.

### 20.4 Required S2c fields

Per capability/event:

- `technicalEligibleSet[]` = E_c
- `qualityAcceptableSet[]` = F_c
- `pairwiseMatrixSha256`
- `decisionClaimsSha256`
- `mpidStatus`
- `highestTaskQualityEvaluatedSet[]`
- `qualityOutcomeReason`

Joint decision reference in each event decision-v2:

- `jointOperationalDecisionSha256`
- `technicalSelectionOutcome`
- `technicalSelectedSet[]` = T as person×vehicle pairs
- `technicalWinner` or null
- `profileClearedSet{profile: []}` = `T_r` (from `QUALIFICATION_PENDING`; absent/`null` before)
- `implementationEligibleSet[]` = `T_impl` (from `QUALIFICATION_PENDING`; absent/`null` before)
- `implementationPair` = `{personUnitId, vehicleUnitId}` **or `null`**, following the M1 state rule:
  - `TECHNICAL_DECISION_RECORDED`: must be `null`;
  - `QUALIFICATION_PENDING`: `null` (not yet chosen) or a pair in `T_impl`;
  - `CLOSED`: a pair in `T_impl` when an implementation exists, otherwise `null`.

  Both event decision-v2 documents are either both `null` or carry the identical pair, and both cite the same joint-decision version. Each event's own implementation unit is its coordinate of the pair.
- per-event `outcome` at `CLOSED`, derived from that event's coordinate:
  - a learned unit → `SELECTED_FOR_PACKAGING`;
  - a packageable baseline → `BASELINE_SELECTED`;
  - the disabled-capability fallback, or `implementationPair = null` → `NO_QUALIFIABLE_CANDIDATE`, with the capability left disabled.

  A capability can therefore be `NO_QUALIFIABLE_CANDIDATE` while the other capability of the same pair is `SELECTED_FOR_PACKAGING`.
- `qualityContractHash`
- `operationalContractHash`
- `decisionEvidenceHash`

### 20.5 Highest task quality

S2c no longer requires a scalar task-quality maximum where multidimensional evidence does not support one. A set is valid.

### 20.6 Validator obligations

The updated `credibility.py` / decision validator must recompute:

- E_c membership from supplied gate/MPID inputs;
- P_c matrix validity against declared decision outcomes;
- F_c;
- joint admitted pairs;
- H*/T from H_lo/H_up;
- profile-cleared sets;
- `K_person`, `K_vehicle` and `C_impl` from `J_c`, licence status and each component's credibility class on its event's decision snapshot (M1 §8), including the fallback rule; and `T_impl` over `C_impl`;
- that the implementation-stage version's `technicalStage` is byte-identical to the superseded version's;
- the state rules of §20.4: no pair and no `T_r`/`T_impl` before `QUALIFICATION_PENDING`; `NO_QUALIFIABLE_CANDIDATE` only at `CLOSED`; outcome consistent with the event's coordinate;
- that both event decision-v2 documents cite the same `jointOperationalDecisionSha256` and carry the identical `implementationPair` (or both `null`), and, when non-null, that this exact `(personUnitId, vehicleUnitId)` pair is a member of `T_impl` (per-coordinate membership alone is not sufficient).

It must no longer derive S2c winners from scalar `taskQualityScore` or `comparativeScore`.

### 20.7 What remains human-reviewed

Machine validation cannot prove:

- that workload/camera classes are representative;
- that a licence determination is legally correct;
- that a human-labelled b-1 comparison result is scientifically well grounded beyond the harness evidence;
- that an owner-selected SLA/NI/MPID margin is wise;
- until S2c.3 emits a hash-chained first-selection-read record, that the protocol freeze occurred before any selection-partition read.

These remain reviewed protocol inputs with retained evidence/attestation.

---

## 21. Historical weighted/Pareto reconciliation

The implementation must enumerate and reconcile every live scalar/ranking assumption, including at minimum:

- MSR README §3.2 references to comparative weights/scoring;
- README §8 generic comparative-score layer;
- README §9 “first in full technical ranking” / alternatives in rank order;
- selection-record template §6 “Technical ranking”;
- `candidate-credibility.md` scalar derivations;
- current `credibility.py` v1 maxima;
- parent S2c §9.5 weighted table;
- parent §9.5a top-K/rank-sum composition generation;
- parent references to ranking instability / score sensitivity;
- parent-plan S2c.3/S2c.4 rows so the E2 candidate-runner/real-runner seam is explicit;
- any “best finalist” language whose governing definition is removed.

For S2c, weighted score and Pareto frontier are historical/diagnostic only.

---

## 22. Owner inputs frozen before selection

### Inherited from b-1
- quality gate table;
- margins;
- support rules;
- robustness claims;
- MPID.

### Defined by b-2
- capability scopes;
- Q_person and Q_vehicle;
- simultaneous-inference family;
- composition manifest;
- predeclared per-capability fallback operational units;
- predeclared `MPID_COMPARATOR_UNAVAILABLE` disposition;
- host class/profile;
- workload family;
- lifecycle/owner SLA;
- failure scenarios;
- 500-camera envelope;
- reserve/max-host/memory/IO limits;
- E2 calibration traces and E3 held-out traces;
- H_lo/H_up uncertainty rule;
- primary deployment objective;
- allowed topology search space;
- licence deployment profiles;
- revision invalidation rule.

---

## 23. Validator and tests

### 23.1 Contract refusal tests

Reject:

- duplicate keys;
- unknown/missing exact keys;
- bool/int coercion;
- non-finite numbers;
- missing b-1 deferred disposition;
- b-1 redefinition;
- weighted S2c score;
- missing Q_c or direction;
- incomplete simultaneous family;
- comparator deletion before F_c;
- extension candidate in E_c after MPID failure;
- PO-B0 in E;
- selection-time manifest/objective change;
- frozen-test selection evidence;
- owner implementation outside `T_impl`;
- event decision-v2 documents whose `implementationPair` differ, cite different `jointOperationalDecisionSha256`, or name a pair not in `T_impl` even when each coordinate appears in some `T_impl` pair;
- owner choice of a frozen fallback pair refused merely because the fallback is outside `F_c`;
- lifecycle instant fields without the `...Utc` suffix or with non-UTC offsets;
- a pair in `T_impl` containing an `emerging` learned component without a recorded promotion dated on or before the decision snapshot, including one component of a person composition;
- `T` or `T_r` altered by credibility, or an `emerging` technical winner dropped from `T`;
- a non-null `implementationPair`, `T_r` or `T_impl` at `TECHNICAL_DECISION_RECORDED`;
- `NO_QUALIFIABLE_CANDIDATE` recorded while any required licence status is still pending, or at any state other than `CLOSED`;
- an implementation-stage joint version whose `technicalStage` differs from the version it supersedes;
- a per-event `CLOSED` outcome inconsistent with that event's coordinate of the pair;
- missing/invalid quality-result artefact, non-canonical bytes, or mismatched event/ledger/contract/experiment hashes;
- quality-result artefact whose stored E_c/F_c does not recompute from referenced evidence;
- missing/invalid joint-decision artefact or mismatched event/ledger/quality-result/contract hashes;
- any joint-decision artefact that cites a full event decision hash (cycle forbidden);
- S2c event using decision-v1;
- scalar S2c winner schema where v2 is required.

### 23.2 Decision counterexamples

Must include:

1. chained NI A→B→C with A failing protection vs C;
2. noisy weak C blocking F when evidence is inconclusive;
3. multidimensional cross-trade;
4. empty F;
5. tied host requirement;
6. mixed host classes refused by default;
7. different job-size skew at same Track rate;
8. host loss with nearly completed jobs;
9. Phase-A before D / publication after D but valid;
10. composition interaction;
11. MPID with no comparator;
12. E3 contradiction.

### 23.3 Lifecycle/replay tests

- FIFO by queued timestamp;
- retry keeps original queue position;
- attempt consumed at claim;
- lease capped at deadline;
- reclaim only after expiry + claim;
- one unit/process;
- identity fence;
- restart and lease expiry overlap;
- lost work re-executed;
- protected publication cap;
- acknowledgement distinct from commit;
- no claim/reclaim at or after deadline;
- `CompletedAtUtc` corresponds to the Phase-C publication commit.

### 23.4 Joint operational tests

- person/vehicle individually attractive but poor jointly;
- alternate pair wins on joint host count;
- H_lo/H_up overlap yields tied set;
- unique winner only with separation of uncertainty intervals;
- licence filtering recomputes cleared pair optimum without altering F;
- licence/profile filtering is formed from `J_person × J_vehicle`, not `F_person × F_vehicle`;
- a fallback-containing pair enters `C_r`/`C_all` only when that exact fallback is cleared/admissible for every required profile;
- empty `F_vehicle` uses the frozen vehicle fallback without rewriting the vehicle quality outcome;
- no valid fallback yields `NO_OPERATIONALLY_COMPLETE_IDENTITY`;
- per-profile optima with empty intersection still allow a valid `T_impl` from `C_impl`;
- an `emerging`-only (or not-cleared-only) `F_person` falls back to the frozen person fallback in `K_person`, so the vehicle capability is still implementable.

---

## 24. Expected implementation file set

Planning/protocol/validator surfaces only:

- b-2 JSON contract;
- b-2 Markdown protocol;
- b-2 standard-library validator/checker;
- pure decision helpers;
- bounded job replay helper;
- tests;
- MSR README revision M2;
- decision schema v2;
- per-event `mavi-s2c-quality-result-v1` artefacts/schema support;
- joint `mavi-s2c-joint-operational-decision-v1` artefact/schema support;
- `candidate-credibility.md`;
- `credibility.py` and its tests;
- protocol/record templates;
- S2c parent-plan reconciliation;
- qualification-plan additive authority only if genuinely required;
- b-2 implementation record;
- roadmap/register status text.

No runtime/API/UI/Model-Pack/Runtime-Pack implementation belongs in this slice.

---

## 25. Implementation sequence

1. Write discriminating tests first.
2. Add M2 / decision-v2 schema and validator tests.
3. Implement canonical b-2 contract + cross-load b-1.
4. Implement pure per-capability decision helpers:
   - E_c;
   - MPID filter;
   - P_c;
   - F_c.
5. Implement joint operational helpers:
   - fluid screen;
   - bounded replay;
   - H_lo/H_up;
   - T;
   - T_r;
   - T_impl and the joint-decision artefact.
6. Add deterministic Markdown projection.
7. Amend templates/MSR docs/parent plan.
8. Record implementation/non-claims.
9. Perform one comprehensive closure review with complete P1/P2 ledger before edits, then one consolidated repair.
10. After closure, only bounded regression/merge-gate verification unless new scope is introduced.

---

## 26. Acceptance criteria

Complete only when:

1. all 15 deferred subjects have explicit disposition;
2. b-1 remains unchanged;
3. Q_c and simultaneous family are frozen and machine represented;
4. MPID runs before F_c;
5. baseline membership rules are explicit;
6. F_c is computed against complete E_c;
7. person/vehicle operational selection is joint;
8. H_lo/H_up and T rules are deterministic;
9. licence profile sets are derived explicitly;
10. M2/decision-v2 are governing for S2c;
11. scalar S2c winner derivation is removed;
12. lifecycle replay matches S2b queue/lease/attempt/publication semantics;
13. timestamp provenance is explicit;
14. E2 and E3 are distinct;
15. 500-camera claim boundary is explicit;
16. composition search limitation is explicit;
17. MPID no-comparator disposition is frozen before selection and is not auto-passed;
18. fallback operational units are frozen before selection and cannot rewrite empty-F quality outcomes;
19. `T_impl` is derived over `C_impl = K_person × K_vehicle` (per-capability implementable, all-profile-cleared units, falling back to the frozen fallback when none; credibility applied only there), not by intersecting per-profile optima, and `C_r/C_all` are formed from the effective `J_c` sets so frozen fallbacks survive licence/implementation selection without rewriting quality outcomes;
20. each event emits a canonical immutable `mavi-s2c-quality-result-v1` artefact whose E_c/F_c recompute from referenced evidence;
21. the checked joint-decision artefact is staged (technical at `TECHNICAL_DECISION_RECORDED`, implementation at `QUALIFICATION_PENDING`, with a byte-identical technical stage), `implementationPair` follows the M1 state rule, and the artefact cross-links both S2c events **without hash cycles**, using event ids, ledger hashes and per-event quality-result hashes; event decision-v2 documents reference the already-hashed joint artefact;
22. b-1 repository check passes;
23. b-2 repository check passes;
24. `tools/verify_repo.py` passes;
25. exact-head CI is green;
26. no P1/P2/material review thread remains;
27. no model was selected/downloaded/trained/benchmarked;
28. no F/G acceptance row changed.

---

## 27. Claude B1–B10 disposition and bounded-closure amendments

| Finding | Disposition |
|---|---|
| B1 per-capability operational decision conflicts with joint runtime | accepted — joint pair stage §§7.1, 17 |
| B2 P(a,b) unbounded/no simultaneous family | accepted — Q_c + simultaneous family §§15–16 |
| B3 MPID candidate can poison F | accepted — MPID filter before E/F §14 |
| B4 baseline membership undefined | accepted — §10.4 |
| B5 H equality/tolerance undefined | accepted — H_lo/H_up §17.3 |
| B6 licence filtering ambiguous | accepted — recomputed profile set §18 |
| B7 scalar M1 schema conflicts with sets | accepted — M2 + decision-v2 §20 |
| B8 no 15-row disposition table | accepted — §3.2 |
| B9 E2/E3 undefined | accepted — §§12, 19 |
| B10 replay fidelity incomplete | accepted — §§7.2–7.6, 11.2 |
| N1 empty F in one capability deadlocks joint identity | accepted — frozen fallback operational unit + `J_c` §17.0 |
| B3 residual no-comparator disposition result-dependent | accepted — disposition frozen in §§6, 14.1 |
| B6 residual multi-profile implementation ambiguity | accepted — `C_all` / `T_impl` §18 |
| B7 residual no joint cross-event document | accepted — checked joint-decision artefact §20.2 |
| N2 joint/event decision hash cycle | accepted — one-way ledger/quality-result → joint decision → event decision-v2 hash chain §§20.2–20.3 |
| F1 fallback dropped during licence/implementation filtering | accepted — `C_r/C_all` now derive from effective `J_c` sets §18 |
| F2 per-event quality-result node undefined | accepted — canonical `mavi-s2c-quality-result-v1` artefact §20.2 |
| A M1 implementation eligibility (established/mavi-owned) not reapplied | accepted — credibility applied only at the implementation boundary: per-capability `K_c`, `C_impl = K_person × K_vehicle`, `T_impl` over `C_impl`; T/T_r stay credibility-blind §18 |
| B implementationPair required at every state | accepted — M1 state rule for `implementationPair`; staged joint artefact (technical at TECHNICAL_DECISION_RECORDED, implementation at QUALIFICATION_PENDING, byte-identical technical stage); `NO_QUALIFIABLE_CANDIDATE` only at CLOSED §§18, 20.3–20.4 |
| A′ credibility/licence gap in one capability would block the other through C_impl | accepted — per-capability `K_c` falls back to the frozen fallback §18 |

---

## 28. Final bounded review target

The architecture is now intentionally narrow:

- quality remains per capability;
- final runtime/deployment selection is joint;
- only a small predeclared claim set drives pairwise quality protection;
- extension candidates are filtered before they can block F;
- deployment selection uses explicit uncertainty bounds;
- set-valued outcomes are first-class;
- replay follows the actual S2b lifecycle;
- M2/v2 makes the prose enforceable.

The next review should be bounded to verifying that B1–B10 are correctly closed and that these amendments introduce no new authority contradiction. No further open-ended redesign should occur unless a new material defect is found.
