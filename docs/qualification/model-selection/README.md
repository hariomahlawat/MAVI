# Model Selection Records — Methodology (MSR method v1)

**Status:** Proposed with the S2c planning change (`docs/superpowers/plans/2026-09-28-stage2-s2c-learned-attribute-model-packs.md` §9); takes effect when that change is accepted, under the proposed ADR-014 note "Model Selection Records".
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
3. **Licence / deployment qualification.** Under what terms the exact code, weights, training provenance and dependencies may be used, for which deployment profile.
   - It is recorded from primary sources only: the licence text with its retrieved-bytes hash, and the model card.
   - Legal readings and end-use applicability are **human qualification decisions**, recorded with the decision-maker and date.
   - The MSR never reinterprets a licence and never infers an application domain. MAVI is domain-neutral unless a deployment's own qualification record states its use.

Assessments 1 and 2 together form the **technical ranking**. Licence terms never enter it: no weight, no tie-break, no pre-filter.

**The one carve-out: evaluation permission.** Whether MAVI may lawfully *run* a candidate on its data is a human legal precondition to measurement, not a ranking input. It is recorded with decision-maker, date and primary source. A candidate that may not be evaluated becomes `REFERENCE_ONLY`: its reported evidence stays in the record at full strength and is marked "not reproduced by MAVI". It is never `NOT_SHORTLISTED`. Where the method is usable but the released checkpoint is not, the method trained on MAVI-permitted data represents it.

Assessment 3 is applied afterwards to decide which ranked candidates are deployable for a profile. A technically superior candidate stays in the record at its rank, marked with its constraint, even when it cannot be deployed.

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
| `TECHNICAL_DECISION_RECORDED` | gates evaluated, measurements tabulated, technical ranking computed by the frozen rule; strongest technical candidate named |
| `QUALIFICATION_PENDING` | licence/deployment qualification per target profile recorded or awaited; strongest deployable candidate named; implementation candidate chosen by the owner |
| `CLOSED` | one of the outcomes below is recorded; record hashed |

A `CLOSED` event has exactly one **outcome**:
- `SELECTED_FOR_PACKAGING`: an implementation candidate goes on to become a Model Pack.
- `INCUMBENT_RETAINED`: no challenger justified replacement.
- `BASELINE_SELECTED`: no learned candidate beat the deterministic baseline, and the baseline is packaged.
- `NO_QUALIFIABLE_CANDIDATE`: the capability or attribute stays disabled.

`CLOSED` does not mean qualified. Qualification of the resulting pack is decided by its qualification record and reported back through an addendum.

## 4. Candidate lifecycle

Each candidate carries **two independent status axes** and a **role**. They are never collapsed into one field.

**Role:** `baseline` (deterministic/simple floor), `incumbent` (the currently bound pack, if any), `challenger`, or `reference` (reported only, never evaluated).

**Technical disposition:**

```
DISCOVERED ─→ SHORTLISTED ─→ EVALUATED ─→ TECHNICALLY_SELECTED
    │              │             ├──────→ TECHNICAL_ALTERNATIVE   (passed the technical gates; ranked below)
    │              │             └──────→ REJECTED_TECHNICAL      (failed a technical gate, or dominated; gate/measurement cited)
    │              ├──────────────────→ DEFERRED                  (evidence or resources insufficient; revisit trigger stated)
    │              └──────────────────→ REFERENCE_ONLY            (could not be evaluated: permission, availability; reported evidence kept, marked not reproduced)
    └──────────────────────────────────→ NOT_SHORTLISTED          (technical reason recorded; never a licence reason)
```

**Licence / deployment qualification status** (per target deployment profile; independent of technical disposition):

| Status | Meaning |
|---|---|
| `NOT_ASSESSED` | no review yet |
| `REVIEW_PENDING` | primary sources captured, human determination awaited |
| `CLEARED` | human reviewer recorded that the exact code, weights, training provenance and dependencies may be used for the named profile(s); decision-maker and date recorded |
| `CONSTRAINED` | use is restricted for the named profile(s) by recorded terms: non-commercial, research-only, end-use clause needing a per-deployment determination, redistribution limits, or unstated terms. The candidate stays at its technical rank |
| `NOT_CLEARED` | reviewer recorded that it may not be used for the named profile(s) |

**Lifecycle after the event** (recorded in later addenda or later events, never by rewriting a closed record):
- `QUALIFIED_INCUMBENT`: the implementation candidate's Model Pack passed its qualification record for a profile and is bound. The qualification record is the authority; the addendum cites it by id and hash.
- `SUPERSEDED`: a later event replaced it; the addendum names that event.

