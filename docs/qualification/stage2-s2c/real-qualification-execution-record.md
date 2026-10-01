# S2c real qualification — execution record

**Governing plan:** `docs/superpowers/plans/2026-09-30-stage2-s2c-real-qualification-execution.md` (merged in PR #123, `main@d0db6efff201a003b9699cde675d8069259f980e`).
**Events:** `msr-person-attributes-2026-01`, `msr-vehicle-attributes-2026-01`; joint `eventPairId = msr-attributes-2026-01`.
**Status:** Slice A (accountable inputs and candidate manifest preparation) is **ACCEPTED 2026-09-30**. SA-B1 is resolved (§4.3.6–§4.3.7), and SA-B2 is resolved by the reviewed completed controlled-acquisition manifest (§4.3.11). Every R-5-permitted first-pass artefact is pinned in the controlled store; non-permitted/pending candidates remain explicitly blocked. Slices B–J have not started. Both MSRs remain `PLANNED`. No candidate has been run, trained, tuned, measured or selected. No selection or frozen-test label has been read, and no experiment, protocol, ledger freeze, E/F/J/T, E1/E2/E3 or Model Pack exists. F1, F3 and every other F/G row keep their state.

This record holds the dated execution evidence and dispositions required by plan §18. It is not a registry. Candidate facts come from the committed survey (`model-candidate-survey.md`, 2026-09-28), the parent plan (§9.2), the two MSRs and the retained controlled-acquisition evidence (§4.3.11). Reported survey figures remain class R unless separately reproduced by MAVI. Candidate bytes stay outside Git in the designated controlled store.

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

### 2.1 Reassignment from 2026-10-01 (prospective)

The table above is the historical record of the 2026-09-30 assignments. Actions taken under it stay attributed as recorded. On 2026-10-01 the owner changed two roles and made two new appointments; the record is `s2c-owner-decisions-2026-10-01.md` §1:
- R-1 is **Hari Om** from 2026-10-01 (Aarav until 2026-09-30).
- R-3 is **Hari Om** from 2026-10-01 (Aarav until 2026-09-30).
- Hari Om is appointed **footage rights reviewer** and **footage privacy reviewer**. These appointments are not a blanket permission or admission: per-file determinations are still required.

R-2, R-4, R-5, R-6, R-7 and every R-5 model-licence determination (§4.3.8) are unchanged.

**Independence.** R-2 "cannot be R-1", and from 2026-10-01 Hari Om holds both. R-2 and R-7 are therefore conflicted for freeze, protocol and closure review, for recipe review, for review of new ledger history or shortlist decisions that Hari Om records or decides, and for review of the custodian's seal and access log. The owner must assign a separate independent reviewer before any of those actions. No reviewer is named here. Hari Om's R-2 review of 2026-09-30 (§4.3.6) remains valid. See `s2c-owner-decisions-2026-10-01.md` §2.

## 3. Owner-input checklist (plan §19)

Each item is **MISSING** unless an evidence reference is entered here. `Blocks from` identifies the first dependent action for the unresolved part of that input; rows may be `PARTIAL` when an earlier-slice portion is satisfied and a later-slice portion remains open. A missing or partial value blocks that dependent action, but it does not retroactively fail an earlier slice whose governing acceptance explicitly permits unresolved later inputs or an explicit blocked disposition. Nothing here is a default.

| Id | Input (plan §19 item) | Blocks from | Status | Notes |
|---|---|---|---|---|
| OI-1 | Named roles R-1…R-7 | A; independent review from B (recipe) and D (freeze) | **COMPLETE** for Slice A (2026-09-30); **PARTIAL** from 2026-10-01 | 2026-09-30: R-1 Aarav; R-2 Hari Om; R-3 Aarav; R-4 Aarav + Savita (independent); R-5 Aarav; R-6 Aarav; R-7 Hari Om (§2). From 2026-10-01: R-1 and R-3 Hari Om, and an independent reviewer separate from Hari Om is MISSING for the actions listed in §2.1 |
| OI-2 | Authorized real footage; retention/access arrangements; site/camera/day/night coverage; stable raw-evidence pin; annotation time; independently reviewable custody store | B | MISSING | footage availability is not assumed |
| OI-3 | Pilot-rule confirmation; task/vocabulary/headwear decision; required attribute scope per capability; lawful fallback policy | A (scope/fallback, §6), B (pilot) | PARTIAL | owner fixed first-event scope and fallback direction (§3.1, §6); pilot/vocabulary confirmation remains for Slice B |
| OI-4 | Candidate evaluation budget; source/acquisition access (including gated terms); evaluation/fitting permissions; which committed proposals are pursued; exact checkpoint variant per family | A (scope/access/permissions), C2 (evaluation budget) | PARTIAL | the A-stage portion is complete: owner fixed the initial families and conditional acquisition authority (§3.1); variants are resolved (§4.3.2); R-5 determinations are recorded (§4.3.8); the controlled store is designated and every permitted first-pass artefact is acquired/verified (§4.3.11). Awiros, MobileNetV3-Small and VTFPAR++ stay REVIEW_PENDING; DINOv3 is NOT_PERMITTED_FOR_EVALUATION and gated access is NOT APPROVED. Candidate evaluation budget remains explicitly unspecified for C2; no password/token/model byte is stored in Git |
| OI-5 | Every numerical quality/support/slice gate; practical/NI/equivalence/MPID margins; bootstrap seed/replicates/multiplicity/undefined-denominator rule; pilot-simulation coverage tolerance and perturbations — one executable recipe | B | MISSING | no gate threshold is supplied by this record |
| OI-6 | Training/tuning search and compute budgets; calibration family; allowed parameter families; reproducibility tolerances; evidence storage capacity | B | MISSING | |
| OI-7 | Host/OS/runtime variants; detector/platform co-residency; worker range and chosen topology; lease/retry/deadline settings; resource/SLA/host/reserve limits; physical measurement access | D | MISSING | no host limit is supplied |
| OI-8 | Concrete 500-camera envelope; camera-class mix; job/crop/byte distributions; backlog/burst/loss/drain requirements; accepted representation limits | D | MISSING | no workload envelope is supplied |
| OI-9 | Separate calibration and held-out E3 traces; service-bound estimator/error settings; repetition schedule; E3 tolerances | D (calibration), I (E3) | MISSING | no E3 tolerance is supplied |
| OI-10 | Named non-commercial deployment profiles, end uses and delivery route; genuine final legal determinations for every frozen unit and fallback across every required profile (§7); CUDA host and restart-service decisions | D (profile ids before final freeze), F (determinations) | MISSING | no profile id or final per-profile licence determination is supplied here; Slice A records only bounded evaluation permission (§4.3.8) |
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

**Current byte state.** R-5 evaluation permission is recorded in §4.3.8. The designated controlled store and acquisition tooling are recorded in §4.3.9–§4.3.10, and the reviewed completed manifest in §4.3.11 pins every permitted first-pass artefact with immutable revision, exact filename, local SHA-256, size and publisher-integrity checks where available. Pending/not-permitted candidates remain explicitly blocked and unacquired. Operational-use and redistribution clearance remain separate later-stage determinations (§7).

**M1 status.** Superseded for the actively pursued set by §4.3 (2026-09-30 continuation). The working M2 ledgers are committed and validate (§4.3.7); their classes are computed by `credibility.py`, not asserted. Acquisition evidence is separate from M1 credibility and does not alter any class or disposition.

**Runtime marks.** Proposed `existingGraph`/`extension` marks follow parent plan §12.7. The default is a first-party torch module on `mmdetection-phase1-v1` (torch 2.6.0 / torchvision 0.21.0): OpenVINO-IR/ONNX checkpoints are ported with a build-time parity test, and towers are loaded as state dicts (`weights_only=True`). Any other engine is an extension (a separate `attributes-<engine>-v1` family), admitted only past MPID. Every mark is **proposed** until actual bytes and dependency requirements are inspected at pinning. No dependency is added (§9).

### 4.1 Person — T-PC and T-PO components

| Id | Sub-tasks | Upstream family / variant | Kind | Runnable revision located | Evaluation permission (survey input) | Proposed runtime mark | Byte disposition | Proposed disposition and reason |
|---|---|---|---|---|---|---|---|---|
| PC-B0 | T-PC | MAVI deterministic region band + chroma cluster + CIE-Lab naming | mavi-baseline | not implemented (§5) | MAVI-owned | existingGraph | BLOCKED: §5 | shortlist when implemented |
| PC-1 | T-PC | SigLIP 2 image tower + MAVI heads (`google/siglip2-base-patch16-224`, §4.3.2) | method | variant resolved in §4.3.2 (not acquired) | L-A (Apache-2.0) | existingGraph (state-dict tower) | BLOCKED: R-5 determination and acquisition (§4.3.4) | shortlist once pinned; shares identity with PO-1 |
| PO-1 | T-PO | SigLIP 2 heads on the PC-1 tower | method | as PC-1 | as PC-1 | as PC-1 | BLOCKED: as PC-1 | as PC-1 |
| PC-2A | T-PC | DINOv3 tower + MAVI heads (ViT-S/16 LVD-1689M, §4.3.2) | method | variant resolved in §4.3.2 (not acquired); hub access gated | L-B (DINOv3 licence; ITAR/trade-control end-use condition) | existingGraph (state-dict tower) | BLOCKED: end-use review (R-5), acquisition | shortlist only if R-5 permits evaluation; shares identity with PO-2A |
| PO-2A | T-PO | DINOv3 heads on the PC-2A tower | method | as PC-2A | as PC-2A | as PC-2A | BLOCKED: as PC-2A | as PC-2A |
| PC-2B | T-PC | DINOv2 tower + MAVI heads (split from PC-2; ViT-S/14, §4.3.2) | method | variant resolved in §4.3.2 (not acquired) | L-A (Apache-2.0) | existingGraph | BLOCKED: R-5 determination and acquisition (§4.3.4) | shortlist once pinned; shares identity with PO-2B |
| PO-2B | T-PO | DINOv2 heads on the PC-2B tower | method | as PC-2B | as PC-2B | as PC-2B | BLOCKED: as PC-2B | as PC-2B |
| PC-3A | T-PC | PromptPAR method (OpenPAR, CLIP ViT-L/14 prompts) | method | code located, revision unpinned | code L-A (MIT); CLIP card out-of-scope statements (L-B); released checkpoints trained on restricted data (L-D) | extension likely (ViT-L/14 cost) | BLOCKED: acquisition, R-5 | method shortlist once pinned; released checkpoints `REFERENCE_ONLY` (evaluation-permission) unless R-5 permits |
| PO-3A | T-PO | PromptPAR trained on PA-100K | method | as PC-3A | as PC-3A | as PC-3A | BLOCKED: as PC-3A | as PC-3A; shares identity with PC-3A |
| PC-3B | T-PC | VTB method (ViT-B/16 + text; split from PC-3) | method | code located (MIT), no weights located | as PC-3A | existingGraph (proposed) | BLOCKED: acquisition | method shortlist once pinned |
| PO-3B | T-PO | VTB trained on PA-100K | method | as PC-3B | as PC-3B | as PC-3B | BLOCKED: as PC-3B | shares identity with PC-3B |
| PO-3C | T-PO | Strong baseline / Rethinking PAR recipe trained on PA-100K (split from PO-3) | method | code located; weights link empty; no LICENSE found | not stated (R-5) | existingGraph (ResNet-50) | BLOCKED: acquisition, R-5 | method shortlist if R-5 permits |
| PC-4A | T-PC | UPAR-trained ConvNeXt-B baseline | checkpoint | not located as a pinned release | L-C data (CC-BY-NC-SA), derived weights L-D | existingGraph (proposed) | BLOCKED: acquisition, R-5 | `REFERENCE_ONLY` (evaluation-permission) unless R-5 permits |
| PC-4B | T-PC | C2T-Net (UPAR 2024) checkpoint (split from PC-4) | checkpoint | released; revision unpinned; no LICENSE file | as PC-4A | extension likely (Swin + EVA-ViT cost) | BLOCKED: acquisition, R-5 | as PC-4A |
| PC-5 | T-PC, T-PO | Awiros person-attribute-recognition, ConvNeXt V2-Tiny ONNX (PO-4 is this entry) | checkpoint | released revision located (§4.3.2); hub not gated at that revision (the 2026-09-28 survey said gated) | L-D (hub licence `other`; no grant text located) | existingGraph via torch port (proposed) | BLOCKED: licence terms unresolved; R-5 determination pending (§4.3.3) | shortlist only if terms are obtained, else `REFERENCE_ONLY` |
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
| PC-8 | T-PC | small CNN fine-tuned on MAVI labels (torchvision MobileNetV3-Small backbone, §4.3.2) | method | variant resolved in §4.3.2 (not acquired); backbone SHA-256 not published | per chosen backbone (R-5) | existingGraph (torchvision backbone) | BLOCKED: R-5 determination and acquisition; heads not yet trained (§4.3.2–§4.3.4) | shortlist once the backbone is chosen and pinned; a second backbone is a new candidate id |
| PO-7 | T-PO | small CNN fine-tuned on PA-100K + MAVI labels | method | as PC-8 | as PC-8 (PA-100K CC-BY 4.0 stated) | as PC-8 | BLOCKED: as PC-8 | shares identity with PC-8 when the same backbone is used |
| PC-9 | T-PC, T-PO | VTFPAR++ (CLIP ViT-B/16 side-tuned on tracklets; MARS checkpoint; PO-8 is this entry) | checkpoint | located; revision unpinned | not reviewed (CLIP card L-B; MARS terms, R-5) | existingGraph (proposed) | BLOCKED: acquisition, R-5 | conditional shortlist (single- and few-crop modes), else `DEFERRED` |
| C-SEG | T-PC, T-PO | SAM 2.1 / SAM 3 / human parsing (region step) | component | — | SAM 2.1 L-A; SAM 3 L-B | — | not requested | `DEFERRED` (technical): included only by a pre-selection decision (plan §4 item 4), never because results disappoint |
| PO-B0 | T-PO | per-camera training prevalence reference | reference | — | — | — | not packageable | never a unit, component or fallback |
| R-LLMPAR, R-GVLM, R-OPENPAR, R-EVENT, R-OTHER26, R-PAR | — | as in the MSR | reference | — | — | — | — | unchanged MSR dispositions (`NOT_SHORTLISTED` / `REFERENCE_ONLY`) with their recorded reasons |

### 4.2 Vehicle — T-VC components

| Id | Upstream family / variant | Kind | Runnable revision located | Evaluation permission (survey input) | Proposed runtime mark | Byte disposition | Proposed disposition and reason |
|---|---|---|---|---|---|---|---|
| VC-B0 | MAVI deterministic body-region chroma clustering + CIE-Lab naming | mavi-baseline | not implemented (§5) | MAVI-owned | existingGraph | BLOCKED: §5 | shortlist when implemented |
| VC-1A | DINOv3 tower + MAVI colour head (split from VC-1; ViT-S/16, §4.3.2) | method | variant resolved in §4.3.2 (not acquired); hub access gated | L-B (end-use condition) | existingGraph | BLOCKED: R-5, acquisition | shortlist only if R-5 permits evaluation |
| VC-1B | DINOv2 tower + MAVI colour head (ViT-S/14, §4.3.2) | method | variant resolved in §4.3.2 (not acquired) | L-A | existingGraph | BLOCKED: R-5, acquisition | shortlist once pinned |
| VC-2 | SigLIP 2 tower + MAVI colour head (base patch16-224, §4.3.2) | method | variant resolved in §4.3.2 (not acquired) | L-A | existingGraph | BLOCKED: R-5, acquisition | shortlist once pinned; shares identity with VC-RA |
| VC-3 | PP-Vehicle PP-LCNet attribute checkpoint | checkpoint | PaddleDetection release; revision unpinned | code L-A; weights trained on VeRi (NC), L-D | extension (Paddle) unless a parity-tested torch port exists | BLOCKED: R-5, acquisition | shortlist if R-5 permits evaluation, else `REFERENCE_ONLY` |
| VC-4A | CNN fine-tuned on MAVI labels (torchvision MobileNetV3-Small backbone, §4.3.2) | method | variant resolved in §4.3.2 (not acquired); backbone SHA-256 not published | per backbone | existingGraph | BLOCKED: R-5, acquisition; heads not yet trained | shortlist once chosen and pinned |
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

Retained, non-prioritized entries: documents retrieved on 2026-09-30 during the provenance repair (§4.3.5). Retrieval here records provenance only; it changes no acquisition priority.

| Document | Immutable location | SHA-256 of retrieved bytes |
|---|---|---|
| PromptPAR README | OpenPAR @ `15de98ac66e9e834029074d2375571b1bbd281b0` `PromptPAR/README.md` | `8a5b2db9ac4d2632c90ad6cb3e5ea460b1beb32b885fad6be2f60cb8317747bb` |
| VTB README | `github.com/cxh0519/VTB` @ `669153bc1dae3217e1d937e215481e18d19d8947` `README.md` | `0917059930e770a1f692eb4be7f7273406121e05ebbfb3342058ca6db6131cfa` |
| Rethinking-PAR README | `github.com/valencebond/Rethinking_of_PAR` @ `5f09ea67778ff8a3d83b2bb9a4a9b998df0c4333` `README.md` | `4ea1394e35792d6b14e1522d775660d21d0988de91294f82e75db95199c6c601` |
| UPAR README | `github.com/speckean/upar_challenge` @ `d79c1916a12b362433ef880900af525ecce479c1` `README.md` | `d14bee08cb07d2f11fe7fcac7d8cd983fabe8ef758b0d78421ed05b841feb491` |
| C2T-Net README | `github.com/caodoanh2001/upar_challenge` @ `fd31f39f6d7ed8175c5f876af5e3b7f863e8eab2` `README.md` | `77020b2b0ee9469305412f69f1a43d0ec827bc68cec38a963e3011b7be8ead8e` |
| OpenAI CLIP README / model card | `github.com/openai/CLIP` @ `d05afc436d78f1c48dc0dbf8e5980a9d471f35f6` | `f82c5c75e140532eb37a7d943921e1bdd57d740c6b40d0030985bc5b5d11d6f1` / `7baf04f60c6234b301ec2c9ca39e67a3ca54b47c05e9509bddf732cbcbec8b7f` |
| OpenCLIP README | `github.com/mlfoundations/open_clip` @ `8e9b7f4c3fc7deceef098e76840804a19d4adefc` | `1161fd4bd0a9c5588eab7fd6d62023a1c04a7d175b772fccb30711c422efefaf` |
| MobileCLIP README | `github.com/apple/ml-mobileclip` @ `48faa0fea4b08d74188b3841771aca6ff2c92852` | `ee6649a0fa45635dcd6a7b543dec5cc3ac64e017186e70199348f0f4a8cef62e` |
| MetaCLIP README | `github.com/facebookresearch/MetaCLIP` @ `f47f7841f6a91cc5676729a3d125519393d87d1e` | `ae5bc434c348828b6c1947e03d44751ae260db9d3f476270faa5159a048aa030` |
| EVA-CLIP hub card | `huggingface.co/QuanSun/EVA-CLIP` @ `11afd202f2ae80869d6cef18b1ec775e79bd8d12` `README.md` | `ceed3974499d78844d627b4a127be3c88ec0edf1661c912945d668ba87ace709` |
| PP-Human attribute doc | PaddleDetection `release/2.8` = `7a4fc2578e9542d94df12907c10ec3b449be5f1e` `deploy/pipeline/docs/tutorials/pphuman_attribute_en.md` | `4cfd83cefcadd8898e410de0d331b59e7414273d2c5e7ea48d543d918c9aee46` |
| PP-Vehicle attribute doc | PaddleDetection `release/2.6` = `7fde274c27a4a01fd88cbc53348bb05ed9b38313` `…/ppvehicle_attribute.md` | `7dfe183e80e5eeac22bc79b252faa7d4cff1fb2b6c58960767d4e9440d3e7a0b` |
| OMZ 0039 README / model.yml | OMZ @ `a6946b6d6ce42cbf4278df20275fab199655fc7d` `models/intel/vehicle-attributes-recognition-barrier-0039/` | `027ceb592bf5d96070b7ed771db32c35c6a00ddb43e83505f5ab1b81fd5a7521` / `101d05d2c3653fdc32ca4692e68d69d4136c80dedf6a6390a040d1a1ff9b5be7` |

The VTB backbone file is resolved to its hosting tag: timm `v0.1-vitjx` = `7613094fb5cb960813f606a5c42e3c00c961bc8f`, `jx_vit_base_p16_224-80ecf9dd.pth`, SHA-256 not published.

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
| `ledger-drafts/msr-person-attributes-2026-01-evidence-ledger.draft.json` (35 entries) | `38c9d55790027d447e7952de57e41a2d8845c8b5b36a96ff0c4076b01284a9c6` |
| `ledger-drafts/msr-vehicle-attributes-2026-01-evidence-ledger.draft.json` (13 entries) | `6160bdd47098c350f2f9a69599eb09ebf1159985b442e8381c5f584fed573c85` |

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

**Provenance repair (2026-09-30).** An independent review found a P2: the first drafts had omitted provenance the committed material already supported for retained, non-prioritized entries, and those entries computed `excluded-discovery` only because of the omission.

The repaired drafts carry forward, from the committed survey and the retrieved first-party documents above, each entry's:
- upstream repository and immutable revision;
- publisher and author group;
- publication;
- first-party README/card evidence with its SHA-256.

Acquisition priority is kept separate: those entries carry the caveat "Retained discovery; not prioritized for first-pass acquisition", and the owner's first-pass set is unchanged. Unpinned files keep `sha256: UNKNOWN`, every disposition stays `DISCOVERED`, and every class is recomputed by `credibility.py`.

**Validator-computed classes (not asserted):**

| Class | Person | Vehicle |
|---|---|---|
| `mavi-owned` | PC-B0 | VC-B0 |
| `emerging` (High confidence; published hash) | PC-5 (Awiros) | — |
| `reference-only`, High confidence (published hash, no task-quality claim yet) | PC-1, PO-1, PC-2A, PO-2A, PC-2B, PO-2B | VC-1A, VC-1B, VC-2, VC-RA (shares the VC-2 identity) |
| `reference-only`, Low confidence (no SHA-256 published or variant not selected) | PC-7, PO-6B, PO-6C, PC-8, PO-7, PC-9, PC-3A, PO-3A, PC-3B, PO-3B, PC-4B, PC-6A, PC-6B, PC-6C, PC-6D, PC-6E, PO-5A, PO-5B | VC-4A, VC-5A, VC-3, VC-5B, VC-RB |
| `excluded-discovery` | PO-3C, PC-4A, R-LLMPAR, C-SEG, R-GVLM, R-OPENPAR, R-EVENT, R-OTHER26, R-PAR | VC-4B, C-SEG, R-VCR |

**Why the remaining `excluded-discovery` entries are legitimate.** Each follows from genuinely unknown identity inputs, not omission:
- **PO-3C.** The retrieved README does not state the backbone checkpoint source, so the method's identity (its backbone) is UNKNOWN. Its authors, publication and method code are recorded.
- **PC-4A.** No released UPAR ConvNeXt-B checkpoint is located. Its authors, publication and README evidence are recorded.
- **R-LLMPAR and VC-4B.** The committed material gives only the publication. No code/checkpoint source or author group is recorded, and nothing was retrieved for them in this pass.
- **C-SEG, the grouped R-* references and R-VCR.** Each groups several alternative families, so no single identity exists until an entry is split before selection.

Two consequences for shortlisting:
- A `reference-only` class for the frozen towers is the correct M1 result while no traceable task-quality claim exists for them. It cannot be shortlisted.
- PC-5 is `emerging`. Shortlisting it would need an `emergingShortlistBasis`, a second reviewer, snapshotted evidence and R-5 evaluation permission. None exists, so it stays `DISCOVERED`.

**The human action that turns a draft into a working ledger.**
1. R-2 Hari Om reviews the exact draft bytes (the hash above) against the §4.3.1 sources.
2. The recorder appends one `classificationHistory` entry per candidate, carrying the actual date, `recordedBy`, `reviewedBy`, and the `identitySha256`/`inputsSha256`/`checkpointSha256s` values that `credibility.py` computes (`document_sha256`, `classification_inputs_sha256`, `_pinned_files`).
3. The file is committed as `docs/qualification/model-selection/<capability>/<event>-evidence-ledger.json`.
4. `model_selection_check.py repository` must then pass.

The implementation agent cannot perform or attest the recorder action in step 2.

#### 4.3.6 R-2 independent review approval — 2026-09-30

Hari Om, acting as R-2 Independent Reviewer, explicitly approved the repaired draft ledgers after the independent delta review on exact PR head `002803fc1f3ebf56cb309e7581781fc8d0fa97c4`.

The approval is bound to these exact committed draft bytes:
- person draft: `38c9d55790027d447e7952de57e41a2d8845c8b5b36a96ff0c4076b01284a9c6`;
- vehicle draft: `6160bdd47098c350f2f9a69599eb09ebf1159985b442e8381c5f584fed573c85`.

This approval records the R-2 review action only. It does **not** create any `classificationHistory` entry, does not act as the recorder, does not make any R-5 evaluation-permission or licence determination, and does not authorize candidate acquisition. Any change to either draft after the approved hashes requires a fresh R-2 review before those changed bytes can be used to create the working ledgers.

#### 4.3.7 Recorder action and working M2 ledgers — 2026-09-30

R-1 Aarav approved and performed the recorder action for the exact R-2-approved draft bytes (§4.3.6). The drafts were re-verified as `38c9d557…84a9c6` (person) and `6160bdd4…573c85` (vehicle) before use.

**What was written.** One initial `classificationHistory` entry per candidate, **48 in total** (35 person, 13 vehicle), each with:
- `at: 2026-09-30`, `from: null`;
- `to` equal to the validator-computed class already in the approved draft;
- `evidenceIds` naming the entry's evidence items;
- `recordedBy: "Aarav"`, `reviewedBy: "Hari Om"`;
- `identitySha256`, `inputsSha256` and `checkpointSha256s` computed by `credibility.py` (`document_sha256`, `classification_inputs_sha256`, `_pinned_files`; `[]` for the MAVI baselines).

No candidate field, evidence item, classification or disposition differs from the approved drafts. The drafts stay unchanged as retained review evidence.

**Working ledgers.**

| Working ledger | File SHA-256 | Canonical document SHA-256 |
|---|---|---|
| `docs/qualification/model-selection/person-attributes/msr-person-attributes-2026-01-evidence-ledger.json` (35 entries) | `b69b78b9464f1d72a535853d3af60d7dc52fafb8410741073c22493349e5783e` | `76959f5352336cf5dad0571ddf3a3031e7474c207c1c35a50a5244c52c18480b` |
| `docs/qualification/model-selection/vehicle-attributes/msr-vehicle-attributes-2026-01-evidence-ledger.json` (13 entries) | `a1ba4e04592d0f28db6b0c5c554cac8e30aca9e25baf4a9170e42a2dbba9d11f` | `a1536ef67a5d74f2060d57dc0112fee5a5e6cc7831bd253faa66ad067b7a7368` |

**Validation.** `model_selection_check.py ledger` validates both ledgers in full, and `model_selection_check.py repository` now checks both. Classes are unchanged from §4.3.5:
- person: 1 `mavi-owned`, 1 `emerging`, 24 `reference-only`, 9 `excluded-discovery`;
- vehicle: 1 `mavi-owned`, 9 `reference-only`, 3 `excluded-discovery`.

**Scope.** Every disposition stays `DISCOVERED`; nothing is shortlisted. These are working ledgers, not frozen ledgers: no `-frozen` copy exists, and no protocol cites them. This action makes no R-5 determination, authorizes no acquisition, and starts no Slice B work.

#### 4.3.8 R-5 evaluation-permission determinations — 2026-09-30

Aarav, acting as R-5 Licence Review Owner, reviewed the candidate-specific evidence packet and explicitly agreed to the following bounded Development-evaluation determinations. These decisions govern acquisition/evaluation permission only. They do not provide Production, operational-use, derivative, redistribution, Model Pack or deployment-profile clearance, and they do not alter M1 credibility or technical ranking.

| Candidate family | MAVI ids | R-5 determination |
|---|---|---|
| SigLIP 2 base patch16-224 | PC-1, PO-1, VC-2 | `PERMITTED_FOR_EVALUATION` |
| DINOv2 ViT-S/14 | PC-2B, PO-2B, VC-1B | `PERMITTED_FOR_EVALUATION` |
| DINOv3 ViT-S/16 LVD-1689M | PC-2A, PO-2A, VC-1A | `NOT_PERMITTED_FOR_EVALUATION` |
| Intel OMZ 0230 | PC-7 | `PERMITTED_FOR_EVALUATION` |
| Intel OMZ 0234 | PO-6B | `PERMITTED_FOR_EVALUATION` |
| Intel OMZ 0238 | PO-6C | `PERMITTED_FOR_EVALUATION` |
| Intel OMZ 0042 | VC-5A | `PERMITTED_FOR_EVALUATION` |
| Awiros ConvNeXt V2-Tiny | PC-5 | `REVIEW_PENDING` |
| torchvision MobileNetV3-Small | PC-8, PO-7, VC-4A | `REVIEW_PENDING` |
| VTFPAR++ MARS checkpoint | PC-9 | `REVIEW_PENDING` |

**DINOv3 gated access:** `NOT APPROVED`. No gated terms are to be accepted and no DINOv3 model bytes are to be acquired for this event.

**Permitted acquisition set:** SigLIP 2, DINOv2, OMZ 0230, OMZ 0234, OMZ 0238 and OMZ 0042. R-1/R-6 designated the controlled component/evidence store in §4.3.9, and the completed acquisition is retained in §4.3.11. Awiros, MobileNetV3-Small and VTFPAR++ remain on hold; no acquisition or execution is permitted while they are `REVIEW_PENDING`.

No candidate is shortlisted by this action, and every ledger disposition remains `DISCOVERED`.

#### 4.3.9 Controlled store and acquisition tooling — 2026-09-30

**Controlled store.** R-1/R-6 designated `D:\MAVI-Controlled\Models\S2c\2026-01` as the controlled component/evidence store for this event. It lies outside Git and is the only permitted destination for this acquisition.

**Tooling.** The acquisition script is prepared at `tools/qualification/model_selection/acquire_s2c_candidates.ps1` and is compatible with Windows PowerShell 5.1 and PowerShell 7.
- **What it fetches.** Only the six R-5-permitted families (§4.3.8), from a fixed in-script catalog at immutable revisions:
  - SigLIP 2 @ `75de2d55…` and DINOv2 @ `ed25f3a3…`: `model.safetensors`, plus that revision's `config.json` and `preprocessor_config.json`, which are needed to load and preprocess the weights;
  - OMZ 0230/0234/0238/0042: the FP32 `.xml` and `.bin` pair each, from the `2023.0/models_bin/1` storage paths named by `model.yml` at OMZ `a6946b6d…`.
- **Checks on every file.** HTTPS only, with allow-listed hosts on every redirect hop and no credentials. The file is written as `.partial` and renamed only after the published size and the publisher checksum verify:
  - SHA-256 for the HF weights;
  - git blob SHA-1 for the HF configuration files;
  - SHA-384 for OMZ.
- **Hashes and records.** The MAVI SHA-256 is computed locally. No publisher SHA-256 is invented for OMZ. Output goes to `acquisition-manifest.json` and `acquisition-summary.txt` under the store.
- **What it never fetches.** DINOv3, Awiros, MobileNetV3-Small and VTFPAR++ have no source in the script and appear in the manifest only as `BLOCKED`.
- **Tests.** `tools/qualification/tests/test_s2c_acquisition_script.py` checks the catalog and runs PowerShell behaviour tests with a fake downloader; no network is used.

**Historical status at tooling preparation.** Acquisition had not yet been executed when this tooling section was written. The subsequent real runs and final reviewed manifest are recorded in §4.3.10–§4.3.11. Ledger identities remain unchanged.

#### 4.3.10 First real acquisition runs and transfer repair — 2026-09-30

**Real runs.** Acquisition began on the Development machine against `D:\MAVI-Controlled\Models\S2c\2026-01`. The operator reports this observed state, pending the returned manifest:
- **OMZ 0230, 0234, 0238 and 0042:** FP32 `.xml` and `.bin` acquired and verified locally.
- **DINOv2:** `config.json` and `preprocessor_config.json` verified; `model.safetensors` still blocked by transport failures.
- **SigLIP 2:** `config.json` acquired; `preprocessor_config.json` and `model.safetensors` still blocked by transport failures.

No hash, size or identity mismatch occurred.

**Defect exposed.** Hugging Face connections are intermittently reset or fail TLS on this network. The script deleted `.partial` bytes after any failure, sent no `Range` and had no retry, so large weights restarted from byte zero on every run.

**Repair (script 1.1.0).**
- **Partials kept.** `.partial` files survive transient failures, and a rerun resumes with `Range: bytes=<length>-`.
- **Append only on a validated 206.** Bytes are appended only to an HTTP 206 whose `Content-Range` starts exactly at that length and whose total equals the pinned size.
- **200 and 416.** A 200 answer to a Range request never appends: its full body replaces the partial as a fresh transfer. A 416 fails closed unless the partial is already complete.
- **Bounded retry.** Only transient transport errors (resets, TLS failures, timeouts, HTTP 408/429/500/502/503/504) are retried: at most 5 attempts, with 2/4/8/16 s back-off.
- **No weakening.** Identity and integrity checks, promotion rules and the catalog are unchanged. An oversized, mismatching or rejected partial is kept for diagnosis and never promoted.
- **Manifest.** The manifest adds `resumedFromBytes`, `transferAttempts` and `partialRetained` per artefact (additive; schema id unchanged).

**Historical status after the first runs.** At this point SA-B2 remained open pending the remaining Hugging Face files. That condition was later satisfied by the completed manifest recorded in §4.3.11.

#### 4.3.11 Completed controlled acquisition — 2026-09-30

The Development-machine acquisition completed successfully in the designated store `D:\MAVI-Controlled\Models\S2c\2026-01` using acquisition script v1.1.0. The returned `acquisition-manifest.json` reports `overallStatus: COMPLETE` for `msr-person-attributes-2026-01` and `msr-vehicle-attributes-2026-01`.

**Retained run identity.**
- acquisition host: `QUEENSGAMBIT`;
- run UTC: `2026-09-30T14:46:48.015Z` to `2026-09-30T14:48:14.532Z`;
- acquisition manifest SHA-256: `bbc949bc546464f57301dd5f05fdccb368dd54ac87efbee2be038ecbd83618a5`;
- script version: `1.1.0`; script SHA-256: `eaa3069580ac7ddb850389424f1d48f26357448309d56c1e995bf6916977a973`.

**Permitted first-pass artefacts now acquired/verified.**
- DINOv2 `facebook/dinov2-small@ed25f3a31f01632728cabb09d1542f84ab7b0056`: `config.json`, `model.safetensors`, `preprocessor_config.json`. Weight SHA-256 `ae1e99fcefd534ed978cdeb8326f08030c96e28b7a81ffcbc98a857c84d14be1` matches the publisher value.
- SigLIP 2 `google/siglip2-base-patch16-224@75de2d55ec2d0b4efc50b3e9ad70dba96a7b2fa2`: `config.json`, `model.safetensors`, `preprocessor_config.json`. Weight SHA-256 `612923381c76ec5a9bed335d1c48827e3f2e506ac31b044b63b2031fadee6a0b` matches the publisher value.
- OMZ 0230, 0234, 0238 and 0042 at `a6946b6d6ce42cbf4278df20275fab199655fc7d`: each FP32 `.xml` + `.bin` pair is present, publisher SHA-384 checks match, and a local MAVI SHA-256 is retained in the manifest for every file.

All 14 permitted files are therefore present and integrity-verified. Model bytes remain outside Git. The manifest retains the exact source URL, immutable revision, relative path, size, local SHA-256, publisher checksum comparison, acquisition status and timestamp per file.

**Blocked candidates are unchanged.** Awiros (`PC-5`) and MobileNetV3-Small (`PC-8/PO-7/VC-4A`) remain `REVIEW_PENDING`; VTFPAR++ (`PC-9`) remains `REVIEW_PENDING` with no identifiable checkpoint file; DINOv3 (`PC-2A/PO-2A/VC-1A`) remains `NOT_PERMITTED_FOR_EVALUATION` with gated access `NOT APPROVED`. No bytes were acquired for those families.

**Scope.** This completes acquisition/pinning only. It does not shortlist, run, train, tune, measure or select any candidate; it does not create a frozen ledger/protocol, E/F/J/T, E1/E2/E3 or Model Pack.

#### 4.3.12 B0 source admission and acquisition pilot — preparation only, 2026-09-30

Hari Om has no private corpus, so B0 prepares a reproducible way to admit and retain public qualification footage one file at a time. It covers:
- a Commons-only helper, `tools/qualification/source_acquisition/`;
- a per-file admission receipt;
- the pilot plan.

The interpretation of "MAVI-acquired operational footage" is in `s2c-b0-source-acquisition-record.md` §1. In short, footage becomes operational only through the real MAVI ingestion, detector, tracker and Evidence Set path and the corpus tooling. For public sources, disjointness rests on reviewed capture-date evidence, not on construction. That interpretation needs R-2/owner acceptance.

No footage was discovered or acquired in this pass; the pilot has not run. Slice B has not started, and F1 is unchanged. Both MSRs remain `PLANNED`, and no candidate gains any standing from source acquisition.

#### 4.3.13 Slice B preparation — public-source feasibility pilot, first run, 2026-10-01

A bounded metadata-only run of the B0 pilot is recorded in `s2c-b-source-feasibility-pilot-2026-10-01.md`.

- **Scopes:** predeclared.
- **Run:** 15 candidates were described, and live Commons parsing was validated. Repeated HTTP 429 responses then blocked discovery from this environment; the underlying cause was not established (stop condition S4).
- **Acquisition:** nothing was admitted or acquired. No rights or privacy review exists, and `freshnessReferenceDate` is missing.

Public-source sufficiency is UNRESOLVED. The available evidence is exported to a hashed bundle delivered to the owner for retention (durable custody not yet confirmed); the record lists its manifest and the evidence already lost. The record separates the corpus tooling's hard requirements from a recommended capture brief for commissioned or owner capture, and proposes the next bounded step. Slice B corpus execution has not started. F1, both MSRs and S1.4 are unchanged.

**Later on 2026-10-01** (`s2c-owner-decisions-2026-10-01.md`):
- Local custody of the bundle on the Development host is recorded and re-verified: archive SHA-256 `82fe15b7…0331`, manifest `60e4edc8…d599`, all 24 payload files matching.
- The controlled directories are designated.
- R-1/R-3 are reassigned prospectively (§2.1).

The run itself is not re-attributed, and R-3's confirmation of it stays pending.

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

**SA-B1 — RESOLVED (2026-09-30).** R-2 Hari Om approved the exact draft bytes (§4.3.6). R-1 Aarav performed the recorder action, and both working M2 ledgers are committed with genuine initial history (`recordedBy: Aarav`, `reviewedBy: Hari Om`). `model_selection_check.py repository` validates both (§4.3.7).

**SA-B2 — RESOLVED (2026-09-30).** Aarav's R-5 decisions are recorded in §4.3.8, the controlled store is designated in §4.3.9, and the reviewed completed acquisition manifest is recorded in §4.3.11.
- SigLIP 2, DINOv2 and OMZ 0230/0234/0238/0042: every required first-pass file is present and integrity-verified in the controlled store.
- DINOv3 remains `NOT_PERMITTED_FOR_EVALUATION` with gated access `NOT APPROVED`; no byte was acquired.
- Awiros, MobileNetV3-Small and VTFPAR++ remain `REVIEW_PENDING` and explicitly blocked; VTFPAR++ also lacks an identifiable checkpoint file.
- No blocked candidate is required to be acquired to satisfy Slice A: the governing acceptance permits an explicit blocked disposition.

**SA-B3 — baselines not implemented (plan sequencing).** See §5. The implementation moves to C2. This is not an execution blocker.

**Acceptance checklist.**

| Slice A acceptance item | State |
|---|---|
| every proposed runnable component has verifiable bytes or an explicit blocked disposition | **met**: every R-5-permitted first-pass artefact is acquired/verified (§4.3.11); non-permitted/pending candidates retain explicit blocked dispositions (§4.3.8) |
| ledger validator passes | **met**: both working M2 ledgers validate, including under the repository check (§4.3.7) |
| no fixture incumbent / PO-B0 unit | met: the fixture is not a candidate; PO-B0 is in no unit, fallback or ledger entry (§4, §4.3.5, §6) |
| required roles assigned | met (§2) |
| candidate acquisition and identity auditable | **met**: completed controlled manifest records immutable revision, exact file/path, byte size, local SHA-256, publisher-integrity comparison, status and timestamps for all 14 permitted files (§4.3.11) |
| no unresolved owner input silently defaulted | met: supplied inputs are explicit and remaining inputs stay PARTIAL/MISSING (§2, §3) |

**Slice A is ACCEPTED 2026-09-30.** SA-B1 and SA-B2 are resolved, and every Slice A acceptance item above is met. Owner inputs that belong to later slices remain explicitly PARTIAL/MISSING in §3 and are not silently defaulted. Slice B may now begin preparation under its own gates; candidate corpus execution still cannot occur until Slice B's real-footage/seal/recipe prerequisites are satisfied.

## 9. Dependencies and offline policy

No library, SDK, runtime, native binary or model prerequisite is introduced by Slice A. `config/dependencies/offline-dependency-policy-v1.json` and `offline-binary-catalog-v1.json` are unchanged, and the detector/vision runtime lock is not widened. Any candidate that turns out to need another engine is an extension that goes through its own `attributes-<engine>-v1` family, locks, notices and policy entries in the slice that introduces it (parent §12.7; AGENTS.md).
