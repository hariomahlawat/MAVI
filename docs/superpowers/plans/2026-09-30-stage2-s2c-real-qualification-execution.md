# First Real S2c Qualification Execution Plan

> **For agentic workers:** Use `superpowers:executing-plans` to implement this plan task-by-task after review. Steps use checkbox syntax. This document authorizes no implementation, acquisition, candidate evaluation, frozen-test access or deployment by itself.

**Status:** Draft for owner and Claude review; no real experiment is frozen or executed by this document.  
**Goal:** Execute the first evidence-backed person/vehicle selection event, stage the selected Development Model Packs, validate the integrated engineering projection, and close the paired MSRs without changing the accepted selection method.  
**Architecture:** Reuse the merged S2c.2b-1/b-2 contracts, decision functions, S2b lease plane and immutable retention. Implement the missing S2c.3 evaluation/measurement adapters and the already-approved learned-contract prerequisites; do not create another selection system.  
**Tech stack:** Existing Python qualification tools and .NET platform; isolated, offline-capable evaluation dependencies pinned only after candidate preparation.  
**Spec:** `docs/superpowers/plans/2026-09-28-stage2-s2c-learned-attribute-model-packs.md`, interpreted through the governing b-1/b-2 protocols below.  
**Baseline:** PR #122 merge `7b8913982dc6796a1676de075cf1dc22a7676891`. GitHub comparison confirms no file differences from reviewed head `d45a17dd6b36e2ddb529ddaf8c8d40d52b1b782e`; source inspection used that identical tree.  
**Events:** `msr-person-attributes-2026-01`, `msr-vehicle-attributes-2026-01`; joint `eventPairId = msr-attributes-2026-01`.

## 1. Global constraints and authority reconciliation

Read these baseline authorities before implementation:

- `AGENTS.md`; ADR-013 and ADR-014 under `docs/decisions/`.
- ADR-015, `docs/decisions/ADR-015-public-first-protected-qualification.md`, and owner-decision record §8: C+ is adopted policy, not implemented acquisition/partition enforcement or an independent review.
- `docs/qualification/2026-09-23-visual-attributes-qualification-plan.md`, including R1, R2, R3 and R4.
- `docs/qualification/model-selection/README.md`, `candidate-credibility.md`, both selection templates and both event MSRs.
- `docs/qualification/model-selection/s2c-quality-statistics.md` and `s2c-quality-statistics-contract.json`.
- `docs/qualification/model-selection/s2c-operational-selection.md` and `s2c-operational-selection-contract.json`.
- `docs/qualification/stage2-s2c/s2c-2b2-implementation-record.md`.
- The Visual Attributes plan dated 2026-09-23, S2c parent plan dated 2026-09-28, b-2 plan dated 2026-09-29, and `capability-implementation-roadmap.md`.

The machine contracts govern their owned semantics. M2 and the merged b-2 protocol supersede historical weighted scoring, Pareto ordering, standalone top-K/rank-sum composition pruning and provisional fleet formulas. The parent plan's S2c.9 historical “next candidate” language does not authorize rescue after E3 or frozen-test failure. Record these precedence rules in the event protocols; do not rewrite the architecture documents as part of execution.

Some status paragraphs still say PR #122 implementation is pending. Reconcile those status statements to the supplied merge in Slice A; do not promote F/G acceptance rows. Both MSRs are PLANNED and the committed corpus F1 record is OPEN. S1.4 B1–B6 evidence remains separately governed: corpus preparation must pin the current raw-evidence path and re-derive affected imagery/labels if it changes, not silently claim S1.4 closure.

Required invariants:

- Classification uses S; unsupported assertions on U and I remain separate; failures stay in A. Unknown is not Unavailable, and presence is present/Unknown unless Absent is explicitly qualified.
- Training fits weights, heads and calibration. Tuning selects only permitted operating parameters. Selection only compares frozen executables. S5 alone scores frozen-test labels.
- All ordered manifest-pair × Q claims remain in the frozen simultaneous family. No comparator peeling, result-time scope reduction, scalar winner or licence influence on E/F/J/T.
- Person units are exact executable compositions. One capability binds one Model Pack; shared work is measured, never inferred.
- Real E2 traverses the actual runner/client/platform path. Python never mounts accepted platform evidence storage or accesses its database.
- A real run remains offline-capable, Development/unverified and separate from detector/tracker failure and dependency domains.
- Canonical JSON excludes floats, duplicate keys and bool/int ambiguity. Use the existing canonical writer and explicit UTF-8/LF protocol bytes on Windows and Linux.
- No new state machine, ranking method, registry, generic simulator or provenance framework. Changes to frozen inputs use the existing revision/retention rules.

## 2. Completion milestones and scope of “qualification”

| Milestone | Evidence required | What it does not establish |
|---|---|---|
| Architecture complete | PR #122 merged; b-1/b-2 validators available | Any candidate, corpus or operational result |
| Experiment frozen | Operational F1/seal, pinned executable manifest, owner inputs, frozen M2 ledgers, canonical experiment, retained protocols; first selection read still absent | Quality or engineering pass |
| Technical decision recorded | Per-capability quality results and retained joint technical version; paired decision-v2 records | Licence clearance, implementation choice or pack qualification |
| Technical evaluation complete | Relevant operational population has no unresolved evidence; outcome is complete feasibility/tie/unique/no-identity result | A forced unique winner |
| Implementation admissibility resolved | Decision snapshots and final required profile determinations for every frozen manifest unit, including fallbacks, across every required profile; K and C_impl derived independently of T | Packaging or E3 |
| Owner choice recorded | Exact T_impl pair, rationale and decision-maker in QUALIFICATION_PENDING, only after `pending == false` and `unresolvedOperationalPairs == []` | CLOSED or Production permission |
| Model Pack integration/handoff | Exact staged pack/runtime/profile identities, offline build/install and harness-to-adapter parity | Frozen-test model quality or blanket fleet qualification |
| E3 validated | Held-out engineering execution of staged identity passes frozen projection tolerances | S5 final-test or Production qualification |
| MSRs CLOSED | Final paired decisions, no unresolved relevant engineering/licence inputs, evidence/index/record hashes retained | Stage-2 acceptance or Production rollout |

Successful completion of this execution plan means the paired MSRs are CLOSED and, when a packageable implementation exists, the exact selected Development packs have a verified handoff and E3 evidence. A legitimate final no-qualifiable outcome also completes the decision event; it creates no learned pack and explicitly marks pack/E3 work inapplicable. An incomplete event is a recorded stop, not successful completion.

**Ordering:** record the owner choice while QUALIFICATION_PENDING, stage/integrate that pair, run E3, then CLOSED. This follows parent S2c.6–S2c.10 sequencing. `_event_predecessor()` refuses successors to CLOSED, so closing before E3 would prevent the intended in-event reopening path. After CLOSED, later contradictory evidence uses retained addenda and a subsequent event as required; never edit the closed decision.

S5 / Model Pack frozen-test qualification remains after CLOSED and is not an S2c closure gate. Frozen-test scoring is out of this plan. M-D and M-E evidence must never be labelled M-Q.

## 3. What exists and what must be implemented

| Surface at the baseline | Actual capability | Execution work still needed |
|---|---|---|
| `attribute_corpus.py`, `attributes/corpus/` | Operational manifest/partition/audit/annotation/seal/F1 tooling | Real footage, custody, annotation, pilot, seal and F1 evidence |
| `quality_statistics.py`, `quality_statistics_check.py` | Validate method contract and protected prose projection | Numerical metrics, calibration checks, support simulation and paired inference; these are not implemented by the checker |
| `credibility.py`, `model_selection_check.py` | Validate ledgers, evolution, classification and decision bindings | Actual source review, pinned candidate ledgers and profile determinations |
| `operational.py` | Derive MPID/E/F/J, host-bound T, K/C_impl/T_impl | Valid measured inputs; do not duplicate these algorithms |
| `operational_inputs.py`, `job_replay.py` | Validate concrete host/workload/coverage and replay bounded S2b lifecycle | Representative finite traces and measured service/resource envelopes |
| `operational_measurement.measure_attempts()` | Calls actual AttributeRunner with injected inferencer and actual AttributeApiClient for real-platform mode | Candidate inferencer, authorized job seeding, server timing and host/resource collection |
| `s2c_artifacts.py` and schemas | Build/recompute/retain experiment, quality, joint and paired event artefacts | Thin invocation CLI and real leaf evidence; schema success does not authenticate measurements |
| `s2c_operational_check.py` | `repository`, `contract`, `projection` validation commands | No existing “run experiment” or candidate-training CLI |
| S2b runner/API | Real lease/evidence/hash/upload/completion lifecycle | Learned v2 profile/predictions/aggregation and adapter prerequisites from accepted S2c.5–7 |
| Pack/runtime builders and component sync | Existing generic pack mechanisms | Selected attribute source manifests, approved contract registration, Development overlay, notices and exact bindings |

