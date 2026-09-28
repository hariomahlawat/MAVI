# msr-person-attributes-2026-01 — Model Selection Record

> MSR method v1 (`../README.md`). **State: `PLANNED`.** No candidate has been evaluated, and **no model is selected**. Every candidate below is `DISCOVERED`. The "proposed at freeze" column is the planning proposal that slice S2c.2 confirms or changes when it freezes the protocol. Nothing in this record is a MAVI measurement yet.

## 0. Event

| Field | Value |
|---|---|
| Event id / capability | `msr-person-attributes-2026-01` / `person-attributes` |
| State / outcome | `PLANNED` / — |
| Originating stage | Stage 2 S2c (`docs/superpowers/plans/2026-09-28-stage2-s2c-learned-attribute-model-packs.md` §9, §22) |
| Owner / independent reviewer | MAVI owner (to be named at S2c.0) / to be named at S2c.2 |
| Governing documents | ADR-013, ADR-014; qualification plan `docs/qualification/2026-09-23-visual-attributes-qualification-plan.md` (with R1–R2); register `docs/reviews/2026-09-23-visual-attributes-acceptance.md` |
| Protocol | `msr-person-attributes-2026-01-protocol.md`, not yet written (S2c.2) |
| Incumbent | **none.** The S2b fixture inferencer is a Development-only test double, not a model and not an incumbent |
| Baselines | **PC-B0** (colour): MAVI-owned deterministic region band + dominant chroma cluster + CIE-Lab naming; packageable. **PO-B0** (backpack, bag, headwear): the no-image per-camera prevalence reference of plan §9.5 (smoothed training prevalence per camera, global prior for unseen cameras, threshold-grouped ties per plan §9.5); a statistical floor only, **not packageable** |
| Discovery sources | `docs/qualification/stage2-s2c/model-candidate-survey.md` (2026-09-28); re-run at S2c.2 |
| Target profiles (licence gate SG1) | the declared MAVI **non-commercial** Development deployment profiles where S2c runs the learned pack (MSR method §2.1); their profile ids are named in the protocol at S2c.2. Production profiles are determined later, by addendum; none in S2c |
| Frozen-test access count | 0 (the frozen test is not yet sealed) |

## 1. Task definition

The capability covers two sub-tasks, with vocabularies in plan §6–§7.1:
- **T-PC:** upper and lower clothing colour.
- **T-PO:** backpack, bag and, conditionally, headwear (presence only).

The capability binds one pack (ADR-014 §1). The event therefore records one ranking per sub-task, then selects a **composition** by the bounded procedure of MSR method §5.1 and plan §9.5a:
1. T-PC and T-PO finalists, up to K = 3 each plus baselines;
2. composition candidates by the frozen rule (winner tuple, shared-backbone pairs, up to three further pairs by rank sum);
3. composition evaluation, including the 500-camera projection;
4. Pareto frontier;
5. implementation composition.

No winner or composition is named in this planning record.

## 2. Candidate ledger

Checkpoint identities are pinned at S2c.2 (methodology §5). "Pin at S2c.2" means the exact repository revision, file and SHA-256 are not yet recorded. Licence status is `NOT_ASSESSED` for all candidates: the survey's class (§6 there) is an input to the review, not a determination.

