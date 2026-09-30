# S2c real qualification — execution record

**Governing plan:** `docs/superpowers/plans/2026-09-30-stage2-s2c-real-qualification-execution.md` (merged in PR #123, `main@d0db6efff201a003b9699cde675d8069259f980e`).
**Events:** `msr-person-attributes-2026-01`, `msr-vehicle-attributes-2026-01`; joint `eventPairId = msr-attributes-2026-01`.
**Status:** Slice A (accountable inputs and candidate manifest preparation) prepared on 2026-09-30. Slice A is **not accepted**: roles are assigned and a 2026-09-30 continuation prepared evidence, variants, an R-5 packet and draft ledgers (§4.3), but acceptance depends on human recorder/reviewer and R-5 actions that do not yet exist (§8). Slices B–J have not started. Both MSRs remain `PLANNED`. No candidate has been acquired, run, trained, tuned, measured or selected. No selection or frozen-test label has been read, and no experiment, protocol, ledger freeze, E/F/J/T, E1/E2/E3 or Model Pack exists. F1, F3 and every other F/G row keep their state.

This record holds the dated execution evidence and dispositions required by plan §18. It is not a registry. Candidate facts come from the committed survey (`model-candidate-survey.md`, 2026-09-28), the parent plan (§9.2) and the two MSRs. All figures there are class R (reported, not reproduced by MAVI). No source was re-fetched and no candidate byte was downloaded for this record (§4).

## 1. Status reconciliation (Slice A item 1)

The following statements were stale at `main@d0db6ef` and are reconciled in the same change. The reconciliation is status-only: it records the merges and promotes no acceptance row.

| File | Stale statement | Reconciled to |
|---|---|---|
| `docs/reviews/2026-09-23-visual-attributes-acceptance.md` (status line, banner, evidence log) | S2c.2b-2 "next" | b-2 architecture merged (PR #121), implementation merged (PR #122, `main@7b8913982dc6796a1676de075cf1dc22a7676891`), execution plan merged (PR #123); no row changes |
| `docs/qualification/model-selection/README.md` §14.1 | M2 "implemented for independent review; acceptance requires merge and exact-head CI" | merged in PR #122; the events remain `PLANNED` |
| `docs/qualification/stage2-s2c/s2c-2b2-implementation-record.md` | "exact-head CI and external review remain merge gates" | merged in PR #122 (final head `d45a17dd6b36e2ddb529ddaf8c8d40d52b1b782e`) |
| `docs/superpowers/plans/2026-09-28-stage2-s2c-learned-attribute-model-packs.md` §9.5 reconciliation note | b-2 "implementation is pending independent review and exact-head CI" | merged in PR #122; execution plan PR #123 |
| `docs/superpowers/plans/2026-09-23-visual-attributes.md` S2c status | as above | as above |
| `docs/superpowers/plans/capability-implementation-roadmap.md` (two status sentences) | as above | as above |
| both MSRs §0 owner row | "to be named at S2c.0" (S2c.0 closed without names) | roles and current assignments are tracked in §2 of this record |

Not claimed anywhere: an operational F1 PASS, candidate qualification, real E2, S2c closure, S5, or Production qualification. S1.4 B1–B6 remain separately governed and OPEN.

## 2. Accountable roles (Slice A item 1; owner input OI-1)

Owner assignments supplied on 2026-09-30 are recorded below. All R-1…R-7 roles are assigned. No role is defaulted to the repository owner or to the drafting agent.

| Id | Role | Responsibility in this plan | First slice that needs it | Status |
|---|---|---|---|---|
| R-1 | Accountable execution owner | owner of both events; signs owner inputs; later owner implementation choice (Slice G) | A (to accept this slice) | **Aarav — ASSIGNED 2026-09-30** |
| R-2 | Independent reviewer | reviews freeze, protocol and closure; cannot be R-1 | A (ledger history `reviewedBy`) | **Hari Om — ASSIGNED 2026-09-30** |
| R-3 | Corpus Custodian | footage custody, partitions, seal, access log, reference swatches | B | **Aarav — ASSIGNED 2026-09-30** |
| R-4 | Annotation owner and annotators (at least two, one independent) | pilot, main labelling, adjudication | B | **Aarav — annotation owner/annotator; Savita — independent annotator/reviewer; ASSIGNED 2026-09-30** |
| R-5 | Licence Review Owner | evaluation permissions now; final per-unit, per-profile determinations later | A (evaluation permission) | **Aarav — ASSIGNED 2026-09-30** |
| R-6 | Scale/Performance Evidence Owner | host profile, workload envelope, E1/E2/E3 evidence | D | **Aarav — ASSIGNED 2026-09-30** |
| R-7 | Statistical recipe reviewer | reviews the one executable b-1 recipe | B | **Hari Om — ASSIGNED 2026-09-30** |

The ledger's `classificationHistory` needs a named `recordedBy` and a different named `reviewedBy` for every entry (`tools/qualification/model_selection/credibility.py`, `history_reviewer_not_independent`). R-1 Aarav and R-2 Hari Om satisfy the identity/independence prerequisite. Their assignment does **not** itself create a classification-history action: the working ledgers still need actual dated evidence items and explicit recorder/reviewer actions (§8).

## 3. Owner-input checklist (plan §19)

Each item is **MISSING** unless an evidence reference is entered here. A missing item blocks the first slice listed and every slice after it. Nothing here is a default.

| Id | Input (plan §19 item) | Blocks from | Status | Notes |
|---|---|---|---|---|
| OI-1 | Named roles R-1…R-7 | A | **COMPLETE** | R-1 Aarav; R-2 Hari Om; R-3 Aarav; R-4 Aarav + Savita (independent); R-5 Aarav; R-6 Aarav; R-7 Hari Om (§2) |
| OI-2 | Authorized real footage; retention/access arrangements; site/camera/day/night coverage; stable raw-evidence pin; annotation time; independently reviewable custody store | B | MISSING | footage availability is not assumed |
| OI-3 | Pilot-rule confirmation; task/vocabulary/headwear decision; required attribute scope per capability; lawful fallback policy | A (scope/fallback, §6), B (pilot) | PARTIAL | owner fixed first-event scope and fallback direction (§3.1, §6); pilot/vocabulary confirmation remains for Slice B |
| OI-4 | Candidate evaluation budget; source/acquisition access (including gated terms); evaluation/fitting permissions; which committed proposals are pursued; exact checkpoint variant per family | A | PARTIAL | owner fixed the initial families and conditional acquisition authority (§3.1); variants resolved under the R-1 variant rule (§4.3.2); budget, R-5 evaluation determinations, DINOv3 gated-access acceptance and the controlled store location remain MISSING; no passwords or tokens in Git |
| OI-5 | Every numerical quality/support/slice gate; practical/NI/equivalence/MPID margins; bootstrap seed/replicates/multiplicity/undefined-denominator rule; pilot-simulation coverage tolerance and perturbations — one executable recipe | B | MISSING | no gate threshold is supplied by this record |
| OI-6 | Training/tuning search and compute budgets; calibration family; allowed parameter families; reproducibility tolerances; evidence storage capacity | B | MISSING | |
| OI-7 | Host/OS/runtime variants; detector/platform co-residency; worker range and chosen topology; lease/retry/deadline settings; resource/SLA/host/reserve limits; physical measurement access | D | MISSING | no host limit is supplied |
| OI-8 | Concrete 500-camera envelope; camera-class mix; job/crop/byte distributions; backlog/burst/loss/drain requirements; accepted representation limits | D | MISSING | no workload envelope is supplied |
| OI-9 | Separate calibration and held-out E3 traces; service-bound estimator/error settings; repetition schedule; E3 tolerances | D (calibration), I (E3) | MISSING | no E3 tolerance is supplied |
| OI-10 | Named non-commercial deployment profiles, end uses and delivery route; genuine final legal determinations for every frozen unit and fallback across every required profile (§7); CUDA host and restart-service decisions | A (profile ids), F (determinations) | MISSING | no licence determination is made here |
| OI-11 | At the decision stage only: exact owner pair within a complete T_impl; authorization for the Development integration environment | G | NOT YET APPLICABLE | no implementation choice exists or is implied |

### 3.1 Owner directions recorded 2026-09-30

These directions narrow the first execution event without freezing the protocol or creating any licence determination.

- **Required scope.** Person: upper clothing colour, lower clothing colour, backpack, bag and headwear. Vehicle: dominant body colour.
- **Fallback.** Person: `fallback: null`. Vehicle: VC-B0 only after implementation and passage of its own frozen gates; otherwise `fallback: null`. No disabled fallback is introduced for the first event.
- **Initial person families to pursue.** SigLIP 2 + MAVI heads (PC-1/PO-1); DINOv3 + MAVI heads (PC-2A/PO-2A); DINOv2 + MAVI heads (PC-2B/PO-2B); Intel OMZ 0230 plus 0234/0238 for headwear as applicable (PC-7/PO-6B/PO-6C); Awiros ConvNeXt V2-Tiny (PC-5), subject to R-5; the MAVI small-CNN route (PC-8/PO-7); and VTFPAR++ (PC-9), conditional on R-5 and Evidence-Set compatibility. Other surveyed person families stay in the record but are not prioritized for first-pass acquisition.
- **Initial vehicle families to pursue.** DINOv3 + MAVI colour head (VC-1A); DINOv2 + MAVI colour head (VC-1B); SigLIP 2 + MAVI colour head (VC-2); Intel OMZ 0042 (VC-5A); the MAVI compact-CNN route (VC-4A); and VC-B0. PP-Vehicle, OMZ 0039 and zero-shot references remain retained but are not prioritized for first-pass acquisition.
- **Variant rule.** Start with one smallest/base variant per actively pursued family that preserves the intended method and is realistically executable on the declared Development host. Do not create a multi-size bake-off unless the first variant cannot represent the method faithfully. Exact variants remain to be confirmed before pinning.
- **Acquisition authorization.** Candidate artefacts may be acquired into the controlled component/evidence store only after R-5 documents evaluation permission for that specific candidate. For every acquired artefact record exact upstream revision, filenames, SHA-256, licence source and acquisition date. No floating tags, runtime network download, credentials or model bytes are committed to Git.

These directions do not themselves mark any candidate `SHORTLISTED`, `CLEARED`, acquired or pinned.

## 4. Candidate re-survey (Slice A items 4–5)

**Method.** Every committed proposal in both MSR ledgers was re-read against the survey and parent plan §9.2. Multi-family and multi-checkpoint rows are split into individually identifiable family variants (plan §4 item 1). A checkpoint serving both person sub-tasks is one entry (ledger rule), and method entries sharing a backbone carry identical identity blocks. No new model family was introduced.

**What was not done, and why.** The survey records source URLs and licence texts, but no immutable revision, checkpoint filename or SHA-256 for any candidate. R-1 has authorized controlled acquisition for the initial families in §3.1 **only after** R-5 records evaluation permission for the specific candidate; no such permission determination exists yet. Exact variants and upstream identities are now resolved in §4.3.2, but nothing has been acquired or pinned by MAVI. Every learned candidate therefore still has an explicit **blocked** byte disposition, and no placeholder hash was written. The evaluation-permission column restates the survey's licence class (L-A…L-D, survey §6) as an **input to R-5**, not a determination. Operational-use and redistribution status is `NOT_ASSESSED` for every candidate and is recorded separately (§7).

**M1 status.** Superseded for the actively pursued set by §4.3 (2026-09-30 continuation). Draft M2 ledgers now exist for review (§4.3.5), and their classes are computed by `credibility.py`, not asserted. The committed working ledgers still do not exist, because no genuine classification-history action has been recorded (SA-B1).

**Runtime marks.** Proposed `existingGraph`/`extension` marks follow parent plan §12.7. The default is a first-party torch module on `mmdetection-phase1-v1` (torch 2.6.0 / torchvision 0.21.0): OpenVINO-IR/ONNX checkpoints are ported with a build-time parity test, and towers are loaded as state dicts (`weights_only=True`). Any other engine is an extension (a separate `attributes-<engine>-v1` family), admitted only past MPID. Every mark is **proposed** until actual bytes and dependency requirements are inspected at pinning. No dependency is added (§9).

### 4.1 Person — T-PC and T-PO components

| Id | Sub-tasks | Upstream family / variant | Kind | Runnable revision located | Evaluation permission (survey input) | Proposed runtime mark | Byte disposition | Proposed disposition and reason |
|---|---|---|---|---|---|---|---|---|
| PC-B0 | T-PC | MAVI deterministic region band + chroma cluster + CIE-Lab naming | mavi-baseline | not implemented (§5) | MAVI-owned | existingGraph | BLOCKED: §5 | shortlist when implemented |
| PC-1 | T-PC | SigLIP 2 image tower + MAVI heads (`google/siglip2-*`; size variant unselected) | method | no revision pinned | L-A (Apache-2.0) | existingGraph (state-dict tower) | BLOCKED: variant (OI-4) and acquisition | shortlist once pinned; shares identity with PO-1 |
| PO-1 | T-PO | SigLIP 2 heads on the PC-1 tower | method | as PC-1 | as PC-1 | as PC-1 | BLOCKED: as PC-1 | as PC-1 |
| PC-2A | T-PC | DINOv3 tower + MAVI heads (ViT-S/B or ConvNeXt; variant unselected) | method | no revision pinned | L-B (DINOv3 licence; ITAR/trade-control end-use condition) | existingGraph (state-dict tower) | BLOCKED: variant (OI-4), end-use review (R-5), acquisition | shortlist only if R-5 permits evaluation; shares identity with PO-2A |
| PO-2A | T-PO | DINOv3 heads on the PC-2A tower | method | as PC-2A | as PC-2A | as PC-2A | BLOCKED: as PC-2A | as PC-2A |
| PC-2B | T-PC | DINOv2 tower + MAVI heads (split from PC-2) | method | no revision pinned | L-A (Apache-2.0) | existingGraph | BLOCKED: variant (OI-4) and acquisition | shortlist once pinned; shares identity with PO-2B |
| PO-2B | T-PO | DINOv2 heads on the PC-2B tower | method | as PC-2B | as PC-2B | as PC-2B | BLOCKED: as PC-2B | as PC-2B |
| PC-3A | T-PC | PromptPAR method (OpenPAR, CLIP ViT-L/14 prompts) | method | code located, revision unpinned | code L-A (MIT); CLIP card out-of-scope statements (L-B); released checkpoints trained on restricted data (L-D) | extension likely (ViT-L/14 cost) | BLOCKED: acquisition, R-5 | method shortlist once pinned; released checkpoints `REFERENCE_ONLY` (evaluation-permission) unless R-5 permits |
| PO-3A | T-PO | PromptPAR trained on PA-100K | method | as PC-3A | as PC-3A | as PC-3A | BLOCKED: as PC-3A | as PC-3A; shares identity with PC-3A |
| PC-3B | T-PC | VTB method (ViT-B/16 + text; split from PC-3) | method | code located (MIT), no weights located | as PC-3A | existingGraph (proposed) | BLOCKED: acquisition | method shortlist once pinned |
| PO-3B | T-PO | VTB trained on PA-100K | method | as PC-3B | as PC-3B | as PC-3B | BLOCKED: as PC-3B | shares identity with PC-3B |
| PO-3C | T-PO | Strong baseline / Rethinking PAR recipe trained on PA-100K (split from PO-3) | method | code located; weights link empty; no LICENSE found | not stated (R-5) | existingGraph (ResNet-50) | BLOCKED: acquisition, R-5 | method shortlist if R-5 permits |
| PC-4A | T-PC | UPAR-trained ConvNeXt-B baseline | checkpoint | not located as a pinned release | L-C data (CC-BY-NC-SA), derived weights L-D | existingGraph (proposed) | BLOCKED: acquisition, R-5 | `REFERENCE_ONLY` (evaluation-permission) unless R-5 permits |
| PC-4B | T-PC | C2T-Net (UPAR 2024) checkpoint (split from PC-4) | checkpoint | released; revision unpinned; no LICENSE file | as PC-4A | extension likely (Swin + EVA-ViT cost) | BLOCKED: acquisition, R-5 | as PC-4A |
| PC-5 | T-PC, T-PO | Awiros person-attribute-recognition, ConvNeXt V2-Tiny ONNX (PO-4 is this entry) | checkpoint | gated; terms not obtained | L-D (terms not stated; gated) | existingGraph via torch port (proposed) | BLOCKED: gated terms (OI-4, R-5) | shortlist only if terms are obtained, else `REFERENCE_ONLY` |
| PC-6A | T-PC | OpenAI CLIP tower + MAVI heads (split from PC-6) | method | no revision pinned | L-B (card: surveillance out of scope) | existingGraph | BLOCKED: R-5, acquisition | shortlist only if R-5 permits evaluation |
| PC-6B | T-PC | OpenCLIP tower (LAION-2B / DataComp) + MAVI heads | method | no revision pinned | L-B | existingGraph | BLOCKED: R-5, acquisition | as PC-6A |
| PC-6C | T-PC | MobileCLIP 2 tower + MAVI heads | method | no revision pinned | L-C (Apple research-only; derivatives research-only) | existingGraph | BLOCKED: R-5 | expected `REFERENCE_ONLY` (evaluation-permission) unless R-5 finds the profile permitted |
| PC-6D | T-PC | MetaCLIP tower + MAVI heads | method | no revision pinned | L-C (CC-BY-NC) | existingGraph | BLOCKED: R-5 | as PC-6C |
| PC-6E | T-PC | EVA-CLIP tower + MAVI heads | method | no revision pinned | L-A (unreviewed) | existingGraph | BLOCKED: R-5, acquisition | shortlist once pinned and reviewed |
| PC-7 | T-PC, T-PO | Intel OMZ person-attributes-recognition-crossroad-0230 (colour points + Lab naming; has_bag/has_backpack/has_hat; PO-6A is this entry) | checkpoint | OMZ release; revision unpinned | L-A (Apache-2.0 via `model.yml`; training data undisclosed) | existingGraph via torch port with parity test | BLOCKED: acquisition | shortlist once pinned |
| PO-6B | T-PO | Intel OMZ 0234 (headwear; split from PO-6) | checkpoint | as PC-7 | as PC-7 | as PC-7 | BLOCKED: acquisition | shortlist once pinned, if headwear is in scope (OI-3) |
| PO-6C | T-PO | Intel OMZ 0238 (headwear) | checkpoint | as PC-7 | as PC-7 | as PC-7 | BLOCKED: acquisition | as PO-6B |
| PO-5A | T-PO | PP-Human attribute, PP-LCNet (split from PO-5) | checkpoint | PaddleDetection release; revision unpinned | code L-A; weights L-D (training data inheritance, R-5) | extension (Paddle) unless a parity-tested torch port exists | BLOCKED: R-5, acquisition | shortlist if R-5 permits evaluation, else `REFERENCE_ONLY` |
| PO-5B | T-PO | PP-Human attribute, PP-HGNet | checkpoint | as PO-5A | as PO-5A | as PO-5A | BLOCKED: as PO-5A | as PO-5A |
| PC-8 | T-PC | small CNN fine-tuned on MAVI labels (MobileNetV3 / ResNet / ConvNeXt-T; one backbone to be chosen) | method | backbone unselected | per chosen backbone (R-5) | existingGraph (torchvision backbone) | BLOCKED: backbone variant (OI-4, OI-6) | shortlist once the backbone is chosen and pinned; a second backbone is a new candidate id |
| PO-7 | T-PO | small CNN fine-tuned on PA-100K + MAVI labels | method | as PC-8 | as PC-8 (PA-100K CC-BY 4.0 stated) | as PC-8 | BLOCKED: as PC-8 | shares identity with PC-8 when the same backbone is used |
| PC-9 | T-PC, T-PO | VTFPAR++ (CLIP ViT-B/16 side-tuned on tracklets; MARS checkpoint; PO-8 is this entry) | checkpoint | located; revision unpinned | not reviewed (CLIP card L-B; MARS terms, R-5) | existingGraph (proposed) | BLOCKED: acquisition, R-5 | conditional shortlist (single- and few-crop modes), else `DEFERRED` |
| C-SEG | T-PC, T-PO | SAM 2.1 / SAM 3 / human parsing (region step) | component | — | SAM 2.1 L-A; SAM 3 L-B | — | not requested | `DEFERRED` (technical): included only by a pre-selection decision (plan §4 item 4), never because results disappoint |
| PO-B0 | T-PO | per-camera training prevalence reference | reference | — | — | — | not packageable | never a unit, component or fallback |
| R-LLMPAR, R-GVLM, R-OPENPAR, R-EVENT, R-OTHER26, R-PAR | — | as in the MSR | reference | — | — | — | — | unchanged MSR dispositions (`NOT_SHORTLISTED` / `REFERENCE_ONLY`) with their recorded reasons |

### 4.2 Vehicle — T-VC components

| Id | Upstream family / variant | Kind | Runnable revision located | Evaluation permission (survey input) | Proposed runtime mark | Byte disposition | Proposed disposition and reason |
|---|---|---|---|---|---|---|---|
| VC-B0 | MAVI deterministic body-region chroma clustering + CIE-Lab naming | mavi-baseline | not implemented (§5) | MAVI-owned | existingGraph | BLOCKED: §5 | shortlist when implemented |
| VC-1A | DINOv3 tower + MAVI colour head (split from VC-1) | method | no revision pinned | L-B (end-use condition) | existingGraph | BLOCKED: variant (OI-4), R-5, acquisition | shortlist only if R-5 permits evaluation |
| VC-1B | DINOv2 tower + MAVI colour head | method | no revision pinned | L-A | existingGraph | BLOCKED: variant, acquisition | shortlist once pinned |
| VC-2 | SigLIP 2 tower + MAVI colour head | method | no revision pinned | L-A | existingGraph | BLOCKED: variant, acquisition | shortlist once pinned; shares identity with VC-RA |
| VC-3 | PP-Vehicle PP-LCNet attribute checkpoint | checkpoint | PaddleDetection release; revision unpinned | code L-A; weights trained on VeRi (NC), L-D | extension (Paddle) unless a parity-tested torch port exists | BLOCKED: R-5, acquisition | shortlist if R-5 permits evaluation, else `REFERENCE_ONLY` |
| VC-4A | CNN fine-tuned on MAVI labels (Lima et al. recipe; backbone to be chosen) | method | backbone unselected | per backbone | existingGraph | BLOCKED: backbone variant (OI-4, OI-6) | shortlist once chosen and pinned |
| VC-4B | ViT-B/16 fine-tuned on MAVI labels (Lima et al.) | method | backbone revision unpinned | per backbone (R-5) | existingGraph | BLOCKED: acquisition | shortlist once pinned |
| VC-5A | Intel OMZ vehicle-attributes-recognition-barrier-0042 | checkpoint | OMZ release; revision unpinned | L-A (training data undisclosed) | existingGraph via torch port with parity test | BLOCKED: acquisition | shortlist once pinned |
| VC-5B | Intel OMZ vehicle-attributes-recognition-barrier-0039 (small reference; split from VC-5) | checkpoint | as VC-5A | as VC-5A | as VC-5A | BLOCKED: acquisition | shortlist once pinned |
| VC-RA | SigLIP 2 zero-shot prompts (split from VC-R) | checkpoint | as VC-2 | L-A | existingGraph | BLOCKED: as VC-2 | uncalibrated reference; selectable only if it passes every gate |
| VC-RB | CLIP zero-shot prompts | checkpoint | no revision pinned | L-B | existingGraph | BLOCKED: R-5, acquisition | as VC-RA, subject to R-5 |
| C-SEG | SAM 2.1 / SAM 3 body masks | component | — | as above | — | not requested | `DEFERRED` (technical) |
| R-VCR | other published vehicle-colour methods | reference | — | — | — | — | unchanged MSR disposition |

**Pinned versus blocked.** Pinned: **none**. Blocked: every learned candidate above (a missing variant choice, missing acquisition authority, missing evaluation permission, or several of these) and both MAVI baselines (§5). This meets the Slice A requirement of "verifiable bytes or an explicit blocked disposition" for every proposed runnable component. It does not meet the purpose of Slice A, which stays open.

### 4.3 Continuation 2026-09-30: primary evidence, variants, R-5 packet and draft ledgers

This continuation was performed by the implementation agent on 2026-09-30. It retrieved primary documents at immutable revisions and read upstream-published metadata. It **downloaded no model weights**, accepted no gated terms, used no credentials, and read no MAVI label of any partition.

**Where §4.1–§4.2 differ.** For the actively pursued set (§3.1), this section supersedes the "runnable revision", "evaluation permission" and "byte disposition" columns of §4.1–§4.2. Those tables remain the pre-continuation re-survey.

#### 4.3.1 Retrieved primary documents

Each document was retrieved on 2026-09-30 from the stated immutable location. The SHA-256 is of the retrieved bytes. The documents are third-party texts and are not committed; each is reproducible from its URL.

| Document | Immutable location | SHA-256 of retrieved bytes |
|---|---|---|
| SigLIP 2 base model card | `huggingface.co/google/siglip2-base-patch16-224` @ `75de2d55ec2d0b4efc50b3e9ad70dba96a7b2fa2` `README.md` | `39ac3705d62af9ffa1a14675b8ccb220a75f2d81acd530e564a3b1e3dfe418d8` |
| DINOv2 small model card | `huggingface.co/facebook/dinov2-small` @ `ed25f3a31f01632728cabb09d1542f84ab7b0056` `README.md` | `4c20dca454a8e5c670e8de5c7e6040f512aeca5438516f7623eedc4e3b00599c` |
| DINOv2 LICENSE | `github.com/facebookresearch/dinov2` @ `7764ea0f912e53c92e82eb78a2a1631e92725fc8` `LICENSE` | `600cc67cc4cb2f5ea317dcfc687ad1c74dc4bec8782bbe9db0afd83513b935b7` |
| DINOv3 README | `github.com/facebookresearch/dinov3` @ `6876159a11b4df116f30f667f8c9888617df0751` `README.md` | `da4e6e2fa1f2580be9a782338dc108ae68f98b6c9d10636583f97d8a340e664d` |
| DINOv3 License | same revision, `LICENSE.md` | `25d122eb8f5b880fd23c736fb6ea8018ee45c12237e00b8a86d14c653904999e` |
| OMZ LICENSE | `github.com/openvinotoolkit/open_model_zoo` @ `a6946b6d6ce42cbf4278df20275fab199655fc7d` `LICENSE` | `c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4` |
| OMZ 0230 README / model.yml | same revision, `models/intel/person-attributes-recognition-crossroad-0230/` | `1a5064c4869a696474d1416f3070ee50fbf1372e1c0cef5db0884b460ca8c70b` / `67ff0345485208ec679200cb9b3bfffdb7ce189e4ceaf8e92e9d4f081a9ae0ba` |
| OMZ 0234 README / model.yml | same revision, `…-crossroad-0234/` | `7f31e8b5a1841a293a81a3ba416a201f1d11c2fc21b84fbaa4f0022d639284b2` / `fe1de6a6e330bfdd506b49fd8ca76c4695c3f4977570aa759d461aaac107fb7f` |
| OMZ 0238 README / model.yml | same revision, `…-crossroad-0238/` | `d4acfbde0151feb9e85f0f678739ec6e14989ece741c2e95c39bf3294a79a554` / `d37996182ed4fe4d6179e50464c4db9df9b55aeacbfc4977310d67b2d6e8d8c6` |
| OMZ 0042 README / model.yml | same revision, `models/intel/vehicle-attributes-recognition-barrier-0042/` | `e94c0cdcd470f6de7721f3c922aebceb43ee19418fa156ee7c59a4e7f9f64c76` / `66de75615f6f7fd48c2ea7c3eb6d506e3bc7eb2b5a4ecc0761ca620f6f4f19d4` |
| Awiros model card | `huggingface.co/Awiros/person-attribute-recognition` @ `e43ac25dc08ac6fce65a69ca37f79a1006a48283` `README.md` | `980ad220edfae5ca62c79d0471b3f7f99ae7eac62d2ed09d63138406cf101e5b` |
| torchvision MobileNetV3 weights definition | `github.com/pytorch/vision` tag `v0.21.0` = `7af698794eded568735f9519593603c1ec889eba` `torchvision/models/mobilenetv3.py` | `f97937da6fd6767f9aa7cc022f84e5ef08e244e2300f085ab089d84ccc303ab1` |
| torchvision LICENSE | same revision, `LICENSE` | `6502f676851cfe25f8af75531dfb32375b7325b73c37e7b43741fa422893e71d` |
| OpenPAR README / LICENSE | `github.com/Event-AHU/OpenPAR` @ `15de98ac66e9e834029074d2375571b1bbd281b0` | `be1cac7a42b904e4c7b34ad43d8a9f653921139fe13b68c8eaa41905fa6d05df` / `4a83a0af74830e9e42b3d40576838ddffb481a92f7ef614bb8bfdf75da13f742` |
| VTFPAR++ README | same revision, `VTFPAR++/README.md` | `21c1fa4fa75b679528cdf91cafc565064b047947fbf9d11506c43936270a8f7a` |

#### 4.3.2 Variants resolved under the R-1 variant rule

One smallest or base CPU-realistic variant was chosen per family. No choice used any MAVI result.

"Upstream-published SHA-256" is the publisher's hub metadata for that file at that immutable revision. It is **not** a MAVI-verified hash of acquired bytes: acquisition is blocked (§4.3.4), and the pinning run must recompute and compare it.

| Family (ids) | Chosen variant | Immutable revision | Weight file | Upstream-published SHA-256 | Why this variant |
|---|---|---|---|---|---|
| SigLIP 2 (PC-1, PO-1, VC-2) | `google/siglip2-base-patch16-224` | `75de2d55ec2d0b4efc50b3e9ad70dba96a7b2fa2` | `model.safetensors` (1,500,800,904 B; includes the unused text tower) | `612923381c76ec5a9bed335d1c48827e3f2e506ac31b044b63b2031fadee6a0b` | base is the smallest SigLIP 2 size; fixed 224 px (NaFlex not chosen) |
| DINOv3 (PC-2A, PO-2A, VC-1A) | `facebook/dinov3-vits16-pretrain-lvd1689m` | `114c1379950215c8b35dfcd4e90a5c251dde0d32` | `model.safetensors` (86,406,384 B) | `4610ad75edef83e75afdebf162d148dc628045ea6cbb83d67d4708c709c4f91d` | smallest DINOv3 ViT; hub access is **gated (manual approval)** |
| DINOv2 (PC-2B, PO-2B, VC-1B) | `facebook/dinov2-small` (ViT-S/14) | `ed25f3a31f01632728cabb09d1542f84ab7b0056` | `model.safetensors` (88,249,960 B) | `ae1e99fcefd534ed978cdeb8326f08030c96e28b7a81ffcbc98a857c84d14be1` | smallest DINOv2 |
| OMZ 0230 (PC-7; PO-6A alias) | FP32 IR | OMZ `a6946b6d6ce42cbf4278df20275fab199655fc7d` | `FP32/person-attributes-recognition-crossroad-0230.{xml,bin}` | not published: `model.yml` gives SHA-384 only | FP32 for torch-port parity; the only 0230 model |
| OMZ 0234 / 0238 (PO-6B / PO-6C) | FP32 IR | as above | `FP32/…-0234.{xml,bin}`, `FP32/…-0238.{xml,bin}` | not published (SHA-384 only) | headwear models named by R-1 |
| OMZ 0042 (VC-5A) | FP32 IR | as above | `FP32/vehicle-attributes-recognition-barrier-0042.{xml,bin}` | not published (SHA-384 only) | the model named by R-1 |
| Awiros (PC-5; PO-4 alias) | single released ONNX | `e43ac25dc08ac6fce65a69ca37f79a1006a48283` | `person-attribute-recognition-model-17-attrs.onnx` (112,032,282 B) | `b5186578597bc5a783e5fca593629435d39eabcc68de36897956d0e87ba9a5ef` | the only released file; the hub is **not** gated at this revision (the 2026-09-28 survey said gated) |
| Small / compact CNN (PC-8, PO-7, VC-4A) | torchvision MobileNetV3-Small `IMAGENET1K_V1` backbone | torchvision `v0.21.0` = `7af698794eded568735f9519593603c1ec889eba` (matches the existing `torchvision==0.21.0` runtime lock) | `mobilenet_v3_small-047dcff4.pth` (10,306,551 B per server header) | not published (the filename carries an 8-hex prefix only) | smallest backbone in the parent-plan list; MAVI-trained heads do not exist yet, and no checkpoint hash is invented |
| VTFPAR++ (PC-9; PO-8 alias) | ViT-B/16 MARS checkpoint | OpenPAR `15de98ac66e9e834029074d2375571b1bbd281b0` (code) | not identifiable: cloud-drive link only | not published | **BLOCKED**: no filename or hash; MARS-trained |
| PC-B0 / VC-B0 | — | — | — | — | §5; implementation moves to C2 |

#### 4.3.3 R-5 evaluation-permission packet

This packet was prepared by the implementation agent from primary sources for R-5 (Aarav).

**Every status below is `REVIEW_PENDING`.** A candidate-specific evaluation-permission determination is a Licence Review Owner action. The agent cannot make it on R-5's behalf, and R-5 has not recorded one. The "primary-source finding" column is evidence for R-5, not a determination. The survey's L-A…L-D classes are not used as outcomes.

Evaluation permission, operational use, derivatives, redistribution and profile clearance stay separate. Every one of the last four is `NOT_ASSESSED`.

| Candidate(s) | Primary-source finding (retrieved document, §4.3.1) | What R-5 must decide | Evaluation-permission status |
|---|---|---|---|
| SigLIP 2 base (PC-1, PO-1, VC-2) | Publisher model card declares `license: apache-2.0`; the hub revision has no separate LICENSE file | whether the card-declared Apache-2.0 grant covers evaluation and fine-tuning of these weights | REVIEW_PENDING |
| DINOv2 small (PC-2B, PO-2B, VC-1B) | Model card declares `apache-2.0`; the repository LICENSE is Apache-2.0 | as above | REVIEW_PENDING |
| DINOv3 ViT-S/16 (PC-2A, PO-2A, VC-1A) | DINOv3 License §1(a) grants a limited licence to use, reproduce, distribute and create derivatives. §1(b)(v) prohibits ITAR / trade-control end uses, including military or warfare purposes. The term starts on acceptance **or access**, and hub download needs manual approval. | whether MAVI's declared end uses fall outside the prohibited uses; who may accept the agreement; whether to request access | REVIEW_PENDING (legal interpretation and gated acceptance required) |
| OMZ 0230 / 0234 / 0238 / 0042 (PC-7, PO-6B, PO-6C, VC-5A) | `model.yml` names the OMZ LICENSE (Apache-2.0; its URL points at `master`, so the pinned-revision copy was retrieved). Training data is undisclosed. | whether Apache-2.0 on these IR weights suffices for evaluation, given the undisclosed training data | REVIEW_PENDING |
| Awiros (PC-5) | Hub licence field `other`, and no licence text is present. The card states an intended use ("legitimate computer-vision research, benchmarking, and responsible video-analytics development"), not a grant. The model has gender/age heads, which must be discarded. | whether any evaluation right exists without written terms; obtaining terms from the publisher | REVIEW_PENDING (terms absent) |
| MobileNetV3-Small (PC-8, PO-7, VC-4A) | torchvision code is BSD-3-Clause. The retrieved documents state no separate terms for the ImageNet-trained weights. | whether the weights' terms (and ImageNet provenance) permit evaluation and fine-tuning | REVIEW_PENDING |
| VTFPAR++ (PC-9) | OpenPAR code is MIT. The checkpoint is trained on MARS, and the MARS terms were not retrieved. | MARS terms; whether any evaluation right attaches to the checkpoint | REVIEW_PENDING (and identity BLOCKED) |

#### 4.3.4 Acquisition and pinning result

**No artefact was acquired, and no artefact is pinned by MAVI.** Acquisition is authorized only after a documented, candidate-specific R-5 determination (§3.1), and none exists. Two further gaps block it:
- DINOv3 additionally needs a gated-access acceptance, which is a legal act for R-5 or R-1, not the agent.
- The controlled component/evidence store outside Git is not identified in this environment. Its location is an R-1/R-6 input, and nothing may be stored in Git.

Upstream-published SHA-256 identities are recorded for SigLIP 2, DINOv3, DINOv2 and Awiros (§4.3.2). The OMZ, MobileNetV3 and VTFPAR++ identities cannot be completed without acquisition, because their publishers give no SHA-256.

#### 4.3.5 Draft M2 ledgers and validator-derived classes

The two draft ledgers are **drafts, not the working ledgers**. Their paths do not match the validator's committed-ledger glob, so the repository check does not treat them as event ledgers.

| Draft | SHA-256 of the committed draft file |
|---|---|
| `ledger-drafts/msr-person-attributes-2026-01-evidence-ledger.draft.json` (35 entries) | `7761fac49acfb8572ebf47c02202efa5336325d1e375ea5cb974aa198979f658` |
| `ledger-drafts/msr-vehicle-attributes-2026-01-evidence-ledger.draft.json` (13 entries) | `375b0a51988f30b6166f4f71384f0a0d78af27aefed3b1c0c44da4bbf9efc76f` |

**Contents.**
- `methodRevision: msr-v1-m2`.
- The drafts hold every MSR-listed candidate and discovery, including retained non-pursued entries and references. Aliases (PO-4, PO-6A, PO-8) are the same entries as PC-5, PC-7 and PC-9. PO-B0 is not a ledger candidate; it is a statistical reference with no identity. The VC-1 ensemble is not an entry, because it is a composition of unidentified components.
- Evidence items are first-party documents from §4.3.1 with their retrieved SHA-256. Claims are copied only from the retrieved OMZ and Awiros documents.
- The ledgers contain no licence text (the validator's licence-blind rule refused an earlier draft that had it). All dispositions are `DISCOVERED`: nothing is `SHORTLISTED`.
- `classificationHistory` is **empty** for every entry.

**Validation.**
- Each entry passes the validator's structure, identity, evidence, claim and disposition checks. Its `classification` equals `credibility_class` and `provenance_confidence` as computed by `tools/qualification/model_selection/credibility.py`.
- Full `validate_ledger` refuses both drafts with exactly `history_required`.
- A throwaway in-memory probe with an obviously synthetic history entry (never written) validated both drafts completely. The only missing input is therefore the genuine recorder/reviewer action.

**Validator-computed classes (not asserted):**

| Class | Person | Vehicle |
|---|---|---|
| `mavi-owned` | PC-B0 | VC-B0 |
| `emerging` (High confidence; published hash) | PC-5 (Awiros) | — |
| `reference-only`, High confidence (published hash, no task-quality claim yet) | PC-1, PO-1, PC-2A, PO-2A, PC-2B, PO-2B | VC-1A, VC-1B, VC-2 |
| `reference-only`, Low confidence (no SHA-256 published) | PC-7, PO-6B, PO-6C, PC-8, PO-7, PC-9 | VC-4A, VC-5A |
| `excluded-discovery` (identity not yet recorded) | the 21 retained non-pursued entries and references | the 7 retained non-pursued entries and references |

Two consequences for shortlisting:
- A `reference-only` class for the frozen towers is the correct M1 result while no traceable task-quality claim exists for them. It cannot be shortlisted.
- PC-5 is `emerging`. Shortlisting it would need an `emergingShortlistBasis`, a second reviewer, snapshotted evidence and R-5 evaluation permission. None exists, so it stays `DISCOVERED`.

**The human action that turns a draft into a working ledger.**
1. R-2 Hari Om reviews the exact draft bytes (the hash above) against the §4.3.1 sources.
2. The recorder appends one `classificationHistory` entry per candidate, carrying the actual date, `recordedBy`, `reviewedBy`, and the `identitySha256`/`inputsSha256`/`checkpointSha256s` values that `credibility.py` computes (`document_sha256`, `classification_inputs_sha256`, `_pinned_files`).
3. The file is committed as `docs/qualification/model-selection/<capability>/<event>-evidence-ledger.json`.
4. `model_selection_check.py repository` must then pass.

The implementation agent cannot perform or attest steps 1–2.

## 5. PC-B0 / VC-B0 status and a discrepancy with the plan

The plan's Slice A says "implement PC-B0/VC-B0". Implementing either baseline now would be premature, for four reasons:
1. **Vocabulary.** Their output values are the colour vocabulary, which stays a candidate until the pilot and the owner decision (annotation guide §10; `attribute-task-v1-candidate.json`). Merges such as grey/white or silver/grey happen in Slice B.
2. **Naming reference centres.** The naming reference centres are the colour-family swatch centres produced by the Corpus Custodian (annotation guide §4; R-3 missing). Choosing Lab centroids now would invent method content.
3. **Tuned parameters.** Their admissibility floors and colour margins are operating parameters tuned on the tuning partition (execution plan §5 data-access table). That happens in C2. Any other fixed parameter, such as band geometry, belongs in the reviewed preparation recipe (Slice B), not in an unreviewed code default.
4. **Output contract.** Abstention and aggregation must be expressed through the approved v2 contracts (Slice C1, S2c.5). The parent plan places the baseline code at S2c.3 ("MAVI code (commit at S2c.3)") and its adapter at S2c.7.

**Smallest plan-faithful change.** Record both baselines as proposed `mavi-baseline` candidates with byte disposition BLOCKED. The ledger identity is `{"repository": "MAVI", "revision": "UNKNOWN"}` until the implementing commit exists. Their implementation and revision pin move to Slice C2, after the vocabulary freeze (B) and the v2 contracts (C1). Slice A's acceptance allows this ("explicit blocked disposition"), so it is **not** an EXECUTION BLOCKER. When implemented, a baseline must be deterministic, task-compatible, offline-capable, explicitly identified, covered by focused tests, and never labelled a learned or qualified model.

PO-B0 stays a training-derived reference only. It is never a unit, component or fallback.

## 6. Draft executable-unit proposals, required scope and fallback (Slice A items 7–8)

These drafts are **preparation, not freeze**. The final manifest is enumerated at freeze from the admitted shortlist under the b-2 rule: every compatible composition when tractable; otherwise a subset fixed before selection with the search limitation recorded. K=3 is only a preparation budget, and no result-time pruning is permitted. Each unit will carry exactly `unitId`, `kind`, sorted `components`, `configurationSha256`, sorted `enabledAttributes`, `extension`, `existingGraph`. `configurationSha256` cannot be computed until the configuration document exists (after training/tuning), so it is not written here. `enabledAttributes` below assume the candidate v1 attribute set. Owner direction keeps headwear in the first-event required scope.

**Person: 10 currently identifiable structural unit/baseline proposals, excluding cross-family tuples to be enumerated pre-selection from the admitted shortlist.** A selectable person composition must cover the required scope; PC-B0 remains a colour-only baseline component unless paired with an admitted T-PO component:

| Draft unit | kind | components | enabledAttributes (candidate) | extension / existingGraph (proposed) | Why it is required |
|---|---|---|---|---|---|
| U-P-SIGLIP2 | learned | PC-1, PO-1 | all five | false / true | shared backbone |
| U-P-DINOV3 | learned | PC-2A, PO-2A | all five | false / true | shared backbone |
| U-P-DINOV2 | learned | PC-2B, PO-2B | all five | false / true | shared backbone |
| U-P-PROMPTPAR | learned | PC-3A, PO-3A | all five | true / false (proposed) | shared backbone |
| U-P-VTB | learned | PC-3B, PO-3B | all five | false / true | shared backbone |
| U-P-SMALLCNN | learned | PC-8, PO-7 | all five | false / true | shared backbone (same chosen backbone) |
| U-P-AWIROS | learned | PC-5 | all five | false / true | single checkpoint covering both sub-tasks |
| U-P-OMZ0230 | learned | PC-7 (+ PO-6B or PO-6C when headwear is required) | all five | false / true | single checkpoint covering both sub-tasks |
| U-P-VTFPAR | learned | PC-9 | all five | false / true | single checkpoint covering both sub-tasks |
| U-P-B0-COLOUR | baseline | PC-B0 | upper/lower colour only | false / true | colour baseline only; not a full-scope person fallback under the current owner direction |

Cross-sub-task tuples (a T-PC component from one family with a T-PO component from another, including PC-B0 with a learned T-PO component) are enumerated at freeze from the admitted shortlist. They are not listed now because no component is admitted yet. The unit identifiers above are working labels, and the frozen `unitId` values are assigned at freeze.

**Vehicle (proposed units: 11).** Vehicle units are single-component: VC-B0, VC-1A, VC-1B, VC-2, VC-3, VC-4A, VC-4B, VC-5A, VC-5B, VC-RA and VC-RB. The ensemble variant from VC-1 (DINOv3 with CNNs) would be a multi-component unit. Its CNN members are not identified in the survey, so it is recorded as **BLOCKED** (unidentified components) and is not counted. Adding it later requires a pre-selection decision with identified components.

**Required scope (OI-3, owner direction recorded 2026-09-30).**
- Person: upper colour, lower colour, backpack, bag and headwear. Presence is present/Unknown only; there is no Absent.
- Vehicle: dominant body colour.

These are the required first-event capabilities. The vocabulary/pilot details are still finalized in Slice B and the protocol freeze remains later; this direction does not create a frozen protocol.

**Fallback policy.**
- **Person.** Owner direction for the first event is `fallback: null`. PC-B0 is colour-only and cannot cover the required T-PO scope by itself. No disabled person fallback is introduced.
- **Vehicle.** Owner direction is VC-B0 as the intended fallback **only after** it is implemented and passes its own frozen gates; until then the vehicle fallback is `null`. No disabled vehicle fallback is introduced.
- **No invented gate passes.** A disabled identity never receives conventional model-quality evidence, and no gate pass is recorded for it without the frozen rule and the evidence that rule names.

## 7. Licence-review scope (Slice A item 9)

- **What must be determined.** Final licence determinations must cover **every frozen unit, including every fallback (a disabled fallback too), across every required profile**. The builder's licence table holds all of them (`operational.implementation_sets`), and `pending` is true while any row is `NOT_ASSESSED` or `REVIEW_PENDING`.
- **Closure.** `NOT_ASSESSED` and `REVIEW_PENDING` cannot remain at `CLOSED`. A placeholder `NOT_CLEARED` for a unit that was never reviewed is prohibited, because it would be a fabricated determination.
- **Budget.** R-5 must plan review effort for losers as well as finalists.
- **Two separate questions.** Evaluation permission (needed before any byte is acquired or executed; §4 column) and final operational-use, derivative and redistribution clearance (Slice F onward) are distinct. The second never scores technical quality.
- **Nothing is adjudicated here.** No authoritative determination is present, and none is made in this record. The survey's L-A…L-D classes and §5 questions are inputs to R-5.
- **Profiles.** Profile ids are MISSING (OI-10).

## 8. Slice A blockers and acceptance

**SA-B1 — draft ledgers exist; the working ledgers need a genuine human recorder/reviewer action (EXECUTION DEPENDENCY).**
- **Done.** R-1/R-2 are named and distinct. Both draft M2 ledgers are built from dated primary evidence and pass every validator check except `history_required` (§4.3.5).
- **Remaining.** No classification-history action exists. The implementation agent cannot truthfully record Hari Om's review or Aarav's recording, so no working `<event>-evidence-ledger.json` is committed, and `model_selection_check.py repository` still does not exercise an event ledger.
- **Smallest resolution.** R-2 reviews the draft bytes; the recorder appends genuine dated history entries and commits the working ledgers (§4.3.5 steps 1–4).

**SA-B2 — no candidate bytes acquired or pinned by MAVI (EXECUTION DEPENDENCY: R-5 determinations, gated terms, store location).**
- **Done.** Variants are resolved for every pursued family. Immutable revisions and upstream-published SHA-256 values are recorded where the publisher provides them (SigLIP 2, DINOv3, DINOv2, Awiros). An R-5 evidence packet is prepared (§4.3.2–§4.3.3).
- **Remaining.**
  - Every candidate-specific R-5 evaluation-permission determination is still `REVIEW_PENDING`.
  - DINOv3 access acceptance is still required.
  - The controlled component-store location is unidentified.
  - OMZ, MobileNetV3 and VTFPAR++ publish no SHA-256.
  - VTFPAR++ has no identifiable checkpoint file.
- **Smallest resolution.**
  1. R-5 records a dated determination per candidate.
  2. R-1/R-6 name the controlled store.
  3. For each permitted candidate, a controlled acquisition run fetches the exact file at the recorded revision into that store, computes SHA-256, compares it with any published value, and records the acquisition date.

**SA-B3 — baselines not implemented (plan sequencing).** See §5. The implementation moves to C2. This is not an execution blocker.

**Acceptance checklist.**

| Slice A acceptance item | State |
|---|---|
| every proposed runnable component has verifiable bytes or an explicit blocked disposition | met: nothing is acquired, and each pursued component has an exact blocked reason (§4.3.2–§4.3.4) |
| ledger validator passes | **not met**: the drafts fail only `history_required`, and no working ledger is committed (SA-B1) |
| no fixture incumbent / PO-B0 unit | met: the fixture is not a candidate; PO-B0 is in no unit, fallback or ledger entry (§4, §4.3.5, §6) |
| required roles assigned | met (§2) |
| candidate acquisition and identity auditable | partial: retrieved documents and upstream identities are recorded with SHA-256 and immutable revisions (§4.3.1–§4.3.2); no acquisition exists yet to audit (SA-B2) |
| no unresolved owner input silently defaulted | met: supplied inputs are explicit and remaining inputs stay PARTIAL/MISSING (§2, §3) |

Slice A therefore stays **OPEN**. Slice B may not start candidate corpus execution, and no later slice may start, until the SA-B1 human ledger actions and the SA-B2 R-5 determinations and controlled acquisition are completed, this record is updated, and the result is reviewed.

## 9. Dependencies and offline policy

No library, SDK, runtime, native binary or model prerequisite is introduced by Slice A. `config/dependencies/offline-dependency-policy-v1.json` and `offline-binary-catalog-v1.json` are unchanged, and the detector/vision runtime lock is not widened. Any candidate that turns out to need another engine is an extension that goes through its own `attributes-<engine>-v1` family, locks, notices and policy entries in the slice that introduces it (parent §12.7; AGENTS.md).