Do not copy synthetic test fixtures into the real evidence tree. In particular, `apiMode: real-platform` and a hand-written timing table are not proof that an API run occurred.

## 4. Candidate preparation and artefact identity

Start with the committed candidate tables and survey; their entries are discovery proposals, not selected models. Re-check primary sources and actual evaluation permission before acquiring or running bytes. Preserve references and exclusions, with reasons. Do not introduce a new model family through this plan.

1. Split multi-family/multi-checkpoint proposals into individually pinned candidates before freeze. Each executable variant has one unambiguous identity; the plan's combined DINOv3/DINOv2 or multi-tower rows cannot remain one executable.
2. Implement and pin the committed packageable baselines PC-B0 and VC-B0. PO-B0 is the training-derived no-image prevalence reference only, never a component of a selectable person unit or fallback. The S2b fixture is neither a model nor an incumbent.
3. Apply M1 shortlist rules, including reviewed emerging exceptions where allowed. Evaluation permission precedes execution. Final operational-use/redistribution clearance belongs to the later implementation stage and never scores technical quality.
4. Enumerate a finite compatible person-composition manifest before selection, including explicit shared-tower variants. K=3 may constrain preparation budget but is not a result-time pruning rule. Region/mask alternatives require pre-selection inclusion; do not add C-SEG because selection results disappoint.
5. Each unit records exactly `unitId`, `kind`, sorted `components`, `configurationSha256`, sorted `enabledAttributes`, `extension`, `existingGraph`. Vehicle units are normally single-component. Shared-backbone heads, preprocessing and aggregation are part of the composed executable's configuration.
6. Freeze required scope per capability. A colour-only baseline cannot pass a person scope requiring presence. Use PC-B0 as a fallback only where it really covers the frozen required scope. A disabled fallback is permitted only as the explicit `kind: disabled` fallback with no components/attributes and an owner-frozen admissibility rule for every required gate. The corresponding evidence and rule must support each gate verdict; never fabricate conventional model-quality evidence for a disabled identity. If no valid disabled-fallback rule is frozen, use `fallback: null`. A disabled fallback also requires the full required licence rows. Record disable-policy applicability separately from statistical claims.
7. Mark extension/existing-graph status from actual dependency/runtime requirements. Pin the existing Runtime Pack manifest/family and evaluation environment; build any permitted experimental extension in a separate evaluation environment. Do not widen the detector lock.

For every component, retain upstream immutable code/checkpoint revision, exact filenames and SHA-256 of all bytes; MAVI source revision; input/preprocessing configuration; output mapping and discarded outputs; frozen vocabulary/scope; calibration artefacts; Runtime Pack dependency; environment lock and notices. Method candidates additionally retain training data-manifest hash, training recipe/seed/code/environment hash and produced heads/calibration hashes. `componentArtefacts[c][id]` must use the existing `candidateId`, `artefactSha256s`, `maviTrainedArtefacts`, `maviRevision` fields. Every selectable frozen shortlist component must occur in a unit or fallback, and every such component must be in that shortlist.

Store weights, images and large prediction data outside Git in the controlled evidence/component stores. Retain hash manifests and reviewable results in the existing evidence areas. Paths/locators must not leak into corpus records.

## 5. Corpus, label access and the two preparation boundaries

There is one final machine experiment freeze, preceded by preparation under an approved recipe; these are not additional event states.

**C+ source policy (2026-10-02).** Public material is actively used for cleared non-frozen purposes under ADR-015; public selection carries explicit contamination/domain caveats, and private selection is added only for a demonstrated preparation gap. Public footage cannot enter the frozen qualification test. Preserve the B0 S1 closure and all 63 human decisions; any separate engineering purpose is recorded without changing its original B0 decision. Future public discovery requires a new purpose-specific declaration. Training, Development/Tuning, Public Benchmark/Reference, Selection, Qualification Candidate, Frozen Qualification and Regression/Challenge are separate pools; engineering calibration/E3 separation below remains unchanged.

Protected commissioned/owner footage may be **physically captured before final executable freeze**, after applicable checkpoint pinning/chronology requirements, only while sealed in controlled custody and inaccessible to development/selection. Raw capture custody is not the annotated corpus seal. The latter still follows R1 before candidate execution on corpus data. Final sequence: public/private development → training/tuning → selection protocol fixed → candidate executable(s) frozen → selection on separate data and implementation choice → authorized protected final-holdout access → final qualification. Preparation methods are fixed before training; the final selection protocol binds actual trained artefact hashes before selection access. Existing integration/E3/CLOSED prerequisites and S5-only final-test scoring are unchanged.

If developers use final-test imagery, labels or results to change the system, that test becomes exposed regression/challenge evidence, subject to permissions; a new independent holdout is required for a new final qualification claim. No poor-result corpus expansion or same-test rescue is allowed. Duration, clusters, attributes and conditions are assessed through the predeclared support recipe, not a universal raw-hour minimum. Current tooling gaps in reference acquisition/mixed-source frozen enforcement are execution prerequisites (ADR-015 §2), not permission to bypass a validator.

**Before candidate corpus execution (R1):** retain a content-addressed preparation recipe before the first training read. It enumerates upstream candidate identities and bytes; metric, aggregation and calibration families; threshold-selection procedure; training/tuning search spaces; equal-budget rules; seeds; and partition allowlists/data-access rules. Freeze annotation guide, partition method, aggregation family and threshold-selection procedure; run the pilot on training; freeze the task; complete annotation/adjudication; seal the frozen qualification test. Keep frozen imagery and ground truth outside candidate environments, not merely hidden labels in an accessible directory.

**Before selection access:** finish training/tuning, support calibration simulation, label-free topology calibration and executable pinning; create the final experiment and protocols with actual artefact hashes. The existing machine contract cannot freeze unresolved future training outputs. Maintain a reviewed preparation recipe/commit before training, then bind its hash and all resulting configuration hashes into the final protocol.

| Data | Permitted readers/actions | Forbidden actions |
|---|---|---|
| Training | Candidate head/weight fitting; group-disjoint calibration fitting; training-only calibration-method choice; pilot/support simulation; PO-B0 prior fitting | Learning from selection or final-test outcomes |
| Tuning | Thresholds, colour margins, admissibility, floors, pooling/aggregation parameters within the approved family and equal bounded budgets | Fitting calibration coefficients; candidate selection using selection labels |
| Selection | Frozen executable inference, support/gates and paired comparisons after freeze | Fit/tune, change candidates/scope/margins/family, adapt search budgets |
| Frozen test | Custodian annotation/seal workflows; later S5 authorized scoring | Any candidate, operational tuning or rescue access during this plan |
| Engineering | Owner-declared label-free traces; service/resource/topology calibration; separately held-out E3 traces | Quality labels influencing engineering exclusion; any use of the sealed test |

Reuse corpus commands for manifest validation, recurrence/duplicate audits, partitioning, annotator registration, pilot assignments/submission, task freeze, main annotation, adjudication, ground truth and seal. Run `check-f1 --record ... --store ...`; require a real operational corpus, reconstructed custody records and PASS before selection. Camera-count floors do not establish statistical adequacy. Preserve site/date grouping, duplicate/recurrence moves and all Track crops together.

The thin executor must accept explicit partition manifests/allowlists, reject a frozen member before loading its bytes, and retain a first-selection-read receipt at `docs/qualification/stage2-s2c/first-selection-read-receipt.json` (or its content-addressed evidence location). The receipt records `eventPairId`, experiment/protocol/recipe/partition/seal hashes, harness revision, actor, freeze-accepted UTC and first-selection-read UTC. A wrapper writes and verifies it immediately before the first selection read and refuses progression if the receipt is absent, hashes disagree, or the read precedes freeze. Use the existing seal/access-log machinery and this small run-specific receipt, not a new provenance service. The recipe hash is cited by both MSRs while PLANNED and bound by the final protocols. Human reviewed `freezeAttestation` remains mandatory. Improper frozen access invalidates the seal; use the existing fresh-footage/reseal procedure, not a renamed old test set.

## 6. Final freeze artefacts and owner policy

