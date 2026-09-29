# Model Selection Records — Methodology (MSR method v1)

**Status:** Accepted — PR #115 merged the independently reviewed MSR method v1 at `main@677afb6b73edf436e23f8d275bb95a7d5b3badac`; that merge is the acceptance event. Future learned Model Pack selections must follow the accepted ADR-014 Model Selection Records note. S2c.0 records/reconciles the accepted method into the implementation baseline; it does not create a second acceptance event. **Revision M1** (candidate credibility and admissibility, `candidate-credibility.md`, slice S2c.2a) is an additive revision of v1, merged in PR #118 at `main@db2b25a24d0f850c3841a9eabcb915f7c92eebfb` (§14).
**Scope:** every learned component MAVI binds through a Model Pack. That includes detectors, trackers with learned parts, person and vehicle attributes, embeddings, re-identification, segmentation, OCR, VLMs, and any later capability.
**Purpose:** make every model choice reconstructible years later without the author's memory. A future reader must be able to answer:
- which models were considered, and how they were found;
- which exact bytes were evaluated;
- what published and MAVI-measured evidence existed at the time;
- why the chosen one was chosen;
- what was rejected or deferred, and why;
- what a successor must beat.

---

## 1. What this methodology is, and is not

A **Model Selection Record (MSR)** is the decision and evidence history of one **Model Selection Event**. The event chooses a model for one capability id (ADR-014 §2) at one point in time.

The MSR does not replace any authoritative document. It cites them:

| Document | Authority | Relation to the MSR |
|---|---|---|
| ADRs (`docs/decisions/`) | architecture: capability contracts, Model/Runtime Pack model, identity rules | the MSR cannot change architecture; a candidate that needs an architectural change is recorded with that need, and the change goes through an ADR first |
| Stage acceptance register (`docs/reviews/<date>-<stage>-acceptance.md`) | the only exit gate of its stage | the MSR is evidence a register row may cite; it holds no acceptance list and marks nothing PASS |
| Qualification plan (for Stage 2: `docs/qualification/2026-09-23-visual-attributes-qualification-plan.md`) | qualification protocol: corpus governance, partitions, labelling, metrics, freeze order, requalification triggers | the MSR's selection protocol instantiates it and may not weaken it; the frozen qualification test is never used for selection |
| Candidate credibility and admissibility (`candidate-credibility.md`, revision M1) | which candidates are credible enough for the shortlist and for implementation; the External Evidence Ledger | part of this method; it adds a credibility axis and never changes the technical ranking |
| S2c quality/statistical protocol (`s2c-quality-statistics.md` + machine contract) | S2c-specific populations, metric denominators, partition authority, calibration and inferential-comparison semantics under qualification-plan R3 | event-specific protocol used by the person/vehicle MSRs; **not** a generic MSR-method revision and does not define the b-2 final technical ordering |
| Candidate survey (for S2c: `docs/qualification/stage2-s2c/model-candidate-survey.md`) | discovery and research evidence at a date; reported, not reproduced | an input; the MSR cites survey rows and snapshots what it relies on (§6) |
| Model Pack qualification record (`models/qualifications/*.json`) | qualification of one exact packaged model per variant and profile | the MSR explains *why* this pack exists; the record says whether it is *qualified*; the record cites the closed MSR by hash (§10) |
| Implementation plan (for S2c: the plan above) | implementation sequencing | says in which slice each MSR state transition happens |
| Dependency/offline policy (`docs/architecture/dependency-and-offline-packaging-policy.md`, `config/dependencies/`) | dependency admission | the MSR records a candidate's dependency burden; admission of a dependency is decided there |

If an MSR ever disagrees with an authoritative document, the authoritative document wins. The MSR then gets an erratum (§11).

## 2. Three assessments that are never merged

Every event records three assessments separately. **No single score combines them.**

1. **Technical assessment.** Which candidate is strongest for the task on retained evidence: task quality, calibration, abstention and robustness.
2. **Operational / engineering assessment.** How the candidate behaves under MAVI's constraints:
   - runtime budget, memory and co-residency;
   - determinism, offline operation and packaging;
   - Runtime Pack impact, dependency burden, maintainability and failure behaviour.
3. **Licence / deployment qualification.** Under what terms the exact code, weights, training provenance and dependencies may be used, for which **declared MAVI deployment profile** (§2.1).
   - It is recorded from primary sources only: the licence text with its retrieved-bytes hash, and the model card.
   - Legal readings and end-use applicability are **human qualification decisions**, recorded with the decision-maker and date.
   - The MSR never reinterprets a licence and never infers an application domain. MAVI is domain-neutral unless a deployment's own qualification record states its use.

Assessments 1 and 2 together form the **technical ranking**. Licence terms never enter it: no weight, no tie-break, no pre-filter.

