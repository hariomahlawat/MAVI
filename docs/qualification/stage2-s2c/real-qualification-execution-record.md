# S2c real qualification — execution record

**Governing plan:** `docs/superpowers/plans/2026-09-30-stage2-s2c-real-qualification-execution.md` (merged in PR #123, `main@d0db6efff201a003b9699cde675d8069259f980e`).
**Events:** `msr-person-attributes-2026-01`, `msr-vehicle-attributes-2026-01`; joint `eventPairId = msr-attributes-2026-01`.
**Status:** Slice A (accountable inputs and candidate manifest preparation) prepared on 2026-09-30. Slice A is **not accepted**: its acceptance depends on owner inputs that are still missing (§8). Slices B–J have not started. Both MSRs remain `PLANNED`. No candidate has been acquired, run, trained, tuned, measured or selected. No selection or frozen-test label has been read, and no experiment, protocol, ledger freeze, E/F/J/T, E1/E2/E3 or Model Pack exists. F1, F3 and every other F/G row keep their state.

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
| both MSRs §0 owner row | "to be named at S2c.0" (S2c.0 closed without names) | roles and their missing names are tracked in §2 of this record |

Not claimed anywhere: an operational F1 PASS, candidate qualification, real E2, S2c closure, S5, or Production qualification. S1.4 B1–B6 remain separately governed and OPEN.

## 2. Accountable roles (Slice A item 1; owner input OI-1)

No human name has been supplied. Every role below is **MISSING**. None is defaulted to the repository owner or to the drafting agent. A role is filled only by an entry here naming the person and the date the owner assigned them.

| Id | Role | Responsibility in this plan | First slice that needs it | Status |
|---|---|---|---|---|
| R-1 | Accountable execution owner | owner of both events; signs owner inputs; later owner implementation choice (Slice G) | A (to accept this slice) | MISSING |
| R-2 | Independent reviewer | reviews freeze, protocol and closure; cannot be R-1 | A (ledger history `reviewedBy`) | MISSING |
| R-3 | Corpus Custodian | footage custody, partitions, seal, access log, reference swatches | B | MISSING |
| R-4 | Annotation owner and annotators (at least two, one independent) | pilot, main labelling, adjudication | B | MISSING |
| R-5 | Licence Review Owner | evaluation permissions now; final per-unit, per-profile determinations later | A (evaluation permission) | MISSING |
| R-6 | Scale/Performance Evidence Owner | host profile, workload envelope, E1/E2/E3 evidence | D | MISSING |
| R-7 | Statistical recipe reviewer | reviews the one executable b-1 recipe | B | MISSING |

The ledger's `classificationHistory` needs a named `recordedBy` and a different named `reviewedBy` for every entry (`tools/qualification/model_selection/credibility.py`, `history_reviewer_not_independent`). The working ledgers therefore cannot be written honestly until R-1/R-2 (or other named recorders and reviewers) exist (§8, blocker SA-B1).

## 3. Owner-input checklist (plan §19)

Each item is **MISSING** unless an evidence reference is entered here. A missing item blocks the first slice listed and every slice after it. Nothing here is a default.

| Id | Input (plan §19 item) | Blocks from | Status | Notes |
|---|---|---|---|---|
| OI-1 | Named roles R-1…R-7 | A | MISSING | §2 |
| OI-2 | Authorized real footage; retention/access arrangements; site/camera/day/night coverage; stable raw-evidence pin; annotation time; independently reviewable custody store | B | MISSING | footage availability is not assumed |
| OI-3 | Pilot-rule confirmation; task/vocabulary/headwear decision; required attribute scope per capability; lawful fallback policy | A (scope/fallback, §6), B (pilot) | MISSING | a disabled or colour-only fallback is not assumed |
| OI-4 | Candidate evaluation budget; source/acquisition access (including gated terms); evaluation/fitting permissions; which committed proposals are pursued; exact checkpoint variant per family | A | MISSING | no passwords or tokens in Git |
| OI-5 | Every numerical quality/support/slice gate; practical/NI/equivalence/MPID margins; bootstrap seed/replicates/multiplicity/undefined-denominator rule; pilot-simulation coverage tolerance and perturbations — one executable recipe | B | MISSING | no gate threshold is supplied by this record |
| OI-6 | Training/tuning search and compute budgets; calibration family; allowed parameter families; reproducibility tolerances; evidence storage capacity | B | MISSING | |
| OI-7 | Host/OS/runtime variants; detector/platform co-residency; worker range and chosen topology; lease/retry/deadline settings; resource/SLA/host/reserve limits; physical measurement access | D | MISSING | no host limit is supplied |
| OI-8 | Concrete 500-camera envelope; camera-class mix; job/crop/byte distributions; backlog/burst/loss/drain requirements; accepted representation limits | D | MISSING | no workload envelope is supplied |
| OI-9 | Separate calibration and held-out E3 traces; service-bound estimator/error settings; repetition schedule; E3 tolerances | D (calibration), I (E3) | MISSING | no E3 tolerance is supplied |
| OI-10 | Named non-commercial deployment profiles, end uses and delivery route; genuine final legal determinations for every frozen unit and fallback across every required profile (§7); CUDA host and restart-service decisions | A (profile ids), F (determinations) | MISSING | no licence determination is made here |
| OI-11 | At the decision stage only: exact owner pair within a complete T_impl; authorization for the Development integration environment | G | NOT YET APPLICABLE | no implementation choice exists or is implied |

## 4. Candidate re-survey (Slice A items 4–5)

**Method.** Every committed proposal in both MSR ledgers was re-read against the survey and parent plan §9.2. Multi-family and multi-checkpoint rows are split into individually identifiable family variants (plan §4 item 1). A checkpoint serving both person sub-tasks is one entry (ledger rule), and method entries sharing a backbone carry identical identity blocks. No new model family was introduced.

**What was not done, and why.** The survey records source URLs and licence texts, but no immutable revision, checkpoint filename or SHA-256 for any candidate. Acquiring bytes needs authorized network acquisition and evaluation permission (OI-4, R-5), which Slice A does not have. Every learned candidate therefore has an explicit **blocked** byte disposition, and no placeholder hash was written. The evaluation-permission column restates the survey's licence class (L-A…L-D, survey §6) as an **input to R-5**, not a determination. Operational-use and redistribution status is `NOT_ASSESSED` for every candidate and is recorded separately (§7).

**M1 status.** No External Evidence Ledger exists yet (SA-B1). No evidence item has a snapshot (`retrievedSha256`), and no candidate has pinned files. Under `credibility.py`, a non-baseline candidate without pinned files has `Low` provenance confidence. It can therefore compute at most `reference-only`, or `excluded-discovery` when its origin repository, publisher or author group is unknown. It cannot be `SHORTLISTED`: `shortlist_requires_pinned_provenance` would refuse it. The class is always computed by the validator and is never asserted here. MAVI baselines compute `mavi-owned` once they have an implemented revision.

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

## 5. PC-B0 / VC-B0 status and a discrepancy with the plan

The plan's Slice A says "implement PC-B0/VC-B0". Implementing either baseline now would be premature, for four reasons:
1. **Vocabulary.** Their output values are the colour vocabulary, which stays a candidate until the pilot and the owner decision (annotation guide §10; `attribute-task-v1-candidate.json`). Merges such as grey/white or silver/grey happen in Slice B.
2. **Naming reference centres.** The naming reference centres are the colour-family swatch centres produced by the Corpus Custodian (annotation guide §4; R-3 missing). Choosing Lab centroids now would invent method content.
3. **Tuned parameters.** Their admissibility floors and colour margins are operating parameters tuned on the tuning partition (execution plan §5 data-access table). That happens in C2. Any other fixed parameter, such as band geometry, belongs in the reviewed preparation recipe (Slice B), not in an unreviewed code default.
4. **Output contract.** Abstention and aggregation must be expressed through the approved v2 contracts (Slice C1, S2c.5). The parent plan places the baseline code at S2c.3 ("MAVI code (commit at S2c.3)") and its adapter at S2c.7.

**Smallest plan-faithful change.** Record both baselines as proposed `mavi-baseline` candidates with byte disposition BLOCKED. The ledger identity is `{"repository": "MAVI", "revision": "UNKNOWN"}` until the implementing commit exists. Their implementation and revision pin move to Slice C2, after the vocabulary freeze (B) and the v2 contracts (C1). Slice A's acceptance allows this ("explicit blocked disposition"), so it is **not** an EXECUTION BLOCKER. When implemented, a baseline must be deterministic, task-compatible, offline-capable, explicitly identified, covered by focused tests, and never labelled a learned or qualified model.

PO-B0 stays a training-derived reference only. It is never a unit, component or fallback.

## 6. Draft executable-unit proposals, required scope and fallback (Slice A items 7–8)

These drafts are **preparation, not freeze**. The final manifest is enumerated at freeze from the admitted shortlist under the b-2 rule: every compatible composition when tractable; otherwise a subset fixed before selection with the search limitation recorded. K=3 is only a preparation budget, and no result-time pruning is permitted. Each unit will carry exactly `unitId`, `kind`, sorted `components`, `configurationSha256`, sorted `enabledAttributes`, `extension`, `existingGraph`. `configurationSha256` cannot be computed until the configuration document exists (after training/tuning), so it is not written here. `enabledAttributes` below assume the candidate v1 attribute set. Headwear is conditional on OI-3.

**Person (structurally required units: 10).** A person unit is one exact executable composition covering the required scope:

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
| U-P-B0-COLOUR | baseline | PC-B0 | upper/lower colour only | false / true | colour baseline; admissible only if the required scope excludes T-PO (OI-3) |

Cross-sub-task tuples (a T-PC component from one family with a T-PO component from another, including PC-B0 with a learned T-PO component) are enumerated at freeze from the admitted shortlist. They are not listed now because no component is admitted yet. The unit identifiers above are working labels, and the frozen `unitId` values are assigned at freeze.

**Vehicle (proposed units: 11).** Vehicle units are single-component: VC-B0, VC-1A, VC-1B, VC-2, VC-3, VC-4A, VC-4B, VC-5A, VC-5B, VC-RA and VC-RB. The ensemble variant from VC-1 (DINOv3 with CNNs) would be a multi-component unit. Its CNN members are not identified in the survey, so it is recorded as **BLOCKED** (unidentified components) and is not counted. Adding it later requires a pre-selection decision with identified components.

**Required scope (OI-3, MISSING).**
- Person: upper colour, lower colour, backpack, bag; headwear only if the owner keeps it in scope. Presence is present/Unknown only; there is no Absent.
- Vehicle: dominant body colour.

These are the candidate v1 attributes. The required scope is frozen only by the owner at freeze. Until then no fallback can be judged.

**Fallback policy.**
- **Person.** PC-B0 is colour-only, so it can be the person fallback only if the frozen required scope excludes T-PO. With presence in the required scope, the only fallback options are:
  - a `kind: disabled` fallback, allowed only with an owner-frozen admissibility rule for every required gate, and the full licence rows (§7); or
  - `fallback: null`.

  No such rule exists, so the person fallback status is **BLOCKED on OI-3**, and the value is `null` unless the owner supplies either the colour-only scope or the disabled rule.
- **Vehicle.** VC-B0 covers the vehicle scope, so it is the proposed fallback once implemented (§5), subject to its own gates. A disabled vehicle fallback likewise needs an owner-frozen rule. Status: proposed VC-B0, BLOCKED until VC-B0 is implemented.
- **No invented gate passes.** A disabled identity never receives conventional model-quality evidence, and no gate pass is recorded for it without the frozen rule and the evidence that rule names.

## 7. Licence-review scope (Slice A item 9)

- **What must be determined.** Final licence determinations must cover **every frozen unit, including every fallback (a disabled fallback too), across every required profile**. The builder's licence table holds all of them (`operational.implementation_sets`), and `pending` is true while any row is `NOT_ASSESSED` or `REVIEW_PENDING`.
- **Closure.** `NOT_ASSESSED` and `REVIEW_PENDING` cannot remain at `CLOSED`. A placeholder `NOT_CLEARED` for a unit that was never reviewed is prohibited, because it would be a fabricated determination.
- **Budget.** R-5 must plan review effort for losers as well as finalists.
- **Two separate questions.** Evaluation permission (needed before any byte is acquired or executed; §4 column) and final operational-use, derivative and redistribution clearance (Slice F onward) are distinct. The second never scores technical quality.
- **Nothing is adjudicated here.** No authoritative determination is present, and none is made in this record. The survey's L-A…L-D classes and §5 questions are inputs to R-5.
- **Profiles.** Profile ids are MISSING (OI-10).

## 8. Slice A blockers and acceptance

**SA-B1 — working ledgers cannot be written honestly (owner input).**
- **Cause.** Every ledger entry needs a named, independent recorder and reviewer, and no role is named (OI-1).
- **Consequence.** No `<event>-evidence-ledger.json` is committed. `model_selection_check.py repository` passes, but only vacuously: there is nothing to validate.
- **Smallest resolution.** Name R-1/R-2 (or other named recorders and reviewers). Then write both M2 ledgers (`methodRevision: msr-v1-m2`) from §4 with dated evidence items, and copy each validator-computed class.

**SA-B2 — no candidate bytes pinned (owner input and authority).**
- **Cause.** Variant choices, acquisition authority, gated terms and evaluation permissions are missing (OI-4, R-5).
- **Smallest resolution.** R-5 records evaluation permission per candidate. The owner chooses variants and authorizes acquisition into the controlled component store. The pinning run then records the revision, file paths and SHA-256 for every byte outside Git.

**SA-B3 — baselines not implemented (plan sequencing).** See §5. The implementation moves to C2. This is not an execution blocker.

**Acceptance checklist.**

| Slice A acceptance item | State |
|---|---|
| every proposed runnable component has verifiable bytes or an explicit blocked disposition | met: all blocked, with reasons (§4) |
| ledger validator passes | not yet meaningful: no ledger can be written (SA-B1) |
| no fixture incumbent / PO-B0 unit | met: the fixture is not a candidate; PO-B0 is in no unit or fallback (§4, §6) |
| no unresolved owner input silently defaulted | met: all MISSING (§2, §3) |

Slice A therefore stays **OPEN**. Slice B may not start candidate corpus execution, and no later slice may start, until SA-B1 and SA-B2 are resolved and this record is updated and reviewed.

## 9. Dependencies and offline policy

No library, SDK, runtime, native binary or model prerequisite is introduced by Slice A. `config/dependencies/offline-dependency-policy-v1.json` and `offline-binary-catalog-v1.json` are unchanged, and the detector/vision runtime lock is not widened. Any candidate that turns out to need another engine is an extension that goes through its own `attributes-<engine>-v1` family, locks, notices and policy entries in the slice that introduces it (parent §12.7; AGENTS.md).