Use `canonical.canonical`, `sha256` and `s2c_artifacts.retain_evidence`; retain concrete leaf configuration documents before referring to their hashes. The machine validator checks many hashes syntactically rather than resolving their scientific content: the thin executor must resolve the referenced configuration/margins and reject a missing input.

The `mavi-s2c-experiment-v1` document contains precisely `EXPERIMENT_KEYS`; add no ad hoc top-level fields:

| Fields | Freeze content |
|---|---|
| `eventPairId`, `events`, `ledgerHashes` | Joint id above; person/vehicle event ids and canonical frozen M2 ledger hashes |
| `qualityContractHash`, `operationalContractHash` | Existing canonical b-1 and b-2 contract hashes |
| `frozenOn`, `sealedViewOn`, `freezeAttestation` | Actual dates, seal no later than freeze; named distinct recorder/reviewer; truthful `beforeSelectionRead` |
| `capabilities` | Required scope, complete units/fallback, Q/directions/margins hashes, `mpidClaims`, unavailable-comparator disposition, full ordered family and gate ids |
| `componentArtefacts` | Actual checkpoint/training/source artefacts; no placeholders |
| `profiles` | Named non-commercial Development profiles including use/end-use and delivery route, documented in protocols |
| `hostClassId`, `hostProfileSha256`, `workersPerHost` | One fully described host class and one chosen topology; permitted process counts in host profile do not initiate automatic topology optimization |
| `objective`, `reserveHosts`, `maximumHosts` | Literal `minimum-supported-installed-hosts`, reserve and finite host ceiling |
| `wholeJob` | Existing seven positive-integer microsecond/count policy fields: lease, heartbeat extension/interval, attempts, analysis duration, claim poll and sweep poll |
| `workloads`, `requiredWorkloadIds`, `workloadEnvelope` | All six roles and concrete trace/envelope fields from §10 |
| `uncertainty`, `limits` | Lower/upper error ppm; warm, queue-to-publication, backlog, host RAM/I/O and boot-to-ready limits |

Retain owner numerical policy as a concrete document referenced in both protocols, rather than adding fields to the experiment. It must contain every applicable b-1 gate form, metric denominator, bound direction, target, support threshold, required slice/floor/degradation rule, practical/NI/equivalence/MPID margins, permitted training/tuning budget, bootstrap parameters/multiplicity/undefined-replicate rule, engineering pass criteria, service-envelope estimator and E3 tolerances. Missing values block freeze; this plan supplies no universal quality percentage, host budget or invented measured service value.

The finite Q and complete ordered unit-pair × Q family are materialized exactly as `validate_capability()` requires. Freeze the MPID reference-selection rule, not a guessed best comparator: membership in G is determined later from frozen gates. Use `exclude-pending-ADR` when no comparator exists unless an actual accepted route and `noComparatorAuthoritySha256` are already supplied.

Retain two protocols using `retain_protocol(repo, experiment_hash, capability, blob)` and active `<event>-protocol.md` copies with explicit UTF-8/LF bytes. Each protocol cites experiment hash, frozen ledger hash/date, b-1/b-2 hashes, corpus/seal/task/recipe/policy/host hashes, evidence paths and the final executable identity table. Record protocol hashes in the corresponding MSR. Advance both records to PROTOCOL_FROZEN only after all checks and independent freeze review succeed.

## 7. b-1 numerical execution and evidence production

Implement the accepted S2c.3 numerical harness; do not assume `quality_statistics_check.py` computes statistics. Its event-specific recipe must be supplied and reviewed before execution, with no implementation-selected defaults for statistical policy.

1. On training-pilot structure, execute the accepted support calibration simulation, varying prevalence, imbalance, dependence, abstention and effect size. A cluster-label swap alone is inadequate. Retain simulation recipe, seeds, coverage results and minimum independent-cluster counts overall/per required stratum before selection access.
2. Freeze the inherited hierarchical paired percentile bootstrap implementation: site is the default top-level unit for unseen-site claims; resample paired Tracks within drawn clusters; retain all crops per Track. Use the governing S2c 95% level with the protocol's explicitly approved simultaneous-family correction, replicate count/seed, percentile convention and undefined-denominator rule. These missing numerical choices are freeze inputs, not permission for the implementer to invent a statistical method. No runtime choice between correction methods.
3. Run every frozen configuration on the identical authorized selection units; retain predictions, abstentions, failures and per-Track post-aggregation output. Use real subject-validity/scorability labels to derive candidate-independent S/U/I/A. Never remove a failed candidate's assigned Tracks from A.
4. Compute per-value precision/recall, required categorical/presence metrics, useful S coverage, separate U/I unsupported assertions, A delivery, post-aggregation calibration and required slice results. Retain diagnostics without promoting them to sole gates.
5. Check attribute/value and independent-cluster support first. Precision uses predicted positives; unconditional recall uses true positives with abstention already included. Use the approved DEFF/support arithmetic; do not multiply recall coverage twice.
6. Compute paired differences with the same replicate draws for all candidates in each family. Apply the frozen family correction over the full ordered manifest-pair × Q set, including claims involving candidates subsequently excluded from E. Preserve undefined/unsupported cases explicitly.
7. Emit exactly the five b-1 outcomes. Use the approved practical-importance and interval rules, direction reversal for lower-is-better claims, and a frozen precedence rule for overlapping valid predicates. Inconclusive and insufficient-evidence never become equivalent or pass. A declared MPID claim's `superior` outcome is the decision-relevant MPID outcome and must establish the frozen MPID, not merely a smaller generic practical difference; `equivalent` and `non-inferior` remain protected outcomes but do not satisfy the MPID superiority requirement and are not owner-selectable precedence choices.
8. Evaluate component and absolute gates from confidence bounds. Preserve all raw gate rows in the detailed report. Project them into existing `gateIds` (at least `absolute-quality`, `engineering`, `support`); a grouped pass requires every applicable constituent to pass. Label-free exclusion is recorded under `preScreen`, never disguised as a statistical result. For genuinely unevaluated comparisons retain the complete family with explicit insufficient-evidence outcomes and detailed execution disposition.
9. Emit `mavi-s2c-quality-evidence-v1` with exactly `schema`, `experimentSha256`, `capability`, `gateResults`, `pairwise`, `partition: selection`. No extra report fields belong here. Retain detailed reports/predictions by hash and cite them in the MSR alongside this projection; the execution harness must reproduce the projection from those reports.

Numeric leaf results can use documented decimal strings or external numeric tables bound by SHA-256; no binary float may enter canonical b-2 JSON. Freeze numeric precision and comparison behavior so display rounding cannot change a gate.

## 8. MPID, E, F and J: invoke, do not reimplement

Call `build_quality(repo, experiment_hash, capability, evidence_hash)`, then `retain_evidence(repo, quality_result)` for person and vehicle. `validate_quality()` recomputes the result; `operational.quality_sets()` owns derivation.

- Apply label-free pre-screen and absolute/component/support/engineering gates first. Scope must be covered. Missing or insufficient mandatory evidence does not pass.
- For each eligible extension, form G from existing-graph units passing the same required absolute quality/support gates. Prefer `G ∩ eligible`; if empty, use quality-passing G. Require `superior` for every MPID claim against every required comparator and protected outcomes on all other Q. Preserve `NOT_EXTENSION`, `PASS`, `FAIL` or `MPID_COMPARATOR_UNAVAILABLE` as actually emitted; a unit excluded before MPID need not have a fabricated MPID result.
- E is the post-MPID eligible set. F checks each candidate directly against every other member of that original complete E. No deletion/peeling of weak comparators and no inference through a third candidate.
- J is F if nonempty, otherwise the valid frozen fallback, otherwise empty. Preserve the original F/outcome. A fallback must pass its own applicable scope/engineering/support policy; PO-B0 remains prohibited.

Refuse wrong experiment/partition/hash, non-M2 ledger, omitted shortlist component, incomplete/unsorted family, unknown outcomes, missing gate rows or invented fallback. E/F may legitimately be empty; that is an outcome, not a validator bypass opportunity.

## 9. E1/E2 measurement execution

E1 isolates decode/preprocessing/inference/aggregation and startup on the pinned host. Use label-free training-derived or dedicated engineering material, never selection labels. Before final freeze, use designated calibration traces to choose the permitted topology and uncertainty estimator. After freeze, pre-screen the final manifest with the frozen engineering rule. No result-dependent adjustment to worker count, deadlines, threading or reserves.