**The one carve-out: evaluation permission.** Whether MAVI may lawfully *run* a candidate on its data is a human legal precondition to measurement, not a ranking input. It is recorded with decision-maker, date and primary source. A candidate that may not be evaluated becomes `REFERENCE_ONLY`: its reported evidence stays in the record at full strength and is marked "not reproduced by MAVI". It is never `NOT_SHORTLISTED` on that ground. (Under revision M1 an `excluded-discovery`, whose origin cannot be identified, is `NOT_SHORTLISTED` on credibility grounds whatever its evaluation permission.) Where the method is usable but the released checkpoint is not, the method trained on MAVI-permitted data represents it.

Assessment 3 is applied afterwards to decide which ranked candidates are **cleared for a declared deployment profile**. A technically superior candidate stays in the record at its rank, marked with its constraint, even when it is not cleared for any declared profile.

### 2.1 The declared MAVI deployment profile (owner constraint)

**MAVI is a non-commercial solution.** "Enterprise-grade" in MAVI documents means engineering quality: reliability, robustness, maintainability, modularity, security, offline deployability, operational scale and production-quality software engineering. It **does not** mean commercial use.

The licence axis therefore assesses the **declared MAVI deployment profile**, which is non-commercial unless a profile's own record says otherwise. It never assesses a hypothetical commercial product.
- Commercial-use permission is **not** required merely because MAVI is engineered to enterprise standards.
- Non-commercial or research-only terms are **not automatically disqualifying**. They are read against the profile's actual uses. Some research licences exclude "product development" or operational use even when no money changes hands, and whether MAVI's use falls inside such a grant is a human determination.
- "Free of cost" is not "redistributable". Every right is recorded separately (§5 licence rights).
- If local non-commercial use is permitted but redistribution is not, the record says so explicitly. It then states how the weights reach a host without MAVI redistributing them. Bundling weights in a repository, a public kit or an offline media image is **never assumed** to be permitted. Weights are never in Git in any case (AGENTS.md).
- The standard term is **"cleared for the declared MAVI non-commercial deployment profile `<profile id>`"**. The words "deployable" and "commercially usable" are not used as licence verdicts.

## 3. Model Selection Events

### 3.1 Identity and location

- **Event id:** `msr-<capabilityId>-<year>-<nn>`, for example `msr-person-attributes-2026-01`. `<year>` is the year the event opens, and `<nn>` is a two-digit **sequence number** within that capability and year (not a month).
  - The capability id is the stable contract name (ADR-014 §2), so upgrade events line up with it over the years.
  - Lower-case kebab form matches every other MAVI identifier and can appear as a qualification-record evidence reference.
  - The originating stage (for example S2c) is a field of the record, not part of the id, because later events will not belong to a stage.
- **Location:** `docs/qualification/model-selection/<capabilityId>/`, one directory per capability. Each event has three files:

| File | Written | Mutability |
|---|---|---|
| `<event-id>-protocol.md` | at `PROTOCOL_FROZEN` | immutable once its SHA-256 is recorded in the record; any later change is a protocol revision recorded in the record, and it voids the results it could bias |
| `<event-id>.md` (the record) | from `PLANNED` to `CLOSED` | editable while the event is open; **immutable once `CLOSED`**. Its SHA-256 is never written inside itself (a file cannot contain its own hash). It is written in the index (§13), in the addenda header, and in the qualification record's evidence (§10) |
| `<event-id>-addenda.md` | after `CLOSED` | append-only: errata, qualification outcomes, supersession pointers (§11) |

- Templates are in `templates/`. The index of events is §13.

### 3.2 Event states

```
PLANNED → PROTOCOL_FROZEN → EVALUATING → TECHNICAL_DECISION_RECORDED → QUALIFICATION_PENDING → CLOSED
              (any state) → ABANDONED   (with reason; the record is retained)
```

| State | Entry condition |
|---|---|
| `PLANNED` | task definition, capability id, baseline, incumbent (or "none") and discovery sources recorded; candidates `DISCOVERED` |
| `PROTOCOL_FROZEN` | protocol file committed and hashed **before any candidate sees MAVI evaluation data**. The protocol holds: shortlist with exact checkpoint identities, partitions, metrics, gates, comparative weights and scoring rule, the minimum practically important difference (MPID), strata, host class, and report format |
| `EVALUATING` | harness runs under the frozen protocol; results retained by hash |
| `TECHNICAL_DECISION_RECORDED` | gates evaluated, measurements tabulated, technical ranking computed by the frozen rule; strongest reported, highest task-quality and strongest evaluated technical candidates named (§9) |
| `QUALIFICATION_PENDING` | licence/deployment qualification per target profile recorded or awaited; strongest candidate cleared for each target profile named; implementation candidate chosen by the owner |
| `CLOSED` | one of the outcomes below is recorded; record hashed |

