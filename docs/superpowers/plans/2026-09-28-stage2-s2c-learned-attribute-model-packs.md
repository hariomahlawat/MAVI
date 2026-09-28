# Stage 2 S2c — Learned Attribute Model Packs

**Status:** Implementation plan — proposed; awaiting independent plan review. Planning only: no production code, model, weight or dependency accompanies it.
**Date:** 2026-09-28
**Starting baseline:** `main@f7b03a24aba8b8bd303ed3a93b26622395e94c5f` (merge of PR #114, S2b)
**Governing:** ADR-013 (with the proposed 2026-09-28 S2c amendment, items 8–11), ADR-014, ADR-005, ADR-006, ADR-007, ADR-008, ADR-009, the Stage-2 parent plan, the Stage-2 qualification plan (with proposed protocol revision R1, §19), the authoritative Stage-2 acceptance register, the dependency/offline-packaging policy.
**Companion records:** `docs/qualification/stage2-s2c/model-candidate-survey.md` (reported state of the art; nothing reproduced).
**Exit gate:** §20. S2c closes F1, F3 and F9 on executed evidence and runs learned person/vehicle attribute Model Packs through the unchanged S2b lifecycle as **Development / unverified** capabilities. It does not claim model-quality qualification, CUDA qualification or Production.

---

## 1. Baseline

| Check | Result |
|---|---|
| `main` | `f7b03a24aba8b8bd303ed3a93b26622395e94c5f` = "Merge pull request #114 from hariomahlawat/feature/stage2-s2b-attribute-lifecycle" (verified with `git fetch origin main`) |
| PR #114 present | yes — `main` contains `37376fb` (the final PR head) and every earlier S2b commit; exact-head CI on `37376fb` (MAVI Quality Gate with the real-process attribute E2E, deterministic-validation, windows-script-validation, CPU ubuntu, CPU windows) passed before merge |
| Commits after the merge | none |
| Working tree | clean at branch point |
| Docs vs merged implementation | **not consistent** — the acceptance register, parent plan, both roadmaps and the S2a/S2b reconciliation bridge still describe S2b as a draft/next slice; D1–D8 and E1–E4 still read "exact-head CI pending". Status text is corrected by this change (§21); row status is not. |

## 2. Material read

ADR-005, -006, -007, -008, -009, -011, -013 (including the 2026-09-28 S2b implementation amendment), -014 (including the 2026-09-27 amendment); `capability-roadmap.md`; `capability-implementation-roadmap.md`; the Stage-2 parent plan `2026-09-23-visual-attributes.md`; the acceptance register `docs/reviews/2026-09-23-visual-attributes-acceptance.md`; the qualification plan `docs/qualification/2026-09-23-visual-attributes-qualification-plan.md`; the architecture-review resolution; the S2a closure `docs/reviews/2026-09-28-stage2-s2a-closure.md`; the S2a/S2b reconciliation bridge; the S2b plan and implementation record; `dependency-and-offline-packaging-policy.md`, `offline-binary-inventory.md`, `config/dependencies/offline-dependency-policy-v1.json`; `models/manifests/README.md`; the runbooks `vision-runtime-model-component-lifecycle.md`, `mavi-offline-setup.md`, `offline-readiness.md`, `local-development.md`, `windows-cuda-host-session.md`; the UI specification sections on Unknown and confidence. The S2b code was read directly (§3).

## 3. What S2b actually delivered — the lifecycle S2c reuses

S2c adds no lifecycle, persistence path, worker protocol or publication shortcut. Everything below is reused unchanged unless §12 names an amendment.

| Concern | S2b implementation (code on `main`) | S2c consequence |
|---|---|---|
| Aggregate | `VisualAttributeAnalysis` (Queued/Running/Completed/Failed/Superseded), one unit per (run, identity) | reused |
| Identity | canonical tuple (schema, pipeline, aggregation, parameters SHA, sorted capability→modelPackId), fingerprint SHA-256; Python `attributes/pipeline.py` and .NET `VisualAttributeRelease.cs` pinned by `contracts/test-vectors/visual-attribute-identity-v1.json` | a real pack is a new identity; existing fixture analyses become Stale (ADR-013 §9, amendment item 5) |
| Preferred identity | platform reads `VisualAttributes:ComponentBindingPath` + `PipelineProfilePath`; nothing configured → `NotConfigured`; lease fenced on the worker's fingerprint | reused; §12.6 decides what the shipped release configures |
| Lease/attempts | header-only capability, heartbeat, reclaim, deadline (default 6 h), attempts (default 3), publication window | reused; the deadline drives the performance budget (§14) |
| Evidence read | lease-scoped, lifetime-fenced stream; worker verifies size + SHA before decode; transport ≠ evidence | reused; learned models only ever see verified bytes |
| Upload / staging / janitor | streamed, capped (64 MiB), create-once per attempt; janitor judges every directory | reused |
| Completion | three-phase (A validate + publication window, B content-addressed seal, C re-fence + COPY + visibility barrier) | reused |
| Artefact | `mavi-attribute-predictions-v1`, canonical JSON, exact coverage of leased crops, bound ≤ 64 MiB | extended to v2 for abstention (§12.3); v1 stays valid history |
| Rows | one `Observed`/`Unknown` row per applicable (Track, type); `Unavailable` Track outcome with reason; supporting Observation for Observed | reused |
| Default/Stale | derived from the preferred fingerprint; supersession only on success | reused |
| Worker | `mavi_vision.attributes` role on the Component Binding v2 registry → resolver → supervisor; UNAVAILABLE never leases; one serial inference lane; heartbeat task stopped before `/complete` | reused; inferencer seam extended (§12.1); device policy implemented (§11) |
| Inferencer seam | `inference.py`: `AttributeInferencer.score(VerifiedCrop, attributes) → {type: {value: float}}`; `inferencer_for` returns only the fixture, receives no artefact paths | **the only model plug-in point**; extended per ADR-013 amendment item 8 |
| Aggregation | `predictions.py`: `mean-score-argmax` + one global `minimumConfidence`; ties by schema order; supporting = crop scoring the value highest | extended with a second, versioned method (§7.4); the platform validates structure only and never recomputes |
| Fixture refusal | worker `attribute_development_profile_forbidden` in Production; platform refuses `developmentOnly` outside Development/Testing | reused; real packs are Development/unverified by manifest status, not by the fixture flag |
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
| Model discovery and selection | survey record, shortlist, bake-off protocol, bake-off on the MAVI validation partition, model-selection record (§9) |
| Corpus | corpus and partition manifests, annotation guide, double-labelling, agreement report, sealing of the frozen test set (§10); closes **F1** |
| Model Packs | real person/vehicle packs: source manifests, licence notices, acquisition/build, built manifests, install; **F3** |
| Inference adapters | preprocessing, inference, decoding, calibration, admissibility — behind the capability adapter (ADR-013 item 8) |
| Artefact v2 | abstention recording (ADR-013 item 9), both languages |
| Aggregation v2 | a second versioned aggregation method with per-attribute operating points (§7.4) |
| Device policy | truthful CPU/CUDA/auto for the attributes role (ADR-013 item 10) |
| Runtime Pack | only if the bake-off selects a model outside the vision family's dependency graph (§12.5) |
| Failure/isolation | model load, OOM, timeout, NaN, crash, version skew, co-residency; closes **F9** |
| Performance | inference and end-to-end measurement at the 10,000-Track bound (§14) |
| Offline/Setup | pack inventory, offline policy entries, Setup/sync for the `attributes` role (§15) |
| Development execution evidence | CPU on every deployable CPU variant; CUDA only where the Development GPU host is available (§11) |
| Validation-partition quality evidence | crop/Representative/Track metrics, leave-one-camera-out, abstention, calibration — *contributing* evidence for F2, F4, F5, F6, F8, F10 |

### 4.2 S2c does not own

S3: search v4, predicates, cursor, indexes, query plans (E5–E8), attribute filtering or browsing UI. S4: operator UI, Investigation/Review changes. S5: freezing gates and support, frozen-test scoring, retrieval precision (F7), CPU/CUDA *qualification* PASS, requalification matrix closure, Stage-2 acceptance. Also out: vehicle subclass (Stage 3), demographics/face/identity attributes (parent plan §2), a generic IntelligenceJob, a new lifecycle, tracking/detection/Evidence Set changes, scene analytics, live cameras, Production promotion, Task 18, training infrastructure beyond the minimal reproducible probe/fine-tune path the bake-off needs (§9.6), re-analysis requests (ADR-013 §9, not scoped by any slice yet), retention policy (ADR-013 §19; triggers before Production).

## 5. Quality principles for S2c

1. **MAVI owns the semantics; models are engines.** The platform, the artefact, the rows and the operator vocabulary never encode a network, a label index or a vendor.
2. **The model is chosen by evidence, not by the planner.** No checkpoint is named as the winner in this plan (§9).
3. **Unknown is measured, not a failure.** Abstention has reasons, rates and strata.
4. **No capability is exposed because a model can emit it.** Attributes that cannot meet their gate stay disabled.
5. **Replaceability is structural.** A better model later changes a Model Pack, a binding and a qualification record — nothing else (parent plan §7).
6. **Extend only where S2c demonstrates the need.** The four ADR-013 items are the only architectural changes; each is forced by a concrete gap in §3.

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
| Accuracy expectation | set by owner-declared precision targets on the validation frontier (§10.5) — not by benchmark figures | same | same |
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

An Observed row's confidence is the aggregation policy's score for the asserted value in [0,1] (ADR-013 §12). S2c makes it meaningful: adapters output **calibrated** per-value probabilities (calibration fitted on the validation partition and shipped inside the Model Pack, ADR-013 item 8), and aggregation v2 reports the aggregated calibrated probability. The UI rules (integer percent in lists, one decimal in inspectors, never opacity) are S4's and unchanged. A confidence is never shown for Unknown.

### 7.3 Versioning

Any vocabulary change is a new attribute-schema version (new identity, requalification). Merging two colour values after the pilot happens **before** the schema is first bound, so it creates no historical rows. Removing an attribute after qualification (a gate fails in S5) is a new schema version; the old analyses remain readable history (E4).

### 7.4 Aggregation across the Evidence Set (aggregation method v2)

A new method `calibrated-mean-margin-v1` (name provisional), versioned beside S2b's `mean-score-argmax`, Python-only (the platform validates structure, never recomputes; §13):

1. inputs: for each attribute type, the calibrated per-value scores of the crops that were **scored** for that type (abstained crops contribute nothing);
2. `k_min`: minimum number of scored crops (per attribute type; default 1, tuned);
3. per value: mean calibrated score; best value `v*` with deterministic tie rule (S2b's: higher mean, then schema order);
4. Observed iff `mean(v*) ≥ τ(type, v*)` **and** `mean(v*) − mean(v₂) ≥ δ(type)` (margin against the runner-up; guards against inconsistent crops); otherwise Unknown;
5. supporting Observation: S2b's rule (crop scoring `v*` highest, then lower evidence rank);
6. presence attributes (single value `present`): Observed iff mean ≥ τ; otherwise Unknown — never Absent.

`τ`, `δ`, `k_min` and any role weighting are parameters (in identity), chosen on the validation partition by the procedure of §10.5, and frozen before frozen-test scoring (R1 step 3). Whether evidence-role weighting (e.g. NearView over a fallback Representative) helps is a bake-off question; the default is unweighted.

## 8. Evidence quality and applicability

### 8.1 Outcome distinctions (reusing S2b's taxonomy)

| Situation | Level | Result | Mechanism |
|---|---|---|---|
| Model scored the crop, aggregated value clears τ and δ | attribute | **Observed** (valid prediction) | aggregation |
| Scored, but below τ or δ | attribute | **Unknown** (low confidence) | aggregation |
| Crop inadmissible for this attribute (too small, achromatic for a colour type, region not present) | crop × attribute | **abstained** with reason; contributes no score | admissibility policy (ADR-013 item 9) |
| No crop scored for the type | attribute | **Unknown** | aggregation |
| Every crop abstained but at least one crop was verified | Track | **Analysed**, all attributes Unknown | artefact v2 rule |
| Evidence missing / integrity failed / undecodable / no accepted evidence | crop → Track | **Unavailable**(reason) — S2b unchanged | S2b |
| Unsupported modality for the whole capability (e.g. a model cannot run on greyscale at all) | crop × attribute | abstained `modality_unsupported` | admissibility |
| Model failure (exception, OOM, timeout) | attempt | retryable attempt failure; never a Track outcome | §16 |
| Malformed model output (NaN/Inf, out-of-range, wrong shape) | attempt | terminal `visual_attribute_output_invalid` (S2b) | adapter + aggregation checks |

### 8.2 Condition handling

| Condition | Handling | Measured as |
|---|---|---|
| Low resolution | admissibility minimum per object class (and per region for T-PC), tuned on validation; below it → abstain `subject_too_small` | stratum: crop height bands |
| Partial body / truncation | model abstention (low score) plus lower-body region size check; explicit geometry only if U6 shows it is needed | stratum: truncated yes/no (annotated) |
| Occlusion, second person in crop | model abstention; the selector's occlusion proxy already governs supplemental roles | stratum: occlusion level, crowding (annotated) |
| Blur | model abstention; sharpness not re-measured in S2c unless the bake-off shows material benefit | stratum: blur (annotated) |
| Extreme pose | model abstention | stratum: viewpoint |
| Night / IR / greyscale | deterministic achromatic test (chroma statistics on the crop) → colour types abstain `achromatic_evidence`; presence types still scored | stratum: day/night; achromatic rate |
| Fallback Representative | treated like any crop under the same admissibility contract (ADR-013 item 9); role weighting is a bake-off parameter | Representative-only vs Evidence-Set metrics (qualification plan §6.3) |
| Inconsistent crops within a Track | the margin δ turns disagreement into Unknown | aggregation error analysis |
| Vehicle partially visible | admissibility minimum; model abstention | stratum |

Abstention reason vocabulary (closed, schema-versioned): `subject_too_small`, `region_too_small`, `achromatic_evidence`, `modality_unsupported`. Additions are schema changes.

## 9. Model discovery and selection

### 9.1 Survey (done for planning; reported, not reproduced)

`docs/qualification/stage2-s2c/model-candidate-survey.md` records the 2026-09 survey: supervised pedestrian-attribute recognition (PAR) models and datasets, vehicle-colour methods and datasets, contrastive VLMs, self-supervised backbones, small generative VLMs, segmentation/colour-naming pipelines and industrial models (Intel Open Model Zoo, PaddleDetection, NVIDIA TAO/DeepStream). Its conclusions that shape S2c:

- **Licence, not architecture, is the binding constraint.** Every public dataset with clothing-colour labels (PETA, RAP, Market-1501 attributes, UPAR) and every public vehicle-colour dataset with CCTV imagery (VeRi-776, UFPR-VCR/VeSV, CompCars) is research-only or grants no rights; models trained on them are treated as carrying those restrictions. PA-100K is stated as CC-BY 4.0 but has no colour labels.
- **Published accuracy does not transfer.** Vehicle colour reported at 92–98 % on a saturated frontal benchmark falls to ≈ 66 % top-1 for the same backbone on real CCTV with night imagery; night is < 10 % of that data and ≈ 32 % of its errors. PAR state of the art (≈ 85–93 % mA on PA-100K/PETA/RAP) is measured in-domain on research-only data, and cross-domain splits cost ≈ 15–25 mA points.
- **Published PAR scores mostly do not measure colour.** The standard PETA-35/RAPv1-51 evaluation subsets drop colour labels and PA-100K has none; colour is scored only on Market-1501 attributes and UPAR (both restricted). MAVI's colour quality therefore cannot be inferred from leaderboard numbers at all.
- **Model-card use restrictions matter.** OpenAI CLIP and LAION/DataComp OpenCLIP cards place surveillance and deployed use out of scope; Apple MobileCLIP/DFN weights are research-only; MetaCLIP is CC-BY-NC; DINOv3 and SAM 3 prohibit military/espionage use. SigLIP/SigLIP 2 and DINOv2 are Apache-2.0.
- **Industrial models are the only permissively licensed, task-shaped checkpoints**, with undisclosed training data and OpenVINO-IR-only distribution.
- **MAVI-owned labelled data is the realistic foundation** for a quality learned capability: a frozen Apache-2.0 backbone plus a MAVI-trained head, or a small fine-tuned network, both need MAVI labels.

### 9.2 Shortlist for the bake-off (candidates, not choices)

Each family is evaluated only after its licence gate (§9.4 G1) is at least *provisionally admissible* by the human licence review; a family the review excludes is dropped before any MAVI data is used.

| Task | Id | Candidate family | Why shortlisted | Main risk |
|---|---|---|---|---|
| T-PC | PC-B0 | **Deterministic baseline:** region band + dominant chroma cluster + MAVI-owned CIE-Lab colour naming (no learned weights) | licence-free floor every learned candidate must beat | illumination/white balance |
| T-PC | PC-1 | Frozen **SigLIP 2** image tower (base class) on region crops + MAVI-trained linear/MLP head + calibration | Apache-2.0; strongest licence-clean open-vocabulary features; region cropping avoids upper/lower binding errors | ≈ 0.2 B parameters (CPU cost); low-res degradation; new runtime dependency unless reimplemented on torch |
| T-PC | PC-2 | Frozen **DINOv2** (S or B) + MAVI head | Apache-2.0; efficient; strong probes | colour may be under-represented in invariance-trained features |
| T-PC | PC-3 | **Small CNN fine-tuned** on MAVI labels (torchvision MobileNetV3 / ResNet / ConvNeXt-T family) | runs on the existing Runtime Pack graph; cheap on CPU | ImageNet-pretraining provenance (legal question); needs more labels |
| T-PC | PC-4 | **Intel OMZ person-attributes-recognition-crossroad-0230** colour points + PC-B0 naming | Apache-2.0; tiny; designed for crossroad CCTV | undisclosed training data; IR→torch port and parity; point sampling, not region colour |
| T-PO | PO-1 | **Intel OMZ 0230** `has_backpack`, `has_bag`, `has_hat` | Apache-2.0; task-shaped; tiny | undisclosed data; no published per-attribute accuracy; port |
| T-PO | PO-2 | SigLIP 2 + MAVI head (shared tower with PC-1) | one backbone serves T-PC and T-PO | as PC-1 |
| T-PO | PO-3 | Small CNN fine-tuned on **PA-100K (CC-BY 4.0)** + MAVI labels | the one large permissive PAR dataset covers backpack/bag/hat | data-protection review of PA-100K imagery; domain shift |
| T-PO | PO-4 | DINOv2 + MAVI head | as PC-2 | as PC-2 |
| T-PC + T-PO | PX-5 | **Awiros ConvNeXt V2-Tiny** (ONNX; heads for top/bottom colour, backpack, handbag, head accessory) — **conditional** | the only released task-shaped model trained on CCTV crops; vendor reports colour ≈ 75 %, backpack ≈ 94 % on its own benchmark | licence terms not stated, gated access; pseudo-labels from an unnamed VLM; gender/age heads must be discarded by the adapter; needs onnxruntime or conversion |
| T-VC | VC-B0 | **Deterministic baseline:** body-region chroma clustering + Lab naming | licence-free floor | glare, white balance |
| T-VC | VC-1 | **Intel OMZ vehicle-attributes-recognition-barrier-0042** (0039 as a small reference) | Apache-2.0; task-shaped; fast | 7 colours only; undisclosed data; front-view bias; upstream deprecated |
| T-VC | VC-2 | SigLIP 2 or DINOv2 + MAVI colour head | full vocabulary control; Apache-2.0 | labelling cost; long tail |
| T-VC | VC-3 | Small CNN fine-tuned on MAVI labels | existing graph; cheap | labels; provenance |
| T-VC | VC-R | SigLIP 2 zero-shot prompts — **reference only** | no labels needed; sanity check | uncalibrated; not a deployable candidate |

**Conditionally admitted** (evaluated only if the licence review clears them): OpenCLIP/CLIP ViT-B probes (model-card surveillance statement), Awiros PX-5 (unstated terms). **Upper-bound references** (never deployable; run internally only if the licence review permits evaluation use of restricted-data checkpoints): the UPAR ConvNeXt-B baseline, the UPAR 2024 winner C2T-Net, PromptPAR — they quantify how much quality the licence-clean candidates give up, including on colour. **Excluded** from deployment: every checkpoint trained on research-only data (PromptPAR/VTB/SequencePAR/Rethinking-PAR on PETA/RAP, PP-Human/PP-Vehicle attribute weights, VeRi/UFPR-trained vehicle models), MobileCLIP/DFN, MetaCLIP, DINOv3, SAM 3, NVIDIA DeepStream CarColor (deprecated, EULA-bound). Their **reported** numbers may be cited as context; MAVI does not reproduce them on restricted data unless the licence review permits evaluation use. **Generative VLMs** (Florence-2, SmolVLM, Qwen-VL, Moondream) are not candidates for the classifier role (no native calibration, decoding non-determinism, cost at 40,000 crops); an offline one may be used only as a labelling *assistant* whose output is never ground truth (§10.3).

The shortlist is a floor, not a ceiling: slice S2c.2 re-runs the survey at freeze time and may add a candidate published since, under the same gates.

### 9.3 The bake-off

- **Separation from production.** Candidates run in a *separate evaluation environment* under `tools/qualification/attributes/` (an isolated, pinned venv that may contain `open_clip`, `transformers`, `onnxruntime`, `openvino` for conversion and parity), never in the Runtime Pack. No candidate is integrated into `mavi_vision.attributes` before it wins.
- **Same conditions for all.** The same crops (the real MAVI Evidence Sets of the validation partition, exactly as leased), the same admissibility policy, the same aggregation method family, the same metric code, the same hardware class, recorded thread counts and precision.
- **Inputs.** Crops come from the corpus store by SHA; each candidate's preprocessing is recorded as data; checkpoints are loaded from a hash-pinned local cache populated once from pinned revisions (never a floating tag).
- **Probe/fine-tune candidates** train on the *training* partition only, tune on the validation partition, with fixed seeds and a recorded environment (§9.6).
- **Measurements:** §10.4 quality metrics at crop, Representative-only and Track level with abstention; risk–coverage; calibration; strata (§8.2); per-camera and leave-one-camera-out within the validation partition; CPU and (where available) CUDA latency p50/p95 per crop and per Track, batch behaviour, peak RSS/VRAM, model-load time; determinism on repeat.
- **Statistics.** Differences are reported with a paired bootstrap over Tracks, resampled by camera, 95 % intervals; "better" means the interval excludes zero.
- **Protocol frozen first.** Candidates, weights, gates, strata, the minimum practically important difference (MPID) and the report format are committed (slice S2c.2) **before** any candidate sees MAVI data.

### 9.4 Selection gates and weighted decision

**Hard gates (eliminate):**

| Gate | Rule |
|---|---|
| G1 Licence | code, weights and training-data terms permit offline redistribution and MAVI's operational use, per the human licence review; unresolved → not selectable (may still be *evaluated* if evaluation use is permitted) |
| G2 Offline | loads from pack artefacts alone; no hub, index or network call; verified by a network-denied run |
| G3 Determinism | repeated CPU runs give identical Track decisions and scores within 1e-6; CPU/CUDA variants agree on Track decisions within the predeclared equivalence tolerance (qualification plan §10) or only one variant may be bound |
| G4 Runtime budget | Development-CPU p95 per crop within the budget of §14, or within it on CUDA where the release profile binds CUDA |
| G5 Baseline | beats the deterministic baseline (B0) on the primary quality metric with the bootstrap interval excluding zero; if no learned candidate does, the baseline is selectable and the plan records that the learned capability did not beat it |
| G6 Abstention sanity | on non-subject/error crops of the validation partition it produces Unknown/abstention at a higher rate than on valid crops (F6 direction), and no confident prediction on achromatic crops for colour types |

**Weighted decision among survivors** (weights proposed here, reviewed and frozen in S2c.2 before results exist):

| Group | Criterion | Weight |
|---|---|---|
| Operational quality (50) | Track-level primary metric at the operating coverage (validation) | 20 |
| | worst of the difficult strata (low-res, partial, occlusion, low light) | 10 |
| | calibration and risk–coverage (ECE, AURC) | 10 |
| | leave-one-camera-out stability | 10 |
| Runtime (20) | CPU p95 per crop vs budget | 8 |
| | peak memory with the detector co-resident | 4 |
| | model load / READY time | 2 |
| | CUDA viability | 3 |
| | batching efficiency | 3 |
| Engineering (15) | dependency burden / Runtime Pack impact | 6 |
| | implementation stability and maintenance status | 5 |
| | exportability and replaceability | 4 |
| Deployment (15) | licence risk grade after review | 6 |
| | training-data provenance disclosed | 5 |
| | packaging reproducibility | 4 |

A quality difference inside the bootstrap interval is a tie. **A candidate that needs a Runtime Pack extension** (§12.5) must beat the best candidate on the existing graph by at least the MPID with the interval's lower bound above zero; otherwise the existing-graph candidate is selected. Conversely a candidate is never rejected for needing a reasonable extension when it clears that bar.

### 9.5 Model-selection record

Per task, retained at `docs/qualification/stage2-s2c/model-selection-<task>.md` with raw results under the qualification evidence store: candidates considered; exact checkpoint identities, source revisions and SHA-256s; licences and review outcome; corpus and partition manifest hashes; hardware; runtime and environment lock; preprocessing; metrics and raw per-Track predictions; performance; the reason each candidate was eliminated; the reason the winner was chosen; known weaknesses. The winner is described as *"selected as the strongest qualified candidate for MAVI's defined S2c operating envelope based on retained bake-off evidence"* — never "best".

### 9.6 Minimal training path

Only where a probe/fine-tune candidate is shortlisted: a pinned, seeded script in `tools/qualification/attributes/` that reads the training partition by manifest, writes the head/calibration artefacts with SHA-256s and a training manifest (inputs, seed, environment lock, code revision). Because the corpus is private CCTV, CI cannot rebuild these artefacts; reproducibility is proven by re-running the recorded manifest on the owner-controlled machine and matching the artefact hash (or, where CPU kernels are not bit-stable, the recorded tolerance on decisions). No general training platform, experiment tracker or hyper-parameter service is introduced.

## 10. Qualification strategy

### 10.1 Protocol

The Stage-2 qualification plan governs, with protocol revision R1 (freeze order, §19 there). S2c executes R1 steps 1–2; S5 executes steps 3–4.

### 10.2 Corpus

| Aspect | Rule |
|---|---|
| Source | owner-supplied recorded video representative of MAVI deployment (multiple cameras/scenes, day and night), processed through the **real** MAVI VisionJob so crops are the operational Evidence Sets (fallback Representatives, byte-cap re-encoding included) |
| Storage | outside Git (AGENTS.md: no CCTV in Git); access-controlled evidence store; retention recorded; no cloud labelling service |
| Manifests (in Git) | corpus manifest (video ids, camera ids, ProcessingRun ids, crop SHA-256s, strata tags — no imagery) and partition manifest, each content-hashed |
| Partitions | training / tuning-validation / **frozen test**, grouped by camera and by video so no Track, video or camera-day spans partitions; the frozen test contains whole held-out cameras plus held-out videos of seen cameras |
| Camera count | enough that every partition has at least three cameras and the frozen test has at least one camera unseen elsewhere; the achieved count is a recorded limitation, never waived silently |
| Size | derived, not guessed: for each exposed value the frozen test needs enough positives that a precision estimate at the owner's target has the owner's accepted interval half-width (normal approximation `n ≈ z²·p(1−p)/e²`, e.g. p = 0.9, e = 0.05 → ≈ 139 positives at 95 %); the pilot supplies prevalence per value, from which the number of Tracks to label per partition follows. Values that cannot reach it are reported as insufficient evidence (qualification plan §5) |
| Public data | PA-100K may enter the training partition if the licence review clears it; never the frozen test (qualification plan §3.1); research-only datasets are not used |
| Contamination | frozen test is MAVI-sourced, so disjoint from third-party training data by construction; near-duplicate check (perceptual hash) across partitions |
| Coverage | the strata of §8.2 and qualification plan §3.3; gaps are limitations |
| Sealing | R1 step 1: manifest hash committed, content withheld from the evaluation environment, access logged |

### 10.3 Labels

Annotation guide per attribute (allowed values with reference swatches, Unknown/Unlabelable criteria, partial visibility, patterns, bag/headwear boundaries, vehicle dominant-colour rule, minimum visual evidence). **Pilot:** a small double-labelled pilot measures agreement per value pair and fixes merges before the schema is frozen. **Main labelling:** crop-level and Track-level ground truth, blind to model output; a representative double-labelled subset with at least one annotator independent of model selection; agreement by Cohen's κ (two annotators) or Krippendorff's α (more, nominal); adjudication recorded. Model- or VLM-proposed labels, if used to speed labelling, are recorded as proposals and never accepted without a human decision; they are not used on the double-labelled subset.

### 10.4 Metrics

| Attribute kind | Metrics |
|---|---|
| Colour (categorical) | per-value precision/recall/F1; macro-F1 over values meeting support; balanced accuracy; confusion matrix; coverage and Unknown rate; per stratum; per camera; leave-one-camera-out |
| Presence | positive precision/recall; FPR/FNR; Unknown rate; PR curve; no negative metrics (no Absent) |
| Both | risk–coverage curve and AURC; expected calibration error and reliability diagram; crop vs Representative-only vs Evidence-Set Track level (primary: Track level); values under support are "insufficient evidence", never merged into a passing macro score |

### 10.5 Thresholds and gates — how numbers are established

No percentage is set in this plan. The procedure:

1. S2c reports, per attribute and value, the validation **precision–coverage frontier** of the selected candidate with bootstrap intervals, plus the support measured per value.
2. The owner declares, per exposed attribute, a **target precision** (an operational policy decision, recorded with its rationale) and the minimum support; the operating point `τ` is the lowest threshold whose **lower** 95 % bound meets the target, maximising coverage; δ and `k_min` are chosen the same way.
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

## 12. Model Pack and Runtime Pack design

### 12.1 Capability adapter (ADR-013 item 8)

- `inferencer_for` is replaced by an adapter registry keyed by `adapterId` (closed set, like `IMPLEMENTED_CAPABILITIES`); the supervisor passes each capability's resolved artefact paths (already resolved and hash-checked by `resolve_role`) to its adapter.
- Adapter contract: `load(artifacts, device) → loaded`; `score_batch(crops, attributes) → [{type: {value: score∈[0,1]}} | abstention]`; the runner dispatches by the Track's capability; batches are bounded (§14).
- The fixture becomes one registered adapter (`fixture-v1`, Development-only) so the S2b path is unchanged.
- Admissibility runs before the adapter, from pipeline parameters (identity-bearing), on verified bytes.

### 12.2 Model Pack contents (manifest v2, unchanged schema; new registered sections)

| Element | Content |
|---|---|
| `modelId`/`modelVersion` | MAVI-assigned, e.g. `person-attributes-<family>-v1` (named after the winner, chosen after the bake-off) |
| `capabilityIds` | `person-attributes` and/or `vehicle-attributes` |
| Artefacts | third-party checkpoint(s) (`checkpoint` or `component:<name>`); MAVI-trained head/calibration (`head`, `calibration`); `preprocessing` (JSON: resize/pad/normalise, colour order, region bands); `output-mapping` (JSON: model outputs → schema values, discarded outputs listed); `licence-notice` for **every** third-party component (`licence-notice`, `licence-notice:<component>`) |
| `inputContract` | `evidence-crop-jpeg` / `RGB` (registered for attributes) |
| `outputContract.schemaId` | `attribute-scores-v2` (calibrated per-value scores + abstention) |
| `runtimeCompatibility` | the Runtime Pack family the adapter runs on |
| `licence` | SPDX id of the composite (or `LicenseRef-…`), notice roles, `reviewStatus` from the human review |
| `provenance` | publisher, source repository, immutable revision per component; MAVI training manifest hash for MAVI artefacts |
| `capabilitySpecific.person-attributes` / `.vehicle-attributes` | **new registered sections**: `adapterId`, `preprocessingArtifactRole`, `outputMappingArtifactRole`, `attributeSchema {id, version, sha256}`, `components[]` (role → artefact roles) |
| `verificationStatus` / `qualificationId` | `unverified` / `null` throughout S2c |

A pack may compose several models (e.g. one for colour, one for carried objects) because a capability binds exactly one pack (ADR-014 §1); replacing a component is a new pack.

### 12.3 Artefact v2 (ADR-013 item 9)

Per observation: `status` `scored` (the crop was verified and decoded) or `unavailable` (S2b reasons); a scored observation carries, per applicable attribute type, either `scores` (every schema value, calibrated, finite, [0,1]) or `abstained: <reason>`. Track rule: `analysed` iff ≥ 1 observation is `scored` (verified **and** decoded), even if all its types abstained; exact coverage of leased crops unchanged; decisions equal rows; a supporting Observation must have `scores` for that type. **Version selection:** the artefact schema version is a consequence of the aggregation method — `mean-score-argmax` produces v1, the v2 method produces v2 — and the aggregation policy is identity-bearing, so one identity can never produce both. The platform validator dispatches on the artefact's own `schemaVersion` header (both validated streaming, v1 unchanged); the release parser's schema bound uses the v2 formula (the larger) for every schema. Units already Running under a fixture identity when a learned identity becomes preferred finish under their own identity and become history (S2b default derivation); nothing is converted.

### 12.4 Qualification records and gate sets

One record per capability (`models/qualifications/<pack>-<capability>.json`), all variants `pending`, `overallResult: pending`, policies pinning the pipeline profile id/SHA. New capability gate sets `person-attributes-v1` and `vehicle-attributes-v1` in `config/acceptance/capability-gate-sets-v1.json` naming the §10.5 gate families (every gate `pending` in S2c).

### 12.5 Runtime Pack decision

- **Default:** the selected adapter runs on `mmdetection-phase1-v1` (torch 2.6.0, torchvision 0.21.0, OpenCV, Pillow, NumPy). An OpenVINO-IR candidate is ported to a first-party torch module with a build-time parity test; a SigLIP/DINOv2 tower is reimplemented on torch or loaded as a state dict into first-party code; `torch.load(weights_only=True)` only.
- **Extension (only past the §9.4 MPID bar):** a new family `attributes-<engine>-v1` for the attributes role (ADR-013 item 10), with its own locks per variant, `runtime.json`, offline wheel entries, licence inventory, CI build and ADR-009 status per variant (CUDA starts `pending-hardware-qualification`). The vision family's lock is never changed for an attribute model.

### 12.6 What the shipped release binds

S2c adds the `attributes` role and the two capability bindings to the tracked `phase1-bindings-v2.json` only in slice S2c.8, when the packs exist in the kit; the change moves `componentBindingSha256`, which is the kit compatibility boundary (S2a closure). **Unverified packs must not reach a Production install.** Setup/sync therefore plan roles from the selected deployment profile's enabled roles (today Setup hard-codes `vision`): Development profiles enable `attributes`; Production profiles do not until S5 promotes the packs, so a Production kit neither requires nor installs them. If per-profile role selection cannot be delivered in S2c.8, the attributes role stays in a Development-only overlay and the tracked binding is unchanged (decision U5). The platform's `VisualAttributes:ComponentBindingPath`/`PipelineProfilePath` stay unset in shipped Production configuration and are set by the Development runbook; the Production worker refuses unverified packs regardless. The real attribute pipeline profile moves from test fixtures to `src/vision/config/attributes/` and gains a `verify_repo` loader (vision profiles and attribute profiles are distinct loaders).

## 13. Cross-language contract

| Item | Where pinned | Rule |
|---|---|---|
| Attribute schema | Python `pipeline.py`, .NET `VisualAttributeRelease.cs` | unchanged format; real vocabulary; new vector case |
| Identity fingerprint | `visual-attribute-identity-v1.json` | unchanged derivation; add a vector with real-shaped pack ids |
| Artefact v2 | Python encoder, .NET streaming validator | new vector `visual-attribute-predictions-v2.json` (valid, abstained, all-abstained, coverage failures) |
| Worst-case bound v2 | both loaders | re-derived formula including abstention records; `visual-attribute-artifact-bound-v2.json` with accepted/refused pair |
| Abstention vocabulary | `contracts.py`, `VisualAttributeContractRules.cs` | closed set; constant-parity test (as S2b's `test_contract_constants_match_the_platform`) |
| Confidence | both | finite, [0,1]; Unknown carries none (unchanged) |
| Aggregation | **Python only** | the platform validates structure and row equality, never recomputes; golden vectors `aggregation-v2-vectors.json` consumed by Python tests only |
| Provenance | both | unchanged fields; `actualDevice` `cuda:N` exercised |

No business rule is implemented twice except where both sides must refuse the same input (schema, artefact, bound, vocabulary), and each of those is held to a shared vector.

## 14. Performance

**Derived budget.** At the 10,000-Track × 4-crop bound (40,000 crops) one attempt must finish within **half** the configured maximum analysis duration (default 6 h), so that a retry after a late failure still fits the absolute deadline: ≤ 10,800 s / 40,000 ≈ **0.27 s per crop end to end** (evidence read + verify + decode + admissibility + inference + aggregation), on the Development CPU host. A candidate over budget fails G4 unless the release profile binds CUDA for the role and it meets the budget there. Raising the deadline is a lifecycle configuration change that needs its own justification; it is never used to hide model slowness.

| Measure | How | Where |
|---|---|---|
| READY / model-load time, RSS after load | supervisor timings | S2c.7 |
| Per-crop and per-Track inference p50/p95/p99 by batch size | worker instrumentation (inference separated from evidence read and upload) | bake-off and S2c.9 |
| Evidence read time per crop | client timings | S2c.9 |
| Peak RSS; VRAM on CUDA; detector co-resident on one host | process sampling | S2c.9 |
| CPU utilisation, thread count (fixed and recorded) | sampling | S2c.9 |
| 10,000-Track run (synthetic Evidence Sets with real crop sizes) | a scale harness like S2b's timing test, driving the real worker | S2c.9 |
| Artefact size at the bound (v2) | measured vs the derived bound | S2c.5 / S2c.9 |
| Completion/publication time | unchanged S2b measurement repeated with a real identity | S2c.9 |

Batching is bounded by a byte and count cap derived from the crop bounds (≤ 160 KiB encoded, decoded ≤ 1024² × 3); the serial inference lane stays (no concurrent model entry). Worker concurrency stays one unit per process.

## 15. Offline deployment

| Item | Rule |
|---|---|
| Weights in Git | never (`verify_repo` refuses weight extensions; 10 MiB cap) |
| Acquisition | a generalised Model Pack workflow (the RTMDet workflow is hard-wired today) fetches third-party checkpoints on a connected CI runner from **pinned immutable URLs/revisions**, verifies SHA-256 against the source manifest, extracts licence notices byte-exactly, and runs `build_model_pack.py` |
| MAVI-trained artefacts | built on the owner-controlled machine from a recorded training manifest (§9.6); only their hashes are in Git; they enter the kit by hash |
| Kit | content-addressed `vision/models/<modelPackId>/`; `component-inventory.json`; the sync tool already collects every enabled pack of a role |
| Setup | `Mavi.VisionSetup.psm1` and the sync `plan` step extended from `vision` to every startable role, so the attributes packs are installed and verified by the same launcher |
| Policy | `offline-dependency-policy-v1.json`: model entries for each pack (source, licence, notice, hashes, owner); `offline-binary-inventory.md`: Model Pack rows; any new Python package: `managedSources.python`, wheelhouse, lock, and (§12.5) a new family |
| No hidden download | adapters import no hub-capable library at runtime; the learned E2E runs with outbound network denied except the platform endpoint; `HF_HUB_OFFLINE`/`TORCH_HOME`-style hooks are not relied on — absence of the code path is |
| Verification | `verify_repo` re-derives pack ids, checks licence-notice artefacts, attribute profiles and bindings; installer verifies hashes before use |

## 16. Security and trust boundary

S2b's boundary is unchanged: no filesystem access to accepted evidence, lease-scoped and lifetime-fenced reads, cross-run IDOR refused, capability never logged. S2c adds:

- **Artefact integrity before deserialisation.** Every artefact is hash-checked by the resolver before load (ADR-005 §6); state dicts load with `weights_only=True`; TorchScript/pickled full models are not accepted; converted OpenVINO models are shipped as first-party torch modules plus state dict.
- **Bounded loads.** Artefact byte caps per role in the source manifest check; JSON artefacts (preprocessing, mapping) parsed with the strict release-JSON reader and schema-validated.
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
| CUDA unavailable with `cuda` policy | UNAVAILABLE `attribute_device_unavailable:cuda`; no CPU fallback | operator-visible |
| `auto` in Development | resolves visibly; provenance records the device | — |
| Inference exception | attempt fails retryable `visual_attribute_inference_failed`; no Track outcome | retryable attempt failure |
| OOM during inference | the runner stops its heartbeat, reports `/fail` with `visual_attribute_inference_failed` (retryable), then the process exits non-zero so its launcher starts a fresh process that must reach READY again; if `/fail` cannot be delivered the lease expires and the unit is reclaimed (S2b). A degraded process never leases again | retryable + operator-visible |
| Inference timeout (per batch, `inference_timeout_seconds` in worker settings — not identity — set from the measured p99 × a recorded margin and bounded below the lease so a heartbeat cycle always fits) | same order as OOM: `/fail` retryable, then exit, because a hung native call on the inference thread cannot be cancelled and the serial lane must not be reused | retryable |
| Worker crash | lease expires; reclaim; attempts bound (S2b) | retryable |
| Capability unavailable mid-lease (device lost) | as inference exception/timeout | retryable |
| Malformed output, NaN/Inf, out-of-range | terminal `visual_attribute_output_invalid` (deterministic model defect) | terminal unit failure |
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
- **Regression corpus:** a small, licence-clean, repository-owned regression set (synthetic or owner-cleared crops, hashes only in Git, bytes in the kit) with expected Track decisions and scores within tolerance, run on every pack change.
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

Target: every S-mutant killed; equivalents recorded with the reason, as in S2b.

## 20. Acceptance-register mapping

No row changes in this planning change. At S2c exit:

| Row | S2c target | Implementation evidence | Test evidence | Qualification evidence | Retained artefacts | Limitations |
|---|---|---|---|---|---|---|
| F1 | **PASS** | annotation guide per attribute, corpus + partition manifests (hashed), sealing record | agreement computation unit tests | pilot + main agreement/adjudication report | manifests, guide, report hashes | camera count achieved |
| F3 | **PASS** if the licence review approves every component; otherwise OPEN with the review's finding | source/built manifests, notices, offline policy + inventory entries, pack build workflow | `verify_repo`, resolver, installer tests | licence review record; offline install run | built manifests, kit inventory, review | Development/unverified only |
| F9 | **PASS** | failure containment, device policy, version-skew refusal, co-residency | §17 negative tests, mutations S12, S18, S19 | co-resident run on the Development host(s) | run logs, RSS/VRAM samples | CUDA co-residency only if a GPU host was available |
| F2, F4, F5, F6, F8, F10 | contributes | — | — | validation-partition reports, model-selection record, draft requalification matrix | reports | closed by S5 on the frozen identity |
| F7 | none | — | — | — | — | needs S3 search |
| G3, G4 | contributes | Setup for the attributes role; network-denied E2E | — | disconnected run of the learned role | run record | full G3/G4 is S5 |
| G6, G7 | per S2c PR | — | exact-head CI | — | — | — |

The historical acceptance criteria are not rewritten.

## 21. Documentation reconciliation

| # | Statement | Classification | Action |
|---|---|---|---|
| R1 | Register D1–D8/E1–E4 "exact-head CI pending" | must amend before S2c implementation | separate S2b closure entry with PR #114 exact-head and post-merge evidence (this planning change only corrects the verdict text) |
| R2 | Register header/verdict "S2b … draft PR / NEXT"; E-section "E1–E4 remain OPEN until …" | must amend before | **done here** (text only) |
| R3 | Register §F had no owner | must amend before | **done here**: owner column, no status change |
| R4 | Parent plan S2b status "(draft PR, not merged)" | must amend before | **done here**; S2c status line added |
| R5 | S2a/S2b reconciliation bridge "S2b … next" | must amend before | **done here** (dated status notes) |
| R6 | Both roadmaps' Stage-2 status (S1.4 active) | must amend before | **done here** (status text) |
| R7 | Qualification plan §18 freeze order not executable | must amend before | **proposed here** as protocol revision R1 |
| R8 | ADR-013 open points (adapter, abstention, device/runtime, §9 claim-helper record) | must amend before | **proposed here** as amendment items 8–11 |
| R9 | Setup/runbooks vision-role-only (`mavi-offline-setup.md`, `Mavi.VisionSetup.psm1`) | amend during S2c | S2c.8 |
| R10 | Lifecycle runbook detector-centric wording; `local-development.md` "no attribute worker exists" | amend during S2c | S2c.8 |
| R11 | `offline-dependency-policy-v1.json` `setupIntegration` predates S2a.4; `offline-binary-inventory.md` has no Model Pack rows; CUDA CPython row imprecise | amend during S2c | S2c.6 |
| R12 | `implementation-record.md` attributes schema limits to "ADR-013 §12" | amend during S2c | S2c.5 (the limits are S2b choices) |
| R13 | `capability-implementation-roadmap.md` "Worker boundary … one ADR when stage 2 begins" | amend during S2c | mark done (ADR-013 §8) |
| R14 | S2a closure "next slice is S2b"; S2b plan/record status lines; ADR-007 v1 binding names; `windows-cuda-host-session.md` retired file names; baseline tables | historical | leave |

## 22. Implementation slices

Each slice is a reviewable PR on the S2c feature branch (or a sequence of PRs), test-first, with its own exact-head CI. Slices S2c.3 and S2c.5 are model-neutral and may run in parallel with corpus work.

| Slice | Purpose | Likely files | Tests first | Evidence | Stop conditions | Deferred |
|---|---|---|---|---|---|---|
| **S2c.0 Baseline** | S2b closure entry (R1); acceptance of ADR-013 items 8–11 and R1; record the licence-review and corpus owners | register evidence log; ADR status | — | closure entry | amendments not accepted → stop | — |
| **S2c.1 Task + corpus + labels** | corpus/partition manifest schemas and tooling (hashing, near-duplicate check, grouping); annotation guide v1; pilot; agreement tooling; vocabulary freeze; main labelling; **seal the frozen test** | `tools/qualification/attributes/corpus/`, `docs/qualification/stage2-s2c/annotation-guide.md`, manifests | manifest schema, grouping/leakage, agreement computation (known κ/α cases) | pilot + agreement report; sealed manifest hash (**F1**) | agreement too low for an attribute → the attribute is removed or merged, recorded | frozen-test scoring (S5) |
| **S2c.2 Protocol freeze** | re-run the survey; licence review of shortlisted families; commit bake-off protocol (candidates, gates, weights, MPID, strata, report format) | `docs/qualification/stage2-s2c/bake-off-protocol.md`, survey update | — | protocol hash committed before results | no family survives G1 for a task → that task is re-scoped with the owner | — |
| **S2c.3 Evaluation harness** | isolated eval environment; candidate runners; metrics; bootstrap; stratified reports; latency/memory probes | `tools/qualification/attributes/` | metrics on synthetic predictions with known answers; bootstrap determinism; runner interface | harness self-test report | — | no production code |
| **S2c.4 Bake-off** | run candidates on the validation partition; train probe heads where shortlisted; selection record per task | evidence store; `model-selection-*.md` | — | raw results, selection records | no candidate passes G1–G6 for an attribute → attribute disabled for S2c; baseline-only outcome recorded | — |
| **S2c.5 Contracts** | artefact v2, bound v2, abstention vocabulary, aggregation v2, admissibility parameters, registered manifest sections, gate sets, adapter registry (fixture as `fixture-v1`) | `attributes/{inference,predictions,pipeline,contracts}.py`, `model_manifest_v2.py`, `AttributePredictionsValidator.cs`, `VisualAttributeRelease.cs`, `VisualAttributeContractRules.cs`, vectors | vectors and validators first | vectors, mutations S6–S9, S16, S17 | — | — |
| **S2c.6 Model Packs** | source manifests, notices, pinned acquisition, generalised pack workflow, built manifests, qualification records, offline policy/inventory; Runtime Pack family only if §12.5 bar met | `models/manifests/`, `models/qualifications/`, `.github/workflows/`, `config/dependencies/`, `docs/architecture/offline-binary-inventory.md` | `verify_repo` negatives, pack-id derivation | built packs, pack ids (**F3** part) | licence review not approved → F3 stays OPEN; Development use only if the review allows evaluation use | Production promotion |
| **S2c.7 Adapters + device** | adapters for the winners; parity with the harness (same crops → same scores within tolerance); device policy; batching; timeout; OOM containment | `attributes/adapters/`, `supervisor.py`, `runner.py`, `settings.py` | parity, device, failure tests | parity report; mutations S1–S5, S11–S14, S18, S19 | parity fails → fix adapter, never retune on the frozen test | — |
| **S2c.8 Lifecycle + release** | attributes role and bindings in the shipped binding; real pipeline profile under `src/vision/config/attributes/`; `verify_repo` attribute loader; Setup/sync for the role; runbooks | binding, profile, `verify_repo.py`, `Mavi.VisionSetup.psm1`, sync tool, runbooks | integration and learned E2E (network denied) | E2E record; mutation S15 | — | S3 search |
| **S2c.9 Performance + Development execution** | 10,000-Track run; CPU on both CPU variants; CUDA and co-residency where the GPU host is available; determinism and variant equivalence | scale harness | — | performance report; ADR-009 Development evidence (**F9**) | budget missed → back to S2c.4 (next candidate) or record limitation; never relax the deadline silently | CUDA qualification |
| **S2c.10 Closure** | mutation programme, documentation reconciliation R9–R13, register evidence for F1/F3/F9, contributing reports, independent cold review | docs | — | mutation record; register entries | open P1/P2 → not done | S5 freeze and frozen-test scoring |

## 23. Risks, unresolved decisions and external dependencies

| # | Item | Owner | Blocks |
|---|---|---|---|
| U1 | **Licence review** of every shortlisted family: ImageNet-pretraining provenance of torchvision weights; OMZ training-data provenance; PA-100K images/data protection; binding force of CLIP/OpenCLIP model-card "surveillance" statements; SigLIP 2/WebLI; evaluation-only use of research datasets | owner + legal | S2c.2 (selection), F3 |
| U2 | **Corpus footage** (cameras, day/night) and **annotators** (≥ 2, one independent) | owner | S2c.1, S2c.4 |
| U3 | **Product decisions**: colour merges after the pilot; target precision per attribute; MPID; whether headwear stays a candidate | owner | S2c.1/S2c.2 (MPID), S5 (targets) |
| U4 | Development GPU host availability for CUDA evidence | owner | S2c.9 (CUDA part only) |
| U5 | Enabling the attributes role in the shipped binding moves the kit compatibility boundary (§12.6) | reviewer | S2c.8 |
| U6 | Whether truncation needs explicit crop geometry in the lease (additive field) | bake-off evidence | S2c.4 → possibly S2c.5 |
| R-a | No licence-clean candidate reaches a useful precision for colour on MAVI imagery | — | mitigated by B0 floor and MAVI-trained heads; outcome may be "attribute disabled" |
| R-b | Probe candidates need more labels than the owner can provide | — | pilot measures learning curves early |
| R-c | CPU budget excludes the most accurate backbone | — | CUDA binding for the role or a smaller tower; §9.4 decides |
| R-d | MAVI-trained artefacts cannot be rebuilt in CI | — | recorded training manifest + owner-machine rebuild check (§9.6) |

## 24. Cold review of this plan

PENDING

## 25. Scope guard

S2c changes no lifecycle state, publication protocol, evidence boundary, identity derivation, supersession rule, search, UI, detector, tracker, Evidence Set or Production gate. It adds no generic job framework, no training platform and no network path. Any change outside §4.1 needs its own ADR amendment and plan revision first.