E2 runs every pair in `J_person × J_vehicle` that remains relevant. Additional frozen fallback combinations may be measured now without using credibility to select the technical population, or later when K makes them necessary. An incomplete pair is retained explicitly and blocks a conclusive decision in its relevant population. A genuinely unevaluated comparison is reported as `insufficient-evidence`, with an empty `highestTaskQualityEvaluatedSet`; the executor must not manufacture a highest set from a vacuous/singleton helper result.

**Actual path:** qualification job driver → real local/qualification platform API → `AttributeApiClient` → `operational_measurement.measure_attempts(..., api_mode="real-platform")` → existing `AttributeRunner` with the pair's candidate `AttributeInferencer` → authorized evidence reads/hash checks → inference/aggregation → bounded upload → real Phase A/B/C publication. Launch one serial inference lane per worker process. No Python database writes and no alternative claim/completion implementation.

The qualification driver must produce actual accepted Track Evidence Sets and actual analysis identities through the existing platform/test-host facilities. E2 runs on a Development platform host with the real API/runner path; the host is explicitly identified in the host profile. The seed helper creates accepted Evidence Sets for each frozen job/crop/byte shape, including the 10,000-Track shape where applicable, through the intended Development/test-host storage seam. Retain the mapping between the experiment's `runtime_identity(experiment, pair)` and the platform identity fingerprint, Model Pack/configuration, Runtime Pack/variant, code revision and host profile. The experiment hash is not a replacement for the platform identity. Do not execute learned bytes while claiming the fixture model's identity. Prepare isolated, locally held qualification bindings for each evaluated pair; where loaders require a built pack, assemble an evaluation-only pack from the pinned candidate bytes under their evaluation permissions. These experimental identities are not the selected-product handoff, do not alter the shipped binding and do not authorize redistribution. Account for any candidate-versus-final-pack packaging difference in parity/E3 evidence.

**Prerequisite:** current `inferencer_for()` only constructs the fixture, and v1 contracts cannot express all approved learned abstention/aggregation semantics. Implement the already-accepted model-neutral S2c.5 contract work before authoritative learned E2; reuse its tested aggregation/admissibility path in the quality harness. E2 uses evaluation inferencers through the existing seam; selected production adapter integration remains later. If a chosen executable cannot be represented faithfully, stop rather than measure a simplified surrogate.

Collect repeated whole-job observations for every service shape/signature and the frozen worker topology, including active detector/platform co-residency and saturation. Pin CPU/cores/SMT, RAM, OS, storage, API placement, power policy, threads, worker range/chosen count and Runtime manifest in `mavi-s2c-host-profile-v1`. Retain exact environment/build/device identity and repeat schedule.

Measurements include boot-to-READY/model load separately; claimed-to-Phase-A warm service; publication and acknowledgement; host peak memory including restart transients; CPU diagnostic utilization; aggregate I/O/API demand; model/runtime/deployment bytes; and explicit failure, restart, lease-reclaim, worker/platform publication loss and host-loss traces. No per-crop-p95 multiplication and no assumed shared-backbone savings.

Retain the actual `mavi-s2c-e2-runner-evidence-v1` output. For each pair, the frozen schedule names one designated `e2TraceSha256` (no result-time choice); every worker/repeat trace, including failures, remains retained as raw evidence. Repeat count and schedule are frozen in advance, every scheduled repeat is retained, and no rerun or cherry-pick is allowed after results are seen. It contains client UTC boundaries and monotonic durations but **does not provide authoritative server transaction instants or host resource measurements**. The Development-only timing export is disabled by default and refused in Production: the .NET platform emits documented JSON-lines to a configured local path, capturing bounded Phase-A validation, Phase-C timestamp sample and successful commit. Correlate by analysis/attempt with the client acknowledgement. Do not substitute CompletedAtUtc or the HTTP response time for commit. Capture no lease secrets or imagery in timing records.

The timing export is a qualification-only Development seam, not generalized telemetry: the Development platform host writes JSON-lines to the configured local path, while Production configuration refuses the option. The likely .NET implementation/test touch points are `src/platform/Mavi.Infrastructure/VisualAttributes/VisualAttributeCompletionService.cs`, `src/platform/Mavi.Api/Endpoints/VisualAttributeCompletionEndpoint.cs`, `src/platform/Mavi.Application/Modules/VisualAttributes/VisualAttributeOptions.cs`, `tests/Mavi.IntegrationTests/VisualAttributeApiHost.cs`, `tests/Mavi.IntegrationTests/VisualAttributeCompletionTimingTests.cs` and a focused seed/helper test alongside the existing `VisualAttributeWorld`/completion builders. The helper must seed accepted Track Evidence Sets through the real Development host seam, preserve job/crop/byte cardinalities and exercise the 10,000-Track case where the frozen workload requires it; it must not add a production database or telemetry framework.

Create five `mavi-s2c-engineering-measurements-v1` source records per pair: `startup`, `services` (including `serviceCoverage`), `resources`, `footprint`, `serverTiming`. Each binds exact pair, runtime identity, host profile, recorder/time and matching measurements. Server timing has ordered claimed/Phase-A/completed/committed/acknowledged instants. Apply the frozen estimator to repeats to obtain lower/upper service/startup inputs; retain raw repeat data. Model uncertainty is calibrated only with calibration traces, not E3 held-out results.

## 10. Concrete workload and 500-camera projection

The owner supplies a finite envelope, not merely “500 cameras”. Populate exactly the current `workloadEnvelope` fields: target 500; camera classes/proportions summing to 1,000,000 ppm; correlated busy windows; release cadence/run duration; aggregate jobs per class/interval; person/vehicle Tracks-per-job histograms; crops-per-Track and Evidence Set byte histograms; initial backlog; burst/failure workload ids; drain/storage/API limits.

- Each job has id, shape, queued UTC instant, identity hash, person/vehicle Track counts, sorted per-capability crop-count arrays of exactly those cardinalities, and total input Evidence Set bytes.
- Histogram `count` refers to each complete 500-camera trace, including pre-start backlog. Tracks are one observation per job/capability; crops one per Track; bytes one total per job. Other stress traces do not inflate those counts.
- Camera classes are the service-shape ids for the 500-camera trace. The current validator requires the declared per-class job count at every release-cadence tick. Use an owner-approved conservative synchronous finite envelope that fits this implemented representation; do not feed an arbitrary variable-arrival trace and claim it conforms. Dedicated burst/recovery traces carry additional stress. Record any limitation honestly.
- Every declared busy window contains an actual simultaneous release of all its named classes; it makes no further intensity claim. Owner review must establish that the concrete trace bounds the intended deployment load.
- `serviceCoverage` lists exactly the distinct person/vehicle/crop/byte payload signatures used by each shape across all traces. One lower/upper service scenario for a shape must cover all its listed signatures; do not average away its costly signatures. Shapes unsupported by measurements are refused.
- Supply the six required roles: typical, small-burst, 10k-boundary, mixed, recovery and 500-camera. The boundary contains a 10,000-Track job; mixed has different job sizes; recovery has explicit losses. Outage worker ids must exist at every evaluated host count; model host loss by enumerating all affected workers. Test the smallest evaluated topology before a long replay.
- Use current search/event limits: at most 1,000 maximum hosts and 1,000 workers/host in experiment validation, at most 10,000 actual replay workers, 100,000 jobs and bounded polling/event counts. Preflight these limits. Do not shorten the required horizon silently to fit the helper.

Call `operational_projection()` through the joint builder. It uses the fluid necessary-capacity screen, then the existing bounded replay for both frozen demand/error cases, over installed hosts up to the cap. Reserve hosts count as installed and are withheld from active capacity; do not claim reserve activation behavior that the helper does not simulate. The helper encloses the two supported counts with min/max because timed loss need not be monotone.

Admission requires finite bounds and all runtime, cold, memory, I/O, API, footprint, warm, queue, recovery and publication constraints. Use measured topology-wide peaks/demand, including platform bottlenecks, not isolated worker RSS mislabeled as host peak. The helper compares supplied resource values to caps; it does not simulate detector/storage saturation or derive those measurements.

Retain lower/upper projection reports: installed/active hosts, workers, cold READY, latency distributions, retries/failures, Phase-A/SLA misses, waiting/unfinished work, oldest queue age, backlog and drain. Publish the result as **M-E projection on declared hardware and finite load**, not physical qualification of 500 cameras or indefinite queue stability.

## 11. Technical joint decision and immutable publication