A `CLOSED` event has exactly one **outcome**:
- `SELECTED_FOR_PACKAGING`: an implementation candidate goes on to become a Model Pack.
- `INCUMBENT_RETAINED`: no challenger justified replacement.
- `BASELINE_SELECTED`: no learned candidate beat the deterministic baseline, and the baseline is packaged.
- `NO_QUALIFIABLE_CANDIDATE`: the capability or attribute stays disabled.

`CLOSED` does not mean qualified. Qualification of the resulting pack is decided by its qualification record and reported back through an addendum.

## 4. Candidate lifecycle

Each candidate carries **two independent status axes** and a **role**. They are never collapsed into one field. Revision M1 adds a third, independent **credibility class** (`established`, `emerging`, `reference-only`, `excluded-discovery`, `mavi-owned`), computed from the event's External Evidence Ledger (`candidate-credibility.md` §3). It restricts which candidates may be `SHORTLISTED` and which may become the implementation candidate. It never enters the technical ranking.

**Role:** `baseline` (deterministic/simple floor), `incumbent` (the currently bound pack, if any), `challenger`, or `reference` (reported only, never evaluated).

**Technical disposition:**

```
DISCOVERED ─→ SHORTLISTED ─→ EVALUATED ─→ TECHNICALLY_SELECTED
    │              │             ├──────→ TECHNICAL_ALTERNATIVE   (passed the technical gates; ranked below)
    │              │             └──────→ REJECTED_TECHNICAL      (failed a technical gate, or dominated; gate/measurement cited)
    │              ├──────────────────→ DEFERRED                  (evidence or resources insufficient; revisit trigger stated)
    │              └──────────────────→ REFERENCE_ONLY            (could not be evaluated: permission, availability; or under M1 held for credibility; reported evidence kept, marked not reproduced)
    └──────────────────────────────────→ NOT_SHORTLISTED          (technical reason recorded, or under M1 the credibility reason of an excluded discovery; never a licence reason)
```

**Licence / deployment qualification status** (per target deployment profile; independent of technical disposition):

| Status | Meaning |
|---|---|
| `NOT_ASSESSED` | no review yet |
| `REVIEW_PENDING` | primary sources captured, human determination awaited |
| `CLEARED` | a human reviewer recorded that every right the declared profile actually exercises is granted for the exact code, weights, training provenance and dependencies (§5 licence rights). This covers evaluation, operational running, any fine-tuning and derivatives MAVI makes, and whatever distribution the profile's delivery route requires. Decision-maker, date and profile id are recorded. A candidate restricted from commercial use can be `CLEARED` for a non-commercial profile |
| `CONSTRAINED` | a recorded term restricts a use the declared profile **actually needs**, for example redistribution when the profile ships weights in an offline kit, derivative rights when MAVI fine-tunes, operational use under a research-only grant, or an end-use clause awaiting a per-deployment determination. Terms that restrict only uses the profile does not make (such as commercial sale) do not by themselves make a candidate `CONSTRAINED`. The candidate stays at its technical rank |
| `NOT_CLEARED` | reviewer recorded that it may not be used for the named profile(s) |

**Lifecycle after the event** (recorded in later addenda or later events, never by rewriting a closed record):
- `QUALIFIED_INCUMBENT`: the implementation candidate's Model Pack passed its qualification record for a profile and is bound. The qualification record is the authority; the addendum cites it by id and hash.
- `SUPERSEDED`: a later event replaced it; the addendum names that event.

Required combinations:
- A candidate can be `TECHNICALLY_SELECTED` and `CONSTRAINED` at once. That is the case this methodology exists to preserve.
- A candidate whose licence forbids commercial use but grants every use the declared non-commercial profile makes is a fully valid implementation candidate.
- The **implementation candidate** is the owner's choice among candidates that are at least `TECHNICAL_ALTERNATIVE`, past every technical gate, and `CLEARED` for **each named target profile** of the event (the licence gate is per profile). An event may not close as `SELECTED_FOR_PACKAGING` for a profile whose determination is still pending. Profiles determined later (for example a Production deployment) are recorded as licence/deployment-determination addenda (§11) and in the qualification record's `licence` gate evidence. It may differ from the strongest evaluated technical candidate. The measured gap between them is always recorded (§9).
- Under revision M1 the implementation candidate (each component, for a composition) must also have credibility class `established` (or `mavi-owned`). That class must be reached by a recorded history entry dated on or before the decision (`candidate-credibility.md` §8). An `emerging` candidate that wins the bake-off stays at its rank as the strongest evaluated technical candidate. It needs a recorded promotion before it can be implemented.

## 5. Candidate record: exact identity

A candidate is identified by the **bytes evaluated**, never by a family name.