Required combinations:
- A candidate can be `TECHNICALLY_SELECTED` and `CONSTRAINED` at once. That is the case this methodology exists to preserve.
- The **implementation candidate** is the owner's choice among candidates that are at least `TECHNICAL_ALTERNATIVE`, past every technical gate, and `CLEARED` for **each named target profile** of the event (the licence gate is per profile). An event may not close as `SELECTED_FOR_PACKAGING` for a profile whose determination is still pending. Profiles determined later (for example a Production deployment) are recorded as licence/deployment-determination addenda (§11) and in the qualification record's `licence` gate evidence. It may differ from the strongest technical candidate. The measured gap between them is always recorded.

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

Every serious candidate records, where available, the fields below. Unknown means `UNKNOWN`, and `UNVERIFIED` marks an unconfirmed claim. Nothing is left blank or guessed.

| Group | Fields |
|---|---|
| Identity | candidate id; canonical model/family name; exact checkpoint (above); upstream repository; release/tag/commit; weight SHA-256; publication or model-card date; retrieval date |
| Architecture | architecture; parameter count (the part executed at inference); input resolution; preprocessing (as data: resize, normalisation, colour order, crop policy), with its hash |
| Data | pretraining datasets; training datasets; fine-tuning datasets (MAVI's by manifest hash); known overlap with MAVI data |
| Reported evidence | each reported figure with its source, table or section, dataset and split, and date, marked **reported** (§6) |
| Licence (primary sources) | code licence; weights licence; dataset terms; derivative/fine-tune terms; stated use restrictions (commercial, redistribution, surveillance/security/law-enforcement, military/defence, other); what each term applies to (code, weights, derived models, data); SHA-256 of each retrieved licence and card text; licence class per the capability's analysis; review status per profile (§4) |
| Runtime | framework/runtime requirements; export route; CPU/CUDA requirements; offline viability (loads from pack artefacts alone?); Runtime Pack impact (existing family or extension) |
| Judgement | reason for inclusion; known uncertainties; disposition with reason and evidence reference |

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
   - Differences within the protocol's statistical interval score as ties.
   - Scores are reported at the precision the data supports, never more.
   - The record reports a **sensitivity check**: does the top-ranked candidate change when any one weight group moves by the protocol's declared perturbation, or when any group is removed? An unstable ranking is recorded as unstable, and the choice between the tied candidates becomes an explicit owner decision.
4. **Owner decisions.** For example the MPID, target precisions, whether to seek a licence for a stronger constrained candidate, and the implementation candidate. Each has a rationale, decision-maker and date.
5. **Qualification decisions.**
   - Licence/deployment determinations per profile (human, §2).
   - Then the Model Pack qualification record (authoritative, §1).

**Statistical rule.** "Better" means the paired interval of the difference excludes zero. The resampling unit and interval are fixed in the protocol; for S2c this is a paired bootstrap over Tracks resampled by camera, 95 %.

A candidate needing an architectural extension (for example a new Runtime Pack family) must clear the protocol's MPID over the best candidate that needs none, and must pass the ADR route. It is **never rejected merely for needing a reasonable extension** once it clears that bar.

## 9. Required selection output

A record at `TECHNICAL_DECISION_RECORDED` or later states explicitly:
- baseline and incumbent;
- **strongest technical candidate**;
- **strongest deployable candidate** per target profile: the highest-ranked candidate whose status is `CLEARED` for that profile;
- **implementation candidate**;
- alternatives in rank order;
- rejected, deferred and reference-only candidates, each with its reason;
- the measured gap between the strongest technical and the implementation candidate;
- the evidence supporting the decision, by hash;
- unresolved risks and assumptions;
- qualification status.

Once they exist, the identities follow, recorded when created and by reference:
- Model Pack id;
- Runtime Pack id per variant;
- capability binding and pipeline profile/identity;
- qualification record id.

These roles may name different models. The methodology never forces them to coincide.

The standard wording for the implementation candidate is: *"selected as the strongest qualified candidate for MAVI's defined \<capability\> operating envelope based on retained bake-off evidence"*. It is never called "best". "Qualified" in that sentence means it passed the event's mandatory gates (§8), including the licence gate for its named target profiles. It does not mean that the Model Pack qualification record has passed, and it says nothing about Production.

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

**The links that make the record auditable.** Every hash below is taken over **LF-normalised bytes**, so a Windows checkout that converts line endings does not produce a false mismatch.
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
   - resource delta (latency, memory, pack size);
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