1. Retain `mavi-s2c-operational-evidence-v1` with experiment hash and sorted pair rows. Complete rows carry all measured fields/references. Incomplete rows set every measurement field to null, `evidenceComplete: false`, and retain exact pair/runtime identity.
2. Invoke `build_technical(repo, experiment_hash, quality_hashes, operational_hash)`. It recomputes quality and projection over J_person × J_vehicle. H* is minimum admitted H_up; T contains admitted pairs with H_lo ≤ H*. Do not change this uncertainty rule.
3. Any unresolved relevant pair gives `TECHNICAL_EVIDENCE_INCOMPLETE`; the admitted subset/T is provisional and not an owner-selectable winner. Complete infeasibility is different. No admitted pair with complete evidence yields the existing no-feasible result; empty J yields no complete identity. Otherwise record unique or tied T. An E3 candidate-specific mismatch is not a technical-successor shortcut: retain the evidence/disposition, leave QUALIFICATION_PENDING and raise the §13 execution blocker until a legitimate frozen-input revision and fresh basis can be attested.
4. Invoke `retain_joint()`; first retained version is technical v1 with no predecessor. Invoke `build_event_decision()` for both capabilities at TECHNICAL_DECISION_RECORDED with null implementation pair/owner choice, then `retain_event_pair()`.
5. Update both MSRs with exact decision/protocol hashes, detailed report hashes, E/F/J, MPID, technical outcomes and limitations. No implementation snapshot/licence/profile selection data enters this stage.

A recorded incomplete technical result is not “technical evaluation complete”. For this first run, retain partial measurement evidence and stop before publishing a technical decision when required measurements are still outstanding; do not use incomplete joint versions merely as progress checkpoints. If an incomplete technical version has deliberately been published, preserve it: a successor technical revision currently requires a different experiment hash, permitted revision reason and fresh evaluation basis. Merely filling a missing row under the same experiment is not an implemented revision path. Stop and review that concrete recovery case if a legitimate re-freeze is unavailable; do not alter dates or frozen inputs solely to evade the guard. Never overwrite an incomplete original raw row within an implementation-only revision: the current validator preserves original technical pair evidence byte-for-byte.

## 12. M1/licence and implementation selection

Only after recording the technical result, create decision-date snapshots of both append-only M2 ledgers. M1 facts may have been gathered earlier for legal evaluation/shortlist entry; their implementation effect starts here.

Record licence status for every frozen manifest unit, including every fallback, across every required profile, covering code, weights, training data, derived weights and delivery route. Resolve rights from retained source clauses and a named review owner; never equate non-commercial/free-of-charge with unrestricted deployment. `NOT_ASSESSED` and `REVIEW_PENDING` cannot remain at CLOSED, and no placeholder `NOT_CLEARED` may be invented merely to complete the matrix; the owner must supply genuine final determinations. Pass the existing nested `licence[capability][unitId][profile]` table, with actual allowed enum values, to the implementation builder. Keep detailed human licence determinations by hash beside the snapshots.

Every learned component must be `established` at the snapshot/decision date, or a legitimate `mavi-owned` component under existing rules. Emerging technical candidates stay visible in T but cannot be chosen for implementation. Do not change the frozen technical population because their licence or credibility is inconvenient.

`implementation_sets()` computes credibility-blind C_r/T_r and C_all from J, then K per capability using M1 plus all-required-profile clearance. If that capability has no qualifying J member, only its valid frozen fallback may enter K. C_impl is K_person × K_vehicle. Measure any newly relevant frozen fallback pairs through E2 under the same protocol. Every operational row introduced by an implementation-stage version is append-only and must remain byte-identical in every later implementation version; new rows may appear only for pairs newly entering C_impl. An incomplete implementation-stage row may not be re-measured or completed as rescue; the thin implementation wrapper must refuse that case and raise an execution blocker, with a regression test. Preserve every original technical pair row exactly; only append permitted additional pair evidence.

Call `build_implementation(repo, predecessor_hash, snapshot_hashes, dates, licence, operational_hash)` and `retain_joint()`. First implementation version extends the immediate technical version; subsequent licence/snapshot-only versions extend the immediate implementation predecessor with unchanged technical/frozen data and append-only, date-consistent snapshots. Recompute T_impl over C_impl; never intersect T with a filter.

Retain paired QUALIFICATION_PENDING decisions. Implementation selection is complete only when `pending == false` and `unresolvedOperationalPairs == []`; either condition blocks owner choice, Model Pack handoff and E3. `unresolvedProfilePairs` preserves profile uncertainty. An unresolved pair outside C_impl need not block implementation, but it cannot disappear from the technical/profile account. The current `pending` flag covers all unit/profile licence rows supplied to the builder; resolve those required rows to final determinations before CLOSED, including explicit rejection where appropriate.

## 13. Owner choice, handoff, E3 and closure

The owner may select only an exact pair in a complete T_impl. Record `ownerChoice = {decidedBy, rationale}` and the same pair/joint identity in both event decisions. Ties are legitimate; the rationale explains the permitted implementation preference without claiming a unique statistical winner. Keep pair/choice null while relevant evidence is unresolved. An empty T_impl may support no-qualifiable only when evidence and determinations are final.

**Development handoff before final closure:** stage the selected components using the accepted S2c.6–8 route. Build source manifests and notices, reproduce Model Pack ids, pin exact Runtime Pack variants, register the already-approved attribute sections/contracts, and create `src/vision/config/components/development-attributes-v2.json` with identity-bearing profiles under `src/vision/config/attributes/`. Keep the shipped phase1 binding unchanged. Stage qualification records with pending gates, `verificationStatus: unverified`, `qualificationId: null` in source packs as governed; do not invent passed gates. Production must refuse the learned Development profile. A component/calibration/mapping change creates a new identity, not a file replacement under the old id.

Implement only the selected approved capability adapters for deployment. Verify same accepted crops produce the harness-equivalent scores/abstentions/Track semantics within frozen tolerances, offline installation, device policy, model-load failures, OOM/timeout/restart and fixture-v1 history coexistence. Existing generic builders/resolvers are reused; qualification metadata later cites CLOSED MSR hashes without changing selected model bytes.

**E3:** run the staged exact identity through integrated multi-worker/platform execution on held-out engineering traces, distinct from calibration traces and from the frozen test. Freeze projection outputs before revealing E3 observations. Validate one-sided dangerous underprediction protection and any declared symmetric tolerance for host support, queue/SLA/drain and resources. Measure observed performance; a successful replay is not E3. Repeat on the CPU variants required by the accepted parent execution plan; only the declared primary host class determines the selection objective. CUDA evidence is conditional on its actual host/variant and never silently substitutes for CPU evidence.

- Candidate-specific mismatch: retain the E3 evidence and `e3_disposition()` result; do not publish a new joint/event successor merely to bypass the failure. Leave the affected event at `QUALIFICATION_PENDING` and raise an explicit EXECUTION BLOCKER identifying the legitimate frozen input that would change, the applicable existing `revision.changes` token, the fresh evaluation basis, and how `beforeSelectionRead` can truthfully be attested. If no legitimate re-freeze exists, the event cannot close under this execution plan. Applicable E3 occurs before immutable CLOSED. Do not inherit the stale parent-plan S2c.9 instruction to proceed to the “next candidate” after a budget miss. A revision changing frozen inputs requires fresh unbiased evidence where prior exposure could affect selection; do not invent a revision mechanism.
- Candidate-independent calibration/model error: use a numbered method/workload revision, re-evaluate all affected pairs consistently from still-valid evidence or new calibration traces, retain predecessors, and validate on fresh held-out engineering evidence. Do not tune the method on E3 and call that same trace validation.
- The existing `e3_disposition()` only returns the allowed disposition label. The execution report, human diagnosis and revision builder must carry the actual evidence; the function is not an E3 validator.

**CLOSED checklist:** final licence statuses for every frozen manifest unit/fallback/profile, with no `NOT_ASSESSED` or `REVIEW_PENDING`; `pending == false`; `unresolvedOperationalPairs == []`; final owner pair exactly equals the owner's pair chosen at QUALIFICATION_PENDING and remains in current T_impl (or a justified null with empty T_impl); staged Model Pack identity and E3 evidence/report hash are recorded in the execution record and both MSRs; completed applicable integration/E3 work; no open execution P1/P2; both capabilities cite the same retained implementation version/pair; final snapshots/dates valid; event and joint predecessor chains complete. The thin close wrapper must refuse any mismatch between CLOSED.implementationPair, ownerChoice, current T_impl, staged pack identity or E3 hash; changing the owner pair requires repeating Model Pack staging and E3. Retain paired CLOSED decision-v2 versions, update active projections and MSR outcomes, calculate closed MSR hashes and update the existing MSR index/qualification references. Disabled coordinates derive NO_QUALIFIABLE_CANDIDATE as the current builder specifies. Do not reopen or mutate CLOSED files afterward.