**Checkpoint candidates** (released weights) record:
- upstream repository;
- immutable revision (tag *and* commit, or model-hub revision hash);
- file path;
- SHA-256 of every weight file MAVI evaluated.

**Method candidates** (an architecture trained or fitted by MAVI) record:
- the backbone checkpoint identity as above;
- the MAVI training manifest hash (inputs by manifest hash, seed, environment lock, code revision);
- the SHA-256 of each produced artefact (head, calibration).

Every serious candidate also has an entry in the event's **External Evidence Ledger** (`<event-id>-evidence-ledger.json`, revision M1; `candidate-credibility.md` §4). The ledger keeps first-party claims apart from independent evidence and traces each reported figure to its origin. Its checkpoint identity is the one below.

Every serious candidate records, where available, the fields below. Unknown means `UNKNOWN`, and `UNVERIFIED` marks an unconfirmed claim. Nothing is left blank or guessed.

| Group | Fields |
|---|---|
| Identity | candidate id; canonical model/family name; exact checkpoint (above); upstream repository; release/tag/commit; weight SHA-256; publication or model-card date; retrieval date |
| Architecture | architecture; parameter count (the part executed at inference); input resolution; preprocessing (as data: resize, normalisation, colour order, crop policy), with its hash |
| Data | pretraining datasets; training datasets; fine-tuning datasets (MAVI's by manifest hash); known overlap with MAVI data |
| Reported evidence | each reported figure with its source, table or section, dataset and split, and date, marked **reported** (§6) |
| Licence (primary sources) | code licence; weights licence; dataset terms; SHA-256 of each retrieved licence and card text; licence class per the capability's analysis; review status per profile (§4). Plus a **rights inventory**, each entry granted / not granted / not stated / UNVERIFIED, with source clause, and what it applies to (code, weights, derived models, data): right to **evaluate**; right to **run operationally**; right to **modify / fine-tune**; right to **create derivatives**; right to **redistribute the weights**; right to **redistribute derived weights**; **attribution/notice** obligations; **end-use** restrictions (commercial, surveillance/security/law-enforcement, military/defence, other); **data/provenance** restrictions. The profile's delivery route (local acquisition on the host, or inclusion in an offline kit) is recorded beside it, because it decides whether redistribution is exercised |
| Runtime | framework/runtime requirements; export route; CPU/CUDA requirements; offline viability (loads from pack artefacts alone?); Runtime Pack impact (existing family or extension) |
| Judgement | reason for inclusion; known uncertainties; disposition with reason and evidence reference |

### 5.1 Multi-component capabilities: composition candidates

Some capabilities are served by one Model Pack that composes components solving different sub-tasks. `person-attributes`, for example, covers clothing colour (T-PC) and carried objects/headwear (T-PO). Winners of separate sub-tasks do not automatically make a good pack: a shared backbone, memory, load time and failure domain all change. The event therefore runs a fixed sequence:

1. **Sub-task evaluation.** Each sub-task's candidates are evaluated and ranked on their own (§8), producing per-sub-task **component finalists**. These are the candidates that pass the per-component gates for at least one attribute of the sub-task, capped at the protocol's `K` best by the sub-task ranking. A packageable baseline may be one of them. Budget and scale gates are judged per composition (step 3). A small `K`, for example 3, keeps the search bounded.
2. **Composition generation, by a rule frozen in the protocol.** The composition candidates are:
   - the tuple of the sub-task winners;
   - every tuple of finalists that **share a backbone** (one tower serving both sub-tasks with separate heads), which is evaluated as its own candidate because its heads are trained on the shared features;
   - the protocol's cap on further tuples from the finalist product, ordered by the sum of sub-task ranks.

   Non-packageable baselines never enter a tuple. Each composition is written as an exact tuple (`<T-PC component>`, `<T-PO component>`, optional shared backbone or region component), each element with its exact identity (§5). No composition may be proposed after results are seen.
3. **Composition evaluation**, on the same partitions and hosts. Each composition records:
   - combined per-attribute quality, with each sub-task's primary metrics taken from its components;
   - end-to-end CPU latency per crop and per Track, and aggregate throughput;
   - peak RAM/VRAM with the detector co-resident;
   - model-load/READY time;
   - Model Pack size;
   - dependency and Runtime Pack impact;
   - whether a backbone is shared;
   - the system-scale projection (§7.1);
   - the failure-domain implications (one process holding all components, and what one component's failure takes down).
   **Every composition must pass the protocol's technical and engineering gates as a unit** (offline, determinism, budget, abstention, system scale, with memory inside the scale/host envelope); gates judged on heads are re-run on the composition's actual heads: components that each fit can exceed the envelope together. Failing compositions are recorded with the reason. So are attributes whose composition heads fail the re-run baseline gate; those are disabled in that composition.
4. **Pareto frontier.** Compositions are compared on scalar axes frozen in the protocol: a quality scalar (for example the equal-weight mean over a fixed attribute set of the primary-metric improvement over baseline, with disabled attributes scored as zero, which keeps dominance transitive), per-crop cost and memory. Dominated compositions are recorded as dominated, not deleted. The frontier is typically two to four compositions, and the comparative score of §8 ranks within it.
5. **Implementation composition.** The owner chooses a frontier composition under the same rules as a single implementation candidate (§4, §9). Its components all need licence status `CLEARED` for the target profile.

A single-component capability skips steps 2–4. Its composition is the implementation candidate itself.

## 6. Evidence classes

Every number in an MSR carries its class. Classes are never mixed in one column, and a figure never changes class.

| Class | Meaning | Example | May decide a gate? |
|---|---|---|---|
| **R — reported** | published by others; not reproduced by MAVI | paper benchmark; model-card result; vendor throughput claim | no; context only |
| **M-D — MAVI development estimate** | measured by the MAVI harness on training, tuning or selection partitions | per-attribute AP/AUROC, macro-F1, calibration, abstention, cross-site/leave-one-camera-out, strata | yes, for selection gates; never a qualification claim |
| **M-E — MAVI engineering measurement** | measured on a pinned host class | latency p50/p95, throughput, memory, CPU/CUDA, deterministic replay, offline run, pack size, load time | yes, for engineering gates |
| **M-Q — MAVI qualification result** | frozen-test result for a frozen identity (qualification plan R1 steps 3–4) | S5 frozen-test report | only through the qualification record; an MSR cites it by reference and hash in an addendum |

A reported figure stays reported: it never silently becomes a MAVI claim. When MAVI reproduces a reported benchmark, the reproduction is a separate M-row that cites the R-row it checks.

Every M-row records:
- the harness version and evaluation configuration;
- the partition manifest hash;
- the result artefact SHA-256.

Because URLs rot, an R-row relied on by a decision is snapshotted at `PROTOCOL_FROZEN`: the figure, the source, the retrieval date, and the SHA-256 of the retrieved document where it can be captured.

## 7. Evaluation dimensions

The protocol chooses the applicable dimensions **before results exist**, and records why any dimension is excluded.

- **Task quality:** task accuracy; threshold-free primary metrics; precision at the declared operating point; recall; unknown/unavailable behaviour; abstention behaviour; calibration.
- **Robustness:** cross-camera/site; day/night; image quality; occlusion; crop size; domain shift.
- **Runtime:** inference latency; throughput; memory; CPU viability; CUDA performance; determinism; reproducibility.
- **Deployment:** offline operability; Runtime Pack impact; Model Pack size; dependency burden.
- **Engineering:** engineering complexity; maintainability (upstream maintenance status, replaceability); failure behaviour; security/offline implications.
- **System scale** (§7.1): aggregate throughput; worker/process topology; CPU/GPU fleet sizing; concurrency; queue depth and backlog; latency under sustained load; storage and evidence growth; memory pressure; model-load footprint; startup/recovery; offline deployment footprint; scheduling across hosts; horizontal scaling; failure isolation; per-camera and aggregate resource cost.

### 7.1 System-scale principle

**A model or composition is never selected on single-worker accuracy alone when its resource profile would make MAVI architecturally unsuitable at the platform's declared scale.** The owner's standing requirement is deployments of up to **500 cameras**. Each event records the scale target in force when it opens.

The protocol freezes a **scaling evaluation method**. The record retains, per finalist or composition:
- **Measured quantities (M-E):**
  - per-crop service time distribution;
  - crops-per-Track distribution;
  - per-worker throughput;
  - peak CPU/GPU memory;
  - how many workers fit on one host of the declared class;
  - model-load/startup cost;
  - recovery time after a worker loss;
  - Model Pack and storage footprint.
- **Workload model:** Tracks per camera per minute under the declared representative camera loads, and its distribution. It is owner-declared and versioned.
- **Projection to the scale target:**
  - required worker count and hosts;
  - steady-state queue depth, and backlog drain time after a peak or a worker/host loss;
  - aggregate memory and storage growth (evidence and artefacts).

  The projection is reproducible from the measured quantities and the workload model by a script retained by hash.
- **Validation of the extrapolation:** accelerated or synthetic load at a meaningful fraction of the target, with several workers on more than one host where available. The record states the load actually executed. **If the validation disagrees with the projection beyond the protocol's tolerance, the selection is re-opened** with the measured quantities.

A projection is class **M-E (projected)** and never a scale qualification. No record claims a 500-camera qualification unless one was physically executed. Horizontal scaling relies on the existing lease model: several attribute workers, on one or many hosts, claim units concurrently (S2b `FOR UPDATE SKIP LOCKED` claims per worker id). A candidate whose projection needs an architectural change to reach the target is recorded with that need (§1) and does not pass the protocol's scale gate until the change exists.

## 8. Decision methodology

A decision is reconstructed from five separate layers, recorded in this order. No layer is hidden inside another.

1. **Mandatory gates.**
   - Pass/fail rules frozen in the protocol, each with the measurement that decided it.
   - Technical and engineering gates (for example offline, determinism, runtime budget, beating the baseline, abstention sanity) apply to the ranking.
   - The licence/deployment gate is a qualification gate (§2) and never affects the ranking.
   - A weighted score can never compensate for a failed gate.
2. **Measured metrics.** The full measurement table, with intervals and evidence classes, for every evaluated candidate including the losers. Raw per-item predictions are retained by hash.
3. **Comparative scores (optional ordering aid).**
   - Weights and the rule converting each measurement into a criterion score are frozen in the protocol.
   - Differences within the protocol's statistical interval score as ties **unless the capability-specific governing protocol defines explicit superiority/non-inferiority/equivalence/inconclusive states**. For S2c person/vehicle events, qualification-plan R3 + `s2c-quality-statistics.md` override this generic aid: interval overlap is not equivalence, and an inconclusive/insufficient-evidence result cannot become a tie or statistical winner.
   - Scores are reported at the precision the data supports, never more.
   - The record reports a **sensitivity check**: does the top-ranked candidate change when any one weight group moves by the protocol's declared perturbation, or when any group is removed? An unstable ranking is recorded as unstable, and the choice between the tied candidates becomes an explicit owner decision.
4. **Owner decisions.** For example the MPID, target precisions, whether to seek a licence for a stronger constrained candidate, and the implementation candidate. Each has a rationale, decision-maker and date.
5. **Qualification decisions.**
   - Licence/deployment determinations per profile (human, §2).
   - Then the Model Pack qualification record (authoritative, §1).

### 8.1 Statistical rule (cluster-aware)

Evidence units are correlated: Tracks from one camera, cameras within one site, repeated scene/date conditions, and recurring subjects. Two adequacy requirements are therefore kept separate, and both are frozen in the protocol.

1. **Attribute/value support.**
   - Precision needs predicted-positive support at the operating point.
   - Recall needs ground-truth-positive support.
   - Prevalence and coverage are measured.
   - Each iid-based count is multiplied by the **design effect** `DEFF = 1 + (m̄ − 1)·ρ`, with `m̄` the size-weighted mean cluster size `Σm²/Σm`, which does not understate DEFF when clusters are unequal, and `ρ` the intra-cluster correlation of the relevant indicator. `ρ` is estimated on the pilot (training partition) where feasible, otherwise taken as a declared conservative value.
2. **Independent cluster support**, for camera/site generalisation, for model-comparison intervals and for difficult-stratum claims. The sampling unit is the top-level cluster: the site, or the camera where a site has one camera.

**Resampling method: hierarchical paired bootstrap.**
- Resample top-level clusters (site, or camera block) with replacement, then Tracks with replacement within each drawn cluster.
- Each replicate computes the metric difference for both candidates on the **same** resampled units.
- The interval is the percentile interval at the protocol's level (95 % in S2c).
- Seeds and replicate count are recorded.

**Sufficiency is determined, not assumed.** Before any candidate result, a calibration simulation runs on the **training-partition pilot**. The protocol freezes its method and perturbation model; its output, the minimum cluster count, is appended to the protocol by hash before selection data is read. The simulation works as follows:
- It takes the baseline's predictions and a synthetic perturbation of them with the same expected quality.
- It swaps the two **at cluster level** at random, which creates a known zero difference.
- It checks that the procedure's interval covers zero at close to its nominal rate across simulated cluster counts. The protocol freezes the minimum number of top-level clusters at which coverage stays within its declared tolerance, and the same check is applied per stratum.

**When support falls short, the claim is downgraded, never reported as significant.**
- **Comparison:** below the minimum cluster count, no "significant winner" is declared. The record reports per-cluster results, a cluster-level sign count, and "insufficient independent clusters for an inferential claim". The choice becomes an explicit owner decision (§8 layer 4).
- **Generalisation and strata:** these claims become "limited evidence".
- **Value support:** a value below its DEFF-inflated support is "insufficient evidence" (qualification plan §5).

"Better" means the hierarchical paired interval of the difference excludes zero, **and** the cluster count meets the frozen minimum.

A candidate needing an architectural extension (for example a new Runtime Pack family) must clear the protocol's MPID over the best candidate that needs none, and must pass the ADR route. It is **never rejected merely for needing a reasonable extension** once it clears that bar.

## 9. Required selection output

A record at `TECHNICAL_DECISION_RECORDED` or later states each of the following explicitly. They are separate fields because they may name different candidates, and the methodology never forces them to coincide.

| Field | Meaning |
|---|---|
| Baseline / incumbent | as defined in the protocol |
| **Strongest reported / reference candidate** | the strongest candidate on **reported** (class R) evidence, including `REFERENCE_ONLY` candidates MAVI could not run. It is marked "reported, not reproduced by MAVI", and it never implies a MAVI result |
| **Highest task-quality evaluated candidate** | best on the frozen primary task-quality metrics alone (M-D), ignoring runtime and engineering |
| **Strongest evaluated technical candidate** | first in the full technical ranking (quality, runtime, engineering, system scale; §8), among candidates MAVI actually evaluated |
| **Strongest candidate cleared for `<profile id>`** | per target profile: the highest-ranked evaluated candidate whose licence status is `CLEARED` for that declared profile |
| **Implementation candidate** | the owner's choice (§4); for a multi-component capability, the implementation **composition** (§5.1) |
| Alternatives | in rank order; for compositions, the Pareto frontier with dominated compositions listed |
| Rejected / deferred / reference-only / not shortlisted | each with its reason and revisit trigger |
| Deltas | quality and resource deltas between each pair of the fields above that differ: highest task-quality vs strongest evaluated technical, which shows when accuracy lost on cost or scale; strongest evaluated technical vs strongest cleared; strongest cleared vs implementation |
| Projected system-scale footprint | per finalist or composition (§7.1) |
| Evidence, risks, qualification status | evidence by hash; unresolved risks and assumptions; qualification status |

Once they exist, the identities follow, recorded when created and by reference:
- Model Pack id;
- Runtime Pack id per variant;
- capability binding and pipeline profile/identity;
- qualification record id.

**Standard wording, which is conditional and never stretched to fit the choice:**
- If the implementation candidate **is** the strongest candidate cleared for the target profile, the record says: *"selected as the strongest candidate cleared for the declared MAVI deployment profile `<profile id>` within MAVI's defined \<capability\> operating envelope, based on retained bake-off evidence"*.
- If it **is not**, that sentence is not used. The record states instead:
  - the strongest evaluated technical candidate;
  - the strongest candidate cleared for the profile;
  - the implementation candidate;
  - why the implementation candidate differs;
  - the measured quality and resource delta;
  - the owner decision, with decision-maker and date.

"Strongest" is never redefined to match the final choice, and no candidate is called "best". None of this wording means the Model Pack qualification record has passed, and none of it says anything about Production.

## 10. Reproducibility and hash links

The record references, and does not duplicate, the authoritative identities:
- corpus manifest hash and partition manifest hash;
- evaluation harness commit and environment lock hash;
- evaluation configuration hash;
- per candidate: checkpoint digests, preprocessing hash and adapter id;
- Runtime Pack id where the candidate runs in a pack;
- host class and host observation hash (the ADR-009 Development evidence identity form);
- device policy and thread count;
- software versions via the lock;
- random seeds;
- result artefact hashes and report hashes.

Imagery and private derived data stay in the access-controlled evidence store (AGENTS.md: no CCTV in Git). Git holds manifests, protocol, record and summary results.

**The links that make the record auditable.** Every hash below is taken over **LF-normalised bytes**: SHA-256 of the UTF-8 file after replacing each CRLF with LF, with no other transformation. A byte-order mark, a lone CR or trailing-whitespace changes all change the hash. A Windows checkout that converts line endings therefore does not produce a false mismatch.
1. The record cites its protocol by SHA-256.
2. A `CLOSED` event's record SHA-256 is written in the index (§13) and in the addenda header, whatever the outcome, so `INCUMBENT_RETAINED` and `NO_QUALIFIABLE_CANDIDATE` events are covered too.
3. When a pack results, its qualification record cites the closed record as `{kind: "model-selection-record", reference: "<path>", sha256: "<record sha>"}`. This is evidence for the capability's own selection gate (`<capabilityId>-model-selection`), in the capability gate set, because gate names are unique across all gate sets. The existing evidence shape is used, and the qualification-record schema does not change.
4. `verify_repo` re-derives all three kinds of hash: record, index and protocol. A closed record or frozen protocol edited later therefore fails verification.

## 11. Immutability, errata and addenda

A closed record and a frozen protocol are never edited. Later information goes to `<event-id>-addenda.md`. The file opens with the closed record's SHA-256, followed by dated, numbered entries of one of four kinds:
- **Erratum:** a factual correction to the closed record, stating what was wrong, the corrected fact, whether the decision would change, and who recorded it. If the decision would change, a new event is opened.
- **Licence/deployment determination:** a later human determination for a named profile (for example a Production deployment's end-use determination for an L-B pack), with its decision-maker, date and primary source. It does not re-rank anything.
- **Qualification outcome:** the resulting pack's qualification record id and hash, and per-profile results.
- **Supersession:** the later event id that replaced the selection.

Records written before this methodology existed (for example the Phase-1 detector) have no MSR. The first event for such a capability names the incumbent and states **"selection history unrecorded (pre-methodology)"**. A retrospective record may be written only if it is marked as retrospective and cites only evidence that still exists; nothing is reconstructed from memory.

## 12. Upgrade procedure: what a future model must beat

A new model is never adopted because it is newer.

**Triggers for opening an event:**
- a claimed stronger model;
- an incumbent's licence, maintenance or runtime becoming untenable;
- a requalification trigger that invalidates the incumbent's evidence (qualification plan §16), for example a domain expansion;
- a capability change.

A replacement follows these steps:
1. **Open a new event** (`…-<year>-<nn+1>`). Never overwrite or extend a closed one.
2. **Name the incumbent** by Model Pack id and its qualification record, and add a pointer from the incumbent's addenda.
3. **Re-run discovery**, and carry every historical candidate forward with its last disposition. A previously `DEFERRED`, `REFERENCE_ONLY` or `CONSTRAINED` candidate is re-examined against its stated revisit trigger.
4. **Freeze the protocol** under the then-current qualification plan, including the replacement bar:
   - the challenger beats the **incumbent re-measured in the same harness, on the same partitions** (never its historical numbers) by at least the MPID on the primary metric, with the interval's lower bound above zero;
   - it fails no mandatory gate;
   - it regresses no protocol-declared stratum beyond its declared tolerance.
5. **Evaluate the incumbent, the baseline and the challengers under identical conditions.**
6. **Record the deltas:**
   - what improved and what regressed, per metric and stratum;
   - resource delta (latency, memory, pack size) and system-scale projection delta (§7.1);
   - dependency and Runtime Pack delta;
   - qualification delta (which gates must be re-run);
   - migration impact (new pipeline identity, Stale analyses, re-analysis cost).
7. **Run the licence/deployment qualification separately** for the challenger and each target profile.
8. **Justify the replacement** against the bar, or close the event as `INCUMBENT_RETAINED`. A retained incumbent is a preserved result, not a failed event.
9. **Create the new identities and requalify** where the replacement proceeds: a new Model Pack means a new capability qualification identity (ADR-014 §7), a new pipeline identity, and the re-analysis the lifecycle implies.
10. **Close the event**, record its hash in the new qualification record, and append supersession addenda to the replaced event.

**Frozen-test reuse.** Every event records how many times, and for which identities, the current frozen qualification test has been scored. Whether it must be refreshed is decided by the qualification plan, not by the MSR. The frozen test is never used to choose between candidates.

## 13. Event index

| Event | Capability | Originating stage | State | Outcome | Protocol SHA-256 | Closed record SHA-256 |
|---|---|---|---|---|---|---|
| [`msr-person-attributes-2026-01`](person-attributes/msr-person-attributes-2026-01.md) | `person-attributes` | S2c | `PLANNED` | — | — | — |
| [`msr-vehicle-attributes-2026-01`](vehicle-attributes/msr-vehicle-attributes-2026-01.md) | `vehicle-attributes` | S2c | `PLANNED` | — | — | — |

## 14. Method revisions

Revisions are additive and numbered, and never silently rewrite an earlier rule. Each becomes governing when its change merges after independent review and exact-head CI.

| Revision | Slice | Content | Status |
|---|---|---|---|
| **M1** Candidate credibility and admissibility | S2c.2a | `candidate-credibility.md`. It adds: credibility classes computed from an External Evidence Ledger; laundering-resistant tracing of reported figures to their origin; a shortlist rule requiring pinned, original-source provenance; an implementation rule requiring `established` with a recorded promotion; and a checked decision summary (`<event-id>-decision.json`) that derives the §9 outputs. Validator: `tools/qualification/model_selection_check.py` | **governing — PR #118 merged** |

*M1 trade-off:*
- **Cost:** every serious candidate needs a ledger entry and a reviewer check of its independent evidence. A genuinely strong but newly published model cannot be implemented until independent evidence exists.
- **Gain:** no model reaches a Model Pack on self-reported or copied numbers, and every inclusion and exclusion can be reconstructed.
- **What changes:** M1 adds a precondition to the owner's implementation choice (§4): an implementation candidate must now also be `established`. It also adds a shortlist precondition and three event files: the ledger, its frozen copy and the decision summary. The technical ranking, the licence axis, the outcomes and the qualification-record link are unchanged.
- **What does not change:** no ADR, contract, schema of any existing record, or gate set. ADR-014's Model Selection Records note governs the method, including its revisions. The note's decision list (three separate assessments, exact bytes, reported versus measured evidence) is what M1 strengthens.
