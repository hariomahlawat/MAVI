# Stage 2 S2c.2b-2 — Operational and Multi-objective Protocol

**Status:** Draft implementation plan — not governing until independently reviewed, accepted, exact-head CI passes, and the implementation slice merges.  
**Date:** 2026-09-29  
**Starting baseline:** `main@7d97cca565098bf1bef9a48122e01540ec5a37db` (PR #120 merge; S2c.2b-1 reconciled and governing).  
**Scope:** planning and protocol design for S2c.2b-2 only. No model is selected, downloaded, trained, calibrated or benchmarked by this plan. No F/G acceptance row changes.  
**Governing authorities:** ADR-013, ADR-014, the Stage-2 parent plan, the Stage-2 qualification plan including R1/R2/R3, the authoritative Stage-2 acceptance register, MSR method v1 + M1, and the governing S2c.2b-1 quality/statistical protocol and machine contract.  
**b-1 prerequisite:** `docs/qualification/model-selection/s2c-quality-statistics-contract.json` remains authoritative for S/U/I/A populations, calibration, partition authority, quality gates, statistical outcomes and the exact fifteen subjects delegated to this slice.

---

## 1. Purpose

S2c.2b-1 froze the quality/statistical half of model selection and deliberately left operational performance, composition resource accounting, fleet projection and final technical ordering undefined. S2c.2b-2 closes that boundary before either S2c event can reach `PROTOCOL_FROZEN`.

This slice must make the technical decision process executable without inventing owner policy numbers and without allowing runtime cost, fleet cost or an owner preference to override:

- a failed b-1 quality gate;
- `inconclusive` or `insufficient-evidence` statistical outcomes;
- the partition firewall;
- the frozen-test prohibition on tuning, ranking, replacement or rescue.

The intended decision architecture is:

> **mandatory gates → quality-protected eligibility → operational admissibility → multi-objective resource/scale comparison → deterministic technical outcome**

There is **no weighted scalar score** for S2c.

---

## 2. Non-goals

S2c.2b-2 does **not**:

- choose a model, component or composition;
- instantiate event-specific numerical owner targets;
- define the actual Development CPU host model, maximum host count, workload rates or backlog-drain SLA;
- execute candidate measurements;
- expose selection or frozen-test data;
- change the S2b lifecycle, worker, lease plane, Runtime Pack or Model Pack implementation;
- make CUDA a Production or S2c release requirement;
- change b-1 S/U/I/A semantics, statistics or quality-gate forms;
- promote any Stage-2 acceptance row.

Those values and identities are supplied later at S2c.2 protocol freeze, before selection results are read.

---

## 3. Authority boundary

### 3.1 b-1 remains untouched

The following remain wholly governed by S2c.2b-1:

- S/U/I/A populations and metric denominators;
- post-aggregation Track calibration;
- training-only fitting and tuning-only operating-parameter choice;
- paired cluster-aware comparison;
- practical/non-inferiority/equivalence margins;
- the five comparison outcomes;
- support and independent-cluster sufficiency;
- owner quality targets frozen before selection;
- frozen-test non-selection semantics.

b-2 may consume b-1 gate outcomes and pairwise comparison outcomes. It may not reinterpret them.

### 3.2 Exact b-2 subjects

The implementation must cover every subject currently listed in b-1 `deferredToS2c2b2`:

1. operational-performance;
2. whole-job-cpu-host-gates;
3. composition-resource-accounting;
4. 10k-track-deadline-mechanics;
5. 500-camera-projection;
6. pareto-axes;
7. pareto-directions;
8. pareto-normalization;
9. dominance-semantics;
10. disabled-attribute-frontier-treatment;
11. non-dominated-set-construction;
12. sub-task-finalist-ordering;
13. final-technical-selection;
14. msr-final-ranking-representation;
15. historical-weighted-ordering-reconciliation.

No item may remain implicit in prose.

---

## 4. Design principles

1. **Quality is protected, not traded for cost.** Resource advantages cannot compensate for a failed quality gate or an unresolved quality comparison where the rule requires non-inferiority.
2. **Whole-job evidence governs operational claims.** Per-crop latency remains diagnostic. The gate is based on the complete unit of work actually executed through the worker path.
3. **Compositions are measured as compositions.** Shared-backbone savings or combined-resource costs count only when measured in the exact composed executable configuration.
4. **Projection is not qualification.** A 500-camera result is an M-E projection validated against executed load; it is never described as a physical 500-camera qualification.
5. **No normalization is required for dominance.** Pareto/resource comparisons use native, directionally declared units. No hidden utility function or weighted sum is introduced.
6. **An unresolved comparison stays unresolved.** The deterministic rule may return a set or `NO_UNIQUE_TECHNICAL_WINNER`; determinism does not mean manufacturing a winner.
7. **Owner policy values are data, not method.** b-2 defines their schema, freeze point and use; it does not invent universal values.
8. **Licence remains separate.** Technical ordering never reads licence status or credibility class. Licence determines the strongest candidate cleared for a target profile only after technical ordering.

---

## 5. Canonical b-2 machine contract

Implementation creates:

`docs/qualification/model-selection/s2c-operational-selection-contract.json`

with schema:

`mavi-s2c-operational-selection-v1`

and method:

`s2c-2b2`.

The JSON contract is the canonical machine authority. Its top-level sections are exact-key validated:

- `schema`
- `method`
- `prerequisite`
- `wholeJob`
- `hostProfile`
- `compositionAccounting`
- `scaleProjection`
- `multiObjective`
- `finalistOrdering`
- `finalSelection`
- `msrRepresentation`
- `historicalOrdering`
- `ownerInputs`
- `frozenInvariants`
- `invariantStatements`

The Markdown protocol contains one deterministic protected projection rendered from the JSON contract and compared byte-for-byte, following the b-1 pattern. Arbitrary prose outside that block is explanatory only.

The validator is standard-library Python and lives beside the b-1 validator under:

`tools/qualification/model_selection/`

with a repository entry point analogous to `quality_statistics_check.py`.

### 5.1 Cross-contract requirement

The b-2 repository validator must load the b-1 contract and require that:

- every current `deferredToS2c2b2` subject has an explicit b-2 disposition;
- b-2 does not redefine any b-1 partition authority, population, statistical outcome or quality-gate form;
- no event template can claim `PROTOCOL_FROZEN` unless both contract ids/hashes are cited.

This prevents b-1 and b-2 from drifting independently.

---

## 6. Whole-job operational-performance contract

### 6.1 Gate object

The primary CPU operational gate is the **analysis-unit whole-job gate**, not a per-crop p95.

For a frozen candidate or composition, one analysis unit is the existing S2b work unit for one ProcessingRun/capability identity. The 10k test fixture contains exactly 10,000 Tracks, using the event's frozen crop-count/size distribution subject to the production Evidence Set bound.

The measured whole-job interval starts when the platform successfully grants the claim and ends only when the successful completion request is acknowledged and the resulting analysis is visible under the existing S2b completion semantics.

It therefore includes, where applicable:

- lease-authorised evidence reads;
- byte/hash verification;
- JPEG decode;
- admissibility;
- preprocessing;
- inference;
- aggregation/abstention;
- prediction artefact construction;
- upload;
- completion/publication.

It excludes service boot/model load in the **steady-state** measurement because READY is a prerequisite to leasing. Model-load/READY time is measured separately and is included in the recovery/deadline scenario below.

Per-crop and per-Track p50/p95/p99 remain diagnostic evidence and may explain a whole-job result; they are not independent substitutes for the gate.

### 6.2 Host profile

Every S2c event freezes a host-profile object before selection:

- host-profile id/version;
- CPU model;
- logical/physical core count;
- RAM;
- OS/build;
- Runtime Pack id;
- Python/runtime lock identity;
- detector co-residency state;
- number of attribute worker processes;
- inference thread count and relevant runtime thread variables;
- power/performance policy where controllable;
- storage class used for accepted evidence;
- network topology to the platform where it materially affects evidence-read timing.

The generic b-2 contract defines the required fields, not their values.

The CPU gate is mandatory because the S2c release binding does not require CUDA. CUDA measurements remain additional Development evidence unless a later frozen target profile explicitly binds CUDA.

### 6.3 Run validity

A whole-job run is valid only if:

- the candidate/composition identity and executable configuration are frozen;
- the host profile matches the protocol;
- no tuning occurs during the run;
- all assigned Tracks are accounted for under b-1 population A;
- heartbeat/fencing remain valid;
- the run records failures/retries rather than silently dropping them;
- workload fixture and result artefacts are hash retained.

A run invalidated by infrastructure unrelated to the candidate is repeated under a predeclared invalid-run rule. Candidate-caused OOM, timeout, malformed output or deterministic failure is **not** an invalid run; it is candidate evidence.

---

## 7. 10,000-Track deadline and retry mechanics

The lifecycle deadline `D` is an event protocol input read from the configured S2b lifecycle. It is frozen before selection and cannot be increased after candidate results to rescue a candidate.

b-2 defines two separate operational checks.

### 7.1 SG4a — steady-state whole-job gate

The exact frozen 10k workload is executed from claim to successful publication on the pinned CPU host profile.

The event protocol provides the maximum allowed whole-job elapsed time and any required throughput floor. The pass/fail comparison uses retained elapsed time and the predeclared repetition/summary rule.

The generic b-2 method does not invent the numeric elapsed-time target.

### 7.2 SG4b — recoverability/deadline gate

A separate injected-failure scenario demonstrates that one allowed retry can still finish inside the lifecycle deadline.

The scenario freezes:

- failure injection point, expressed as a fraction/stage of the first attempt;
- launcher restart/backoff settings;
- model-load/READY measurement;
- lease expiry/reclaim delay where the failure prevents `/fail`;
- retry claim time;
- second-attempt whole-job execution.

The clock is from the **first attempt's claim** to successful completion of the retry. All restart, load, reclaim and retry time counts.

Pass requires completion within the frozen `D` and within the existing attempt bound.

The protocol may use two failure paths where S2b distinguishes explicit retryable failure from hard process loss. If both are relevant to the target profile, both must pass.

No algebraic per-crop budget is itself a gate. The old `(D − T_restart − T_load − T_lease)/2` and ~0.266 s/crop values remain historical/provisional only.

---

## 8. Composition resource accounting

For `person-attributes`, operational gates apply to the exact composition executable, not to the arithmetic sum of component measurements.

Every composition record includes:

- exact component identities;
- shared-backbone identity, if any;
- exact heads and region component;
- Runtime Pack family;
- enabled target attributes;
- whole-job elapsed time;
- sustained worker throughput on the frozen workload;
- peak RSS;
- peak VRAM where measured;
- model-load/READY time;
- pack bytes;
- runtime/offline-kit incremental bytes;
- workers-per-host achieved under the host profile;
- failure-domain description;
- 500-camera projection outputs.

### 8.1 Shared resources

A shared-backbone benefit counts only if the composition actually executes one shared backbone and the measured process demonstrates the saving.

It is forbidden to:

- subtract theoretical duplicated memory;
- add separately measured component throughputs;
- infer composition load time from component load times;
- claim shared-backbone savings from architecture diagrams alone.

Component measurements remain diagnostics.

### 8.2 Co-residency

Where the host profile requires detector co-residency, memory and CPU measurements include that condition. The protocol records whether the detector is actively processing, resident but idle, or represented by a frozen resource reservation. The same mode is used for every compared candidate.

### 8.3 Disabled attributes

The event protocol freezes its **target attribute set** before selection.

A candidate/composition with any target attribute disabled because its applicable b-1 gate failed is:

- ineligible for full-capability technical selection;
- retained in the MSR as a partial-capability result;
- never made non-dominated merely because disabling the difficult attribute reduced cost.

If the owner removes an attribute from the target set, that is a protocol decision made before selection results and applies to every candidate.

This is the b-2 disposition of `disabled-attribute-frontier-treatment`.

---

## 9. 500-camera workload and projection

### 9.1 Owner-declared workload envelope

Before selection, each event freezes a versioned workload envelope containing:

- target camera count (500 for owner constraint B);
- time-binned Track arrivals per camera or camera class;
- quiet/typical/busy or equivalent declared strata;
- person/vehicle share relevant to the capability;
- Evidence Set crops-per-Track distribution;
- crop-size distribution or frozen workload-manifest reference;
- peak-window duration;
- maximum host count;
- host-profile ids and memory per host;
- accepted maximum steady-state backlog, if non-zero;
- accepted backlog-drain time after the declared peak;
- accepted backlog-drain time after one-host loss;
- any required reserve-capacity rule.

b-2 defines this schema. The owner supplies the values at S2c.2 protocol freeze.

### 9.2 Capacity measurement

Projection capacity is based on **executed sustained whole-worker throughput** on the exact host profile and candidate/composition, not the sum of per-crop timings.

The retained capacity record contains:

- workload-manifest hash;
- completed Tracks/time;
- crop distribution actually executed;
- worker count;
- peak RSS;
- heartbeat performance;
- candidate-caused failures/retries;
- elapsed measurement interval.

The projection uses a conservative capacity quantity predeclared in the event protocol, such as a lower confidence bound or declared low quantile of repeated sustained-throughput runs. The exact summary rule is frozen before selection.

### 9.3 Deterministic fluid-queue projection

The generic projection is a deterministic time-step replay, not a stochastic black box.

For each workload bin `t`:

- `arrivals[t]` is the frozen workload-envelope Track arrival count;
- `capacity[t]` is the available validated worker capacity for that bin;
- `backlog[t+1] = max(0, backlog[t] + arrivals[t] - capacity[t])`.

The projection is run for:

1. the declared steady/peak workload;
2. the same workload with the declared one-host-loss interval and recovery time;
3. any additional target-profile scenario frozen before selection.

The script reports at minimum:

- required worker count;
- required host count;
- maximum queue/backlog;
- maximum and end-of-window backlog;
- drain time after peak;
- drain time after one-host loss;
- aggregate peak memory;
- reserve/headroom implied by the declared envelope;
- pack/runtime deployment bytes across hosts.

No normalization combines these into a score.

### 9.4 SG7a — projected scale gate

A candidate/composition passes SG7a only if the deterministic projection fits every frozen owner envelope constraint.

A projection that requires an unimplemented architectural change fails SG7a for the current event. The change may be pursued through a later ADR/event; it is not assumed into the projection.

### 9.5 SG7b — projection validation

S2c.9 executes an accelerated load through the real lease plane.

The event protocol freezes:

- executed camera-equivalent fraction or arrival-rate trace;
- worker count;
- host count;
- duration;
- predicted metrics to compare;
- relative/absolute agreement tolerances;
- which scenario(s) must be executed.

Validation compares projected versus observed throughput, queue/backlog and drain behaviour.

A metric outside tolerance fails SG7b and invalidates the corresponding projection claim. The model-selection event is not silently re-ranked with a repaired projection; the protocol/result is reopened through the documented event mechanism.

If cross-host behaviour required by the target envelope cannot be executed, that claim remains unvalidated and cannot be marked passed.

The record always says **projected to the 500-camera envelope**, never **qualified on 500 cameras**, unless a future stage actually performs such a qualification.

---

## 10. Multi-objective technical comparison

### 10.1 No weighted score

S2c retires the historical weighted technical score as a governing mechanism.

There is:

- no sum of quality/runtime/engineering points;
- no redistribution of weights when a measurement is unavailable;
- no sensitivity analysis over score weights;
- no scalar `comparativeScore` used to derive the S2c technical winner.

The historical table remains in Git as planning history with an explicit supersession note.

### 10.2 Eligibility before comparison

A candidate/composition enters the b-2 technical comparison only if it passes all applicable technical/engineering gates:

- SG2 Offline;
- SG3 Determinism;
- b-1 SG5 quality/baseline gates;
- b-1 SG6 abstention/unsupported-assertion gates;
- SG4a whole-job;
- SG4b recoverability/deadline where applicable;
- SG7a projected scale.

SG7b is later executed validation evidence and cannot retrospectively cause frozen-test-style rescue. A failure reopens the event/selection under the documented lifecycle rather than selecting the next alternative using the same exposed evidence.

Licence SG1 is not read by this technical comparison.

### 10.3 Quality relation

For two eligible candidates A and B, define `qualitySafe(A,B)` only when every required paired b-1 quality comparison needed by the protocol establishes A as one of:

- `superior`;
- `non-inferior`;
- `equivalent`

relative to B.

If any required comparison is `inconclusive` or `insufficient-evidence`, `qualitySafe(A,B)` is false for ordering purposes.

If B is established superior over A on a required quality claim, A is not quality-safe relative to B.

This does not collapse multiple attributes into a scalar.

### 10.4 Pareto axes and directions

Resource dominance is evaluated only where quality protection permits it.

The b-2 resource vector uses native units:

| Axis | Direction |
|---|---|
| projected host count at frozen 500-camera envelope | minimize |
| projected worker count | minimize |
| aggregate peak host memory / binding-constrained memory footprint | minimize |
| 10k steady-state whole-job elapsed time | minimize |
| model-load/READY time | minimize |
| offline deployment footprint (Model Pack + incremental Runtime Pack bytes as defined by protocol) | minimize |

The event may record additional diagnostics but may not add a new decision axis after selection data are read.

CUDA viability is not an axis unless the frozen target profile requires CUDA.

Maintenance popularity, reported benchmark reputation, licence status and credibility class are not Pareto axes.

### 10.5 Normalization

**None.**

Dominance compares directionally declared native values under frozen measurement precision/tolerance. The method does not map unlike units to [0,1], ranks or utility points.

### 10.6 Resource dominance

A may resource-dominate B only if:

1. `qualitySafe(A,B)` is true;
2. A is no worse than B on every applicable resource axis after the protocol's frozen measurement-equivalence tolerance; and
3. A is strictly better than B on at least one resource axis beyond that tolerance.

An unavailable **required** axis makes the comparison unresolved; it is not dropped and its weight is not redistributed.

A non-required diagnostic axis is not read by dominance.

### 10.7 Non-dominated set

The non-dominated set contains every eligible candidate/composition not resource-dominated by another eligible candidate/composition.

The set is deterministic for a fixed measurement table and frozen tolerances.

An unresolved quality relation can therefore leave more than one candidate non-dominated. This is intentional.

### 10.8 Architectural-extension / MPID rule

MSR method §8.1 already requires a candidate that needs an architectural extension (for example a new Runtime Pack family) to clear the frozen MPID over the best candidate that needs no such extension and to follow the ADR route. b-2 makes that rule executable without inventing a scalar score.

1. Run the b-2 technical rule first on the eligible **existing-graph subset**.
2. If that subset has one unique technical winner, it is the existing-graph reference.
3. If that subset has no unique winner, the **entire unresolved existing-graph technical set** is the reference set.
4. An extension candidate is implementation-eligible only if the frozen b-1 quality comparisons establish the required MPID/practical superiority against **every member of that reference set** on the protocol-declared MPID quality claims, and all other applicable gates pass.
5. If the extension candidate does not clear that bar, it remains retained technical evidence but cannot become the implementation candidate for this event merely because it is cheaper or attractive on another axis.
6. If there is no eligible existing-graph candidate, the MPID replacement bar is not applicable; the extension still requires its normal gates and ADR route.

No runtime/dependency burden is converted into an arbitrary penalty score.

---

## 11. Sub-task finalist ordering

Person-attributes composition generation needs up to `K = 3` finalists for T-PC and T-PO.

For each sub-task:

1. apply all component-level applicable gates;
2. construct quality-dominance tiers using b-1 paired outcomes:
   - A quality-dominates B only when A is `qualitySafe(A,B)` and at least one required quality comparison is `superior`;
3. tier 1 is the set not quality-dominated by another candidate;
4. remove tier 1 and repeat for later tiers;
5. fill the finalist list from successive tiers until K is reached.

Within one tier, candidates may be ordered by the b-2 resource lexicographic rule **only when each candidate considered ahead is quality-safe relative to the candidate it would displace**.

The frozen resource lexicographic order is:

1. projected host count;
2. projected worker count;
3. aggregate peak memory;
4. 10k whole-job elapsed time;
5. model-load/READY time;
6. offline deployment footprint;
7. canonical candidate id may order **presentation only** after all preceding decision measurements are equivalent; it never decides which technically equivalent candidate survives a K boundary.

### 11.1 Finalist overflow

If a quality/resource-equivalent or unresolved tier would straddle the K boundary, the outcome is `FINALIST_OVERFLOW_UNRESOLVED`.

The event must then collect more evidence or defer. Changing K after this result has been observed requires a numbered protocol revision that explicitly invalidates the affected selection results and reruns the affected selection step under the revised protocol; K may not be expanded adaptively while retaining the already-exposed result.

Candidates may not be discarded by index order, canonical id, popularity, owner preference or prospective shared-backbone convenience.

This makes composition generation deterministic without manufacturing a statistical winner or suppressing a potentially material composition interaction.

---

## 12. Final technical selection

### 12.1 Single-component vehicle event

For eligible vehicle candidates:

1. construct the non-dominated set;
2. identify candidates that are quality-safe relative to every other member they would outrank;
3. if exactly one candidate remains, it is `UNIQUE_TECHNICAL_WINNER`;
4. if several candidates are mutually quality-safe/equivalent and differ on resource axes, apply the frozen lexicographic resource order;
5. canonical candidate id may break only a complete measurement-equivalence tie;
6. if unresolved quality relations prevent a defensible unique ordering, return `NO_UNIQUE_TECHNICAL_WINNER` with the unresolved set.

### 12.2 Person composition event

The same rule operates over the exact composition candidates generated from the frozen finalist rule.

Every composition must pass unit-level gates. A component's earlier pass does not waive a composition failure.

### 12.3 Outcome vocabulary

The b-2 technical decision outcome is one of:

- `UNIQUE_TECHNICAL_WINNER`
- `NO_UNIQUE_TECHNICAL_WINNER`
- `NO_TECHNICALLY_ELIGIBLE_CANDIDATE`
- `FINALIST_OVERFLOW_UNRESOLVED` (person sub-task stage)
- `NO_QUALIFIABLE_CANDIDATE` remains an MSR/deployment outcome after licence/profile filtering, not a technical-ranking result.

A deterministic method is allowed to deterministically report no unique winner.

### 12.4 Owner implementation choice

The owner may still choose the implementation candidate under MSR method §8/§9, but:

- a failed technical gate cannot be waived;
- an inconclusive/insufficient quality comparison cannot be relabelled;
- an owner-selected implementation must not be recorded as the strongest technical candidate unless b-2 produced that outcome;
- if b-2 returned `NO_UNIQUE_TECHNICAL_WINNER`, the record retains the unresolved technical set and records the owner's operational/deployment rationale separately.

---

## 13. MSR representation

S2c must stop deriving “strongest evaluated technical candidate” from a scalar `comparativeScore`.

The S2c decision summary is revised to carry:

- `technicalDecisionOutcome`;
- `technicalWinnerCandidateId` or `null`;
- `technicalNonDominatedCandidateIds[]`;
- `technicalUnresolvedCandidateIds[]`;
- `technicalOrdering[]` only for candidates the frozen rule actually orders;
- `orderingEvidenceHash`;
- `operationalContractHash`;
- `qualityContractHash`.

For S2c:

- “strongest evaluated technical candidate” is a candidate only when `technicalDecisionOutcome == UNIQUE_TECHNICAL_WINNER`;
- otherwise the MSR writes `UNRESOLVED — see technical set`, not a fabricated single id;
- “strongest cleared candidate” is derived only over candidates technically ordered/eligible under the b-2 representation and cleared for the target profile;
- the implementation candidate remains a separate owner field.

M1's generic scalar `comparativeScore` path remains available for non-S2c events but is not used for S2c person/vehicle events.

The selection-record template is amended accordingly.

---

## 14. Historical weighted-ordering reconciliation

The weighted table currently preserved in the S2c parent plan remains historical evidence of an earlier design.

The b-2 implementation must:

- label it superseded/non-governing by the merged b-2 protocol;
- remove language saying its weights/rank conversions are frozen at S2c.2;
- remove “interval overlap scored as ties” from any S2c decision path;
- remove weight redistribution for missing criteria;
- remove score-sensitivity as a selection mechanism;
- replace the S2c M1 decision-summary dependency on `comparativeScore`;
- preserve the historical text where useful for audit, without leaving two live decision systems.

No historical score is recalculated for new S2c results.

---

## 15. Owner inputs and freeze points

b-2 defines schemas but does not invent values.

Before either event reaches `PROTOCOL_FROZEN`, the owner must provide/freeze:

### Quality inputs inherited from b-1
- owner gate table;
- confidence-bound directions;
- practical/non-inferiority/equivalence margins;
- required robustness slices;
- MPID/replacement bar where applicable.

### Operational inputs defined by b-2
- CPU host profile;
- lifecycle deadline `D`;
- whole-job elapsed-time/throughput gate;
- run repetition and summary rule;
- retry/failure scenario(s);
- workload envelope for 500 cameras;
- maximum host count and memory envelope;
- backlog and drain-time constraints;
- projection-capacity summary rule;
- projection-validation scenarios and tolerances;
- resource measurement-equivalence tolerances;
- target attribute set.

No value may be inserted after selection data are read except through a protocol revision that invalidates affected results.

---

## 16. Event-template changes

### 16.1 Selection protocol template

Add explicit sections/fields for:

- b-2 contract id/hash;
- host profile;
- 10k workload manifest;
- SG4a and SG4b rules;
- composition resource-accounting mode;
- target attribute set;
- 500-camera workload envelope;
- deterministic projection script/version;
- SG7a envelope;
- SG7b validation scenario/tolerances;
- exact b-2 Pareto axes/directions;
- `normalization: none`;
- measurement-equivalence tolerances;
- finalist-ordering rule and K;
- final technical outcome vocabulary;
- owner inputs freeze hash.

### 16.2 Selection record template

Add retained evidence for:

- whole-job runs and recovery runs;
- host profile hash;
- composition resource table;
- projection input/output hashes;
- executed validation vs projection;
- non-dominated set;
- unresolved-quality pairs;
- finalist tiers;
- technical decision outcome;
- owner implementation choice separated from technical outcome.

---

## 17. Validator and tests

Implementation is test-first.

### 17.1 Contract refusal tests

Reject:

- missing/unknown top-level keys;
- bool/int coercion where strict booleans are required;
- duplicate JSON keys;
- any missing b-1 deferred subject disposition;
- a new b-2 field that attempts to redefine b-1 partition/population/statistics;
- weighted-score or normalization enabled for S2c;
- resource axis with missing direction;
- disabled target attributes admitted to full-capability selection;
- licence/credibility used as a technical axis;
- missing host/workload freeze fields in a frozen event;
- selection-time changes to owner inputs;
- frozen-test data referenced as technical ordering evidence.

### 17.2 Algorithm known-answer tests

Use synthetic fixtures to prove:

- whole-job clock includes upload/completion but steady-state excludes startup;
- recoverability clock includes restart/load/reclaim where applicable;
- component arithmetic cannot substitute for measured composition resources;
- fluid queue recurrence and host-loss drain are exact on closed-form cases;
- SG7a fails an envelope breach;
- SG7b fails a projection/observed mismatch beyond tolerance;
- quality-inconclusive pairs do not become technical winners;
- non-inferior lower-resource candidate may dominate a higher-resource peer;
- a quality-superior candidate is not displaced merely by cheaper resources where the cheaper candidate is not quality-safe;
- native-unit dominance works with no normalization;
- unavailable required axis yields unresolved comparison;
- disabled target attribute blocks full-capability selection;
- finalist overflow is fail-closed;
- canonical id is used only for complete measurement-equivalence ties;
- technical result can be `NO_UNIQUE_TECHNICAL_WINNER`.

### 17.3 Mutation targets

At minimum kill mutants that:

1. start the whole-job clock after evidence read;
2. stop it before publication acknowledgement;
3. omit restart/load/reclaim from SG4b;
4. use per-crop p95 as SG4 pass;
5. sum component resources instead of measuring composition;
6. count theoretical shared-backbone savings;
7. drop a required scale-envelope constraint;
8. clamp negative backlog incorrectly or ignore host loss;
9. use point-estimate throughput instead of frozen conservative capacity summary;
10. normalize/resource-score axes;
11. let failed quality gate enter comparison;
12. treat `inconclusive` as tie/non-inferior;
13. drop an unavailable required axis;
14. allow a disabled target attribute onto the frontier;
15. use licence or credibility in technical ordering;
16. use weighted `comparativeScore`;
17. choose first candidate on unresolved finalist overflow;
18. use candidate id before all measurements are equivalent;
19. emit a single strongest technical candidate when the outcome is unresolved;
20. allow owner choice to rewrite the technical outcome.

---

## 18. Expected implementation file set

The implementation PR is expected to touch only planning/protocol/validator surfaces, approximately:

- new `docs/qualification/model-selection/s2c-operational-selection-contract.json`;
- new `docs/qualification/model-selection/s2c-operational-selection.md`;
- new b-2 validator/checker under `tools/qualification/model_selection/`;
- validator tests;
- `docs/qualification/model-selection/README.md`;
- `docs/qualification/model-selection/candidate-credibility.md` only where S2c decision-summary representation must stop requiring scalar `comparativeScore`;
- selection protocol/record templates;
- S2c parent plan §§9.5, 9.5a, 14, 14.1 and slice table;
- Stage-2 qualification plan only if an additive R4 is genuinely required to make b-2 authority explicit;
- acceptance/roadmap status text and a b-2 implementation record.

No runtime, worker, API, UI, Model Pack or Runtime Pack code belongs in this slice.

---

## 19. Implementation sequence

### Step 1 — write discriminating tests first
Create failing tests for the contract, cross-contract boundary, queue projection, dominance/finalist/final-selection semantics and S2c MSR representation.

### Step 2 — canonical contract + validator
Implement the exact JSON schema-by-code validator and cross-load b-1.

### Step 3 — deterministic algorithms
Implement pure standard-library helpers for:

- whole-job/recovery accounting validation;
- fluid-queue projection;
- quality-safe relation input validation;
- native-unit resource dominance;
- non-dominated set;
- finalist tiers/overflow;
- final technical decision outcome.

These helpers operate on synthetic/event-result documents only. They do not run models.

### Step 4 — Markdown projection
Render the protected authority block from the canonical contract and byte-compare it.

### Step 5 — templates/MSR representation
Amend protocol and record templates and M1 S2c decision-summary validation.

### Step 6 — parent-plan reconciliation
Supersede the old weighted score and provisional operational formulas without deleting historical reasoning.

### Step 7 — implementation record + status
Record scope, non-claims, tests, review findings and exact deferred-to-next-stage items.

### Step 8 — bounded closure review
Before merge, perform one comprehensive authority-chain review and produce a complete P1/P2 ledger before edits, then one consolidated repair pass. After closure, only mechanical regression/merge-gate verification unless a new change introduces new scope.

---

## 20. Acceptance criteria for the b-2 implementation slice

The slice is complete only when:

1. every b-1 deferred subject has exactly one explicit b-2 disposition;
2. b-1 semantics remain unchanged;
3. the b-2 contract and Markdown projection are deterministic and machine checked;
4. whole-job and recoverability semantics are explicit;
5. composition resource accounting is executable and cannot use theoretical savings;
6. 500-camera projection is reproducible, deterministic and honest about its claim boundary;
7. axes/directions/normalization/dominance/non-dominated-set semantics are complete;
8. finalist ordering is deterministic and fail-closed on unresolved overflow;
9. final technical selection may return no unique winner rather than fabricate one;
10. S2c no longer uses a weighted scalar comparative score;
11. MSR can represent unresolved technical sets without lying about a strongest candidate;
12. templates require all owner operational inputs before selection;
13. discriminating tests and mutants prove the refusal paths;
14. `quality_statistics_check.py repository --repo .` still passes;
15. the new b-2 repository check passes;
16. `tools/verify_repo.py` passes;
17. exact-head CI is green;
18. no unresolved P1/P2 or material review thread remains;
19. no model was selected/downloaded/trained/benchmarked;
20. no F/G acceptance row was promoted.

After b-2 merges, S2c.2 protocol freeze may begin. It must instantiate **both** the b-1 and b-2 contracts before any selection result is read.

---

## 21. Review questions for Astra

Astra should challenge the design rather than edit it mechanically:

1. Is whole-job + recoverability separation the right operational abstraction?
2. Is the deterministic fluid-queue model adequate and falsifiable for a 500-camera projection, or is a different transparent model materially better?
3. Are the resource axes sufficient without creating an “everything is non-dominated” frontier?
4. Is `qualitySafe(A,B)` too strict, too weak or circular?
5. Can finalist ordering produce hidden selection bias before composition generation?
6. Are there cases where the lexicographic resource order rewards an operationally worse system?
7. Is `NO_UNIQUE_TECHNICAL_WINNER` the correct fail-closed outcome?
8. Does any part of the design accidentally let cost trade against unresolved quality?
9. Is there a simpler method with the same auditability and protection?
10. What failure/queue/resource corner case would invalidate the proposed method?

Astra is asked for architecture/methodology criticism only; it should not implement.

---

## 22. Review questions for Claude

Claude should perform a cold repository-grounded review against current `main`:

- ADR-013/014;
- qualification plan R1/R2/R3;
- b-1 protocol and contract;
- MSR method/M1;
- event templates;
- S2c parent plan;
- acceptance register and roadmaps.

It should actively search for:

- authority contradictions;
- any b-2 rule that reopens b-1;
- accidental owner-value invention;
- mismatch between technical outcome and M1 decision-summary schema;
- frontier/dominance ambiguities;
- final-selection paths that turn inconclusive/insufficient evidence into an ordering;
- composition leakage;
- 500-camera projection claims stronger than executed evidence;
- selection-time tuning;
- frozen-test rescue;
- validation claims stronger than machine enforcement;
- missing refusal tests.

Claude should produce a complete P1/P2 ledger before proposing edits.

---

## 23. Decision record for this draft

The draft deliberately chooses:

- whole-job, not per-crop, operational gating;
- separate steady-state and recovery/deadline checks;
- measured composition resources;
- deterministic fluid-queue fleet projection;
- native-unit resource axes with **no normalization**;
- quality-protected resource dominance;
- a non-dominated set rather than a weighted utility score;
- fail-closed unresolved finalist/final-selection outcomes;
- explicit S2c removal of scalar `comparativeScore` as technical authority.

These are the primary subjects Astra and Claude should challenge before implementation begins.