## 14. Execution tooling and interfaces

Existing validation commands, run from repository root:

```bash
python tools/qualification/attribute_corpus.py --help
python tools/qualification/attribute_corpus.py check-f1 --record docs/qualification/stage2-s2c/corpus/f1-evidence-record.json --store <custodian-record-store>
python tools/qualification/quality_statistics_check.py repository --repo .
python tools/qualification/model_selection_check.py repository --repo .
python tools/qualification/s2c_operational_check.py repository --repo .
python tools/verify_repo.py
git diff --check
```

The store placeholder is a required local input, never committed into corpus records. Ledger/evolution/decision validation subcommands already exist in `model_selection_check.py`. `s2c_operational_check.py projection` renders the method contract; it does **not** run a fleet projection.

Add these focused execution modules; names below are implementation targets, not existing tools:

| New file | Responsibility and interface |
|---|---|
| `tools/qualification/attributes/candidate_runner.py` | Explicit adapters for frozen selected-for-evaluation families; `load_candidate(configuration: dict, artefact_root: Path)` returns an AttributeInferencer-compatible object. Reuse accepted learned admissibility/aggregation code; no model discovery or network fetch at run time. Training entry points accept training-only views; tuning accepts tuning-only views. |
| `tools/qualification/attributes/quality_execution.py` | `evaluate_quality(experiment: dict, capability: str, predictions: Path, truth: Path, recipe: dict) -> tuple[dict, dict]`: detailed numerical report plus existing quality-evidence projection. Implement inherited b-1 arithmetic/resampling once. |
| `tools/qualification/attributes/engineering_run.py` | `measure_pair(experiment: dict, pair: dict, run_config: dict) -> dict` and pure `compare_e3(frozen_prediction, observed, tolerances) -> verdict`; real runner measurements and existing engineering source/evidence rows; local host samplers/job driver, no replacement scheduler. |
| `tools/qualification/s2c_execution.py` | Thin CLI: `preflight`, `freeze`, `quality`, `measure`, `e3`, `technical`, `implementation`, `close`; explicit input files and `--repo`. Dispatch to modules and existing artefact builders; nonzero on refusal; never auto-select a pair or advance over incomplete evidence. The `e3` subcommand retains the frozen prediction content-addressed before execution, reuses measurement machinery, and records the pure comparison verdict. |

Freeze/technical/implementation/close wrappers must validate all inputs in a staging repository/evidence area before publishing the complete paired artefacts. Use existing create-only retention; handle interrupted writes as a refused incomplete publication requiring restoration of the staged transaction, not silent mutation of an accepted version. Repository-only validators must pass after publication. Do not introduce a database, job orchestrator or new registry for these scripts.

Add four corresponding tests under `tools/qualification/tests/`: `test_s2c_candidate_runner.py`, `test_s2c_quality_execution.py`, `test_s2c_engineering_run.py`, `test_s2c_execution.py`. `test_s2c_engineering_run.py` must cover `compare_e3` and retained prediction/observation mismatch paths. Numerical implementation uses known-answer and perturbation tests, not assertions that merely mirror emitted fields. Production dependencies, if required by actual candidate families, get exact locks/licences and offline-policy entries; no dependency is selected by this plan.

## 15. Expected artefact set

Let `R = docs/qualification/model-selection`, `c = person|vehicle`, `e` be that capability's event id, and `x` the canonical experiment hash. These are filename substitutions, not new registries.

| Artefact | Required location/retention |
|---|---|
| Operational corpus/task/partition/audits/annotations/seal/access log | Existing custodian record store; F1 hashes and status in `docs/qualification/stage2-s2c/corpus/f1-evidence-record.json`; no imagery/frozen ground truth in Git |
| Candidate cards, owner policy, training/tuning receipts, raw predictions and numerical/engineering reports | Existing event MSR references and controlled evidence store; canonical small leaf documents under `R/s2c-evidence/<sha256>.json`; large data outside Git with hashes |
| Working/frozen M2 ledgers | `R/<c>-attributes/<e>-evidence-ledger.json` and `<e>-evidence-ledger-frozen.json`; frozen canonical copy also content-addressed |
| Experiment, host profile, configuration/margin documents | `R/s2c-evidence/<sha256>.json`, with referenced hashes resolved by execution preflight |
| Protocols | `R/<c>-attributes/<e>-protocol.md` and immutable `<e>-protocol-<x>.md`; hashes in MSR |
| Quality evidence and results | Existing quality-evidence/result schema documents content-addressed; `<e>-quality-result.json` and subsequent retained versions created by `retain_evidence()` |
| E2/raw source/projection evidence | Existing E2 schema, five engineering source kinds, operational-evidence documents under content addresses; projection reports embedded by builder; raw samples referenced separately |
| Joint versions/index | `R/s2c-joint/msr-attributes-2026-01-joint-technical-v<n>.json`, `...-joint-implementation-v<n>.json`, `...-joint-index.json`; one contiguous global version sequence |
| Paired event decisions | `R/<c>-attributes/<e>-decision-v<n>.json` plus `<e>-decision.json` active projection; separate contiguous event-version sequence and exact predecessor hashes |
| Decision snapshots/licence evidence | Content-addressed snapshots and final detailed rights determinations for every frozen unit/fallback × required profile; active `<e>-evidence-ledger-decided.json`; hashes in MSR. No `NOT_ASSESSED`/`REVIEW_PENDING` or invented placeholder `NOT_CLEARED` at CLOSED |
| Final records | Existing two MSRs and MSR index, with final decision/snapshot/protocol/closed-record hashes; no circular hashing |
| Model Pack handoff | `models/manifests/<selected-pack>.json`, `models/qualifications/<selected-pack>-<capability>.json`, staged built packs outside Git, component notices/provenance, runtime ids, Development overlay/profile and parity/offline reports |
| E3 | Frozen predicted reports, held-out trace hashes, actual observations, tolerance verdict and any retained revision/disposition; linked in MSRs and applicable qualification evidence |

Joint versions never cite hashes of full event decisions. Decisions cite retained joint versions. Indexes are projections re-derived from retained files, not trusted lineage authority. Keep both addressable evidence and required event-addressed copies; a bare hash is insufficient where validators resolve a file.

## 16. Review focus and verification/refusal matrix

| Input/failure | Required result | Owning slice/test |
|---|---|---|
| Missing/mismatched model, preprocessing, calibration or runtime bytes | Stop candidate execution before inference; no placeholder hash | A/C: candidate pin mismatch |
| Frozen-test member/path presented to training/tuning/selection/engineering | Refuse before read; improper access follows custody invalidation | B/C: partition firewall with attempted file-open observation |
| Wrong or incomplete pair×Q family, including an excluded comparator | Refuse projection; preserve ordered frozen family | C/E: incomplete-family known case |
| High apparent metric with insufficient positives/clusters | Insufficient-evidence; cannot pass/win | C: known denominators, cluster duplication and abstention cases |
| MPID failure/missing comparator | Exclude extension or explicit frozen ADR disposition; no owner override | E: existing `quality_sets` regressions plus real projection check |
| Incomplete relevant operational pair | Incomplete technical result, null winner; block implementation choice/CLOSED when relevant to C_impl | E/G: repaired mixed/incomplete tests plus CLI end-to-end |
| Complete but infeasible pair | Final infeasibility remains distinct from missing evidence | E/G: existing repaired negative/positive closure pair |
| Host/runtime/pair mismatch or synthetic client offered as real E2 | Refuse; no relabelled source measurements | D: real-client and identity mismatch |
| Histogram/backlog/busy-window mismatch or unmeasured crop/byte signature | Refuse projection before deriving H | D: repaired envelope tests plus imported real trace preflight |
| Expired/stale attempt callback | Drain matching lane only; next job runs; no new lane released | D: repaired attempt/generation tests unchanged |
| Pending profile status or emerging-only implementation | Remain pending or use valid capability-local fallback; never alter T | F/G: existing M1 tests plus snapshot-bound CLI |
| Owner pair assembled from individually valid coordinates but not an exact T_impl member | Refuse | G: exact-pair test |
| Missing, skipped, forked, backdated or rewritten chain version | Refuse repository publication | E/G/J: retained-chain suite and staged interrupted-publication test |
| E3 contradiction | Retain evidence/disposition; leave QUALIFICATION_PENDING and raise the explicit frozen-input/revision/`beforeSelectionRead` blocker; no bypass successor or next-best rescue | I: candidate-specific and method-wide counterexamples |
| Learned result packaged under fixture identity or Production activation | Refuse; preserve fixture history and Development boundary | C/H: cross-language identity/version and Production-negative tests |

