# Stage 2 S2c.2b-2 — Operational and Multi-objective Protocol

**Status:** Revised draft implementation plan — architecture rewritten after independent Astra review; not governing until repository-grounded review, acceptance, exact-head CI and merge.  
**Date:** 2026-09-29  
**Starting baseline:** `main@7d97cca565098bf1bef9a48122e01540ec5a37db` (PR #120 merge; S2c.2b-1 governing).  
**Scope:** planning/protocol design only. No model is selected, downloaded, trained, calibrated or benchmarked. No F/G acceptance row changes.  
**Governing authorities:** ADR-013, ADR-014, Stage-2 parent plan, Stage-2 qualification plan including R1/R2/R3, the Stage-2 acceptance register, MSR method v1 + M1, and the governing S2c.2b-1 quality/statistical protocol and machine contract.  
**Independent design input:** Astra architecture review of PR #121 at head `03462d4`, incorporated where valid. The original pairwise-dominance/tiering selection core and Track-fluid-only fleet model are superseded by this revision.

---

## 1. Purpose

S2c.2b-1 defines trustworthy quality evidence but deliberately stops before operational selection. S2c.2b-2 must convert already-frozen measurements into an auditable, executable technical decision without:

- trading away failed or unresolved quality for lower resource cost;
- inventing transitivity where b-1 pairwise outcomes do not provide it;
- treating Track throughput as if Tracks were independently schedulable work;
- using a weighted utility score;
- turning an owner preference into a statistical winner;
- overstating a 500-camera projection as a 500-camera qualification.

The revised decision architecture is:

> **freeze complete experiment → apply mandatory gates → establish direct quality protection against the complete eligible comparison set → optimize a declared deployment objective subject to operational constraints → preserve genuine ties and unresolved outcomes**

---

## 2. Non-goals

This slice does not:

- choose any real candidate or composition;
- invent event-specific quality or operational numbers;
- execute models or expose selection/frozen-test data;
- change the S2b worker/lifecycle/lease plane;
- make CUDA mandatory;
- change b-1 populations, partition authority, statistical outcomes or gate forms;
- promote any acceptance row;
- create a generic optimization or simulation platform.

The method is intentionally bounded to S2c person/vehicle Model Selection Events.

---

## 3. Authority boundary

### 3.1 b-1 remains authoritative

b-2 consumes but does not redefine:

- S/U/I/A;
- post-aggregation calibration;
- training/tuning/selection/frozen-test authority;
- paired cluster-aware comparisons;
- support sufficiency;
- practical/non-inferiority/equivalence margins;
- outcomes `superior`, `non-inferior`, `equivalent`, `inconclusive`, `insufficient-evidence`;
- owner quality targets frozen before selection;
- no frozen-test tuning, ranking, replacement or rescue.

### 3.2 Exact b-2 subjects

The b-2 contract must explicitly resolve all fifteen b-1 deferred subjects:

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

The revised design resolves the Pareto-related subjects by **not using a Pareto frontier as the final selection engine**. That is an explicit disposition, not an omission.

---

## 4. Design principles

1. **Direct quality protection.** A candidate may not reach resource selection by successively eliminating the comparator against which its quality protection would fail.
2. **No transitivity assumption.** Pairwise non-inferiority/equivalence is not assumed transitive.
3. **Complete candidates before selection.** Candidate/composition identities and configurations are frozen before selection evidence is read.
4. **Actual compositions, not component arithmetic.** Shared execution benefits and combined costs must be measured on the exact composition.
5. **Operational constraints before optimization.** Deadline, memory, queueing, recovery and deployment limits are feasibility constraints, not score components.
6. **One declared primary deployment objective.** b-2 does not create a universal six-axis ranking. The event declares the operational objective before selection.
7. **Set-valued outcomes are valid.** Equivalent, tied or unresolved technical sets are legitimate outputs.
8. **Projection is not qualification.** 500-camera claims remain projected and bounded by executed validation.
9. **Owner decisions do not rewrite evidence.**
10. **Licence/credibility remain separate from technical evidence.**

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
- `scaleProjection`
- `qualityProtection`
- `deploymentObjective`
- `finalSelection`
- `mpidExtensionRule`
- `msrRepresentation`
- `historicalOrdering`
- `ownerInputs`
- `frozenInvariants`
- `invariantStatements`

The Markdown protocol contains one deterministic protected projection from this contract and is byte-compared like b-1.

### 5.1 Cross-contract enforcement

The repository validator must load b-1 and prove:

- every current b-1 deferred subject has one explicit b-2 disposition;
- no b-2 field redefines b-1 populations, partition authority, statistical outcomes or gate forms;
- event `PROTOCOL_FROZEN` requires both b-1 and b-2 ids/hashes;
- no S2c event uses weighted `comparativeScore` as technical authority.

---

## 6. Freeze complete experiment before selection

Before any selection result is read, each event freezes:

- exact candidate/component identities;
- exact executable configurations;
- target attribute set/profile;
- aggregation/admissibility family already allowed by b-1;
- complete composition manifest for multi-component events;
- host profile;
- workload family;
- quality gate table and margins;
- operational constraints;
- deployment objective;
- MPID rule;
- required engineering evidence and allowed pending stages;
- decision/report schema.

No candidate, composition, workload shape, objective or decision rule may be added after selection data are read except by a numbered protocol revision with explicit invalidation semantics.

A revision made because selection results exposed a weakness is **not made unbiased merely by rerunning the same deterministic selection data**. If the change could alter candidate inclusion, comparison or selection, the affected confirmatory evidence requires a fresh evaluation basis or a new event.

---

## 7. Whole-job operational-performance contract

### 7.1 Scheduling unit

The operational unit is the existing S2b **analysis of one ProcessingRun/capability identity**, not an independently schedulable Track.

Tracks remain useful demand descriptors inside a run, but operational deadline/recovery claims are made at the analysis-job level.

### 7.2 Required timestamps

Retain at minimum:

- `jobAvailableAt` — work becomes eligible for the attributes lease plane;
- `firstClaimAt`;
- each `attemptClaimAt`;
- `phaseAValidatedAt` — completion validation/deadline point under current S2b lifecycle;
- `publicationCommittedAt`;
- `completionAcknowledgedAt`;
- `readyAt` for worker startup/restart.

These timestamps serve different claims.

### 7.3 Performance views

Report separately:

1. **boot-to-READY** — startup/recovery evidence;
2. **claim-to-Phase-A** — lifecycle deadline evidence;
3. **claim-to-publication** — service/recovery performance;
4. **available-to-publication** — queueing + service operational latency;
5. **publication-to-acknowledgement** — transport/confirmation diagnostic.

A protected publication committed after the nominal lifecycle deadline may still be valid under S2b if Phase A was timely. b-2 must not relabel that as lifecycle failure. An owner SLA may nevertheless require publication by a stricter bound; that is a separate frozen operational gate.

### 7.4 Steady-state whole-job gate

The primary warm CPU gate is claim-to-publication for a frozen workload shape on the pinned host profile.

It includes:

- lease-scoped evidence reads;
- hash verification;
- decode;
- admissibility;
- preprocessing;
- inference;
- aggregation/abstention;
- artefact construction/upload;
- completion/publication.

It excludes initial boot/model load because READY precedes leasing, but startup is measured separately.

Per-crop/per-Track p50/p95/p99 remain diagnostics and model inputs, not substitutes for the whole-job gate.

### 7.5 Recoverability gate

Injected retry/process-loss scenarios preserve the original first-claim lifecycle deadline and explicitly model:

- work already consumed before failure;
- explicit `/fail` vs silent process loss;
- lease expiry/reclaim where required;
- launcher restart/backoff;
- model load/READY;
- retry claim;
- re-execution;
- Phase-A validation;
- publication.

Restart and lease expiry may overlap. The implementation models actual event ordering rather than blindly summing delays.

Candidate-caused OOM, timeout, malformed output or deterministic failure is evidence, not an invalid run.

---

## 8. Workload family and 10k boundary

A single 10,000-Track workload is insufficient to characterize a ProcessingRun service model.

The frozen workload family contains at minimum:

- representative typical jobs;
- small-job burst scenario;
- demanding feasible 10k-Track boundary job;
- mixed person/vehicle job mix where relevant;
- recovery/failure scenario;
- any workload shape required by the 500-camera envelope.

Each workload definition records:

- job/run count;
- Track count per job;
- person/vehicle composition;
- Evidence Set crops/Track distribution;
- crop-size distribution;
- byte-volume bounds;
- release cadence;
- initial backlog if any.

The 10k job remains a hard capacity/resilience boundary, not the only operational workload.

---

## 9. Host profile and co-residency

Freeze before selection:

- host id/version;
- CPU model;
- physical/logical cores;
- RAM;
- OS/build;
- Runtime Pack id/lock;
- attribute worker count;
- inference/runtime threads;
- storage/evidence path class;
- detector co-residency state;
- active/resident/reserved detector mode;
- relevant power/performance policy;
- network topology where material.

An idle detector does not prove safe active co-residency. The same co-residency mode must be used across compared candidates.

---

## 10. Composition accounting

For person attributes, quality and resources are measured on the exact composition.

Record:

- component identities;
- shared-backbone identity;
- trained heads and training-manifest hashes;
- region component if any;
- enabled target attributes;
- Runtime Pack family;
- whole-job service by workload shape;
- sustained throughput;
- peak RSS/VRAM;
- startup/READY;
- pack/runtime bytes;
- workers/host;
- failure domain;
- scale-model inputs/outputs.

### 10.1 Shared resources

A shared-backbone benefit counts only if the executable actually shares it.

Forbidden:

- subtracting theoretical duplicate memory;
- summing separate component throughputs;
- inferring composition latency/load time from components;
- calling same-checkpoint components “shared” when execution is duplicated.

### 10.2 Target attributes

The target attribute set is frozen before selection.

A candidate/composition missing or disabling a required attribute because a b-1 gate failed is ineligible for that full-capability profile.

Partial profiles are allowed only if **predeclared as separate profiles before selection**, with their own decision rule.

### 10.3 Composition manifest

The person event freezes a **bounded composition manifest** before selection.

Preferred rule:

- enumerate every compatible composition among the admitted component shortlist when the product is tractable;
- explicitly include shared-backbone configurations intended for evaluation;
- train any composition-specific/shared heads on training data;
- tune allowed parameters on tuning data;
- freeze all executable compositions before selection.

The accepted parent-plan K=3 language is amended for S2c.2b-2: K is not a statistical selection law. It may remain a planning/budget parameter, but no standalone top-K rule is permitted to discard a component after selection results are read.

Where the Cartesian product is too large, the experiment budget and retained composition subset are frozen **before** selection and reported as a search limitation. b-2 does not claim dominance-preserving pruning from standalone component measurements unless such preservation is formally demonstrated.

This supersedes the original PR #121 quality-tier/finalist-overflow algorithm.

---

## 11. 500-camera methodology

Use two levels for two different questions.

### 11.1 Level 1 — fluid capacity screening

Use worker-service demand:

`W[t+1] = max(0, W[t] + A[t] - C[t])`

where:

- `A[t]` = service demand released in bin t;
- `C[t]` = available service capacity in bin t;
- `W[t]` = unfinished service demand.

This gives coarse:

- stability;
- initial host sizing;
- reserve/headroom estimates;
- rough drain behaviour.

It does **not** establish job deadlines, publication latency or lost-work recovery.

### 11.2 Level 2 — deterministic analysis-job replay

Implement a small standard-library discrete-event helper over actual analysis jobs and workers.

For a healthy worker:

`start[j] = max(available[j], workerFree[w])`

`finish[j] = start[j] + service[j,w]`

The helper extends this narrowly for:

- claim/polling discipline;
- attempts;
- leases;
- explicit failure;
- process loss;
- restart/READY;
- host loss;
- lost work;
- Phase-A validation;
- publication.

It is not a generic simulation framework.

### 11.3 Owner workload envelope

Freeze:

- target camera count;
- camera classes/proportions;
- correlated busy periods;
- run duration/release cadence;
- jobs per interval;
- Tracks/job distribution;
- person/vehicle mix;
- Evidence Set count/size distributions;
- initial backlog;
- burst traces;
- failure timing/duration;
- reserve policy;
- maximum installed hosts;
- memory/IO constraints;
- backlog/queue-age/drain limits.

“500 cameras × average Tracks/minute” is insufficient.

### 11.4 Required measurements

On the exact candidate/configuration:

- warm and cold startup;
- whole-job service by representative job size/composition;
- 10k boundary job;
- admitted concurrency/topology;
- active co-residency;
- evidence-read demand;
- upload/publication demand;
- heartbeat behaviour;
- explicit-failure recovery;
- process-loss recovery;
- host-loss recovery;
- joint memory peak including restart transients;
- deployment/storage growth.

Retain distributions or trace samples where available. Do not multiply per-crop p95 by crop count and call it a job p95.

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
- owner SLA misses;
- peak backlog;
- post-peak drain;
- post-host-loss drain;
- memory/IO bottlenecks;
- deployment footprint;
- sensitivity to frozen workload/service assumptions.

### 11.6 Projection validation

Freeze projected outputs **before** integrated validation.

S2c.9 executes the real lease/evidence/publication path at several meaningful loads, including:

- intended operating region;
- burst scenario;
- failure/host-loss scenario where feasible.

Separate:

- traces used to calibrate the performance model;
- held-out engineering traces used to validate it.

These are engineering traces, not the ML frozen test.

Validation includes one-sided protection against dangerous **underprediction**, not only symmetric agreement.

A materially failed validation invalidates the affected projection method/claim. The event is revised/reopened and affected candidates are re-evaluated consistently. The preferred candidate is not simply assigned a new host number.

Permitted wording:

> projected attribute-processing capacity for the declared 500-camera workload envelope, validated against the stated executed loads and hardware.

Not permitted:

> qualified for 500 live cameras.

---

## 12. Technical eligibility

Let `E` be the complete set of evaluated frozen candidates/compositions for the profile that pass all applicable absolute technical/engineering gates.

At minimum:

- SG2 Offline;
- SG3 Determinism;
- b-1 SG5 quality/baseline gates;
- b-1 SG6 abstention/unsupported-assertion gates;
- required whole-job operational gates;
- memory/co-residency constraints;
- projected scale feasibility;
- mandatory evidence completeness for the selection stage.

Rules:

- missing mandatory evidence is not a pass;
- insufficient support remains insufficient evidence;
- disabled required attributes exclude the candidate from that profile;
- licence and credibility do not affect membership in E;
- reported class-R evidence cannot satisfy measured technical gates;
- integrated S2c.9 obligations not yet executed remain visibly pending rather than being misrepresented as selection-stage execution.

---

## 13. Direct quality protection against the complete set

For every ordered pair `a,b in E`, b-1 supplies the required paired quality outcomes.

Define:

`P(a,b) = true`

only when **every required quality comparison needed by the frozen protocol** establishes that candidate a satisfies the declared protection relative to b, using only supported:

- `superior`;
- `non-inferior`;
- `equivalent`.

If any required comparison is:

- `inconclusive`;
- `insufficient-evidence`;
- or establishes a material loss beyond the frozen permitted margin,

then `P(a,b) = false`.

Now define the **quality-acceptable set**:

`F = { a in E : P(a,b) for every b in E, b != a }`

Crucially, F is computed against the **original complete E**. No candidate is removed first and no comparison obligation disappears because of resource elimination.

Consequences:

- no chained non-inferiority degradation;
- no transitivity assumption;
- no Condorcet/tier-peeling requirement;
- quality cycles yield unresolved evidence rather than an arbitrary winner;
- an inconclusive comparison cannot be converted into a resource tie;
- a cheaper candidate cannot bypass a materially better challenger that remains in E.

### 13.1 Empty F

If F is empty:

`NO_QUALITY_PROTECTED_TECHNICAL_CHOICE`

The event must collect more evidence, defer, retain a permitted baseline/incumbent, or open a later event. Resource optimization does not run.

### 13.2 Meaning

Membership in F means:

> acceptable under the frozen quality-loss/protection policy against every eligible evaluated alternative.

It does **not** mean identical quality or universal superiority.

---

## 14. Deployment optimization

b-2 does not define a six-axis universal Pareto ranking.

The event freezes one **primary deployment objective** before selection.

Default S2c objective:

> **minimize supported installed attribute-host count for the declared workload envelope on the frozen host class, including the frozen reserve requirement.**

For candidate a:

`H[a] = minimum admitted host topology that satisfies every frozen workload, recovery, memory, queue/backlog and SLA constraint`.

Only topology settings allowed by the frozen protocol may be searched. Batch/thread/process settings are not selection-time tuning.

### 14.1 Other resource quantities

Use primarily as constraints/evidence:

- memory/host;
- queue age;
- backlog drain;
- whole-job completion;
- recovery time;
- load/READY;
- evidence/API/storage capacity;
- offline pack/runtime bytes;
- workers/host;
- CPU saturation/headroom;
- failure-domain limits.

A secondary objective is allowed only if frozen in advance and justified operationally. b-2 does not impose a universal lexicographic chain.

### 14.2 Resource uncertainty

A claimed host-count advantage must be supported at the declared engineering confidence/tolerance. If measurement/model uncertainty could change required host count, that advantage is not established.

---

## 15. Final technical selection

If `F` is non-empty, compute the minimum supported deployment objective:

`H* = min(H[a] for a in F)`

and:

`T = { a in F : H[a] == H* under the frozen support/tolerance rule }`

Outcomes:

- `UNIQUE_TECHNICAL_WINNER` if |T| = 1;
- `TECHNICAL_TIED_SET` if |T| > 1;
- `NO_QUALITY_PROTECTED_TECHNICAL_CHOICE` if F is empty;
- `NO_TECHNICALLY_ELIGIBLE_CANDIDATE` if E is empty;
- `TECHNICAL_EVIDENCE_INCOMPLETE` if required evidence is missing.

Canonical candidate id may order presentation only. It never creates a winner.

No Pareto/non-dominated set is required for the governing selection rule. Pareto plots may be retained as diagnostics, but they have no decision authority.

This explicitly resolves b-1's Pareto/dominance deferred subjects by replacing the historical frontier concept with constrained quality-protected deployment optimization.

---

## 16. Owner implementation choice

The owner may choose among candidates in T.

The owner may not:

- waive a failed gate;
- choose outside F merely for cost/convenience;
- reinterpret inconclusive/insufficient evidence;
- alter target attributes or margins after seeing results;
- relabel a tied set as statistical superiority;
- overwrite the technical outcome.

If T contains several candidates, the owner records operational reasons separately.

If F is empty, “owner choice” cannot be used as a hidden ranking algorithm. The allowed actions remain those already permitted by MSR §8.2: more evidence, defer, abandon, later event, baseline/incumbent/disabled capability where applicable.

---

## 17. Architectural-extension / MPID rule

The accepted MSR requirement remains: an architectural extension is not rejected merely because it needs an extension, but it must clear the frozen material-quality bar and ADR/dependency route.

Do **not** derive the reference through the old frontier.

For an extension candidate x:

1. identify all comparable gate-passing **existing-graph** candidates in E;
2. if an accepted single quality reference exists under the event protocol, use it;
3. otherwise use the relevant existing-graph quality envelope/reference set and direct simultaneous comparisons;
4. require the frozen MPID on the protocol-declared improvement claim(s);
5. require normal quality protection on all other required dimensions;
6. require all operational/deployment gates separately.

No arbitrary dependency penalty score is introduced.

If no eligible existing-graph comparator exists, the record states that the MPID comparator is unavailable. b-2 does **not** silently claim the material-improvement requirement satisfied. The authority disposition for that case must be explicit in the protocol/ADR review before implementation selection.

---

## 18. Combined attributes-role deployment check

Person and vehicle events remain separate for quality and MSR history.

However, before the Development role is treated as operationally viable, the selected/retained person and vehicle packs are also checked together under the declared attributes-role deployment for:

- Runtime Pack compatibility;
- combined resident memory;
- mixed job workload;
- worker/host topology;
- evidence/API pressure;
- failure behaviour;
- startup/recovery.

Separate capability passes do not imply the combined role passes.

This combined check is deployment evidence, not a merged quality ranking.

---

## 19. MSR representation

S2c decision summaries become set-valued where the evidence requires it.

Required S2c fields include:

- `highestTaskQualityEvaluatedSet[]`;
- `technicalEligibleSet[]`;
- `qualityAcceptableSet[]`;
- `technicalSelectionOutcome`;
- `technicalSelectedSet[]`;
- `technicalWinnerCandidateId` or null;
- `profileClearedTechnicalSet[]` per target profile;
- `implementationCandidateId` or composition id;
- `qualityContractHash`;
- `operationalContractHash`;
- `decisionEvidenceHash`.

### 19.1 Highest task quality

S2c no longer requires a scalar task-quality score to manufacture one “highest task-quality candidate” where multidimensional b-1 evidence does not support one. A supported set is valid.

### 19.2 Strongest evaluated technical

- one candidate only when outcome is `UNIQUE_TECHNICAL_WINNER`;
- otherwise `UNRESOLVED/SET — see technicalSelectedSet`.

### 19.3 Profile-cleared set

Licence clearance filters technically supported candidates for a declared profile; it does not remove technical comparators retrospectively or establish missing quality relations.

### 19.4 Implementation candidate

Remains a separate owner field and must be a permitted member under the governing technical/profile rules.

Generic scalar `comparativeScore` remains available for non-S2c MSR events but is not used to derive S2c outputs.

---

## 20. Historical weighted/Pareto reconciliation

The S2c parent plan's old weighted table and provisional Pareto language become historical only.

Implementation must:

- mark the weighted rule superseded/non-governing;
- remove S2c dependence on scalar `comparativeScore`;
- remove weight redistribution for unavailable criteria;
- remove “interval overlap = tie” paths;
- remove score-sensitivity as selection authority;
- state that Pareto plots/frontiers, if retained, are diagnostics only;
- preserve historical text for audit without leaving two live selection systems.

---

## 21. Owner inputs frozen before selection

### Inherited from b-1
- quality gate table;
- confidence-bound directions;
- practical/non-inferiority/equivalence margins;
- required robustness slices;
- MPID/replacement bar where applicable.

### Defined by b-2
- target profile/attribute set;
- host profile;
- workload family;
- lifecycle deadline and owner SLA(s);
- run repetition/summary rule;
- failure scenarios;
- 500-camera workload envelope;
- reserve policy;
- maximum hosts/memory/IO bounds;
- queue-age/backlog/drain constraints;
- model calibration vs held-out validation trace split;
- projection validation tolerances;
- primary deployment objective;
- allowed topology search space;
- composition manifest/experiment budget;
- combined-role deployment requirements.

No value is added after selection without a protocol revision and explicit evidence invalidation consequences.

---

## 22. Evidence stages

The plan distinguishes three engineering evidence stages.

### E1 — isolated bake-off measurement
Candidate/composition measurements in the network-denied evaluation harness.

### E2 — selection-stage operational model
Whole-job/service/topology measurements sufficient to compute the frozen b-2 decision consistently across candidates.

### E3 — integrated S2c.9 validation
Real worker/lease/evidence/publication execution for selected/finalist configurations, including projection validation and combined-role deployment.

The MSR must never describe E2 estimates as E3 execution.

If E3 materially contradicts the frozen model, the selection event is reopened/revised consistently; the next candidate is not silently “rescued” using the same exposed evidence.

---

## 23. Event-template changes

### Selection protocol
Require:

- b-1 and b-2 contract ids/hashes;
- experiment-freeze hash;
- complete candidate/composition manifest;
- target profile/attributes;
- host profile;
- workload family;
- lifecycle deadline vs owner SLA;
- quality comparison matrix requirements;
- deployment objective;
- topology search space;
- 500-camera fluid/replay model config;
- validation traces/tolerances;
- MPID reference rule;
- combined-role deployment requirement;
- revision invalidation rule.

### Selection record
Retain:

- quality comparison matrix;
- E and F sets;
- deployment objective result per F candidate;
- T set;
- evidence-stage labels;
- workload/model hashes;
- integrated validation status;
- MPID evidence;
- combined-role evidence;
- profile-cleared set;
- owner implementation choice separately.

---

## 24. Validator and algorithm tests

### 24.1 Contract refusal tests

Reject:

- duplicate keys;
- unknown/missing exact keys;
- Python bool/int coercion;
- non-finite numbers;
- missing b-1 deferred dispositions;
- redefinition of b-1 authority;
- weighted S2c comparative score;
- selection rule based on transitive closure/tier peeling;
- comparator deletion after resource elimination;
- licence/credibility in technical selection;
- missing composition manifest at freeze;
- selection-time workload/objective changes;
- frozen-test references in selection;
- owner implementation outside permitted technical/profile set.

### 24.2 Known-answer decision tests

Must cover:

1. chained non-inferiority A→B→C where A fails direct protection vs C;
2. cyclic quality outcomes;
3. cheaper candidate with inconclusive quality relation;
4. resource-cheaper candidate facing materially superior challenger;
5. full-set F empty;
6. F with one candidate;
7. F with several candidates and one minimum host count;
8. exact deployment tie preserving a set;
9. missing required evidence producing `TECHNICAL_EVIDENCE_INCOMPLETE`;
10. licence filtering not rewriting technical sets;
11. owner choice not rewriting outcome;
12. MPID extension with and without eligible comparator.

### 24.3 Composition tests

- fourth standalone-equivalent component forms best shared-backbone composition;
- no standalone top-K pruning after selection;
- actual composition resources differ from component arithmetic;
- shared-backbone claim without actual shared execution refused;
- partial target attribute cannot enter full profile;
- predeclared partial profile remains separate.

### 24.4 Fleet/replay tests

- fluid recurrence closed-form cases;
- same Track throughput but different job-size distribution gives different queue latency;
- synchronized release burst;
- one long job with idle workers;
- process loss near completion reintroduces lost work;
- restart and lease expiry overlap;
- host loss removes several workers and their in-flight jobs;
- protected publication after Phase-A deadline point remains lifecycle-valid where S2b allows it;
- owner SLA can still fail separately;
- calibration trace and held-out validation trace separated;
- projection underprediction beyond tolerance fails validation.

### 24.5 Mutation targets

At minimum kill mutants that:

- use transitive/non-inferiority chaining;
- peel comparators before F is computed;
- convert inconclusive to tie;
- rank by weighted score;
- choose by candidate id;
- prune composition by standalone top-K after selection;
- sum component resources;
- ignore lost work on process/host loss;
- use Track-fluid output as job-deadline proof;
- conflate Phase-A deadline with publication SLA;
- reuse calibration trace as validation evidence;
- silently replace E2 with E3 claims;
- let licence delete a technical comparator;
- let owner choice overwrite F/T;
- treat absent MPID comparator as automatic MPID pass.

---

## 25. Expected implementation file set

Planning/protocol/validator surfaces only:

- new b-2 JSON contract;
- new b-2 Markdown protocol;
- standard-library validator/checker;
- unit/known-answer/mutation tests;
- MSR README/M1 S2c representation amendments;
- protocol/record templates;
- S2c parent-plan reconciliation;
- qualification-plan additive authority only if genuinely required;
- b-2 implementation record;
- roadmap/register status text.

No runtime, API, UI, Model Pack or Runtime Pack implementation belongs in this slice.

---

## 26. Implementation sequence

1. Write discriminating tests first.
2. Implement canonical contract + cross-load b-1.
3. Implement pure decision helpers:
   - E construction validation;
   - direct pairwise P matrix;
   - F calculation;
   - deployment objective calculation;
   - T calculation;
   - MPID rule;
   - set-valued MSR derivation.
4. Implement fluid screen + bounded deterministic job replay helper.
5. Add deterministic Markdown projection.
6. Amend templates/M1 representation.
7. Reconcile parent historical weighted/Pareto text.
8. Record implementation/non-claims.
9. Perform one comprehensive closure review with complete P1/P2 ledger before edits, then one consolidated repair.
10. After closure, only bounded regression/merge-gate verification unless new scope is introduced.

---

## 27. Acceptance criteria for b-2 implementation

Complete only when:

1. every b-1 deferred subject has one explicit disposition;
2. b-1 remains unchanged;
3. complete experiment freeze is machine represented;
4. job-level timing semantics match S2b lifecycle;
5. 10k is a boundary inside a workload family, not the sole workload;
6. actual composition accounting is enforced;
7. no post-selection standalone top-K pruning exists;
8. direct quality protection is computed against complete E;
9. no transitivity assumption is used;
10. primary deployment objective and feasibility constraints are explicit;
11. set-valued technical outcomes are supported;
12. weighted S2c comparative score is retired;
13. fluid sizing and job replay are both implemented and clearly separated;
14. 500-camera claim boundary is explicit;
15. integrated validation stage is distinct from selection-stage estimates;
16. combined person+vehicle role deployment check is specified;
17. MPID no-reference case is explicit and not auto-passed;
18. MSR task-quality/technical/profile outputs can be sets;
19. b-1 repository check still passes;
20. b-2 repository check passes;
21. `tools/verify_repo.py` passes;
22. exact-head CI is green;
23. no P1/P2/material review thread remains;
24. no model was selected/downloaded/trained/benchmarked;
25. no F/G row changed.

After b-2 merges, S2c.2 protocol freeze may instantiate both contracts and the real owner inputs before any selection results are read.

---

## 28. Disposition of Astra review findings

| Astra finding | Revised disposition |
|---|---|
| pairwise dominance elimination can discard essential comparator | accepted — removed; direct complete-set quality protection |
| tiering/tolerance dominance can cycle | accepted — tier/frontier selection removed |
| component pruning not composition-preserving | accepted — predeclared bounded composition manifest |
| Track-fluid model wrong unit for deadline/recovery claims | accepted — fluid screening + job replay |
| lifecycle deadline/publication conflated | accepted — explicit Phase-A/publication/SLA timestamps |
| selection vs integrated measurement mismatch | accepted — E1/E2/E3 evidence stages |
| person/vehicle separate passes do not prove role viability | accepted — combined attributes-role deployment check |
| six resource axes obscure decision | accepted — one primary deployment objective + constraints |
| MSR still scalar for task quality | accepted — set-valued task-quality/technical/profile outputs |
| revision after exposure remains adaptive | accepted — explicit fresh-evidence/new-event consequences where bias is possible |

---

## 29. Questions for Claude cold review

Claude should now review this **revised** plan from first principles against current `main`.

Actively attack:

- whether direct quality protection P/F is too strict or under-specified;
- whether any pairwise outcome semantics still violate b-1;
- whether the default minimum-host objective creates hidden owner policy;
- whether the composition manifest amendment properly reconciles accepted parent K=3 text;
- whether E1/E2/E3 evidence staging is implementable without prematurely integrating every candidate;
- whether Phase-A/publication semantics match current code/ADR;
- whether job replay overclaims platform scheduler behaviour;
- whether fluid/replay calibration and validation can leak selection adaptation;
- whether the MPID no-reference rule needs an ADR amendment;
- whether set-valued MSR outputs conflict with M1 validator/current JSON shape;
- whether licence filtering of T/profile sets is mathematically and semantically correct;
- whether the combined-role check belongs in b-2 or a later S2c execution slice;
- whether any owner decision path still creates a hidden ranking;
- whether machine checks prove the claims the prose makes.

Claude must produce a complete P1/P2 ledger before proposing edits and should propose a materially different design if this revision is still not the cleanest architecture.

---

## 30. Decision record for revised draft

This revision deliberately adopts:

- whole-job/job-level operational semantics;
- separate lifecycle deadline validity and publication/SLA claims;
- workload family with 10k boundary;
- actual composition measurement;
- predeclared composition manifest instead of post-selection top-K pruning;
- direct quality protection against the complete eligible set;
- one frozen primary deployment objective with operational constraints;
- set-valued technical outcomes;
- fluid screening plus deterministic job replay;
- combined-role deployment evidence;
- set-valued MSR representation;
- explicit MPID/no-reference handling;
- retirement of weighted and governing Pareto selection for S2c.

These are now the primary subjects for the formal repository-grounded cold review before implementation.