| Id | Sub-task | Role | Candidate (family) | Exact identity | Technical disposition | Proposed at freeze | Survey ref |
|---|---|---|---|---|---|---|---|
| PC-B0 | T-PC | baseline | deterministic Lab colour | MAVI code (commit at S2c.3) | `DISCOVERED` | shortlist | plan §9.2 |
| PC-1 | T-PC | challenger | frozen SigLIP 2 image tower + MAVI heads (method) | backbone checkpoint: pin at S2c.2; heads: MAVI training manifest | `DISCOVERED` | shortlist | §2.1 VLM-PAR, §4 |
| PC-2 | T-PC | challenger | frozen DINOv3 (and DINOv2 paired) + MAVI heads (method) | pin at S2c.2 | `DISCOVERED` | shortlist | §4 |
| PC-3 | T-PC | challenger | PromptPAR / VTB (method; released checkpoints trained on restricted data) | method: pin code revision; checkpoint only if evaluation is permitted | `DISCOVERED` | shortlist (method); released checkpoint `REFERENCE_ONLY` unless evaluation is permitted | §2.1 |
| PC-4 | T-PC | challenger | UPAR-trained ConvNeXt-B / C2T-Net (checkpoint) | pin at S2c.2 | `DISCOVERED` | shortlist if evaluation is permitted, else `REFERENCE_ONLY` | §2.1, §6 |
| PC-5 | T-PC | challenger | Awiros ConvNeXt V2-Tiny (checkpoint, ONNX) | pin at S2c.2 (gated access) | `DISCOVERED` | shortlist if terms obtained, else `REFERENCE_ONLY` | §2.2 |
| PC-6 | T-PC | challenger | CLIP / OpenCLIP / MobileCLIP 2 / MetaCLIP / EVA-CLIP towers + MAVI heads | pin per tower at S2c.2 | `DISCOVERED` | shortlist each tower whose evaluation is permitted; the others `REFERENCE_ONLY` | §4 |
| PC-7 | T-PC | challenger | Intel OMZ person-attributes-recognition-crossroad-0230 colour points + Lab naming | pin at S2c.2 | `DISCOVERED` | shortlist | §2.2 |
| PC-8 | T-PC | challenger | small CNN fine-tuned on MAVI labels (method) | backbone pin at S2c.2 | `DISCOVERED` | shortlist | plan §9.2 |
| PO-1 | T-PO | challenger | SigLIP 2 heads (shared tower with PC-1) | as PC-1 | `DISCOVERED` | shortlist | §4 |
| PO-2 | T-PO | challenger | DINOv3 / DINOv2 heads | as PC-2 | `DISCOVERED` | shortlist | §4 |
| PO-3 | T-PO | challenger | PromptPAR / VTB / strong baseline trained on PA-100K (method + released checkpoints) | pin at S2c.2 | `DISCOVERED` | shortlist | §2.1 |
| PO-4 | T-PO | challenger | Awiros ConvNeXt V2-Tiny | as PC-5 | `DISCOVERED` | as PC-5 | §2.2 |
| PO-5 | T-PO | challenger | PP-Human attribute (PP-LCNet / PP-HGNet) | pin at S2c.2 | `DISCOVERED` | shortlist if evaluation is permitted, else `REFERENCE_ONLY` | §2.2 |
| PO-6 | T-PO | challenger | Intel OMZ 0230 (0234/0238 for hat) | pin at S2c.2 | `DISCOVERED` | shortlist | §2.2 |
| PO-7 | T-PO | challenger | small CNN fine-tuned on PA-100K + MAVI labels | backbone pin at S2c.2 | `DISCOVERED` | shortlist | plan §9.2 |
| PC-9 / PO-8 | both | challenger | VTFPAR++ (CLIP ViT-B/16 side-tuned on video tracklets; MARS checkpoint) | pin at S2c.2 | `DISCOVERED` | shortlist, conditional: the only located released checkpoint covering colour and presence. Single-crop and few-crop modes are benchmarked because MAVI Evidence Sets are not consecutive frames; else `DEFER` | §2.3 |
| C-SEG | both | component | SAM 2.1 / SAM 3 / human parsing for the region step | pin at S2c.2 | `DISCOVERED` | `DEFERRED`: evaluated only if unmasked bands lose materially (plan §9.2) | §4 |
| R-LLMPAR | T-PC/T-PO | reference | LLM-PAR (billions of parameters) | — | `DISCOVERED` | `NOT_SHORTLISTED`: not viable at the CPU budget (technical); reported figures retained as the reported ceiling | §2.1 |
| R-GVLM | T-PC/T-PO | reference | small generative VLMs (Florence-2, SmolVLM 2, Qwen-VL, Moondream, InternVL) | — | `DISCOVERED` | `NOT_SHORTLISTED` for the classifier role (technical: no native calibration, decoding determinism, per-crop cost); a labelling assistant only, never of a candidate's family | §4 |
| R-OPENPAR | T-PC/T-PO | reference | UniPAR, SequencePAR, MambaPAR, KGPAR, UAPAR (no checkpoint located) | — | `DISCOVERED` | `REFERENCE_ONLY`; revisit if weights are published | §2.3 |
| R-EVENT | T-PC/T-PO | reference | PFM-VEPAR, EventPAR/RWKV-PAR | — | `DISCOVERED` | `NOT_SHORTLISTED`: incompatible input modality (needs an event camera) | §2.3 |
| R-OTHER26 | T-PC/T-PO | reference | SNN-PAR, AttackPAR, YOLOv8 + ResNet18 PAR | — | `DISCOVERED` | SNN-PAR `NOT_SHORTLISTED` (no colour; neuromorphic benefit); AttackPAR `NOT_SHORTLISTED` (not a recognizer); YOLOv8+ResNet18 `REFERENCE_ONLY` | §2.3 |
| R-PAR | T-PC/T-PO | reference | other academic PAR (Rethinking-PAR, DAFL, PARFormer, SOLIDER, HAP, ViTA-PAR, FRDL) | — | `DISCOVERED` | reported evidence retained; S2c.2 decides shortlist or `REFERENCE_ONLY` on technical and evaluation-permission grounds | §2.1 |

Candidate cards (methodology §5) are written at S2c.2.

## 3–7. Evidence, gates, ranking, licence qualification

Not started. Reported evidence (class R) is in the survey. It is snapshotted into §3 at S2c.2 for every figure the decision relies on. No M-D, M-E or M-Q evidence exists.

## 8. Decision

None. No model is selected in the planning change. When filled, §8 records the methodology §9 fields:
- strongest reported/reference candidate (left blank until S2c.2; provisional survey-date note only: VLM-PAR has the highest *reported* mA on standard PA-100K/PETA subsets, which exclude colour, so it does not rank MAVI's task);
- highest task-quality evaluated candidate;
- strongest evaluated technical candidate;
- strongest candidate cleared for each declared profile;
- implementation composition;
- deltas between these;
- the composition frontier;
- projected 500-camera footprint;
- owner decisions.

## 9. Resulting identities

None.

## 10. Closure

Open.