The first five cross-cutting review risks are partition leakage, unmeasured executable identity, scientific outcomes without sufficient support, real-platform timing confused with client latency, and premature immutable closure before E3. The owning tests above must exist before their corresponding real execution step.

## 17. Ordered implementation slices and acceptance

For each slice: write its discriminating tests first where code is new, observe the expected failure, implement the smallest adapter, run focused and affected regression checks, retain the report, and obtain normal review/exact-head CI before progressing. Commits/PRs are subsequent implementation actions, not actions of this planning task.

### Slice A — accountable inputs and candidate manifest preparation (S2c.1/2)

- [ ] Reconcile merged status text only; name corpus, annotation, licence, statistics and performance owners. Deliver the complete owner-input checklist below with explicit missing items.
- [ ] Re-survey committed candidate proposals; pin legal evaluation rights, code/weight bytes, Runtime dependencies and M1 source evidence; implement PC-B0/VC-B0 and keep PO-B0 reference-only.
- [ ] Draft bounded executable composition/vehicle lists and required scope/fallback policy; no selection reads. Licence evaluation must cover every frozen unit, including fallbacks, across every required profile; no `NOT_ASSESSED`/`REVIEW_PENDING` may survive closure and no placeholder `NOT_CLEARED` may be invented.
- [ ] **Accept:** every proposed runnable component has verifiable bytes or an explicit blocked disposition; ledger validator passes; no fixture incumbent/PO-B0 unit; no unresolved owner input is silently defaulted.

### Slice B — operational corpus and pre-execution recipe (S2c.1; R1)

- [ ] Use existing corpus commands to collect/hash one raw-evidence pin, audit recurrence/duplicates, partition, run training pilot, freeze task, annotate/adjudicate, and seal.
- [ ] Approve training/tuning/statistical/engineering recipe and owner gates before candidate corpus execution. Establish selection/frozen access isolation and an engineering calibration/E3 split.
- [ ] **Accept:** `check-f1` reconstructs PASS with operational records; seal valid; frozen data unavailable to candidate process; all recipe fields populated and independently reviewed. Preparation may stop here for more footage/support without inventing a pass.

### Slice C1 — model-neutral contracts and cross-language vectors (S2c.5/v2)

- [ ] Implement only the already-accepted model-neutral S2c.5 v2 contracts, identity persistence/activation migration, admissibility and aggregation needed to express/evaluate the real task; share these semantics with later E2.
- [ ] Validate cross-language v1/v2 coexistence, identity persistence and known-answer contract vectors. Candidate adapters must discard non-task outputs and enforce decode/output bounds.
- [ ] **Accept:** model-neutral contracts and migration vectors pass without selection reads or candidate-specific numerical choices.

### Slice C2 — candidate harness and numerical qualification (S2c.3)

- [ ] Implement candidate loading/training/tuning and numerical b-1 execution modules above. Validate known-answer metrics/calibration-after-aggregation, training-only fitting, paired resampling, multiplicity/support refusal and candidate output bounds.
- [ ] Execute authorized training and tuning; retain all tried configurations; finish support simulation and label-free topology calibration. Resolve every real output hash.
- [ ] Before the first training read, content-address the preparation recipe and cite its hash in both PLANNED MSRs; before the first selection read, write the receipt described in §5 and refuse progression if freeze/receipt ordering is invalid.
- [ ] **Accept:** reproducible pinned executable units, frozen task-compatible scores/abstentions, passed numerical tests, recipe/receipt hashes and regression tests; no production-network dependency; no selection read. New evaluation locks/notices comply with AGENTS.

### Slice D — final freeze and measurement capture (S2c.2/3)

- [ ] Implement thin CLI freeze/preflight and E2 measurement collection, using existing retention APIs. Complete host/envelope/source coverage and the server-timing capture.
- [ ] Materialize final M2 frozen ledgers, experiment and both protocols; independently review freeze and record PROTOCOL_FROZEN. Then record EVALUATING before selection begins.
- [ ] Execute frozen label-free pre-screen and E1; prove E2 plumbing on an authorized real baseline identity and finite traces. Synthetic self-tests remain separate.
- [ ] **Accept:** canonical/repository validators pass; first selection read has not preceded freeze; E2 trace from real API, server timestamps and host peaks are captured and cross-correlated; malformed/mismatched workload is refused.

### Slice E — selection quality and technical joint decision (S2c.4)

- [ ] Run frozen selection predictions and b-1 reports; project quality evidence; derive/retain E/F/J via `build_quality()`.
- [ ] Execute E2 for the resulting J product; retain all required sources/coverage, project bounds and retain technical joint plus paired decisions.
- [ ] **Accept:** reports reproduce quality evidence; complete family preserved; all real relevant pair inputs retained; validators recompute identical technical outputs; no implementation-stage fields appear early. If incomplete, publish that status and stop advancement to a conclusive technical result.

### Slice F — implementation admissibility (S2c.6 selection portion)

- [ ] Create decision-date snapshots and detailed final/pending licence determinations for every frozen unit, including fallbacks, across every required profile. Derive K/C_impl and credibility-blind profile results without touching technical evidence.
- [ ] Execute any newly required frozen fallback pairs; retain an immediate implementation successor and paired QUALIFICATION_PENDING decisions. Enforce byte-identical operational rows across later implementation versions; refuse any attempt to complete an earlier incomplete row as rescue and raise an execution blocker.
- [ ] **Accept:** snapshot evolution and dates validate; technical bytes unchanged; `pending == false` and `unresolvedOperationalPairs == []`; all required C_impl measurements exist and none remain unresolved; no emerging component enters an implementation.

### Slice G — implementation decision, not immutable closure

- [ ] Recompute T_impl using the existing helper; implementation selection is complete only when `pending == false` and `unresolvedOperationalPairs == []`. Obtain an exact owner pair/rationale only then; keep unresolved choices null.
- [ ] **Accept:** owner pair is an exact member, both event records agree, no pending evidence is converted to final no-qualifiable. Events remain QUALIFICATION_PENDING for applicable Model Pack staging and E3.

### Slice H — selected Model Pack integration/handoff (S2c.6–8)

- [ ] Begin only after complete T_impl and owner choice. Build selected manifests/notices/runtime bindings and Development overlay; implement approved selected adapters and offline lifecycle integration. Verify same frozen executable, no substituted model, no widened detector lock.
- [ ] **Accept:** builder/identity/rebuild/install and parity tests pass; cross-language v2 vectors pass; Production refuses Development profiles; fixture-v1 history remains valid; selected model bytes and qualification metadata are correctly separated. Final model-selection gate remains pending until CLOSED record exists.

### Slice I — E3 preparation and execution (S2c.9)

- [ ] Freeze held-out execution schedule and projection/tolerance report, then run integrated load/recovery on the exact staged identity; capture observed service/resources/queue/commit behavior.
- [ ] Retain frozen prediction content-addressed before execution; invoke `s2c_execution.py e3`, whose pure `compare_e3(frozen_prediction, observed, tolerances) -> verdict` reuses the existing measurement machinery. Begin only after complete T_impl, owner choice and exact Model Pack staging.
- [ ] **Accept:** held-out provenance and frozen predictions precede actuals; required one-sided/symmetric tolerances pass. For a candidate-specific mismatch, retain evidence and `e3_disposition()`, leave QUALIFICATION_PENDING, and raise the explicit blocker required by §13; do not publish a bypass successor, invent a re-freeze or choose the next candidate. Method-wide error follows the existing revision protocol. Do not advance to CLOSED.

### Slice J — paired closure and qualification handoff (S2c.10)

