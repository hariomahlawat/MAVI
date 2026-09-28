# Stage 2 S2c — Learned Attribute Model Packs

**Status:** Accepted implementation plan — PR #115 merged after independent review and exact-head CI; that merge is the acceptance event. S2c.0 is the separate status/evidence reconciliation and implementation-baseline slice, effective only when its own change passes exact-head CI and merges. No learned model is selected by this plan.
**Date:** 2026-09-28
**Starting baseline:** `main@f7b03a24aba8b8bd303ed3a93b26622395e94c5f` (merge of PR #114, S2b)
**Governing:** ADR-013 (including accepted 2026-09-28 S2c items 8–10), ADR-014 (including the accepted Development overlay and Model Selection Record notes), ADR-005, ADR-006, ADR-007, ADR-008, ADR-009, the Stage-2 parent plan, the Stage-2 qualification plan (including accepted protocol revisions R1, §19, and R2, §20), the authoritative Stage-2 acceptance register, the dependency/offline-packaging policy.
**Companion records:** `docs/qualification/stage2-s2c/model-candidate-survey.md` (discovery input: reported state of the art, nothing reproduced); the accepted Model Selection Record methodology `docs/qualification/model-selection/README.md` (MSR method v1) and the two S2c selection events `msr-person-attributes-2026-01` and `msr-vehicle-attributes-2026-01` (state `PLANNED`, no model selected); S2c.0 baseline record `docs/reviews/2026-09-28-stage2-s2c-0-baseline.md`.
**Exit gate:** §20. S2c closes F1 and F3 on executed evidence and runs learned person/vehicle attribute Model Packs through the unchanged S2b lifecycle as **Development / unverified** capabilities. It does not claim model-quality qualification, CUDA qualification or Production.

---

## 1. Baseline

| Check | Result |
|---|---|
| Planning baseline `main` | `f7b03a24aba8b8bd303ed3a93b26622395e94c5f` = merge of PR #114 (S2b). PR #115 acceptance baseline is `main@677afb6b73edf436e23f8d275bb95a7d5b3badac`; the S2c.0 implementation baseline will be the merge commit of the current reconciliation change. |
| PR #114 present | yes — `main` contains `37376fb` (the final PR head) and every earlier S2b commit; exact-head CI on `37376fb` (MAVI Quality Gate with the real-process attribute E2E, deterministic-validation, windows-script-validation, CPU ubuntu, CPU windows) passed before merge |
| Commits after the PR #114 merge at planning time | none before S2c planning began; PR #115 later merged the accepted plan |
| Planning branch point | clean |
| Docs vs merged implementation | **Inconsistent at the planning baseline**, which is why §21 defined DR1–DR15. PR #115 accepted the governing decisions and corrected the planning/status layer. S2c.0 reconciles DR1/DR7/DR8/DR8a/DR15 into a clean implementation baseline without changing F/G acceptance status; those reconciliations become effective only when S2c.0 merges. |

## 2. Material read

ADR-005, -006, -007, -008, -009, -011, -013 (including the 2026-09-28 S2b implementation amendment), -014 (including the 2026-09-27 amendment); `capability-roadmap.md`; `capability-implementation-roadmap.md`; the Stage-2 parent plan `2026-09-23-visual-attributes.md`; the acceptance register `docs/reviews/2026-09-23-visual-attributes-acceptance.md`; the qualification plan `docs/qualification/2026-09-23-visual-attributes-qualification-plan.md`; the architecture-review resolution; the S2a closure `docs/reviews/2026-09-28-stage2-s2a-closure.md`; the S2a/S2b reconciliation bridge; the S2b plan and implementation record; `dependency-and-offline-packaging-policy.md`, `offline-binary-inventory.md`, `config/dependencies/offline-dependency-policy-v1.json`; `models/manifests/README.md`; the runbooks `vision-runtime-model-component-lifecycle.md`, `mavi-offline-setup.md`, `offline-readiness.md`, `local-development.md`, `windows-cuda-host-session.md`; the UI specification sections on Unknown and confidence. The S2b code was read directly (§3).

## 3. What S2b actually delivered — the lifecycle S2c reuses

S2c adds no lifecycle, persistence path, worker protocol or publication shortcut. Everything below is reused unchanged unless §12 names an amendment.

| Concern | S2b implementation (code on `main`) | S2c consequence |
|---|---|---|
| Aggregate | `VisualAttributeAnalysis` (Queued/Running/Completed/Failed/Superseded), one unit per (run, identity) | reused |
| Identity | canonical tuple (schema, pipeline, aggregation, parameters SHA, sorted capability→modelPackId), fingerprint SHA-256; Python `attributes/pipeline.py` and .NET `VisualAttributeRelease.cs` pinned by `contracts/test-vectors/visual-attribute-identity-v1.json` | a real pack is a new identity; existing fixture analyses become Stale (ADR-013 §9, amendment item 5) |
| Preferred identity | platform reads `VisualAttributes:ComponentBindingPath` + `PipelineProfilePath`; nothing configured → `NotConfigured`; lease fenced on the worker's fingerprint | reused; §12.8: the shipped binding is unchanged and a Development overlay configures the learned role |
| Lease/attempts | header-only capability, heartbeat, reclaim, deadline (default 6 h), attempts (default 3), publication window | reused; the deadline drives the performance budget (§14) |
| Evidence read | lease-scoped, lifetime-fenced stream; worker verifies size + SHA before decode; transport ≠ evidence | reused; learned models only ever see verified bytes |
| Upload / staging / janitor | streamed, capped (64 MiB), create-once per attempt; janitor judges every directory | reused |
| Completion | three-phase (A validate + publication window, B content-addressed seal, C re-fence + COPY + visibility barrier) | reused |
| Artefact | `mavi-attribute-predictions-v1`, canonical JSON, exact coverage of leased crops, bound ≤ 64 MiB | extended to v2 for abstention (§12.3), versioned through identity v2 (§12.4); v1 stays valid history |
| Rows | one `Observed`/`Unknown` row per applicable (Track, type); `Unavailable` Track outcome with reason; supporting Observation for Observed | reused |
| Default/Stale | derived from the preferred fingerprint; supersession only on success | reused |
| Worker | `mavi_vision.attributes` role on the Component Binding v2 registry → resolver → supervisor; UNAVAILABLE never leases; one serial inference lane; heartbeat task stopped before `/complete` | reused; inferencer seam extended (§12.1); device policy implemented (§11) |
| Inferencer seam | `inference.py`: `AttributeInferencer.score(VerifiedCrop, attributes) → {type: {value: float}}`; `inferencer_for` returns only the fixture, receives no artefact paths | **the only model plug-in point**; replaced by the adapter registry (ADR-013 item 8, §12.1), the fixture path kept |
| Aggregation | `predictions.py`: `mean-score-argmax` + one global `minimumConfidence`; ties by schema order; supporting = crop scoring the value highest; the .NET release parser accepts only this method | a second versioned method (§7.4) whose document both languages parse (§12.5); the platform never recomputes decisions |
| Fixture refusal | worker `attribute_development_profile_forbidden` in Production; platform refuses `developmentOnly` outside Development/Testing | reused as the Production fence: every S2c learned pipeline profile is also `developmentOnly: true` (§12.8), so the existing platform and worker refusals keep it out of Production; fixture selection is by `fixtureSeed`, not by the flag (§12.1) |
| Provenance | per-capability modelPackId, manifest SHA, qualification id/SHA, verificationStatus; runtime pack id/source; binding and profile SHAs; configured policy; actual device | reused; `actualDevice` becomes `cuda:N` when CUDA runs |
| Integrity health | per-crop incidents counted once, recorded at artefact validation | reused |
| Bounds | schema tokens, ≤ 16 types, ≤ 8 per class, ≤ 32 values; artefact worst case at 10,000 Tracks × 4 crops ≤ 64 MiB; completion ≤ 3.7 s at 80,000 rows | re-derived for artefact v2 |
| E2E | `VisualAttributeEndToEndTests` runs the real worker process against Kestrel + PostgreSQL | the learned E2E follows the same path (§18) |
| Mutations | 72 killed of 73 (M72 equivalent) | S2c adds its own programme (§19) |

**Gaps S2b leaves for S2c** (from the code, not the roadmap): no attribute role or pack in the shipped binding; no attribute `capabilitySpecific` manifest section; no attribute gate sets in `config/acceptance/capability-gate-sets-v1.json`; `verify_repo` does not load attribute pipeline profiles and allows one tracked binding; the Model Pack CI workflow is hard-wired to RTMDet; Setup plans only the `vision` role; the attributes supervisor refuses `cuda`; the Representative-fallback flag computed by the selector (`evidence/selector.py`, `qualified`) is not persisted or leased, so the worker cannot tell a fallback Representative from a qualified one.

## 4. The S2c boundary

### 4.1 S2c owns

| Area | Extent |
|---|---|
| Task definition | the three inference tasks of §6 and their operating envelope |
| Attribute scope | the v1 operational vocabulary *candidates* and the annotation guide that freezes them (§7) |
| Model discovery and selection | survey record, shortlist, per-event selection protocols, bake-off on the training/tuning/selection partitions, one Model Selection Record per capability under MSR method v1 (§9) |
| Corpus | corpus and partition manifests, annotation guide, double-labelling, agreement report, sealing of the frozen test set (§10); closes **F1** |
| Model Packs | real person/vehicle packs: source manifests, licence notices, acquisition/build, built manifests, install; **F3** |
| Inference adapters | preprocessing, inference, output decoding and calibration behind the capability adapter; crop decode and admissibility in the worker before it (ADR-013 items 8–9) |
| Artefact v2, pipeline profile v2, identity v2 | abstention recording and artefact versioning in identity (ADR-013 item 9), both languages, one migration |
| Aggregation v2 | a second versioned aggregation method with per-attribute operating points (§7.4), parsed by both languages (§12.5) |
| Device policy | truthful CPU/CUDA/Development-auto for the attributes role (ADR-013 §8) |
| Runtime Pack | only if the bake-off selects a model outside the vision family's dependency graph (§12.7, ADR-013 item 10) |
| Failure/isolation | model load, OOM, timeout, NaN, crash, version skew, co-residency; contributes to **F9** |
| Performance | inference and end-to-end measurement at the 10,000-Track bound (§14) |
| Offline/Setup | pack inventory, offline policy entries (runtime and tooling), Development overlay binding, Setup/sync for the `attributes` role in Development profiles (§12.8, §15) |
| Development execution evidence | CPU on every deployable CPU variant; CUDA only where the Development GPU host is available (§11) |
| Development quality estimates | crop/Representative/Track metrics, retrained leave-one-camera-out, abstention, calibration on held-out folds — *contributing* evidence for F2, F4, F5, F6, F8, F9, F10 |

### 4.2 S2c does not own

S3: search v4, predicates, cursor, indexes, query plans (E5–E8), attribute filtering or browsing UI. S4: operator UI, Investigation/Review changes. S5: freezing gates and support, frozen-test scoring, retrieval precision (F7), CPU/CUDA *qualification* PASS, requalification matrix closure, Stage-2 acceptance. Also out: vehicle subclass (Stage 3), demographics/face/identity attributes (parent plan §2), a generic IntelligenceJob, a new lifecycle, tracking/detection/Evidence Set changes, scene analytics, live cameras, Production promotion, Task 18, training infrastructure beyond the minimal reproducible probe/fine-tune path the bake-off needs (§9.7), re-analysis requests (ADR-013 §9, not scoped by any slice yet), retention policy (ADR-013 §19; triggers before Production).

## 5. Quality principles for S2c

1. **MAVI owns the semantics; models are engines.** The platform, the artefact, the rows and the operator vocabulary never encode a network, a label index or a vendor.
2. **The model is chosen by evidence, not by the planner.** No checkpoint is named as the winner in this plan (§9).
3. **Unknown is measured, not a failure.** Abstention has reasons, rates and strata.
4. **No capability is exposed because a model can emit it.** Attributes that cannot meet their gate stay disabled.
5. **Replaceability is structural.** A better model later changes a Model Pack, a binding and a qualification record — nothing else (parent plan §7).
6. **Extend only where S2c demonstrates the need.** Every contract and code change S2c makes is listed in §12.9 and each is forced by a concrete gap in §3; the architectural ones are governed by the accepted ADR-013 items 8–10 and ADR-014 overlay note.
7. **Owner constraint A — MAVI is non-commercial.** "Enterprise-grade" means engineering quality, not commercial use. Licence qualification assesses the declared MAVI non-commercial deployment profile and the exact rights it exercises, never a hypothetical commercial product (MSR method §2.1; §9.3 here).
8. **Owner constraint B — scale to 500 cameras.** This is a standing architectural and qualification requirement. No model or composition is chosen on single-worker accuracy alone if its resource profile would make MAVI unsuitable at that scale. S2c measures the lower-level quantities and projects them with a reproducible workload model, and it never claims a 500-camera qualification it did not execute (§14.1; MSR method §7.1).

## 6. Task definitions — before any model is considered

Each task is its own model-selection problem. One multi-task model is not assumed; one Model Pack per capability may still compose several components (§12.2).

| | **T-PC Person clothing colour** | **T-PO Person carried objects and headwear** | **T-VC Vehicle dominant colour** |
|---|---|---|---|
| Capability id | `person-attributes` | `person-attributes` | `vehicle-attributes` |
| Attributes | upper-clothing colour; lower-clothing colour | backpack presence; other-bag presence; headwear presence (conditional) | dominant body colour |
| Input | verified EvidenceCrop JPEG of one tracked person | same | verified EvidenceCrop of one tracked vehicle |
| Typical crop | ≤ 1024 px long edge; Representative ≤ 64 KiB (≈ 600–700 px ceiling), NearView carries resolution; many far subjects 64–200 px tall | same; objects are a small fraction of the crop | 60–500 px; ≤ 1024 |
| Subjects | full or partial (frame-edge truncation, legs cut, occluders); possible second person in the crop | bag often self-occluded (rear/side views) | partial vehicles at frame edge, occlusion by other vehicles |
| Viewpoint | elevated CCTV, front/rear/side | orientation decisive (backpack visible from behind) | front/rear/side, oblique |
| Modality | day colour; low light; IR/greyscale at night | colour-independent; IR usable in principle | colour; IR/greyscale → colour inapplicable |
| Required Unknown | region not visible, too small, patterned/ambiguous, achromatic imagery | object not assessable (orientation/occlusion/size); **no negative claim in v1** | glare, heavy reflection, achromatic imagery, ambiguous two-tone |
| Accuracy expectation | set by owner-declared precision targets on the tuning-partition precision–coverage frontier, confirmed on the selection partition (§10.5) — not by benchmark figures | same | same |
| Latency/throughput | ≤ the per-crop budget derived in §14 on the Development CPU | same (shared per-crop budget with T-PC when composed) | same |
| Targets | CPU on every deployable CPU variant (Development); CUDA optional Development evidence | same | same |

The frame-edge geometry of a crop is not in the lease today. Whether truncation must be signalled explicitly (an additive lease field) is decided by the bake-off's stratified results (§23, U6), not assumed.

## 7. Attribute scope

### 7.1 Per-attribute definition (candidate v1; frozen only by the annotation guide, §10.3)

| Attribute type | Semantic definition | Candidate values | Unknown when | Minimum evidence | Sensitivity notes |
|---|---|---|---|---|---|
| `person-upper-colour` | dominant colour of the outermost visible upper-body garment (torso; excludes bags, skin, hair) | the basic-colour family `black, white, grey, red, orange, yellow, green, blue, brown, pink, purple` plus `multicolour` only if labelable | torso not visible or below the admissibility size; pattern without a dominant colour; achromatic/IR crop; conflicting crops | ≥ 1 admissible scored crop and the aggregation margin (§7.4) | colour naming is culturally variable — the guide defines boundaries by reference swatches; low-agreement pairs (e.g. grey/white, brown/orange) are merged or removed by the pilot |
| `person-lower-colour` | dominant colour of the lower-body garment (legs/skirt; excludes shoes) | same family | legs truncated/occluded; as above | as above | truncation is common in elevated views; measured stratum |
| `person-backpack` | a backpack carried on the back or one shoulder | `present` | object not assessable; front view with straps invisible | as above | presence only — no `absent` in v1 (ADR-013 §12; qualification plan §6.2) |
| `person-bag` | a carried bag other than a backpack (handbag, shoulder bag, briefcase; excludes luggage trolleys) | `present` | as above | as above | merged with backpack if the pilot shows the distinction is not labelable |
| `person-headwear` | a hat, cap, hood worn up, or helmet | `present` | head not visible/too small | as above | **conditional** (parent plan §2): exposed only if its gate passes in S5; retained as a candidate because the qualification plan requires the decision to be measured; helmet vs hat split is not in v1 |
| `vehicle-colour` | dominant exterior body colour (excludes glass, wheels, lights, reflections) | `black, white, grey, silver, red, orange, yellow, green, blue, brown, beige` plus `multicolour` only if labelable | achromatic/IR crop; glare/reflection dominating; body not visible | as above | `silver` vs `grey` and `beige` vs `brown`/`white` are the known ambiguous pairs; the pilot decides merges |

Schema limits (S2b): tokens `[a-z0-9-]`, ≤ 8 types per class (person needs 5), ≤ 32 values. The artefact v2 worst case is re-derived with these vocabularies before the schema is frozen (§13).

Deliberately excluded: age, gender, ethnicity, face attributes, hair length, sleeve length, garment style, vehicle type/make/model — even though candidate models emit several of them. A model output outside the schema is discarded by the adapter and never enters the artefact or provenance.

### 7.2 Confidence representation

An Observed row's confidence is the aggregation policy's score for the asserted value in [0,1] (ADR-013 §12). S2c makes it meaningful: adapters output **calibrated** per-value probabilities (calibration fitted on the training partition by camera/site-grouped cross-fitting, never on the selection partition or the frozen test, and shipped inside the Model Pack, ADR-013 item 8), and aggregation v2 reports the aggregated calibrated probability. The UI rules (integer percent in lists, one decimal in inspectors, never opacity) are S4's and unchanged. A confidence is never shown for Unknown.

### 7.3 Versioning

Any vocabulary change is a new attribute-schema version (new identity, requalification). Merging two colour values after the pilot happens **before** the schema is first bound, so it creates no historical rows. Removing an attribute after qualification (a gate fails in S5) is a new schema version; the old analyses remain readable history (E4).

### 7.4 Aggregation across the Evidence Set (aggregation method v2)

A new method `calibrated-mean-margin-v1` (name provisional), versioned beside S2b's `mean-score-argmax`, defined by an aggregation-v2 document both languages parse (§12.5) and executed only in Python:

1. inputs per attribute type: the calibrated per-value scores of crops **scored** for that type. Abstained crops contribute nothing, whether abstention came from admissibility or from the adapter (§12.1). Representative crops follow `representativePolicy` (§8.2);
1a. **contributing crops.** For a categorical (colour) type, a scored crop contributes only if its top calibrated score reaches the per-type evidence floor `floor(type)`. A low-evidence crop (partial, occluded, blurred, extreme pose) therefore neither votes nor dilutes the views that show the region clearly. Its scores stay in the artefact for audit. For a presence type, a low score is legitimate evidence *against* presence, so no floor applies. Instead the type pools the **top-`kMin`** crop scores, so a view that cannot show the object (a backpack seen from the front) cannot veto the views that do;
2. if fewer than `kMin(type)` crops contribute → **Unknown**;
3. per value: mean calibrated score; best value `v*`, runner-up `v₂`; deterministic tie rule (S2b's: higher mean, then schema order);
4. **Observed** iff `n_contributing ≥ kMin(type)` **and** `mean(v*) ≥ τ(type, v*)` **and** `mean(v*) − mean(v₂) ≥ δ(type)`; otherwise **Unknown**;
5. supporting Observation: S2b's rule (the crop with the highest `v*` score, then lower evidence rank), restricted to **contributing** crops (step 1a) that the Representative policy allows as support;
6. presence attributes (single value `present`): Observed iff `n_contributing ≥ kMin` (every scored crop contributes) and the top-`kMin` mean ≥ τ; otherwise Unknown — never Absent.

**Predeclared pooling references (aggregation ablation).** Pooling is a *parameter* of the frozen family, chosen from a closed set fixed at S2c.2 before any result:
- presence types: full mean, top-1 (max), top-`kMin` mean (default) and median;
- colour types: mean over contributing crops with the floor (default), and without it.

The bake-off scores every option on the tuning partition, reports all of them in the record, and keeps the default unless another option is better by §9.4's statistical method applied **on the tuning partition**. Nothing outside the set may be added after results. This shows whether top-`kMin` is justified for MAVI's evidence geometry rather than merely intuitive, including its false-positive rate relative to the full mean.

The *family* (this rule shape, with its closed pooling set) and the *threshold-selection method* (§10.5) are frozen in S2c.2 before any MAVI result (R1 step 1); only the parameter values (`kMin`, τ, δ, `floor`, and the pooling option from the closed set) are tuned on the tuning partition (R1 step 2) and frozen before frozen-test scoring (R1 step 3).

## 8. Evidence quality and applicability

### 8.1 Outcome distinctions (reusing S2b's taxonomy)

| Situation | Level | Result | Mechanism |
|---|---|---|---|
| Model scored the crop, aggregated value clears τ and δ | attribute | **Observed** (valid prediction) | aggregation |
| Scored, but below τ or δ | attribute | **Unknown** (low confidence) | aggregation |
| Crop inadmissible for this attribute (too small, achromatic for a colour type, region not present) | crop × attribute | **abstained** with reason; contributes no score | admissibility policy (ADR-013 item 9) |
| The model's own applicability/visibility output says the type cannot be judged on this crop | crop × attribute | **abstained** `model_not_applicable`; contributes no score | adapter output (§12.1), only for models with such an output |
| Scored, but the crop's top score for a colour type is below `floor` | crop × attribute | **scored, non-contributing**; scores kept in the artefact, excluded from the vote | aggregation v2 (§7.4 step 1a) |
| No crop scored for the type | attribute | **Unknown** | aggregation |
| Every crop abstained but at least one crop was verified | Track | **Analysed**, all attributes Unknown | artefact v2 rule |
| Evidence missing / integrity failed / undecodable / no accepted evidence | crop → Track | **Unavailable**(reason) — S2b unchanged | S2b |
| Unsupported modality for the whole capability (e.g. a model cannot run on greyscale at all) | crop × attribute | abstained `modality_unsupported` | admissibility |
| Model failure (exception, OOM, timeout) | attempt | retryable attempt failure; never a Track outcome | §16 |
| Malformed model output (NaN/Inf, out-of-range, wrong shape) | attempt | terminal `visual_attribute_output_invalid` (S2b) | adapter + aggregation checks |

### 8.2 Condition handling

| Condition | Handling | Measured as |
|---|---|---|
| Low resolution | admissibility minimum per object class (and per region for T-PC), tuned on the tuning partition; below it → abstain `subject_too_small` | stratum: crop height bands |
| Partial body / truncation | lower-body region size check (admissibility); colour: evidence floor (§7.4 1a); presence: top-`kMin` pooling; adapter `model_not_applicable` where the model has a visibility output; explicit geometry only if U6 shows it is needed | stratum: truncated yes/no (annotated) |
| Occlusion, second person in crop | evidence floor / top-`kMin` pooling / adapter applicability as above; the selector's occlusion proxy already governs supplemental roles | stratum: occlusion level, crowding (annotated) |
| Blur | evidence floor / top-`kMin` pooling as above; sharpness not re-measured in S2c unless the bake-off shows material benefit | stratum: blur (annotated) |
| Extreme pose | evidence floor / top-`kMin` pooling / adapter applicability as above | stratum: viewpoint |
| Night / IR / greyscale | deterministic achromatic test (chroma statistics on the crop) → colour types abstain `achromatic_evidence`; presence types still scored | stratum: day/night; achromatic rate |
| Fallback Representative | the lease cannot say whether a Representative is a qualified frame or a fallback (the selector's `qualified` flag is neither persisted nor leased), and it cannot be derived (a qualified frame can fill NearView yet fail to displace a fallback Representative under the 64 KiB cap). Default `representativePolicy: abstain` — every Representative crop is recorded as abstained `representative_qualification_unknown`, so Observed values rest only on qualified supplemental evidence and Representative-only Tracks are Analysed with every attribute Unknown. This is the conservative reading of parent plan §8.2; its coverage cost is measured, and the bake-off also scores Representative crops *for evaluation only* to quantify what an explicit qualification contract would recover (decision U7) | Representative-only vs Evidence-Set metrics (qualification plan §6.3); coverage lost to the policy |
| Inconsistent crops within a Track | the margin δ turns disagreement into Unknown | aggregation error analysis |
| Vehicle partially visible | admissibility minimum; evidence floor | stratum |

Abstention reason vocabulary (one closed vocabulary covering both sources, versioned with the admissibility method, which is part of identity v2; an adapter may emit only `model_not_applicable`, and the runner refuses any other adapter reason): `subject_too_small`, `region_too_small`, `achromatic_evidence`, `modality_unsupported`, `representative_qualification_unknown`, `model_not_applicable` (the only adapter-emitted reason). Additions are versioned changes.

## 9. Model discovery and selection

### 9.0 From survey to qualified Model Pack

S2c runs two Model Selection Events under the MSR methodology (`docs/qualification/model-selection/README.md`, MSR method v1): `msr-person-attributes-2026-01` (sub-tasks T-PC and T-PO, plus a composition decision) and `msr-vehicle-attributes-2026-01` (T-VC). They are independent events, and no person result is assumed to transfer to vehicles. The methodology owns the generic rules: event and candidate states, evidence classes, decision layers, immutability and the upgrade procedure. This section, §9.2–§9.7 and §10 instantiate them for S2c and may not weaken them.

| Step | Document | Slice | Event state after | Candidate states |
|---|---|---|---|---|
| Survey (discovery) | `stage2-s2c/model-candidate-survey.md`, reported only, with a dated re-survey addendum at S2c.2 | planning, S2c.2 | `PLANNED` | `DISCOVERED` |
| Shortlist + exact checkpoint pinning + evaluation permission | `<event>-protocol.md` | S2c.2 | `PROTOCOL_FROZEN` (protocol hash in the record before any MAVI data is read) | `SHORTLISTED` / `NOT_SHORTLISTED` (technical reason) / `REFERENCE_ONLY` / `DEFERRED` |
| Frozen evaluation + bake-off | harness (S2c.3); results by hash in the evidence store | S2c.4 | `EVALUATING` | `EVALUATED` → `TECHNICALLY_SELECTED` / `TECHNICAL_ALTERNATIVE` / `REJECTED_TECHNICAL`, per sub-task |
| Composition (person only, §9.5a) | record §6.1 | S2c.4 | `TECHNICAL_DECISION_RECORDED` | component finalists → composition candidates by the frozen rule → composition evaluation → Pareto frontier |
| Licence/deployment qualification | record §7 (human determinations per profile, primary-source hashes) | S2c.2 (evaluation permission), S2c.6 (use) | `QUALIFICATION_PENDING` | licence axis: `REVIEW_PENDING` → `CLEARED` / `CONSTRAINED` / `NOT_CLEARED` |
| Implementation choice + packaging | record §8–§9; Model Pack + qualification record | S2c.6 | `CLOSED` (`SELECTED_FOR_PACKAGING`, `BASELINE_SELECTED` or `NO_QUALIFIABLE_CANDIDATE`) at S2c.10 | — |
| Model Pack qualification | `models/qualifications/*.json` (authoritative), citing the closed record by hash | S2c.10 (record); S5 (quality gates) | addendum records the outcome | `QUALIFIED_INCUMBENT` only through an addendum after the qualification record passes |

The survey stays a discovery input and never becomes the decision record. The MSR never becomes a qualification record.

### 9.1 Survey (done for planning; reported, not reproduced)

`docs/qualification/stage2-s2c/model-candidate-survey.md` records the 2026-09 survey: supervised pedestrian-attribute recognition (PAR) models and datasets, vehicle-colour methods and datasets, contrastive VLMs, self-supervised backbones, small generative VLMs, segmentation/colour-naming pipelines and industrial models (Intel Open Model Zoo, PaddleDetection, NVIDIA TAO/DeepStream). Its conclusions that shape S2c:

- **Published accuracy does not transfer.** Vehicle colour reported at 92–98 % on a saturated frontal benchmark falls to ≈ 66 % top-1 for the same backbone on real CCTV with night imagery; night is < 10 % of that data and ≈ 32 % of its errors. PAR state of the art (≈ 85–93 % mA on PA-100K/PETA/RAP) is measured in-domain, and cross-domain splits cost ≈ 15–25 mA points.
- **Published PAR scores mostly do not measure colour.** The standard PETA-35/RAPv1-51 evaluation subsets drop colour labels and PA-100K has none; colour is scored on Market-1501 attributes and UPAR. MAVI's colour quality cannot be inferred from leaderboard numbers.
- **The strongest reported approaches are frozen foundation backbones with task heads** (VLM-PAR on SigLIP 2; the Orrú vehicle-colour ensemble on DINOv3) and **task-shaped CCTV models** (Awiros, Intel OMZ, PP-Human/PP-Vehicle); both routes need MAVI-domain labels to be measured, and the backbone-plus-head route needs them to be trained.
- **Licences differ by kind, not by application domain.** The survey records permissive, use-scoped, non-commercial and unstated terms separately for code, weights, derived models and training data (§9.3). MAVI is a domain-neutral platform; no candidate is excluded because of an assumed application domain.

Technical ranking (§9.2) and licence qualification (§9.3) are **separate analyses**. Licence convenience never shapes the technical shortlist: a technically strong candidate with a problematic licence stays in the comparison with the issue marked, and the strongest legally usable alternative is evaluated beside it.

### 9.2 Technical shortlist (licence-blind; candidates, not choices)

Ordered within each task by the strength and domain relevance of the *reported* evidence (survey record). A *method* entry means the architecture/recipe trained on MAVI-permitted labels; a *checkpoint* entry means released weights.

**T-PC person clothing colour**

| Id | Candidate | Kind | Reported technical evidence | Technical risk |
|---|---|---|---|---|
| PC-1 | Frozen **SigLIP 2** tower + trained cross-attention/linear heads, region-cropped (VLM-PAR design) | method (backbone checkpoint + MAVI head) | VLM-PAR reports SOTA on PA-100K/PETA/Market (Dec 2025); SigLIP 2 NaFlex handles tall crops | ≈ 86–93 M image-tower parameters at base (≈ 0.4 B with the text tower, which is not needed at inference); low-res degradation; no MAVI evidence |
| PC-2 | Frozen **DINOv3** (ViT-S/B or ConvNeXt) + MAVI heads; **DINOv2** as the paired alternative | method | DINOv3 features used by the strongest reported vehicle-colour ensemble; DINOv2 strong general probes | colour sensitivity of invariance-trained features unmeasured |
| PC-3 | **PromptPAR / VTB** (CLIP ViT-L/14 or ViT-B prompt tuning) | method; released checkpoints trained on PETA/RAP subsets | 87–89 mA in-domain (PromptPAR); the eval subsets it reports exclude colour | GPU-class (L/14); CLIP binding weakness; cross-domain drop (78.8 → 63.2 on MSP60K) |
| PC-4 | **UPAR-trained** ConvNeXt-B baseline / **C2T-Net** (UPAR 2024 winner) | checkpoint (C2T-Net released) | trained on 11-colour upper/lower labels; cross-domain mA ≈ 70 | heavy (Swin + EVA-ViT); domain of source datasets |
| PC-5 | **Awiros ConvNeXt V2-Tiny** | checkpoint (ONNX) | vendor CCTV benchmark: top 74.8 %, bottom 75.2 % | vendor-reported only; pseudo-labels from an unnamed VLM; gender/age heads must be discarded |
| PC-6 | OpenAI **CLIP** / **OpenCLIP**, **MobileCLIP 2**, **MetaCLIP**, **EVA-CLIP** towers + MAVI heads | method | alternative contrastive towers; MobileCLIP 2 is the most CPU-efficient | as PC-1; binding weakness |
| PC-7 | **Intel OMZ person-attributes-recognition-crossroad-0230** colour points + Lab naming | checkpoint (OpenVINO IR) | designed for crossroad CCTV; tiny | point sampling, not region colour; no colour accuracy published |
| PC-8 | Small **CNN fine-tuned** on MAVI labels (MobileNetV3 / ResNet / ConvNeXt-T; strong-baseline recipe) | method | 80–85 mA class in-domain for the recipe | label volume |
| PC-9 | **VTFPAR++** (CLIP ViT-B/16 side-tuned on video tracklets; MARS checkpoint; also PO-8) | checkpoint | the only located released checkpoint covering upper/lower colour *and* bags/hat (survey §2.3) | trained on 6-frame tracklets while MAVI Evidence Sets are a few role-selected crops, so single- and few-crop modes must be benchmarked; CPU cost of several ViT-B passes |
| PC-B0 | **Deterministic baseline**: region band + dominant chroma cluster + MAVI-owned CIE-Lab naming | MAVI-owned | floor every learned candidate must beat | illumination/white balance |

**T-PO person carried objects and headwear**

| Id | Candidate | Kind | Reported technical evidence | Technical risk |
|---|---|---|---|---|
| PO-1 | SigLIP 2 heads (shared tower with PC-1) | method | as PC-1 | small objects at low resolution |
| PO-2 | DINOv3 / DINOv2 heads | method | as PC-2 | as PC-2 |
| PO-3 | **PromptPAR / VTB / strong baseline** trained on **PA-100K** (hat, backpack, handbag, shoulder bag) | method + released checkpoints | 80–87 mA on PA-100K | domain shift to MAVI views |
| PO-4 | **Awiros ConvNeXt V2-Tiny** | checkpoint | vendor: backpack 94.2 %, handbag 91.3 %, head accessory 84.7 % | as PC-5 |
| PO-5 | **PP-Human attribute** (PP-LCNet/PP-HGNet, 26 attributes incl. hat and bags) | checkpoint (Paddle) | mA 94.5–95.4 on a mixed set | Paddle toolchain or conversion |
| PO-6 | **Intel OMZ 0230** `has_backpack`/`has_bag`/`has_hat` (0234/0238 for hat) | checkpoint (IR) | F1 backpack 0.77, bag 0.66, hat 0.64 | weak reported F1; ≥ 80 px width |
| PO-7 | Small CNN fine-tuned on PA-100K + MAVI labels | method | as PC-8 | as PC-8 |
| PO-8 | VTFPAR++ (as PC-9) | checkpoint | as PC-9 | as PC-9 |
| PO-B0 | **Prevalence reference** (§9.5): per-camera training prevalence, no image evidence | statistical floor | floor every presence candidate must beat on AURC/AP | not packageable |

**T-VC vehicle dominant colour** (independent survey and bake-off; no assumption that a person model serves it)

| Id | Candidate | Kind | Reported technical evidence | Technical risk |
|---|---|---|---|---|
| VC-1 | Frozen **DINOv3** (and DINOv2) + MAVI colour head; ensemble with CNNs as in Orrú 2026 | method | UFPR-VeSV 94.6 % micro / 79.7 % macro for the ensemble; ≈ 58 % of residual errors judged ambiguous (IR, grey/silver) | cost of an ensemble; long tail |
| VC-2 | SigLIP 2 + MAVI colour head | method | general features; no VCR result | as PC-1 |
| VC-3 | **PP-Vehicle PP-LCNet** attribute model | checkpoint (Paddle) | colour 90.81 % on VeRi val | single-site training domain; Paddle toolchain |
| VC-4 | Fine-tuned CNN / ViT on MAVI labels (Lima et al. recipe) | method | 92.8 % Chen, 66.2 % UFPR-VCR for ViT-B/16 — the CCTV figure is the relevant one | labels |
| VC-5 | **Intel OMZ vehicle-attributes-recognition-barrier-0042** (0039 small reference) | checkpoint (IR) | colour avg 82.7 % (vendor), yellow 61.5 % | 7 colours; front-facing bias |
| VC-R | SigLIP 2 / CLIP zero-shot prompts | reference | no VCR result | uncalibrated; reference only |
| VC-B0 | **Deterministic baseline**: body-region chroma clustering + Lab naming | MAVI-owned | floor | glare, white balance |

**Not candidates for the classifier role, on technical grounds:** small generative VLMs (Florence-2, SmolVLM 2, Qwen2.5-VL / Qwen3-VL, Moondream, InternVL) — no native calibration, decoding non-determinism, per-crop cost at 40,000 crops; an offline one may assist labelling, never as ground truth (§10.3). Billion-parameter PAR (LLM-PAR) — not viable on the Development CPU at the §14 budget; cited as the reported ceiling. **Segmentation** (SAM 2.1, SAM 3, human parsing) is a *component* candidate for the region step of PC-1/PC-B0/VC-B0, evaluated only if unmasked bands lose materially in the bake-off.

The 2026-09-28 refresh (survey §2.3) recorded and dispositioned UniPAR, SequencePAR, PFM-VEPAR, EventPAR/RWKV-PAR, VTFPAR++, MambaPAR, SNN-PAR, KGPAR, AttackPAR, UAPAR and a YOLOv8 + ResNet18 PAR. Event-camera methods are `NOT_SHORTLISTED` (incompatible input modality); methods without a located checkpoint are `REFERENCE_ONLY`. The shortlist is a floor, not a ceiling: slice S2c.2 re-runs the survey at freeze time and may add a candidate published since. These tables are the planning proposal. The authoritative candidate set and every disposition live in each event's candidate ledger, which retains every candidate, losers included (MSR method §4–§5).

### 9.3 Licence qualification (separate analysis)

Every shortlisted candidate has a row in the survey record's licence matrix (`model-candidate-survey.md` §6) giving: exact licence and its source; commercial-use, redistribution, surveillance/security/law-enforcement, military/defence and other use restrictions; and whether each applies to code, weights, derived models or training data. The classes:

| Class | Meaning |
|---|---|
| **L-A permissive** | no use restriction beyond attribution/notice stated by the source |
| **L-B use-scoped** | commercial use and redistribution are stated as permitted, but certain **end uses** are stated as prohibited or out of scope. Qualification depends on the deployment's actual use, determined per deployment profile, never inferred from MAVI's domain-neutral product definition |
| **L-C non-commercial / research-only** | the source's grant excludes commercial use, or limits use to research. This is **not automatically disqualifying** for MAVI, a non-commercial solution: whether the grant covers every use the declared profile makes (evaluation, operational running, fine-tuning, derivatives, and any redistribution its delivery route needs) is a human determination. Some research grants exclude "product development" or operational use even when nothing is sold |
| **L-D unstated / unresolved** | no licence found, commercial use or redistribution not stated, or the question depends on an unresolved legal reading (for example whether weights inherit their training data's terms). Resolved only by the human review (U1), never by the planner |

The class of each candidate, with its primary source, is recorded once, in the survey's licence matrix (`model-candidate-survey.md` §6), and snapshotted into the event's candidate card at S2c.2. It is not restated here, so the two cannot drift.

Rules:
1. **Evaluation permission is its own question.** It is a human legal precondition to *measuring* a candidate, not a ranking input, and it is recorded with decision-maker, date and primary source. A candidate whose evaluation is not permitted becomes `REFERENCE_ONLY` (reported evidence kept at its reported strength), never `NOT_SHORTLISTED`. A candidate enters the MAVI bake-off only if MAVI's evaluation use is permitted by its terms (some L-C grants cover "testing" for research but exclude product development). Where a checkpoint cannot be evaluated but its *method* code is permissive, the method trained on MAVI-permitted data represents it (e.g. PC-3 re-trained on MAVI labels instead of the PETA/RAP checkpoint); where neither is possible, its reported figures remain in the comparison, marked "not reproduced by MAVI".
2. **Selection needs clearance for each named target profile** (gate SG1, §9.5), applied *after* evaluation. SG1 passes when a human reviewer records the candidate as **cleared for the declared MAVI non-commercial deployment profile**: every right that profile exercises is granted (MSR method §2.1 and the §5 rights inventory).
   - L-A: after review.
   - L-B: with a recorded per-deployment end-use determination.
   - L-C: when the grant covers every use the profile makes, otherwise under a separately obtained licence.
   - L-D: not until the open question is resolved.

   Commercial-use permission is never required on its own, because MAVI is non-commercial. MAVI itself is intended as an open-source solution, but model code and weights are separately licensed artefacts: open-source MAVI distribution does not create redistribution rights for model weights. Redistribution is judged separately; when the profile's delivery route would redistribute weights (for example an offline kit) and the grant does not allow it, the candidate is `CONSTRAINED` for that route even if local use is permitted, while a separately permitted local-acquisition route may remain viable. "Free of cost" is never read as "redistributable".
3. **The record reports** the strongest reported/reference candidate, the highest task-quality evaluated candidate, the strongest evaluated technical candidate, and the strongest candidate cleared for each target profile (MSR method §9), with the measured gaps. If they differ, the owner decides whether to seek a licence for the stronger one; the plan does not decide it.
4. The licence/deployment determination for a profile is recorded as **evidence of the existing common `licence` gate** in that profile's `profileQualifications` entry (`{kind: "licence-use-determination", reference, sha256}`; existing shape, no schema change). For an L-B pack it must be a per-deployment end-use determination; that is a review rule, since `kind` is free text and not machine-checked. A profile cannot become qualified without it: the Production resolver requires profile evidence for every gate. **In S2c no `profileQualifications` entry is written.** An entry forces the profile into `qualifiedProfiles` and needs its policy SHA, and no profile is qualified in S2c. The Development SG1 determination lives in the MSR licence axis (§9.6), and profile entries are written only when a profile is qualified (S5 or later). The variant-level `licence` gate stays `pending` in S2c. Its eventual evidence is the licence review record for the pack's components (qualification plan §14). No licence-class-dependent gate is introduced, so an L-A pack is never left with a gate it cannot satisfy.

### 9.4 The bake-off

- **Separation from production.** Candidates run in a *separate evaluation environment* under `tools/qualification/attributes/` (an isolated, pinned venv that may contain `open_clip`, `transformers`, `onnxruntime`, `openvino` for conversion and parity), never in the Runtime Pack. No candidate is integrated into `mavi_vision.attributes` before it wins.
- **Same conditions for all.** The same crops (the real MAVI Evidence Sets, exactly as leased: training for fitting, tuning for parameter values, selection for comparison), the same admissibility policy, the same aggregation method family, the same metric code, the same hardware class, recorded thread counts and precision.
- **Inputs.** Crops come from the corpus store by SHA; each candidate's preprocessing is recorded as data; checkpoints are loaded from a hash-pinned local cache populated once from pinned revisions (never a floating tag).
- **Folds.** Heads and calibrations are fitted on the *training* partition with camera- and site-grouped cross-fitting; `kMin`/τ/δ and admissibility parameters are tuned on the *tuning* partition; candidates are **compared** on a separate *selection* partition untouched by any fit or tuning; the frozen test is sealed (§10.2). Leave-one-camera-out means retraining each head without the held-out camera. Every S2c number is labelled a development estimate, never a qualification result.
- **Probe/fine-tune candidates** train on the training partition only, with fixed seeds and a recorded environment (§9.7).
- **Measurements:** §10.4 quality metrics at crop, Representative-only and Track level with abstention; risk–coverage; calibration (on held-out folds only — never in-sample); strata (§8.2); per-camera and retrained leave-one-camera-out; CPU and (where available) CUDA latency p50/p95 per crop and per Track, batch behaviour, peak RSS/VRAM, model-load time; determinism on repeat.
- **Statistics** (MSR method §8.1):
  - Differences are reported with a **hierarchical paired bootstrap**. Top-level clusters (site, or camera block where a site has one camera) are resampled with replacement, then Tracks within each drawn cluster. Both candidates are scored on the same replicate, and the interval is the 95 % percentile interval.
  - "Better" means the interval excludes zero **and** the number of top-level clusters meets the minimum frozen at S2c.2 by the calibration simulation.
  - Below that minimum, no significant winner is declared. Per-cluster results and a cluster sign count are reported, and the choice is an owner decision.
- **Protocol frozen first.** Candidates, weights, gates, strata, the minimum practically important difference (MPID) and the report format are committed (slice S2c.2) **before** any candidate sees MAVI data.

### 9.5 Selection gates and weighted decision

The layers follow MSR method §8: mandatory gates, then measured metrics, then comparative scores (an ordering aid), then owner decisions, then qualification decisions. None is folded into another.

**Mandatory gates** (named SG1–SG7b so they cannot be confused with the register's G-section rows). SG2–SG6, SG7a and SG7b are technical/engineering gates and decide the technical ranking. SG1 is the **qualification** gate: it is recorded on the licence axis and never changes a candidate's rank.

| Gate | Rule |
|---|---|
| SG1 Licence qualification | applied after evaluation (§9.3 rule 2): the candidate is cleared for the declared MAVI non-commercial deployment profile named as a target, by the class rules of §9.3 rule 2. Under those rules an L-C grant that covers every use the profile makes can be cleared, and L-D waits until its open question is resolved. SG1 is evaluated per named target profile and passes exactly when the candidate's licence axis is `CLEARED` for that profile (MSR method §4). In S2c the target profiles are the Development deployment profiles, where the learned packs run; Production profiles are determined later, as addenda (MSR method §11), and never in S2c. A candidate failing SG1 stays in the record at its technical rank as the technical reference |
| SG2 Offline | loads from pack artefacts alone; no hub, index or network call; verified by a network-denied run |
| SG3 Determinism | repeated CPU runs with the pinned thread count give identical Track decisions and scores within 1e-6; where CUDA is measured, the CPU/CUDA Track-decision agreement tolerance is **declared in S2c.2** (qualification plan §10 requires one but declares none) and a variant outside it may not be bound |
| SG4 Runtime budget | p95 end-to-end per crop within the §14 budget on the pinned Development CPU host class (CPU-mandatory in S2c) |
| SG5 Baseline | decided **per attribute**: beats the deterministic baseline (B0) on the **primary metric** with the bootstrap interval excluding zero, and is not significantly worse on the co-primary; a candidate is eligible only for the attributes it passes, and an attribute with no passing candidate keeps B0 or is disabled; primary metrics are threshold-free and frozen in S2c.2: Track-level **AURC** (area under the risk–coverage curve) for every attribute, with Track-level macro-F1 at full coverage (colour) and average precision (presence) as co-primary; the baseline for each attribute is defined below the table; if no learned candidate beats a *packageable* baseline, that baseline is selectable, and the record says the learned capability did not beat it |
| SG6 Abstention sanity | on non-subject/error crops of the selection partition it produces Unknown/abstention at a higher rate than on valid crops (F6 direction), and no confident prediction on achromatic crops for colour types |
| SG7a System scale (projection, S2c.4) | the projected fleet at the 500-camera target, under the owner-declared workload model and host envelope (§14.1, U9), fits the envelope: worker count, hosts, memory, backlog drain after one host loss. The projection is computed from per-worker quantities measured in the bake-off. For person-attributes it is evaluated per **composition** (§9.5a), never per component. A candidate or composition needing an architectural change to fit fails SG7a until the change exists (MSR method §7.1) |
| SG7b System scale (validation, S2c.9) | the executed representative multi-worker load agrees with the SG7a projection within the tolerance frozen at S2c.2. If it fails, the selection is **re-opened** at S2c.4 with the measured quantities. With only one host available, host-loss drain is validated as the loss of one worker process, and cross-host behaviour is recorded as an unvalidated limitation, never as a pass |

**Metric tie semantics (all candidates and baselines; frozen at S2c.2).** AP and AURC are computed with **threshold-grouped ties**: all items with an equal score form one operating point, entered together.
- AP = Σ_k (R_k − R_{k−1}) · P_k over the distinct score thresholds k, in descending order, where P_k and R_k are the precision and recall after including group k.
- AURC = Σ_k (C_k − C_{k−1}) · risk_k, where C_k is the coverage and risk_k the error share after including group k.

The remaining terms have one frozen definition, identical for every candidate and baseline:
- **Coverage denominator:** every labelled Track of the evaluation partition for that attribute.
- **Score and ordering.** Tracks are ranked by the *aggregated* Track-level score, after pooling.
  - Presence types: the `present` score.
  - Colour types: the confidence of the predicted value.
- **Error.**
  - Presence: a covered Track counts as a claim of presence, and an error when the Track lacks the object. This is the false-discovery reading, which matches MAVI's Observed-or-Unknown semantics with no Absent.
  - Colour: a covered Track is an error when the predicted value is wrong.
- **Unscorable Tracks** (admissibility abstention, or fewer than `kMin` contributing crops) enter as one **final tie group**, after all scored groups. They count as errors for colour; for presence they count as errors only when the Track lacks the object. Every method therefore reaches full coverage, and abstaining can never lower AURC artificially. For PO-B0, which uses no images, the final group holds admissibility abstentions only; the `kMin` condition does not apply to it.
- **Colour macro-F1 at full coverage** (co-primary): an unscorable Track counts as a false negative for its true value and adds no false positive.

No random or index-order tie breaking is used anywhere, so results do not depend on implementation. Metric unit tests pin the closed forms (mutation S32).

**Baselines per attribute (frozen at S2c.2; SG5):**
- **Colour (PC-B0, VC-B0).** A deterministic region-chroma + CIE-Lab naming classifier. Its confidence is the share of region pixels in the winning colour cluster, and ties are broken by schema order. It is scored under exactly the same Track-level AURC and macro-F1 as a learned candidate. It is **packageable**, so `BASELINE_SELECTED` is possible.
- **Presence (PO-B0: backpack, bag, headwear).** A no-image **prevalence reference**:
  - It emits, for every admissible Track, the smoothed training-partition prevalence of that attribute for the Track's camera. Unseen cameras get the global training prevalence. Smoothing uses the global prior with a pseudo-count frozen at S2c.2.
  - Coverage is full. It abstains exactly where the shared admissibility policy abstains, and never otherwise.
  - Ties follow the **metric tie semantics** above, as for every candidate. Tracks with an equal prior form one tie group, including Tracks of different cameras that share a prior (for example unseen cameras on the global prior).
  - On a single tie group **with no unscorable Tracks**, its AP equals the group's prevalence π exactly, and its risk is 1 − π (risk being the share of covered Tracks without the object). When admissibility abstains, the abstained Tracks form the final group, and AP/AURC follow the general formula over both groups. For example: 8 scored Tracks with 4 positives, plus 2 abstained positives, give AP ≈ 0.533 and AURC = 0.48, not 0.6 and 0.4. The S32 fixtures cover both cases. With per-camera priors, its AP and AURC are those of the **camera-prior ordering**: groups in descending prior, each group one operating point. It thus captures camera-level prevalence differences a learned model must beat, not merely a global constant.
  - A learned presence candidate passes SG5 only if it beats PO-B0 on AURC (primary) and is not significantly worse on AP (co-primary), under §9.4's statistics.
  - PO-B0 is a **statistical floor only and is not packageable**: it uses no image evidence, so an Observed value from it would be meaningless. For presence attributes `BASELINE_SELECTED` is unavailable, and if no learned candidate beats PO-B0 the attribute is disabled.

**Weighted technical decision** (weights proposed here, reviewed and frozen in S2c.2 before results exist). Licence is deliberately **not** a weighted criterion: the weighted score ranks candidates technically, and SG1 then decides which of them can be qualified (§9.3); both rankings are reported:

| Group | Criterion | Weight |
|---|---|---|
| Operational quality (50) | Track-level primary metrics (AURC; macro-F1 / AP) on the selection partition | 20 |
| | worst of the difficult strata (low-res, partial, occlusion, low light) | 10 |
| | calibration and risk–coverage (ECE, AURC) | 10 |
| | leave-one-camera-out stability | 10 |
| Runtime and system scale (25) | CPU p95 per crop vs budget | 7 |
| | projected 500-camera fleet footprint (workers × memory × hosts, §14.1) | 7 |
| | peak memory with the detector co-resident | 4 |
| | CUDA viability | 3 |
| | model load / READY time | 2 |
| | batching efficiency | 2 |
| Engineering (12) | dependency burden / Runtime Pack impact | 5 |
| | implementation stability and maintenance status | 4 |
| | exportability and replaceability | 3 |
| Deployment (13) | offline self-containment and pack size | 5 |
| | training-data provenance disclosed | 4 |
| | packaging reproducibility | 4 |

The record keeps the pure task-quality view beside this ranking. The **highest task-quality evaluated candidate** (operational quality group only) is reported separately (MSR method §9). When it loses on runtime or scale, the delta says so.

The weighted score orders candidates that passed SG2–SG6 and SG7a. For person-attributes, the finalist gates apply per component; SG4 and SG7a apply per composition, and SG2, SG3, SG5 and SG6 are re-run on the unit (§9.5a); and an attribute counts as passing only if some admitted composition enables it. The score never compensates for a failed gate. The rule converting each measurement into a criterion score is frozen with the weights in S2c.2: rank-based within each criterion, with intervals that overlap scored as ties. Per-attribute criterion scores are averaged with equal attribute weight within a sub-task. A criterion that cannot be measured for every candidate (for example CUDA viability when no GPU host is available, U4) is dropped for all candidates, its weight is redistributed pro rata, and the record says so. "Training-data provenance disclosed" is a technical criterion: undisclosed sources make the frozen-test disjointness check (qualification plan §3.1) unverifiable. It is not a licence criterion. The record reports a sensitivity check (each group ±5 points, and each group removed). If the top candidate changes under it, the ranking is recorded as unstable and the choice among the tied candidates is an explicit owner decision. A quality difference inside the bootstrap interval is a tie. **A candidate that needs a Runtime Pack extension** (§12.7) must beat the best candidate on the existing graph by at least the MPID with the interval's lower bound above zero; otherwise the existing-graph candidate is selected. Conversely a candidate is never rejected for needing a reasonable extension when it clears that bar.

### 9.5a Person-attributes composition (MSR method §5.1)

`person-attributes` is one capability and one pack (ADR-014 §1) covering two sub-tasks. The event runs:
1. **Sub-task evaluation.** T-PC and T-PO are ranked separately, and each produces up to **K = 3** component finalists. A finalist passes SG2, SG3, SG5 and SG6 for at least one attribute of its sub-task; SG4 and SG7a are judged per composition. The packageable colour baseline PC-B0 may be a T-PC finalist. The non-packageable PO-B0 never enters a tuple.
2. **Composition candidates**, generated by the rule frozen at S2c.2:
   - the winner tuple (best T-PC finalist, best T-PO finalist);
   - every finalist pair that shares a backbone checkpoint (for example one tower with separate colour and presence heads). Each is evaluated as its own candidate, with heads trained on the shared features;
   - up to **three** further pairs from the finalist product (at most 3 × 3), ordered by the sum of sub-task ranks and taken only if not already listed.

   The set is therefore at most 1 + S + 3 compositions, where S (at most 9) is the number of shared-backbone finalist pairs. Each is an exact tuple of component identities, with an optional shared region component (for example segmentation, if C-SEG is ever triggered).
3. **Composition evaluation**, on the selection partition and the pinned host:
   - combined per-attribute quality;
   - CPU latency per crop and Track;
   - throughput;
   - RAM/VRAM with the detector co-resident;
   - load time;
   - pack size;
   - Runtime Pack impact;
   - whether a backbone is shared;
   - the 500-camera projection (§14.1);
   - the failure domain (one worker process holds all components; what a component fault takes down).

   **Each composition must pass SG2, SG3, SG4, SG6 and SG7a as a unit.** SG5 and SG6 are re-run on the composition's actual heads, because a shared-backbone pair uses retrained heads that are new components. The reason for gating the unit: two components that each fit can exceed the budget, memory or fleet envelope together. A failing composition is recorded with its reason. Attribute coverage is recorded too: an attribute whose composition heads fail the re-run SG5 is disabled in that composition.
4. **Pareto frontier** on three scalars: **quality**, the equal-weight mean over the **fixed full attribute set** of T-PC and T-PO of the primary-metric improvement over each attribute's baseline, with a disabled attribute scored as zero improvement; **per-crop cost** (CPU p95); and **peak memory**. The fixed set keeps dominance transitive, and the enabled attributes of each composition are recorded beside it. The §9.5 weighted score ranks within the frontier, and dominated compositions stay in the record.
5. **Implementation composition.** The owner's choice from the frontier. Every component must be cleared for the target profile.

The vehicle event is single-component and skips steps 2–4.

### 9.6 Model Selection Records

Each capability's decision is recorded in its event under `docs/qualification/model-selection/<capabilityId>/`, following MSR method v1.
- **Protocol.** `<event>-protocol.md` is frozen at S2c.2 with its hash in the record.
- **Record.** `<event>.md` holds:
  - a candidate ledger retaining every candidate, with its exact checkpoint identity, role, technical disposition and per-profile licence status;
  - reported evidence (class R, snapshotted) kept apart from MAVI measurements (M-D, M-E);
  - gates, the technical ranking with its sensitivity check, and the separate licence qualification;
  - the decision outputs (MSR method §9):
    - baseline;
    - incumbent ("none" in S2c);
    - strongest reported/reference candidate;
    - highest task-quality evaluated candidate;
    - strongest evaluated technical candidate;
    - strongest candidate cleared for each target profile;
    - implementation candidate or composition;
    - deltas between these;
    - alternatives and the composition frontier;
    - rejected, deferred and reference-only candidates, with reasons;
    - projected system-scale footprint;
    - owner decisions;
    - risks;
    - resulting identities.
- **Addenda.** `<event>-addenda.md` receives later qualification outcomes, errata and supersession.
- **Raw results.** Per-Track predictions, reports and training manifests stay in the qualification evidence store, referenced by SHA-256.
- **Closure.** A closed record is immutable. Its LF-normalised SHA-256 goes into the MSR index and addenda header. The capability's qualification record cites it under the `<capabilityId>-model-selection` gate (§12.6). `verify_repo` re-derives the record, index and protocol hashes (§12.9).

The wording is conditional (MSR method §9):
- If the implementation candidate **is** the strongest candidate cleared for the target profile, the record says *"selected as the strongest candidate cleared for the declared MAVI deployment profile `<profile id>` within MAVI's defined S2c operating envelope, based on retained bake-off evidence"*.
- Otherwise, the record names the strongest evaluated technical candidate, the strongest cleared candidate and the implementation candidate, and states why they differ, the measured quality/resource delta, and the owner decision and date.

No candidate is called "best", and none of this wording means the Model Pack qualification record has passed. The planning change creates both records in state `PLANNED`, with every candidate `DISCOVERED` and no selection.

### 9.7 Minimal training path

Only where a probe/fine-tune candidate is shortlisted: a pinned, seeded script in `tools/qualification/attributes/` that reads the training partition by manifest, writes the head/calibration artefacts with SHA-256s and a training manifest (inputs, seed, environment lock, code revision). Because the corpus is private CCTV, CI cannot rebuild these artefacts; reproducibility is proven by re-running the recorded manifest on the owner-controlled machine and matching the artefact hash (or, where CPU kernels are not bit-stable, the recorded tolerance on decisions). No general training platform, experiment tracker or hyper-parameter service is introduced.

## 10. Qualification strategy

### 10.1 Protocol

The Stage-2 qualification plan governs, with protocol revisions R1 (freeze order, §19 there) and R2 (model selection records and the four-partition amendment of §3.1, §20 there). S2c executes R1 steps 1–2; S5 executes steps 3–4.

### 10.2 Corpus

| Aspect | Rule |
|---|---|
| Source | owner-supplied recorded video representative of MAVI deployment (multiple cameras/scenes, day and night), processed through the **real** MAVI VisionJob so crops are the operational Evidence Sets (fallback Representatives, byte-cap re-encoding included) |
| Storage | outside Git (AGENTS.md: no CCTV in Git); access-controlled evidence store; retention recorded; no cloud labelling service |
| Manifests (in Git) | corpus manifest (video ids, camera ids, ProcessingRun ids, crop SHA-256s, strata tags — no imagery) and partition manifest, each content-hashed |
| Partitions | **training / tuning / selection / frozen test**, grouped by **site and date** (all cameras of one site on one day fall in one partition, so a person seen by several cameras at once cannot fall in two partitions); dates are assigned in **contiguous blocks**, not interleaved; the frozen test contains whole held-out sites or cameras plus held-out date blocks of seen ones |
| Recurring subjects | site/date grouping does not stop the same regular person or vehicle from recurring on different dates. S2c.1 therefore runs a **cross-partition recurrence audit** before sealing. An evaluation-environment-only appearance-similarity pass, never shipped and never a bake-off candidate's family, proposes cross-partition pairs, and annotators confirm or reject each one. A confirmed recurring subject is moved wholly into one partition, preferring training. The frozen test prefers whole held-out sites, where recurrence is least likely. The audit's recall is sampled, and residual recurrence is a recorded limitation beside the held-camera results. No identity is stored: the audit records crop-SHA pairs only |
| Raw-evidence pin | the corpus manifest records the vision pipeline profile SHA and Evidence Set selector version that produced every crop; a change to either (S1.4 is still open: B1–B6) invalidates crop-level labels under qualification-plan §16 — slice S2c.1 stops and re-derives the affected crops rather than mixing versions |
| Camera and site count | every partition needs at least three cameras, and the frozen test at least one camera unseen elsewhere, as a floor. **Sufficiency for inferential claims is determined, not assumed.** S2c.2 runs the calibration simulation of MSR method §8.1 on the pilot's cluster structure, and freezes the minimum number of top-level clusters (sites, or camera blocks) at which the hierarchical bootstrap keeps its nominal coverage, overall and per stratum. S2c.2 freezes the method and the perturbation model. The simulation tool is built in S2c.3, and the resulting minimum is computed and hash-appended to the protocol, as a pre-registered output, before S2c.4 reads any selection data. Below it, comparison and generalisation claims are downgraded (§9.4). The achieved count is a recorded limitation, never waived silently |
| Size | derived, not guessed. **Precision** is estimated over *predicted* positives at the operating point, so each exposed value needs `n_pred ≈ z²·p(1−p)/e²` Observed decisions (e.g. p = 0.9, e = 0.05 → ≈ 139 at 95 %). With abstention and Unknown, this means labelled positives ≈ `n_pred · p / (recall_op · coverage)`, where `recall_op` and `coverage` are the pilot's estimates at the provisional operating point, re-estimated on the tuning partition. **Recall** has its own requirement, `n_pos ≈ z²·r(1−r)/e²` ground-truth positives. The larger of the two decides. Both counts are then **multiplied by the design effect** `DEFF = 1 + (m̄ − 1)·ρ`: `m̄` is the size-weighted mean Tracks per camera block (`Σm²/Σm`), and `ρ` the intra-cluster correlation estimated on the pilot, or a declared conservative value where the pilot cannot estimate it. The pilot supplies prevalence per value, from which the number of Tracks to label per partition follows. Values that cannot reach it are reported as insufficient evidence (qualification plan §5) |
| Public data | PA-100K may enter the training partition if the licence review clears it; never the frozen test (qualification plan §3.1); research-only datasets are not used |
| Contamination | frozen test is MAVI-sourced, so disjoint from third-party training data by construction; near-duplicate check (perceptual hash) across partitions |
| Coverage | the strata of §8.2 and qualification plan §3.3; gaps are limitations |
| Sealing | R1 step 1: manifest hash committed, content withheld from the evaluation environment, access logged |

### 10.3 Labels

Annotation guide per attribute (allowed values with reference swatches, Unknown/Unlabelable criteria, partial visibility, patterns, bag/headwear boundaries, vehicle dominant-colour rule, minimum visual evidence). **Pilot:** a small double-labelled pilot, drawn **only from the training partition** (its results drive vocabulary merges, so none of it may enter tuning, selection or the frozen test), measures agreement per value pair and fixes merges before the schema is frozen. **Main labelling:** crop-level and Track-level ground truth, blind to model output; a representative double-labelled subset with at least one annotator independent of model selection; agreement by Cohen's κ (two annotators) or Krippendorff's α (more, nominal); adjudication recorded. Model- or VLM-proposed labels, if used to speed labelling, are recorded as proposals with the proposer's model family, are never accepted without a human decision, are not used on the double-labelled subset, and are never produced by a model of the same family as a bake-off candidate (it would bias ground truth toward that candidate). "Family" means shared backbone checkpoint lineage: a generative VLM whose image encoder descends from a candidate's backbone (for example a SigLIP-derived encoder while SigLIP 2 is a candidate) counts as the same family.

### 10.4 Metrics

| Attribute kind | Metrics |
|---|---|
| Colour (categorical) | per-value precision/recall/F1; macro-F1 over values meeting support; balanced accuracy; confusion matrix; coverage and Unknown rate; per stratum; per camera; leave-one-camera-out |
| Presence | positive precision/recall; FPR/FNR; Unknown rate; PR curve; no negative metrics (no Absent) |
| Both | risk–coverage curve and AURC; expected calibration error and reliability diagram; crop vs Representative-only vs Evidence-Set Track level (primary: Track level); values under support are "insufficient evidence", never merged into a passing macro score |

### 10.5 Thresholds and gates — how numbers are established

No percentage is set in this plan. The procedure:

1. S2c reports, per attribute and value, the **precision–coverage frontier** of the selected candidate on the tuning partition (and confirms it on the selection partition) with bootstrap intervals, plus the support measured per value. The frontier is threshold-free, so model selection (§9.5) never needs the owner's targets.
2. The owner declares, per exposed attribute, a **target precision** (an operational policy decision, recorded with its rationale) and the minimum support; the operating point `τ` is the lowest threshold whose **lower** 95 % bound meets the target, maximising coverage; δ and `kMin` are chosen the same way. This *method* is frozen in S2c.2; only its outputs are produced later.
3. Those values are frozen (R1 step 3) before S5 scores the frozen test.

Gate classes kept separate: **functional** (tests, contracts, mutations — S2c), **model quality** (frozen-test gates — S5), **performance** (derived budgets, §14 — S2c measures, S5 re-confirms on the frozen identity), **packaging/reproducibility** (pack id re-derivation, rebuild, offline install — S2c), **Production promotion** (out of Stage-2 S2c; ADR-009).

## 11. CPU, CUDA, Development, Production

| | S2c proves | S2c does not claim |
|---|---|---|
| CPU Development | the learned role runs on every deployable CPU variant (`linux-x86_64-cpu`, `windows-x86_64-cpu`) from an unpacked environment and from an installed Runtime Pack; provenance `actualDevice=cpu`; performance at the bound (§14) | CPU *qualification* PASS (F8 — S5 on the frozen identity) |
| CUDA Development | if the Development GPU host is available: the role runs with `device_policy=cuda` on `windows-x86_64-cuda` (Development-qualified variant; its release lock is still pending), records ADR-009 Development evidence, measures co-residency with the detector on the 4 GiB GPU, and checks CPU/CUDA decision equivalence | CUDA qualification; any `verified` status; Production |
| Linux CUDA | nothing (variant `pending-hardware-qualification`, ADR-014 §4a) | — |
| Production | the learned role **refuses** to start (manifest `unverified`, record `pending`), proven by test | any Production use |
| Fallback | none: `cuda` fails clearly when unavailable; `auto` is Development-only and records its resolution; a binding that requires CUDA never runs on CPU | — |

Model identity is unchanged across variants (ADR-013 §11); runtime pack id/source, variant and actual device remain provenance.

## 12. Model Pack, Runtime Pack and contract changes

### 12.1 Capability adapter (ADR-013 item 8)

- **Decode once, in the worker.** The worker verifies the crop (S2b), decodes it once under a pixel bound (≤ 1024 × 1024 × 3, the Evidence Set maximum), and raises S2b's `CropDecodeError` there; admissibility then runs on the decoded image; the adapter receives decoded pixels, never bytes. Preprocessing (resize/pad/normalise, region bands) is the adapter's, from its pack artefact.
- **Registry.** `inferencer_for` is replaced by an adapter registry keyed by `adapterId` — a closed set in code, like `IMPLEMENTED_CAPABILITIES`. The supervisor passes each capability's already resolved and hash-checked artefact paths (`resolve_role`) to its adapter.
- **Contract.** `load(artifacts, device) → loaded`; `score_batch(images, attributes) → [{scores: {type: {value: score ∈ [0,1]}}, abstained: {type: "model_not_applicable"}}]`. `abstained` is empty unless the model has an explicit applicability or visibility output, which the pack's output mapping declares. Each requested type appears in exactly one map. The runner groups a Track's admissible crops by type, calls the adapter for the Track's capability in bounded batches (§14), and validates every output before aggregation: shape, finite, [0,1], exact type coverage, and only the registered adapter reason.
- **Fixture unchanged.** A manifest without an attribute `capabilitySpecific` section, bound by a Development-only profile whose parameters carry `fixtureSeed`, keeps selecting the S2b fixture exactly as today (its pack identity does not change). A learned pack must carry the section.
- **Generic before specific.** Adapters are data-driven where possible (for example one `torch-classifier-v1` adapter parameterised by a declared architecture from a closed set, preprocessing JSON and output mapping), so a replacement model that fits an existing adapter changes only the Model Pack, binding and qualification record (parent plan §7). A model family that fits no existing adapter needs new worker code (and possibly a Runtime Pack) — reviewed as a code change, never smuggled in as data.

### 12.2 Model Pack contents (manifest v2 common schema unchanged)

| Element | Content |
|---|---|
| `modelId`/`modelVersion` | MAVI-assigned after the bake-off (e.g. `person-attributes-<family>-v1`) |
| `capabilityIds` | `person-attributes` and/or `vehicle-attributes` |
| Artefacts (kebab-case roles, `KEBAB_ID_RE`) | `checkpoint` or `checkpoint-<component>`; MAVI-trained `head` / `head-<component>` and `calibration`; `preprocessing` (JSON); `output-mapping` (JSON: model outputs → schema values; outputs outside the schema — e.g. gender or age heads of a third-party model — are listed as discarded); `component-provenance` (JSON: per component publisher, a non-locator repository identifier such as `owner/name`, immutable revision, licence, notice file hash; MAVI training-manifest hash; acquisition URLs live only in the pack-build workflow, so tracked provenance passes the `verify_repo` network-hazard scan); `licence-notice` — **one** MAVI-assembled notice file containing every component's licence text byte-exactly under a header per component (the single reserved role of `model_manifest_v2.py`) |
| `licence.spdxId` | an SPDX expression covering every component (e.g. `Apache-2.0 AND MIT`); the field is free text today; `LicenseRef-…` for non-SPDX terms |
| `provenance` | the MAVI assembly (publisher MAVI, this repository, the assembling commit); third-party provenance lives in `component-provenance` |
| `inputContract` | `evidence-crop-jpeg` / `RGB` (already registered) |
| `outputContract.schemaId` | `attribute-scores-v2` |
| `capabilitySpecific.person-attributes` / `.vehicle-attributes` | **newly registered sections** (the registry has only `detector` and `embedding`): `adapterId`, `architecture` (for generic adapters), artefact roles of `preprocessing`/`output-mapping`/`component-provenance`, `attributeSchema {id, version, sha256}`, `artifactByteLimits {role: bytes}` checked by the resolver before load |
| `verificationStatus` / `qualificationId` | `unverified` / `null` throughout S2c |

One capability binds exactly one pack (ADR-014 §1), so a pack may compose several components; replacing one is a new pack.

### 12.3 Artefact v2 (ADR-013 item 9)

- Observation `status` stays `scored` (verified and decoded) or `unavailable` (S2b reasons). A scored observation keeps S2b's `scores` map, now holding only the types actually scored, plus an `abstained` map `{type: reason}` for the rest; together they cover every applicable type exactly once. For each type, the v2 bound takes the larger of the scored entry and the abstained entry with the longest registered reason (for a one-value presence type, `representative_qualification_unknown` is one byte longer than a scored entry), plus one empty-map constant per observation. It is recomputed in the bound vector and stays below 90 % of 64 MiB (§12.3 bound).
- Track rule: `analysed` iff ≥ 1 observation is scored, even if every type abstained; exact coverage of leased crops unchanged; decisions equal rows; a supporting Observation must have `scores` for that type; scores finite **and in [0,1]** (new in both languages: today the worker range-checks only the aggregated confidence and per-crop scores only for finiteness; §12.1 output validation adds the per-crop check).
- **Bound:** the §7.1 candidate vocabulary measures 59,654,096 B under the S2b formula (88.9 % of 64 MiB); the vocabulary frozen by the pilot must keep the v2 worst case under the cap, with both loaders refusing otherwise.

### 12.4 Pipeline profile v2 and identity v2 (ADR-013 item 9)

The artefact version must be part of identity, and the platform must know it for every unit it may still complete (claims are fenced on the *worker's* fingerprint, so a unit of a non-preferred identity can still be leased and completed). Therefore:

- pipeline profile schema `mavi-visual-attribute-pipeline-v2` adds `predictionsSchemaVersion` and an `admissibility {method, version}` pair (the method's code is versioned; its parameters live in the parameters file);
- canonical identity `mavi-visual-attribute-identity-v2` includes both; v1 and v2 identities cannot collide (the schema version is inside the canonical bytes); new cross-language identity vector;
- the platform persists `predictions_schema_version` on the identity-activation row (migration; existing rows `v1`) and validates each unit's artefact against the version of **that unit's identity**, requiring the artefact header to match;
- units of the fixture identity still Queued or Running when the learned identity becomes preferred keep their own identity: they complete (v1) or fail as history and become Stale; nothing is converted.

### 12.5 Aggregation policy v2 (both loaders)

The .NET release parser accepts only `mean-score-argmax` with fixed keys, so aggregation v2 is a document schema both languages parse: `mavi-visual-attribute-aggregation-v2` with `method: calibrated-mean-margin-v1`, per-type `kMin`, `margin` (δ), `thresholds {value: τ}`, `floor` (categorical types only; refused on presence types) and `representativePolicy` (§8.2). Python executes it; .NET validates it structurally (types, values, ranges, coverage of the schema) and never recomputes decisions; a shared release-parse vector holds both to the same acceptance.

### 12.6 Qualification records and gate sets

- **Records.** One record per capability (`models/qualifications/<pack>-<capability>.json`), every variant `pending`, `overallResult: pending`, policies pinning the pipeline profile id/SHA.
- **Gate sets.** New capability gate sets `person-attributes-v1` and `vehicle-attributes-v1` in `config/acceptance/capability-gate-sets-v1.json` name the §10.5 gate families plus `person-attributes-model-selection` / `vehicle-attributes-model-selection`.
  - Gate names are unique across *all* gate sets (`qualification_v2.py` refuses `gate_name_duplicate`), so every capability gate is prefixed with its capability id.
  - The selection gate is capability-scoped rather than in `common-v1`, so the detector record is unaffected. A detector replacement adds its own gate in a new detector gate-set version.
  - This is a gate-set configuration change; the qualification-record schema is unchanged.
- **Selection gate.** Its evidence is the closed MSR (`{kind: "model-selection-record", reference: <path>, sha256: <LF-normalised SHA-256>}`).
  - It may become `passed` at S2c.10 only on variants that have a Runtime Pack. The class-A variant `linux-x86_64-cuda` has `runtimePackId: null`, and the parser refuses any passed gate there, so its gate stays `pending`.
  - Every other gate stays `pending` in S2c, so no variant or record reaches `passed`.
- **Licence determination.** It is recorded as `licence`-gate evidence per profile (§9.3 rule 4), not as a separate gate.

### 12.7 Runtime Pack decision

- **Default:** the adapter runs on `mmdetection-phase1-v1` (torch 2.6.0, torchvision 0.21.0, OpenCV, Pillow, NumPy). An OpenVINO-IR or ONNX candidate is ported to a first-party torch module with a build-time parity test; SigLIP 2 / DINOv2 / DINOv3 towers are reimplemented or loaded as state dicts into first-party code; `torch.load(weights_only=True)` only.
- **Extension (only past the §9.5 MPID bar):** a separate family `attributes-<engine>-v1` for the attributes role, with its own locks per variant, `runtime.json`, offline wheels, licence inventory, CI build and ADR-009 status per variant (CUDA starts `pending-hardware-qualification`). The vision family's lock is never widened for an attribute model (ADR-013 item 10).

### 12.8 Release overlay: the shipped binding stays unchanged in S2c

`verify_repo` fails any tracked manifest or record no binding uses and allows exactly one tracked binding; binding real packs in that binding would make every kit and CI build depend on MAVI-trained artefacts CI cannot rebuild, and would change the vision role's `componentBindingSha256` for every VisionJob. S2c therefore:

- keeps `src/vision/config/components/phase1-bindings-v2.json` **unchanged**;
- adds one tracked **Development overlay binding** (`src/vision/config/components/development-attributes-v2.json`: the shipped roles plus the `attributes` role and its bindings) and the real pipeline profile under `src/vision/config/attributes/`; `verify_repo` learns an explicit overlay class — every tracked binding is either the release binding or a declared Development overlay, and an overlay may add roles but may not change the release binding's roles, packs or families (an ADR-014 note records this);
- merges each attribute manifest and record **in the same change as the overlay entry that binds it**, so the "no unbound manifest" rule keeps holding;
- the vision worker keeps using the release binding (its provenance is unchanged); the attributes worker and the platform's `VisualAttributes:*` paths use the overlay in Development only;
- **Production is fenced in code, not only by Setup:** every S2c learned pipeline profile carries `developmentOnly: true`, so the platform refuses it outside Development/Testing (`VisualAttributeReleaseStartup`) and the resolver refuses it in Production. A Production platform pointed at the overlay therefore fails at startup instead of activating a learned identity and staling existing analyses. Dropping the flag is part of the post-S5 promotion (U5), not S2c. Negative tests: a Production-mode platform and worker each refuse the learned profile (mutation S26);
- **how an overlay is declared:** `verify_repo` owns an explicit list of overlay binding paths (initially only `development-attributes-v2.json`), and the file name must start with `development-`. Any other tracked binding beyond the release binding fails `binding_multiple_not_supported` as today. Negative fixtures: an undeclared second binding, a declared overlay without the prefix, and an overlay that changes a release role (S24);
- Setup/sync plan the `attributes` role only for a Development deployment profile; Production Setup neither plans, installs nor starts it, and a Production kit never contains the unverified packs;
- owner-built artefacts (MAVI-trained heads) enter a Development kit through a documented assembly step that verifies each by the hash in the source manifest;
- the CI E2E keeps the fixture overlay (no private artefacts in CI).

### 12.9 Complete list of contract and code changes (nothing else changes)

| Change | Where | Governed by |
|---|---|---|
| Capability adapter registry; worker-side single decode | `attributes/inference.py`, `supervisor.py`, `runner.py` | ADR-013 item 8 |
| Runner batching per Track and type; output validation; timeout; OOM/exit sequence | `runner.py`, `main.py`, `settings.py` | §14, §17 |
| Artefact v2 (both languages) and bound v2 | `predictions.py`, `AttributePredictionsValidator.cs`, `VisualAttributeRelease.cs`, vectors | ADR-013 item 9 |
| Pipeline profile v2, identity v2, activation migration | `pipeline.py`, `VisualAttributeRelease.cs`, EF migration, vectors | ADR-013 item 9 |
| Aggregation v2 document (both loaders) | `pipeline.py`, `predictions.py`, `VisualAttributeRelease.cs`, vector | §12.5 |
| Admissibility method + abstention vocabulary | `attributes/admissibility.py`, `contracts.py`, `VisualAttributeContractRules.cs` | ADR-013 item 9 |
| Registered attribute manifest sections; resolver byte limits | `model_manifest_v2.py`, `resolver.py` | ADR-014 §3 (registry extension) |
| Attribute gate sets (including `<capabilityId>-model-selection`) | `capability-gate-sets-v1.json` | ADR-014 §6 |
| MSR integrity: re-derive the LF-normalised SHA-256 of every record cited as `model-selection-record` evidence, of every `CLOSED` record listed in the MSR index (including events that produced no pack), and of every protocol whose hash a record cites; refuse a mismatch or a missing file | `verify_repo.py` | ADR-014 MSR note; MSR method §10 |
| Development overlay binding class; attribute profile loader | `verify_repo.py`, `binding.py` | ADR-014 note (§12.8) |
| Attributes device policy (`cpu`/`cuda`/Development `auto`) | `supervisor.py`, `settings.py` | ADR-013 §8 (item 10) |
| Setup/sync per deployment profile role set | `Mavi.VisionSetup.psm1`, sync tool | §15 |
| Generalised Model Pack workflow | `.github/workflows/` | §15 |
| Deterministic baseline (B0) adapter, so B0 can be bound and compared end to end | `attributes/adapters/` | §9.5 SG5 |
| Lease crop geometry | **not changed** unless U6 decides it with evidence | U6 |

## 13. Cross-language contract

| Item | Where pinned | Rule |
|---|---|---|
| Attribute schema | `pipeline.py`, `VisualAttributeRelease.cs` | format unchanged; real vocabulary; new vector case |
| Pipeline profile v2 + identity v2 | both | new vector `visual-attribute-identity-v2.json` (real-shaped pack ids, both artefact versions); v1 vector retained |
| Aggregation v2 document | both parse; Python executes | release-parse vector (accepted/refused documents); decision golden vectors consumed by Python only |
| Artefact v2 | Python encoder, .NET streaming validator | `visual-attribute-predictions-v2.json` (scored, partly abstained, all-abstained Analysed, abstained-type-as-supporting refused, out-of-range refused, coverage failures) |
| Worst-case bound v2 | both | `visual-attribute-artifact-bound-v2.json` with accepted/refused pair |
| Abstention vocabulary | `contracts.py`, `VisualAttributeContractRules.cs` | closed set; constant-parity test |
| Confidence | both | finite, [0,1]; Unknown carries none |
| Provenance | both | fields unchanged; `actualDevice` `cuda:N` exercised |

Decisions are computed once, in Python; the platform refuses the same *inputs* the worker refuses, each held to a shared vector.

## 14. Performance

**Derived budget.** At the 10,000-Track × 4-crop bound (40,000 crops) the deadline D (default 6 h) runs from first claim, so a retry must fit after a late failure. Per-attempt budget = (D − T_restart − T_load − T_lease) / 2, where T_restart is the launcher's restart delay (§17), T_load the measured model-load/READY time and T_lease one lease duration (reclaim delay). With placeholder values of 60 s, 120 s and 120 s this is ≈ 10,650 s, i.e. **≈ 0.266 s per crop end to end** (evidence read + verify + decode + admissibility + inference + aggregation). S2c.2 pins the **Development CPU host class** (CPU model, cores, RAM, OS) and the inference thread count (leaving one core for the event loop so heartbeats keep their schedule), and recomputes the figure with measured values. **SG4 is CPU-mandatory in S2c**: no release profile binds the attributes role to CUDA in S2c, so a candidate cannot pass SG4 on CUDA alone. Raising D is a lifecycle configuration change with its own justification, never a way to hide model slowness.

| Measure | How | Where |
|---|---|---|
| READY / model-load time, RSS after load | supervisor timings | S2c.7 |
| Per-crop and per-Track inference p50/p95/p99 by batch size | worker instrumentation, inference separated from evidence read and upload | bake-off and S2c.9 |
| Evidence read per crop | client timings | S2c.9 |
| Heartbeat latency under full inference load | heartbeat timestamps vs schedule | S2c.9 |
| Peak RSS; VRAM on CUDA; detector co-resident on one host | process sampling | S2c.9 |
| 10,000-Track run (synthetic Evidence Sets with real crop sizes) | scale harness driving the real worker | S2c.9 |
| Artefact size at the bound (v2) | measured vs derived bound | S2c.5 / S2c.9 |
| Completion/publication time | S2b measurement repeated with a real identity | S2c.9 |

### 14.1 System scale: up to 500 cameras (owner constraint B)

The per-run budget above protects one ProcessingRun. Scale is the aggregate question: how many attribute workers and hosts 500 cameras need, and whether a candidate makes that fleet unreasonable. No new architecture is assumed. Horizontal scaling uses the existing lease plane: S2b claims `FOR UPDATE SKIP LOCKED` per worker id, so several attribute workers on one or many hosts drain the same queue, and each worker keeps one unit per process (ADR-013 §8).

**Frozen at S2c.2** (MSR method §7.1):
- the owner-declared **workload model** (U9): Tracks per camera per minute as a distribution over representative camera loads (quiet, typical, busy), crops per Track from the real Evidence Set distribution, and the share of person vs vehicle Tracks;
- the **host envelope**: host classes, the maximum host count, and memory per host;
- the projection script.

**Measured per candidate or composition (M-E):**
- per-crop service time distribution, end to end;
- crops/Track;
- per-worker throughput;
- peak RSS/VRAM with the detector co-resident;
- workers per host before memory or CPU saturation;
- model-load/READY time;
- recovery time after a worker loss (restart plus reclaim, §17);
- Model Pack size and evidence/artefact storage growth per Track.

**Projected at 500 cameras (M-E projected):**
- required workers and hosts;
- steady-state queue depth;
- latency under sustained load (queueing on the measured service-time distribution);
- backlog drain time after a peak and after one host loss;
- aggregate memory;
- storage growth per day;
- offline deployment footprint (pack bytes × hosts).

These feed SG7a (and SG7b at S2c.9) and the weighted "projected 500-camera fleet footprint" criterion.

**Validation of the extrapolation (S2c.9):** an accelerated or synthetic load of N ≥ 2 concurrent workers, on two hosts where available, drives the real lease plane at the rate the workload model gives for a declared fraction of 500 cameras. Measured throughput, queue depth and drain time are compared with the projection, within a tolerance frozen at S2c.2 (gate SG7b; a failure re-opens S2c.4).

**Limitation stated honestly:** S2c does not execute a physical 500-camera deployment and claims no 500-camera qualification. It retains a reproducible projection and the load actually executed. Anything the projection shows to need architectural change (for example a platform-side lease or evidence-read bottleneck) is recorded as a finding for an ADR, not absorbed into S2c.

**Batches** are bounded by count and decoded bytes: the count cap `B` and byte cap are fixed in S2c.2 from measured peak memory at the Development host (so that detector + attributes role fit together), never raised at run time. The serial inference lane stays; one unit per process.

## 15. Offline deployment

| Item | Rule |
|---|---|
| Weights in Git | never (`verify_repo` refuses weight extensions; 10 MiB cap) |
| Acquisition | a generalised Model Pack workflow (the RTMDet workflow is hard-wired today) fetches third-party checkpoints on a connected CI runner from **pinned immutable URLs/revisions**, verifies SHA-256 against the source manifest, extracts licence texts byte-exactly into the assembled notice, and runs `build_model_pack.py` |
| MAVI-trained artefacts | built on the owner-controlled machine from a recorded training manifest (§9.7); only hashes in Git; they enter a Development kit by hash (§12.8) |
| Kit | content-addressed `vision/models/<modelPackId>/`; `component-inventory.json`; Development kits only for attribute packs in S2c |
| Setup | Setup/sync plan roles from the deployment profile's role set; Development plans `attributes`, Production does not |
| Runtime policy | `offline-dependency-policy-v1.json`: an entry per attribute pack (source, licence, notice, hashes, owner); `offline-binary-inventory.md`: Model Pack rows; any new runtime Python package: `managedSources.python`, wheelhouse, lock, and (§12.7) a separate family |
| Tooling policy | the evaluation environment (`tools/qualification/attributes/`: e.g. `open_clip`, `transformers`, `onnxruntime`, `openvino`) and any build-time conversion toolchain are new dependencies: each gets a policy entry (non-runtime scope), an exact-hash lock and a licence record in S2c.3 / S2c.6, per CLAUDE.md |
| No hidden download | torch 2.6.0 ships `torch.hub` and `load_state_dict_from_url`, and `requests`/`httpx` are on the lock, so absence of the library is impossible; instead: a static ban (`torch.hub`, torchvision `weights=` arguments, `load_state_dict_from_url`, `from_pretrained`, `hf_hub_download`) enforced by a test over the adapter modules; a socket-deny unit test around adapter load and inference; and the network-denied learned E2E (§18) |
| Evaluation environment | runs network-denied too once checkpoints are cached, because it processes private CCTV crops |
| Verification | `verify_repo` re-derives pack ids, checks the notice artefact and component provenance, attribute profiles and the overlay binding; the installer verifies hashes before use |

## 16. Security and trust boundary

S2b's boundary is unchanged: no filesystem access to accepted evidence, lease-scoped and lifetime-fenced reads, cross-run IDOR refused, capability never logged. S2c adds:

- **Artefact integrity before deserialisation.** Every artefact is hash-checked by the resolver before load (ADR-005 §6); state dicts load with `weights_only=True`; TorchScript/pickled full models are not accepted; converted OpenVINO models are shipped as first-party torch modules plus state dict.
- **Bounded loads.** `artifactByteLimits` in the attribute manifest section, checked by the resolver before any load; JSON artefacts (preprocessing, mapping, component provenance) parsed with the strict release-JSON reader and schema-validated; decoded crops bounded by the Evidence Set pixel maximum.
- **Decompression.** Packs are directories, not archives; kit archive handling is the existing verified path.
- **Output validation.** Adapter outputs are checked for shape, finiteness and range before aggregation; a violation is terminal `output_invalid` for the attempt (S2b).
- **Provenance truthfulness.** The worker reports only resolved identities; `verified` from an unpacked environment is refused by the platform (S2b); the identity fence prevents a worker with other packs from claiming units.
- **Untrusted metadata.** Mapping and preprocessing are data, validated; no code path executes pack-supplied code.
- **Remote GPU node.** Unchanged contract; the role needs only the platform URL, its packs and its runtime.
- **Privacy.** Corpus crops are personal data; §10.2 storage rules; no face-oriented feature; the adapter discards any demographic output a model emits.

## 17. Failure behaviour

| Failure | Behaviour | Class |
|---|---|---|
| Model Pack missing / artefact missing | role UNAVAILABLE at start; never leases; units stay Queued without consuming attempts (D6) | operator-visible capability failure |
| Pack corrupt / hash mismatch | same (`model_artifact_hash_mismatch`) | operator-visible |
| Runtime Pack missing / lock mismatch | same (S2a resolver) | operator-visible |
| Incompatible model/runtime pair | same (`runtimeCompatibility`) | operator-visible |
| Unknown `adapterId` / section | same | operator-visible |
| Model load failure / OOM at load | UNAVAILABLE; reason recorded | operator-visible |
| CUDA unavailable with `cuda` policy | UNAVAILABLE (today's code refuses `cuda` outright with `attribute_device_unsupported:cuda`; S2c keeps a refusal code for a variant the pack does not support and adds `attribute_device_unavailable:cuda` for CUDA that is supported but absent); no CPU fallback | operator-visible |
| `auto` in Development | resolves visibly; provenance records the device | — |
| Inference exception | attempt fails retryable `visual_attribute_inference_failed`; no Track outcome | retryable attempt failure |
| OOM during inference (`MemoryError`, `torch.cuda.OutOfMemoryError` — caught explicitly, not by the generic handler that today reports `inference_failed` and keeps leasing) | fixed sequence: stop the heartbeat → `/fail` `visual_attribute_inference_failed` (retryable) bounded by the request timeout → `os._exit(75)` (a hard exit: `runner.close()` joins executor threads, so a normal exit can hang). The role's launcher restarts it with exponential backoff (T_restart in §14); the fresh process must reach READY, whose start-up includes a one-batch memory probe. A kernel OOM-kill (SIGKILL) gives no `/fail`: the lease expires and S2b reclaims. A deterministic OOM consumes the unit's attempts and fails it — operator-visible, by design | retryable + operator-visible |
| Inference timeout (per batch, `inference_timeout_seconds` in worker settings — not identity — fixed in S2c.2 from the measured p99 batch time × a declared margin, and below the lease duration) | same sequence with `os._exit(76)`: a hung native call cannot be cancelled, and `run_once` would otherwise wait on the in-flight future forever | retryable |
| Worker crash | lease expires; reclaim; attempts bound (S2b) | retryable |
| Capability unavailable mid-lease (device lost) | as inference exception/timeout | retryable |
| Malformed output, NaN/Inf, out-of-range | terminal `visual_attribute_output_invalid` — deliberately: a deterministic model defect must surface rather than be hidden as abstention, even though one pathological crop fails a whole unit; the bake-off and regression corpus must show a zero rate, and the trade-off is recorded | terminal unit failure |
| Preprocessing failure on a decodable crop | terminal `output_invalid` (adapter defect), distinct from decode failure | terminal |
| Undecodable crop | observation Unavailable `evidence_decode_failed` (S2b) | Track Unavailable if all crops |
| Unsupported / inadmissible crop | abstained with reason | attribute Unknown |
| Deadline / attempts exhausted | S2b platform transitions | terminal |

`visual_attribute_capability_unavailable` (defined in S2b, never emitted) is used for the mid-lease device-loss case if it can be distinguished from an exception; otherwise it stays unused and is documented.

## 18. Testing programme (written before the code of each slice)

- **Unit (Python):** preprocessing per adapter (golden images → tensors); output parsing and mapping (discarded outputs never leak); calibration application; admissibility (size, achromatic, per-type); aggregation v2 golden vectors (τ, δ, k_min, ties, presence, all-abstained); abstention vocabulary; identity with real pack ids; provenance with CUDA.
- **Unit (.NET):** artefact v2 validator (valid, abstained, all-abstained Analysed, abstained-but-supporting refused, coverage, unknown reason, v1 still accepted); bound v2; release parser with the real schema.
- **Contract:** Model Pack manifest sections (registered, closed); licence notice per component; qualification record identity; gate sets; binding with the attributes role; cross-language vectors (§13); `verify_repo` negative fixtures (unregistered adapter, missing notice, weight file in Git, attribute profile hash mismatch, network locator).
- **Integration (.NET + real worker):** lease → evidence reads → learned inference → upload → completion → persistence → default selection, with no database shortcut; Stale of the fixture analyses when the real identity becomes preferred.
- **E2E:** the real attributes worker process with the actual selected packs (installed pack and unpacked environment), real platform (Kestrel) and PostgreSQL, network denied except the platform; run in CI where the packs are obtainable from the CI kit build, otherwise as a retained Development run (the CI E2E keeps using the fixture pack so it never needs private artefacts). Network denial is enforced inside the worker process by a test-only launcher that installs a `sys.addaudithook` refusing `socket.connect`/`getaddrinfo` to anything but the platform's loopback address and fails the run on any refused attempt, plus a static import guard that the adapters import no hub-capable module.
- **Regression corpus:** a small regression set with expected Track decisions and scores within tolerance, run on every pack change. Owner crops stay in the evaluation/CI evidence store (hashes only in Git) and **never enter a kit**; anything shipped or run in public CI is synthetic and licence-clean.
- **Failure paths:** one test per §17 sequence (OOM → `/fail` → exit 75; timeout → exit 76; SIGKILL → reclaim), with the launcher's restart/backoff tested separately.
- **Negative:** corrupt checkpoint, wrong hash, wrong pack id in binding, incompatible Runtime Pack, unknown adapter, NaN/Inf output, wrong output shape, simulated OOM at load and in inference, timeout, CUDA requested but absent, Production start refused, fixture in Production refused, network attempt from an adapter import.

## 19. Mutation programme

| # | Mutation | Must be killed by |
|---|---|---|
| S1 | skip artefact hash check before load | `test_a_corrupt_checkpoint_leaves_the_role_unavailable` |
| S2 | accept a manifest whose derived id ≠ bound `modelPackId` | resolver contract test + `verify_repo` negative fixture |
| S3 | accept a pack whose `runtimeCompatibility` excludes the family | `test_an_incompatible_runtime_pack_is_refused` |
| S4 | drop the preprocessing artefact from identity (not an artefact role) | pack-id derivation test with a changed preprocessing file |
| S5 | drop capability provenance fields | platform provenance validator tests (S2b) + learned E2E provenance assertion |
| S6 | turn Unknown into the argmax value when below τ | aggregation v2 golden vector |
| S7 | ignore the margin δ | aggregation v2 golden vector (inconsistent crops) |
| S8 | count abstained crops as scored / average them in | aggregation v2 vector + .NET v2 validator (abstained supporting refused) |
| S9 | score an achromatic crop's colour type instead of abstaining | admissibility unit test + learned regression case |
| S10 | allow the fixture adapter in Production | S2b refusal tests (worker and platform) |
| S11 | import a hub-capable library / open a network socket at adapter load | network-denied E2E + import-guard test |
| S12 | CPU fallback when policy is `cuda` | `test_cuda_policy_without_cuda_is_unavailable` |
| S13 | accept NaN / out-of-range scores | adapter output-validation test + terminal `output_invalid` test |
| S14 | ignore an output-mapping/schema mismatch | adapter load test (`attributeSchema` sha mismatch) |
| S15 | publish learned results without the lifecycle (direct rows) | architecture test: no module outside the completion service writes attribute rows + learned integration test through the API |
| S16 | Analysed requires a scored crop (v1 rule kept) | .NET v2 validator "all abstained is Analysed" + Python encoder vector |
| S17 | emit a non-schema model output into the artefact | .NET exact-coverage validator + mapping unit test |
| S18 | OOM in inference leaves the process leasing | failure-isolation test (process exits, restart READY) |
| S19 | timeout not enforced | inference-timeout test |
| S20 | verified status from an unpacked environment | S2b platform validator |
| S21 | score Representative crops under `representativePolicy: abstain` | Python aggregation v2 vector (Representative crops yield `representative_qualification_unknown`); .NET side via the generic rule that an abstained type is never supporting (the activation row holds no aggregation document) |
| S22 | validate a unit's artefact against the *preferred* identity's version instead of the unit's own | platform test with a fixture-identity unit completing after the learned identity is preferred |
| S23 | drop `predictionsSchemaVersion`/admissibility from the canonical identity | identity v2 vector |
| S24 | allow the overlay binding to change a release-binding role or pack | `verify_repo` negative fixture |
| S25 | plan/install the attributes role in a Production profile | Setup contract test |
| S26 | ship a learned pipeline profile with `developmentOnly: false`, or remove the Production refusal | `verify_repo` profile rule + Production-mode platform startup and resolver negative tests |
| S27 | edit a closed Model Selection Record or a frozen protocol, hash CRLF bytes instead of LF-normalised bytes, or mark a `*-model-selection` gate passed without citing a record | `verify_repo` negative fixtures (record, index and protocol hash mismatch; CRLF copy of an LF record hashes equal; passed gate without `model-selection-record` evidence) |
| S28 | let a sub-floor colour crop vote, apply a floor to a presence type, or pool presence by the full mean | aggregation v2 vectors (low-evidence view; front/back backpack Track) |
| S29 | adapter output with a type in both maps, a missing type, or an unregistered abstention reason | runner output-validation tests |
| S30 | bootstrap resamples Tracks iid, ignoring clusters, or declares a winner below the frozen cluster minimum | harness test on synthetic clustered data with a known zero difference |
| S31 | composition generator adds a tuple outside the frozen rule, or drops a shared-backbone pair | harness test against a fixed finalist set |
| S32 | ties broken by random or index order instead of threshold grouping, PO-B0 treated as packageable, or a composition admitted without passing SG4/SG7a as a unit | metric unit tests (closed-form AP = π and risk = 1 − π on one tie group) + selection-rule tests |

Target: every S-mutant killed; equivalents recorded with the reason, as in S2b.

## 20. Acceptance-register mapping

No row changes in this planning change. At S2c exit:

| Row | S2c target | Implementation evidence | Test evidence | Qualification evidence | Retained artefacts | Limitations |
|---|---|---|---|---|---|---|
| F1 | **PASS** | annotation guide per attribute, corpus + partition manifests (hashed), sealing record | agreement computation unit tests | pilot + main agreement/adjudication report | manifests, guide, report hashes | camera count achieved |
| F3 | **PASS** if the licence review approves every component; otherwise OPEN with the review's finding | source/built manifests, notices, offline policy + inventory entries, pack build workflow | `verify_repo`, resolver, installer tests | licence review record; offline install run | built manifests, kit inventory, review | Development/unverified only |
| F9 | contributes (closing owner S5, which the parent plan gives "resilience") | failure containment, device policy, version-skew refusal, co-residency | §17 tests, mutations S12, S18, S19 | co-resident run on the Development host(s) | run logs, RSS/VRAM samples | S5 re-runs on the frozen identity |
| F2, F4, F5, F6, F8, F10 | contributes | — | — | development-estimate reports (class M-D/M-E) cited by the two Model Selection Records, draft requalification matrix | reports, closed MSRs | closed by S5 on the frozen identity; an MSR is evidence a row may cite, never an acceptance claim |
| F7 | none | — | — | — | — | needs S3 search |
| G3, G4 | contributes | Setup for the attributes role; network-denied E2E | — | disconnected run of the learned role | run record | full G3/G4 is S5 |
| G6, G7 | per S2c PR | — | exact-head CI | — | — | — |

The historical acceptance criteria are not rewritten.

## 21. Documentation reconciliation

Reconciliation items are numbered DR1… so they cannot be confused with the qualification plan's protocol revisions R1 and R2.

| # | Statement | Classification | Action |
|---|---|---|---|
| DR1 | Register D1–D8/E1–E4 "exact-head CI pending" | must amend before S2c implementation | **reconciled by S2c.0 on merge**: closure entry records PR #114 exact-head plus post-merge `main@f7b03a2` evidence |
| DR2 | Register header/verdict "S2b … draft PR / NEXT"; E-section "E1–E4 remain OPEN until …" | must amend before | **done here** (text only) |
| DR3 | Register §F had no owner | must amend before | **done here**: owner column, no status change |
| DR4 | Parent plan S2b status "(draft PR, not merged)" | must amend before | **done here**; S2c status line added |
| DR5 | S2a/S2b reconciliation bridge "S2b … next" | must amend before | **done here** (dated status notes) |
| DR6 | Both roadmaps' Stage-2 status (S1.4 active) | must amend before | **done here** (status text) |
| DR7 | Qualification plan §18 freeze order not executable | must amend before | **accepted by PR #115** as protocol revision R1; S2c.0 records the accepted status |
| DR8 | ADR-013 open points (adapter, abstention/identity, vision-lock rule) and ADR-014 binding cardinality | must amend before | **accepted by PR #115**: ADR-013 items 8–10 and ADR-014 overlay note; S2c.0 records the accepted status |
| DR8a | ADR-013 §9 still lists a generic claim helper and digest verifier that S2b deliberately did not extract (register D2 amendment) | must amend before | **reconciled by S2c.0 on merge**: the S2b closure record retains the deliberate D2 implementation choice; no generic helper is introduced |
| DR9 | Setup/runbooks vision-role-only (`mavi-offline-setup.md`, `Mavi.VisionSetup.psm1`) | amend during S2c | S2c.8 |
| DR10 | Lifecycle runbook detector-centric wording; `local-development.md` "no attribute worker exists" | amend during S2c | S2c.8 |
| DR11 | `offline-dependency-policy-v1.json` `setupIntegration` predates S2a.4; `offline-binary-inventory.md` has no Model Pack rows; CUDA CPython row imprecise | amend during S2c | S2c.6 |
| DR12 | `implementation-record.md` attributes schema limits to "ADR-013 §12" | amend during S2c | S2c.5 (the limits are S2b choices) |
| DR13 | `capability-implementation-roadmap.md` "Worker boundary … one ADR when stage 2 begins" | amend during S2c | mark done (ADR-013 §8) |
| DR14 | S2a closure "next slice is S2b"; S2b plan/record status lines; ADR-007 v1 binding names; `windows-cuda-host-session.md` retired file names; baseline tables | historical | leave |
| DR15 | No durable record of *why* a model was chosen: the survey is dated discovery, and qualification records say only whether a pack passed | must amend before | **accepted by PR #115**: MSR method v1, ADR-014 MSR note and qualification-plan revision R2 are governing; S2c.0 records the accepted status |

## 22. Implementation slices

Each slice is a reviewable PR on the S2c feature branch (or a sequence of PRs), test-first, with its own exact-head CI. Slices S2c.3 and S2c.5 are model-neutral and may run in parallel with corpus work.

| Slice | Purpose | Likely files | Tests first | Evidence | Stop conditions | Deferred |
|---|---|---|---|---|---|---|
| **S2c.0 Baseline** | **Closes only when the current reconciliation change passes exact-head CI and merges.** It records S2b closure evidence (DR1); reconciles the PR #115-accepted ADR-013 items 8–10, ADR-014 overlay/MSR notes, R1–R2 and MSR method v1; and defines accountable roles for licence review, corpus custody and the 500-camera workload envelope | register evidence log; ADR/qualification/MSR status | exact-head documentation CI | baseline reconciliation record | CI failure, unresolved P1/P2 or merge not completed → S2c.1 remains unauthorized | — |
| **S2c.1 Task + corpus + labels** | **Status 2026-09-28: tooling delivered for review (`tools/qualification/attributes/corpus/`, annotation guide v1, implementation record `docs/qualification/stage2-s2c/s2c-1-implementation-record.md`); the slice stays open until operational footage, the Corpus Custodian, at least two annotators (one independent), the owner-confirmed pilot thresholds, the pilot, the freeze decision, main labelling, adjudication and the frozen-test seal exist. F1 OPEN.** corpus/partition manifest schemas and tooling (hashing, site/date-block grouping, near-duplicate check, cross-partition recurrence audit, raw-evidence pin); annotation guide v1; pilot from the training partition; agreement tooling; vocabulary freeze (bound re-checked); main labelling; **seal the frozen test** | `tools/qualification/attributes/corpus/`, `docs/qualification/stage2-s2c/annotation-guide.md`, manifests | manifest schema, grouping/leakage, recurrence-audit bookkeeping (a confirmed pair moves wholly to one partition), agreement computation (known κ/α cases) | pilot + agreement report; sealed manifest hash (**F1**) | agreement too low for an attribute → removed or merged, recorded; a selector/profile change (open S1.4) → re-derive affected crops | frozen-test scoring (S5) |
| **S2c.2 Protocol freeze** | re-run the technical survey; licence matrix and the human review of evaluation permission and qualification class for every shortlisted candidate; per event, move every candidate from `DISCOVERED` to `SHORTLISTED`/`NOT_SHORTLISTED`/`REFERENCE_ONLY`/`DEFERRED`, pin exact checkpoint identities, write the candidate cards and snapshot the reported evidence relied on; commit each event's selection protocol: the composition rule (person), the presence baseline, the pooling reference set, the hierarchical bootstrap with its calibration simulation and minimum cluster count, the DEFF inputs, the workload model and host envelope for the 500-camera projection (U9), the licence review scope (declared profiles, delivery route, rights exercised); candidates, folds, aggregation family, threshold method, primary metrics, gates (incl. SG3 tolerance), weights, MPID, strata, Development CPU host class and thread count, batch caps, timeout margin, report format | `docs/qualification/model-selection/{person,vehicle}-attributes/<event>-protocol.md` and records, survey re-survey addendum | — | each protocol hash recorded in its MSR (state `PROTOCOL_FROZEN`) before any result | no candidate of a task may even be evaluated → re-scope with the owner; strong candidates that cannot be evaluated stay in the record with reported figures | — |
| **S2c.3 Evaluation harness** | isolated, network-denied evaluation environment with its own lock and policy entry; candidate runners; metrics (threshold-grouped AP/AURC); hierarchical paired bootstrap and its calibration simulation; composition generator (frozen rule only); scale projection script; stratified reports; latency/memory probes | `tools/qualification/attributes/`, `config/dependencies/` | metrics on synthetic predictions with known answers (threshold-grouped ties; PO-B0 on one tie group: AP = π, risk = 1 − π); bootstrap determinism and cluster awareness; composition generator emits exactly the frozen set; projection script on a known workload; runner interface; mutations S30–S32 | harness self-test report | — | no production code |
| **S2c.4 Bake-off** | run evaluable candidates; fit heads/calibration with cross-fitting; tune on the tuning partition; compare on the selection partition; each MSR advanced to `TECHNICAL_DECISION_RECORDED`:
- measurements (M-D/M-E) for every evaluated candidate, losers included;
- the pooling ablation;
- the person composition candidates and their Pareto frontier (§9.5a);
- per-finalist 500-camera projections (§14.1);
- gates SG2–SG6 and SG7a (SG7b follows at S2c.9);
- the ranking with its sensitivity check and cluster-sufficiency status;
- the strongest reported, highest task-quality, strongest evaluated technical and strongest cleared candidates per profile | evidence store; the two MSRs | — | raw results by hash; MSRs | no learned candidate passes SG2–SG6 and SG7a for an attribute (for person-attributes: no admitted composition enables it) → for a colour attribute, the packageable B0 is kept if it passes its own gates (outcome `BASELINE_SELECTED`); a presence attribute is disabled, because PO-B0 is not packageable; otherwise the attribute is disabled for S2c (`NO_QUALIFIABLE_CANDIDATE`); the losers stay in the ledger | — |
| **S2c.5 Contracts** | artefact v2 + bound v2; pipeline profile v2 + identity v2 + activation migration; aggregation v2 document (both loaders); admissibility method + vocabulary; registered manifest sections + byte limits; gate sets; adapter registry with the fixture path unchanged; runner batching and output validation | `attributes/{inference,predictions,pipeline,contracts,admissibility}.py`, `model_manifest_v2.py`, `resolver.py`, `AttributePredictionsValidator.cs`, `VisualAttributeRelease.cs`, `VisualAttributeContractRules.cs`, EF migration, vectors | vectors and validators first | vectors; mutations S6–S9, S16, S17, S21–S23, S28, S29 | — | — |
| **S2c.6 Packs, overlay and release** | (interim: until S2c.7 adds a pack's adapter, the overlay role reports UNAVAILABLE in Development and nothing is activated; this is expected, and the B0 adapter lands with S2c.7) per task: source manifest, assembled notice, component provenance, qualification records **and** the overlay-binding entry in one change; the real pipeline profile; `verify_repo` overlay class and attribute-profile loader; generalised pack workflow; offline policy/inventory; Development kit assembly for owner-built artefacts; Setup/sync per profile role set; runbooks; Runtime Pack family only if the §12.7 bar is met | `models/`, `src/vision/config/components/development-attributes-v2.json`, `src/vision/config/attributes/`, `tools/verify_repo.py`, `.github/workflows/`, `config/dependencies/`, `tools/setup/`, sync tool, runbooks | `verify_repo` negatives (S24, S26, S27), pack-id derivation, Setup contract (S25) | built packs, pack ids (**F3**); MSR licence axis and implementation candidate recorded (`QUALIFICATION_PENDING`) | licence review not approved → F3 stays OPEN; Development use only where evaluation/use is permitted; no evaluated candidate clears SG1 for any target profile → the MSR records `NO_QUALIFIABLE_CANDIDATE` (or the owner pursues a licence, U3) | Production promotion |
| **S2c.7 Adapters + device** | adapters for the winners; parity with the harness (same crops → same scores within tolerance); device policy; timeout; OOM/exit sequence; launcher restart policy | `attributes/adapters/`, `supervisor.py`, `runner.py`, `main.py`, `settings.py`, launcher | parity, device and failure-path tests | parity report; mutations S1–S5, S11–S14, S18, S19 | parity fails → fix the adapter, never retune on the frozen test | — |
| **S2c.8 Learned lifecycle** | learned integration and E2E through the real lease plane (network denied); Stale of fixture analyses; in-flight fixture units complete under their own identity | integration tests, E2E harness | integration and E2E first | E2E record; mutations S15, S22 | — | S3 search |
| **S2c.9 Performance + Development execution** | 10,000-Track run; CPU on both CPU variants; heartbeat latency under load; multi-worker (N ≥ 2, two hosts where available) load against the real lease plane to validate the 500-camera projection (§14.1); CUDA and co-residency where the GPU host is available; determinism and variant agreement | scale harness | — | performance report; ADR-009 Development evidence (contributes to F8, F9) | budget missed → next candidate (S2c.4) or recorded limitation; never relax D silently | CUDA qualification |
| **S2c.10 Closure** | mutation programme, documentation reconciliation DR9–DR13, register evidence for F1 and F3, contributing reports; close both MSRs (outcome recorded; record hash in the index and addenda; cited by each qualification record's `<capabilityId>-model-selection` gate on variants with a Runtime Pack); independent cold review | docs, MSRs, `models/qualifications/` | — | mutation record; register entries | open P1/P2 → not done | S5 freeze and frozen-test scoring |

## 23. Risks, unresolved decisions and external dependencies

| # | Item | Owner | Blocks |
|---|---|---|---|
| U1 | **Licence and data review**, separate from technical ranking, of every shortlisted candidate: (a) whether MAVI may *evaluate* it; (b) its class L-A…L-D; (c) for L-B candidates, the per-deployment end-use determination — made from each deployment's actual use, never inferred from MAVI's domain-neutral product definition; (d) the rights inventory against the declared **non-commercial** profile (U10): evaluate, run operationally, fine-tune, derive, redistribute weights and derived weights as the delivery route needs, attribution, end-use, data. Non-commercial or research-only terms are not disqualifying by themselves. Open items include ImageNet-pretraining provenance of torchvision weights; OMZ training-data provenance; PA-100K images/data protection; binding force of CLIP/OpenCLIP model-card "surveillance" statements; SigLIP 2/WebLI; DINOv2 LVD-142M; evaluation-only use of research datasets and restricted checkpoints; privacy and retention of labelling operational CCTV crops (faces and plates visible) | MAVI Product/Repository Owner + designated Licence Review Owner | S2c.2 (selection), F3 |
| U2 | **Corpus footage** (cameras, day/night) and **annotators** (≥ 2, one independent) | MAVI Product/Repository Owner + designated Corpus Custodian | S2c.1, S2c.4 |
| U3 | **Product decisions**: colour merges after the pilot; target precision per attribute; MPID; whether headwear stays a candidate; the implementation candidate per event when it differs from the strongest evaluated technical candidate or the strongest cleared candidate, or when the ranking is unstable (MSR method §8, layer 4) | owner | S2c.1/S2c.2 (MPID), S5 (targets) |
| U4 | Development GPU host availability for CUDA evidence | owner | S2c.9 (CUDA part only) |
| U5 | When (after S5) the attributes role moves from the Development overlay into the release binding, which moves the kit compatibility boundary and the vision role's binding SHA (§12.8) | owner | post-S2c |
| U6 | Whether truncation needs explicit crop geometry in the lease (additive field) | bake-off evidence | S2c.4 → possibly S2c.5 |
| U7 | Whether to recover Representative-only coverage by an explicit qualification contract — persisting and leasing the selector's `qualified` flag for new ProcessingRuns (touches S1: VisionJob completion, persistence, lease) — decided from the bake-off's measured coverage cost of `representativePolicy: abstain` | owner + ADR-013 §4 amendment | after S2c.4 |
| U8 | The launcher/service that restarts the attributes role (§17) on each Development host (Windows service or scheduled task; Linux systemd unit) | owner | S2c.7 |
| U9 | **500-camera workload model and host envelope**: Tracks per camera per minute across representative loads, the person/vehicle share, host classes and maximum host count, and the accepted backlog-drain time after a host loss (§14.1) | MAVI Product/Repository Owner + designated Scale/Performance Evidence Owner | S2c.2 (SG7a/SG7b) |
| U10 | **Declared MAVI deployment profile(s) for licence review**: non-commercial, with their uses (evaluation, operational running, fine-tuning, derivatives) and delivery route (local acquisition or offline kit, which decides whether redistribution is exercised) | owner | S2c.2 (evaluation), S2c.6 (use) |
| R-a | No candidate cleared for the declared non-commercial profile reaches a useful precision for colour on MAVI imagery (the strongest evaluated technical candidate may carry terms that do not cover a use the profile needs, for example redistribution) | — | mitigated by B0 floor and MAVI-trained heads; outcome may be "attribute disabled" |
| R-b | Probe candidates need more labels than the owner can provide | — | pilot measures learning curves early |
| R-c | CPU budget excludes the most accurate backbone | — | a smaller tower or distillation within S2c; a CUDA binding for the role only after CUDA qualification (not S2c); §9.5 decides |
| R-d | MAVI-trained artefacts cannot be rebuilt in CI | — | recorded training manifest + owner-machine rebuild check (§9.7) |

## 24. Cold review of this plan

Three review inputs were applied to the first written draft (commit `458ca2e`): the author's own re-read, an owner context correction, and an independent read-only review against the code on `main`. Every finding and its disposition:

**Author's re-read (before the independent review)**

| # | Finding | Disposition |
|---|---|---|
| A1 | OOM/timeout order of `/fail` vs exit undefined | §17 sequence (later made precise by I-11) |
| A2 | How the platform chooses the artefact validator was unstated | first fix superseded by I-1 |
| A3 | "Verified crop" ambiguous for the all-abstained rule | "verified and decoded" in §12.3 and ADR-013 item 9 |
| A4 | Network-denied E2E had no mechanism | audit-hook launcher + import ban (§15, §18) |
| A5 | Corpus size was unspecified | derivation rule in §10.2 |
| A6 | Unverified packs could reach a Production kit | Development-only role planning (§12.8) |

**Owner context correction (2026-09-28)**

MAVI is a domain-neutral platform. The first draft excluded DINOv3, SAM 3, MobileCLIP, DFN and MetaCLIP and let licence terms pre-filter the shortlist. The repository-context check found **no** document that characterises MAVI itself as military or defence-specific (only normal "defence in depth" code comments); the framing came from the planner's own research prompts. Changed: the technical shortlist is licence-blind (§9.2); licence qualification is a separate analysis with classes L-A–L-D and a per-candidate matrix (§9.3, survey §6); licence is a selection gate after evaluation, not a pre-filter; end-use clauses (DINOv3, SAM 3, CLIP/OpenCLIP cards) are per-deployment determinations recorded in the qualification record; every previously excluded model is back in the comparison with its terms marked. No licence was reinterpreted.

**Independent review of `ec13a15`** (4 P1, 15 P2, 6 P3)

| # | Sev. | Finding | Disposition |
|---|---|---|---|
| I-1 | P1 | Artefact v1/v2 dispatch had no basis: the profile has no version field, identity excludes it, claims are fenced on the worker's fingerprint | **Fixed:** pipeline profile v2 + identity v2 include artefact version and admissibility method; version persisted on the activation (migration); validation against the unit's own identity (§12.4, ADR-013 item 9, mutations S22–S23) |
| I-2 | P1 | "Manifest v2 unchanged" false: role names, single notice role, single provenance, no byte caps | **Fixed without a common-schema change:** kebab roles, one assembled notice, SPDX expression (the field is free text), `component-provenance` artefact, byte limits in the registered attribute section (§12.2) |
| I-3 | P1 | Shipped-binding strategy broke `verify_repo` slice order, CI/kit builds, vision provenance and Production hygiene | **Fixed:** release binding unchanged; tracked Development overlay binding (proposed ADR-014 note); manifests merged with their overlay entry; Production Setup never plans the role (§12.8; slices S2c.6/S2c.8 reordered) |
| I-4 | P1 | The admissibility contract did not satisfy parent plan §8.2 (no qualification floors; fallback flag not leased; not derivable) | **Fixed:** the claim is withdrawn; default `representativePolicy: abstain` so Observed values rest only on qualified supplemental evidence; coverage cost measured; an explicit S1-touching contract is a separate evidence-driven decision U7 (§8.2, ADR-013 item 9) |
| I-5 | P2 | Aggregation v2 not Python-only (the .NET parser refuses other methods); parameter location unspecified; `kMin` missing from the rule | **Fixed:** aggregation-v2 document parsed by both, executed in Python, vector; rule includes `kMin` (§7.4, §12.5) |
| I-6 | P2 | Artefact bound tight (59,654,096 B, 88.9 % — re-computed and confirmed) | **Fixed:** v2 encoding adds no bytes per scored type; bound stated (§12.3) |
| I-7 | P2 | Validation evidence circular (fit, tune, select and report on one partition; in-sample ECE; LOCO meaningless) | **Fixed:** training/tuning/selection/frozen partitions, cross-fitting, held-out calibration, retrained LOCO; numbers labelled development estimates (§9.4, §10.2) |
| I-8 | P2 | Leakage: pilot source, same person across cameras, VLM-proposer bias | **Fixed:** pilot from training only; site-and-date grouping; proposer family recorded and never a candidate's family (§10.2–§10.3) |
| I-9 | P2 | R1 moved the aggregation family and threshold method, which §18 can freeze first | **Fixed:** frozen at R1 step 1 / S2c.2; only parameter values are tuned |
| I-10 | P2 | Operating point needed in S2c but targets deferred to S5; primary metric unnamed | **Fixed:** threshold-free primary metrics (AURC; macro-F1 at full coverage / AP) frozen in S2c.2 (§9.5) |
| I-11 | P2 | OOM/timeout exit unworkable (no restart; normal exit joins hung threads; CUDA OOM swallowed; SIGKILL) | **Fixed:** explicit catch, stop heartbeat → bounded `/fail` → `os._exit(75/76)`; launcher restart with backoff (U8); tests per path (§17, §18) |
| I-12 | P2 | Budget had no margin; host unspecified; CUDA loophole in SG4 | **Fixed:** (D − T_restart − T_load − T_lease)/2; host class and threads pinned in S2c.2; SG4 CPU-mandatory (§14) |
| I-13 | P2 | "No hub-capable library" false (torch.hub, requests, httpx on the lock) | **Fixed:** static ban list, socket-deny test, network-denied E2E and evaluation environment (§15) |
| I-14 | P2 | Evaluation/build dependencies ungoverned | **Fixed:** tooling policy entries, locks and licence records in S2c.3/S2c.6 (§15) |
| I-15 | P2 | Plan pre-empted the licence review; L-B treated inconsistently; RAP mislabelled; U1 incomplete | **Fixed** by the context correction and U1 extension (DINOv2 LVD-142M, CCTV-labelling privacy); RAP marked UNVERIFIED (L-D) |
| I-16 | P2 | Replaceability overstated for a closed adapter registry | **Fixed:** stated limit; data-driven generic adapters preferred (§12.1) |
| I-17 | P2 | Regression-corpus bytes would ship in kits | **Fixed:** owner crops never enter a kit (§18) |
| I-18 | P2 | Corpus depends on the still-open S1 | **Fixed:** raw-evidence pin and stop condition (§10.2, S2c.1) |
| I-19 | P2 | Contract changes unacknowledged | **Fixed:** complete list §12.9; §5.6 and §25 corrected |
| I-20 | P3 | ADR items 10–11 not minimal | **Fixed:** item 10 reduced to the new rule; item 11 moved to the S2b closure entry (DR8a) |
| I-21 | P3 | Fixture-as-adapter would change the fixture pack identity | **Fixed:** fixture path unchanged (§12.1) |
| I-22 | P3 | Who decodes the JPEG was ambiguous | **Fixed:** worker decodes once (§12.1, ADR-013 item 8) |
| I-23 | P3 | Code drift (device reason; validator range check; profile "moves") | **Fixed** (§17, §12.3, §12.8) |
| I-24 | P3 | Unspecified numbers (batch caps, timeout margin, SG3 tolerance); SigLIP 2 size | **Fixed:** fixed in S2c.2 protocol; size corrected |
| I-25 | P3 | Register verdict without run ids; F9 owner vs parent plan; NaN policy; heartbeat under load | **Fixed:** run ids cited; F9 closing owner S5; NaN terminal stated as a deliberate trade-off; heartbeat latency measured (§14) |

**Second independent review of `41d630d`** (0 P1, 1 P2, 7 P3). It checked the code and confirmed that I-1, I-2, I-3, I-5 and I-6 hold. It recomputed the bound (59,654,096 B, 88.9 %) and confirmed the change is documentation-only.

| # | Sev. | Finding | Disposition |
|---|---|---|---|
| J-1 | P2 | Only Setup stops Production from using the overlay; a Production platform pointed at it would activate the learned identity and stale every analysis. The overlay declaration mechanism was unnamed | **Fixed:** learned profiles carry `developmentOnly: true`, reusing the existing platform and resolver refusals; `verify_repo` owns a list of overlay paths with a `development-` prefix; negative tests S24 and S26 (§12.8, ADR-014 note) |
| J-2 | P3 | The v2 bound under-counts abstained entries by one byte for presence types | **Fixed:** max(scored, longest reason) per type (§12.3) |
| J-3 | P3 | The .NET half of S21 needs `representativePolicy`, which the activation row does not hold | **Fixed:** S21 is killed by the Python vector plus the generic abstained-is-never-supporting rule |
| J-4 | P3 | "Range check the worker already applies" was inaccurate | **Fixed:** reworded as new in both languages |
| J-5 | P3 | RAP and Market-1501 checkpoints listed as L-C, but the survey says L-D | **Fixed:** aligned to L-D |
| J-6 | P3 | Tracked component provenance with URLs would fail the network-hazard scan | **Fixed:** non-locator identifiers; URLs stay in the workflow |
| J-7 | P3 | Interim UNAVAILABLE state between S2c.6 and S2c.7; the B0 adapter was missing from §12.9 | **Fixed:** interim state stated; B0 adapter listed |
| J-8 | P3 | Governing list duplicated ADR-014; U6 out of order; dangling "recorded below" | **Fixed** |

After these dispositions the author's assessment is **no P1 or P2 open**. A further independent review is invited on the PR.

**PR review-bot threads on `d4bc044`** (4 P2)

| # | Finding | Disposition |
|---|---|---|
| B-1 | "Model abstention" for partial/occluded/blurred crops had no contract path | **Fixed:** evidence floor for colour types and top-`kMin` pooling for presence types (aggregation v2, §7.4 step 1a); adapter reason `model_not_applicable` for models with a declared applicability output (§12.1); mutations S28, S29 |
| B-2 | Site/date grouping does not stop recurring people/vehicles crossing partitions | **Fixed:** contiguous date blocks plus a cross-partition recurrence audit before sealing, with residual recurrence recorded as a limitation (§10.2) |
| B-3 | Precision sizing counted ground-truth positives, not predicted positives | **Fixed:** predicted positives for precision, ground-truth positives for recall, the larger decides (§10.2) |
| B-4 | Parent plan said S2c closes F9 | **Fixed** (S5 closes; S2c contributes) |

**Model Selection Record methodology (added 2026-09-28)** — MSR method v1 under `docs/qualification/model-selection/`, two S2c events in `PLANNED` state, ADR-014 MSR note, protocol revision R2.

**Independent cold review of the whole PR at `928d4d4`** (0 P1, 8 P2, 9 P3). It confirmed: documentation-only; no row PASS; no model selected; no frozen-test leakage; Production fence intact; domain-neutral.

| # | Sev. | Finding | Disposition |
|---|---|---|---|
| K-1 | P2 | A `model-selection` gate in two gate sets violates `gate_name_duplicate`; "no schema change" overstated | **Fixed:** capability-prefixed gates `<capabilityId>-model-selection` in capability gate sets; wording now "no qualification-record schema change; gate-set configuration change" (§12.6, ADR-014 note, MSR §10) |
| K-2 | P2 | A licence-class-dependent gate could never pass on an L-A pack; "all pending" contradicted "passed at S2c.10"; the class-A CUDA variant cannot pass any gate | **Fixed:** the determination is evidence of the existing `licence` gate per profile (§9.3 rule 4); the selection gate passes only on variants with a Runtime Pack; everything else stays pending (§12.6) |
| K-3 | P2 | A closed record cannot contain its own hash | **Fixed:** the hash lives in the index, the addenda header and the qualification record (MSR §3.1, template §10) |
| K-4 | P2 | CRLF checkouts break byte hashes; `NO_QUALIFIABLE_CANDIDATE` records and protocols were unprotected | **Fixed:** LF-normalised hashing; `verify_repo` checks the record, index and protocol hashes (§12.9, S27) |
| K-5 | P2 | The implementation candidate could be "pending" on SG1 yet had to pass every mandatory gate; no addendum kind for later determinations | **Fixed:** SG1 applies per named target profile (S2c: Development); a licence/deployment-determination addendum kind is added (MSR §4, §11; plan SG1 row) |
| K-6 | P2 | Evaluation permission acted as a licence pre-filter | **Fixed:** an explicit carve-out routes to `REFERENCE_ONLY` only, never `NOT_SHORTLISTED`, recorded with the decision-maker (MSR §2; §9.3 rule 1) |
| K-7 | P2 | Survey classes read beyond the sources (Awiros L-B; weights presumed to inherit data terms) | **Fixed:** Awiros and derived weights are L-D pending U1; L-D now includes "depends on an unresolved legal reading"; the plan no longer restates classes (§9.3 points to survey §6) |
| K-8 | P2 | "Validation partition" was ambiguous with four partitions | **Fixed:** every use is named (training cross-fit / tuning / selection) |
| K-9 | P3 | Qualification plan §3.1 still defined three partitions | **Fixed:** R2 item 7 |
| K-10 | P3 | SG5 multiplicity, score aggregation, unmeasurable criteria and provenance-as-licence were undefined | **Fixed:** SG5 per attribute with co-primary non-inferiority; equal attribute weight; drop-and-redistribute rule; provenance justified as a disjointness criterion (§9.5); required fields added to the protocol template |
| K-11 | P3 | "Strongest qualified" collides with qualification-record meaning | **Superseded** in the 2026-09-28 final repair pass by the conditional wording (MSR §9, plan §9.6) |
| K-12 | P3 | Candidate tables appear three times and drift | **Reduced:** licence classes are recorded only in survey §6; plan §9.2 is marked as a planning proposal superseded by the ledgers; Qwen naming aligned |
| K-13 | P3 | "Same family" undefined for labelling assistants | **Fixed:** shared backbone checkpoint lineage (§10.3) |
| K-14 | P3 | `-2026-01` reads as a month | **Fixed:** defined as a sequence number (MSR §3.1) |
| K-15 | P3 | The MSR had no documentation-precedence rank | **Fixed** (architecture README precedence item 5) |
| K-16 | P3 | §9.0 came after §9.1; reconciliation "R1" collided with protocol revision R1 | **Fixed:** §9.0 moved first; reconciliation items renamed DR1… (register reference updated) |
| K-17 | P3 | "Implementation candidate … explicitly pending" wording | covered by K-5 |

**Re-review of the amended sections (`928d4d4..977074f`)** — 0 P1, 0 P2, 14 P3. It confirmed against `qualification_v2.py`, the resolver and `verify_repo` that the capability-prefixed gates, the `licence`-gate profile evidence, the pending-variant rules and the hash links are valid. The P3s are fixed:
- no `profileQualifications` entry is written in S2c;
- the LF-normalisation transform is defined;
- target profiles are named at S2c.2, with "target profile" wording throughout;
- rule 1 requires the primary source;
- PO-5 routes to `REFERENCE_ONLY`;
- the survey legend and the torchvision class are aligned;
- support is restricted to contributing crops;
- ownership of the abstention vocabulary is stated;
- `n_contributing` wording is used throughout;
- the gate name in §12.9 is corrected;
- the table order is fixed;
- R2's scope is stated.

The per-deployment L-B rule remains a review rule, not a mechanical check (`kind` is free text), as stated in §9.3 rule 4. `.gitattributes` is left unchanged to keep this PR documentation-only, because the hash transform itself is normalised.

**Final repair pass (2026-09-28, from `065cd0c`).** Two owner constraints were made explicit:
- **A — MAVI is non-commercial.** "Enterprise-grade" means engineering quality. Licence qualification assesses the declared non-commercial profile with a per-right inventory (MSR §2.1; §9.3; qualification plan R2 item 8).
- **B — scale to 500 cameras.** See §5 item 8, §14.1, SG7a/SG7b, the weighted footprint criterion, and MSR §7.1.

Findings of the independent whole-PR review of `065cd0c` (0 P1, 4 P2, 5 P3):

| # | Sev. | Finding | Disposition |
|---|---|---|---|
| L-1 | P2 | How sub-task winners become one person pack was undefined | **Fixed:** bounded composition procedure (MSR §5.1; §9.5a); templates and person MSR updated |
| L-2 | P2 | No presence baseline semantics under AURC/AP | **Fixed:** PO-B0 per-camera prevalence reference, threshold-grouped ties, a statistical floor only and not packageable (§9.5) |
| L-3 | P2 | "Strongest qualified candidate" wording could be false | **Fixed:** conditional wording; "strongest evaluated technical candidate" (MSR §9; §9.6) |
| L-4 | P2 | Statistics ignored clustering and design effect | **Fixed:** hierarchical paired bootstrap, DEFF-inflated support, calibration simulation freezing the minimum cluster count, claim downgrade (MSR §8.1; §9.4; §10.2) |
| L-5 | P3 | 2025–2026 PAR survey incomplete | **Fixed:** survey §2.3 refresh with dispositions (VTFPAR++ added as PC-9/PO-8; event-camera methods `NOT_SHORTLISTED`, incompatible modality) |
| L-6 | P3 | No pure task-quality view | **Fixed:** the "highest task-quality evaluated candidate" field, with deltas |
| L-7 | P3 | No aggregation ablation | **Fixed:** closed pooling set, tuned on the tuning partition (§7.4) |
| L-8 | P3 | "Not found" vs "does not exist" | **Fixed:** survey absence-wording rule and audit |
| L-9 | P3 | Reference-only leaders not preserved | **Fixed:** the "strongest reported/reference candidate" field |

Focused cold review of `b7d9fde` (0 P1, 4 P2, 10 P3):

| # | Sev. | Finding | Disposition |
|---|---|---|---|
| M-1 | P2 | Random-order tie expectation contradicts AP = π (E[AP] = 0.75 for N = 2, π = 0.5) | **Fixed:** threshold-grouped tie semantics for every candidate, with closed forms (§9.5; S32) |
| M-2 | P2 | SG1 row kept the old "L-C only under a separate licence, L-D never" | **Fixed:** points to §9.3 rule 2 |
| M-3 | P2 | No rule gated a composition as a unit | **Fixed:** SG2–SG4, SG6 and SG7a per composition; failing compositions recorded; per-attribute coverage recorded (§9.5a; MSR §5.1) |
| M-4 | P2 | SG7 decided at S2c.4 but validated at S2c.9 | **Fixed:** SG7a projection at S2c.4; SG7b validation at S2c.9, which re-opens the selection on failure; single-host rule stated |
| M-5 | P3 | Composition bound "about ten"; baselines in tuples | **Fixed:** exact bound 1 + S + 3; PO-B0 excluded from tuples |
| M-6 | P3 | Pareto quality axis undefined | **Fixed:** scalar quality axis; attribute coverage recorded |
| M-7 | P3 | PO-B0 AURC with per-camera priors ambiguous | **Fixed:** camera-prior ordering; equal priors form one group |
| M-8 | P3 | Calibration simulation unspecified | **Fixed:** baseline vs perturbation on the training pilot, swapped at cluster level |
| M-9 | P3 | Unweighted m̄ understates DEFF | **Fixed:** size-weighted `Σm²/Σm` |
| M-10 | P3 | Pooling not in the tuned list; wrong partition | **Fixed** |
| M-11 | P3 | Survey "G6" stale | **Fixed** (SG6) |
| M-12 | P3 | U3 and K-11 stale terminology | **Fixed** (K-11 superseded) |
| M-13 | P3 | Leftover "deployable" wording | **Fixed** (survey column; MSR §2) |
| M-14 | P3 | Person MSR pre-filled a decision field | **Fixed:** left blank until S2c.2, with a provisional note |

Re-review of the amended sections (`2b0b31e`) found 0 P1, 2 P2 and 11 P3.

| # | Sev. | Finding | Disposition |
|---|---|---|---|
| N-1 | P2 | Person MSR still said "exact tie expectation" | **Fixed:** threshold-grouped ties |
| N-2 | P2 | Presence risk/ordering frozen only for PO-B0, so SG5 comparisons were not like-for-like | **Fixed:** one frozen definition for every candidate and baseline: aggregated score ordering, a false-discovery error for presence, the full labelled set as coverage denominator, and unscorable Tracks as a final tie group (§9.5) |
| N-3..N-13 | P3 | Stale SG7 wording (§9.5, U9); "below" → "above"; the per-component vs per-composition gate rule in the ranking and S2c.4 fallback; README unit-gate list and tuple rule placement; transitive Pareto quality axis (fixed attribute set, disabled = 0); SG5/SG6 re-run on composition heads; calibration simulation built in S2c.3 with its minimum hash-appended before S2c.4; generic "failed validation re-opens selection" | **Fixed** |

Final check of `bfc6a4e` found 0 P1, 1 P2 and 5 P3.
- **O-1 (P2), fixed:** the PO-B0 closed form now holds only for "one tie group with no unscorable Tracks". Otherwise the general formula applies (worked example given), and the S32 fixtures cover both cases.
- **O-2..O-6 (P3), fixed:** colour macro-F1 treats an unscorable Track as a false negative; PO-B0's final group holds admissibility abstentions only; attribute disabling follows the re-run SG5 on the composition's heads; the ranking paragraph lists the gates re-run per unit; duplicated parenthesis removed.

## 25. Scope guard

S2c changes no lifecycle state, publication protocol, evidence-read boundary, supersession rule, search, UI, detector, tracker, Evidence Set selection or Production gate. Every contract and code change it makes is listed in §12.9; the identity derivation, the artefact, the pipeline profile and the aggregation document change only as listed there, under the accepted ADR-013 items 8–10 and the ADR-014 overlay and Model Selection Record notes. No model is selected except through the two MSR events (§9.0), and the planning change selects none. It adds no generic job framework, no training platform and no runtime network path. Any change outside §4.1 and §12.9 needs its own ADR amendment and plan revision first.