- [ ] Apply §13 closure checklist, retain final paired decisions, finalize MSRs/index and add closed-record references to applicable capability qualification records. CLOSED.implementationPair must equal the exact owner pair chosen at QUALIFICATION_PENDING, remain in current T_impl, and preserve ownerChoice; record staged Model Pack identity and E3 evidence/report hash in the execution record and both MSRs. The close wrapper refuses mismatch; changing the pair requires restaging and repeating E3.
- [ ] Re-run full affected qualification/vision/platform tests, repository verification and normal exact-head CI; independent review must find no open P1/P2. Update F1/F3 and contributing evidence only where the acceptance register's closing rules are actually met.
- [ ] **Accept:** repository-only revalidation succeeds from retained files without Git history; final outcome/identity/hashes agree; `pending == false`, `unresolvedOperationalPairs == []`, full licence matrix final, and the chosen/E3-validated exact pair is bound in CLOSED; no unearned passed/Production/M-Q claim. S5 frozen-test access remains zero for this execution and remains after CLOSED.

## 18. File-change boundary

**Exact new execution-tool/test files:** the four Python modules and four Python test files in §14, plus the bounded Development timing/seed helper in the existing .NET integration-test surface identified in §9. Add `docs/qualification/stage2-s2c/real-qualification-execution-record.md` for dated execution evidence and dispositions; do not create a generic registry. The implementation wrapper must add regression coverage for append-only implementation rows and close-pair/owner/E3 identity checks; those are future implementation work, not changes in this plan.

**Existing files expected to change with real evidence:**

- `docs/qualification/model-selection/person-attributes/msr-person-attributes-2026-01.md`
- `docs/qualification/model-selection/vehicle-attributes/msr-vehicle-attributes-2026-01.md`
- `docs/qualification/model-selection/README.md` (existing event index/evidence references only)
- `docs/qualification/stage2-s2c/corpus/f1-evidence-record.json`
- `docs/reviews/2026-09-23-visual-attributes-acceptance.md`
- `docs/qualification/stage2-s2c/s2c-2b2-implementation-record.md` (merged-status reconciliation only)
- `docs/superpowers/plans/capability-implementation-roadmap.md` and the two Visual Attributes/S2c parent plans (status/evidence pointers only)
- `config/dependencies/offline-dependency-policy-v1.json`; `config/dependencies/offline-binary-catalog-v1.json` only when the actual dependency/artifact change requires it.

**Already-approved learned-runtime prerequisite/integration files likely affected:**

- `src/vision/mavi_vision/attributes/inference.py`, `pipeline.py`, `predictions.py`, `contracts.py`, `runner.py`, `supervisor.py`; new `attributes/admissibility.py` and selected modules in `attributes/adapters/`.
- `src/vision/mavi_vision/runtime/model_manifest_v2.py`, `resolver.py`; corresponding `src/vision/tests/` vectors/tests.
- `src/platform/Mavi.Application/Modules/VisualAttributes/Release/VisualAttributeRelease.cs`
- `src/platform/Mavi.Application/Modules/VisualAttributes/Completion/AttributePredictionsValidator.cs`
- `src/platform/Mavi.Contracts/Worker/Attributes/VisualAttributeContractRules.cs`
- `src/platform/Mavi.Infrastructure/VisualAttributes/VisualAttributeCompletionService.cs` (bounded timing capture and approved version handling); approved identity persistence/configuration and EF-generated migration with its SDK-generated filename.
- `src/platform/Mavi.Api/Endpoints/VisualAttributeCompletionEndpoint.cs` and `src/platform/Mavi.Application/Modules/VisualAttributes/VisualAttributeOptions.cs` (Development-only JSON-lines timing export, disabled by default and refused in Production).
- `tests/Mavi.IntegrationTests/VisualAttributeApiHost.cs`, `tests/Mavi.IntegrationTests/VisualAttributeWorld.cs`, `tests/Mavi.IntegrationTests/VisualAttributeCompletionTimingTests.cs` and a focused accepted-Evidence-Set seed/helper test (real platform path, including the applicable 10,000-Track shape).
- `src/platform/Mavi.Api/Startup/VisualAttributeReleaseStartup.cs` and affected platform tests where needed to enforce the accepted Development/version contract.
- New `src/vision/config/components/development-attributes-v2.json` and selected profile/schema/aggregation/parameters files under `src/vision/config/attributes/`.
- Selected manifests/qualification files under `models/`, `tools/vision/build_model_pack.py`, `tools/vision/sync_offline_vision_components.py`, `tools/verify_repo.py` and affected Setup scripts only as required by accepted S2c.6–8 packaging support.

Candidate-specific filenames, hashes, generated migration timestamp and pack ids cannot be named honestly before Slice A/C. Record their exact paths in the execution record before implementation of their slice. The symbolic artefact paths in §15 identify existing naming conventions, not permission to invent additional framework files. `operational.py`, `job_replay.py`, b-1/b-2 contracts and lineage algorithms are reuse targets, not planned rewrite targets.

## 19. Blockers, owner inputs and architecture-closure statement

**EXECUTION BLOCKER — real evidence and policy absent:** the baseline has no operational F1/seal, frozen candidate bytes, owner gate table or deployment load/host envelope. Smallest resolution is supplying and validating those inputs through Slices A–D, not adding synthetic substitutes.

**EXECUTION BLOCKER — numerical execution path absent:** the b-1 checker validates the method, not real metrics/inference. Smallest resolution is the accepted S2c.3 numerical/candidate harness in Slice C, tested against known answers and the approved event recipe.

**EXECUTION BLOCKER — authoritative learned E2 path incomplete:** fixture-only inference and current v1 learned-contract limitations cannot prove approved v2 behavior; the E2 wrapper also lacks server/host measurements. Smallest resolution is the already-approved S2c.5 prerequisites plus bounded measurement adapters in C/D. Do not spoof the fixture identity or call hand-written source records real E2.

These are expected implementation/input prerequisites, not contradictions in the closed selection architecture. No architectural correction is currently proposed. If actual candidate/runtime inspection exposes an impossible contract or an owner workload cannot be represented by the bounded helper, stop that slice and report a separately evidenced EXECUTION BLOCKER with the smallest correction; do not silently extend the framework.

**Human owner inputs required before real qualification execution:**

1. Named accountable owner, independent reviewer, Corpus Custodian, at least two annotators (one independent), Licence Review Owner and Scale/Performance Evidence Owner; statistical recipe reviewer.
2. Authorized real footage and retention/access arrangements; sites/cameras/day/night coverage; stable raw-evidence pin; annotation time and independently reviewable custody store.
3. Pilot-rule confirmation, task/vocabulary/headwear decision, required attribute scope and lawful fallback policy. A disabled or colour-only fallback cannot be assumed.
4. Candidate evaluation budget, source/acquisition access and evaluation/fitting permissions; decision on which committed proposals are actually pursued. No passwords or tokens in Git.
5. Every applicable numerical quality/support/slice gate, practical/NI/equivalence/MPID margin, bootstrap seed/replicate/multiplicity/undefined-denominator specification and training-pilot simulation coverage tolerance/perturbations. The reviewer must supply one complete executable recipe, not several selectable methods.
6. Training/tuning search and compute budgets, calibration method family, allowed parameter families, reproducibility tolerances and evidence storage capacity.
7. Concrete host/OS/runtime variants, detector/platform co-residency, worker count range/chosen topology, lease/retry/deadline settings, resource/SLA/host/reserve limits and physical measurement access.
8. Concrete 500-camera load envelope, camera-class mix, job/crop/byte distributions, backlog/burst/loss/drain requirements and representation limitations accepted before freeze.
9. Separate calibration and held-out E3 engineering traces, service-bound estimator/error settings, repetition schedule and one-sided/symmetric E3 acceptance tolerances.
10. Named non-commercial deployment profiles, actual end uses, delivery route and genuine final legal determinations for every frozen unit/fallback across every required profile, covering evaluation, operational use, derivatives and redistribution; no `NOT_ASSESSED`/`REVIEW_PENDING` or invented placeholder `NOT_CLEARED`; CUDA host/restart-service decisions where applicable.
11. At the decision stage only: exact owner implementation pair and rationale, within complete T_impl; authorization for the Development integration environment. This is not a preselected winner.

**Recommended order:** A → B → C1 → C2 → D → E → F → G → H → I → J. Model-neutral harness/contract self-tests may proceed while real corpus work is pending, but candidate corpus execution cannot precede R1/seal controls and selection cannot precede final freeze.

**Architecture closure is preserved.** This plan instantiates accepted event policy and implements missing execution paths; it adds no selection layer or statistical method. The method, numerical choices and evidence must be approved/frozen before use. Architecture redesign, new scores/ranks, adaptive composition expansion, frozen-test rescue, new attributes, unrelated UI/search work, speculative optimization and Production rollout are out of scope. Submit this plan for review before implementation; do not open a PR or execute a real run as part of producing it.
