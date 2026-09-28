# msr-vehicle-attributes-2026-01 — Model Selection Record

> MSR method v1 (`../README.md`). **State: `PLANNED`.** No candidate has been evaluated, and **no model is selected**. Every candidate below is `DISCOVERED`. The "proposed at freeze" column is the planning proposal that slice S2c.2 confirms or changes. This event is independent of `msr-person-attributes-2026-01`: no person candidate's result is assumed to transfer to vehicles.

## 0. Event

| Field | Value |
|---|---|
| Event id / capability | `msr-vehicle-attributes-2026-01` / `vehicle-attributes` |
| State / outcome | `PLANNED` / — |
| Originating stage | Stage 2 S2c (`docs/superpowers/plans/2026-09-28-stage2-s2c-learned-attribute-model-packs.md` §9, §22) |
| Owner / independent reviewer | MAVI owner (to be named at S2c.0) / to be named at S2c.2 |
| Governing documents | ADR-013, ADR-014; qualification plan `docs/qualification/2026-09-23-visual-attributes-qualification-plan.md` (with R1–R2); register `docs/reviews/2026-09-23-visual-attributes-acceptance.md` |
| Protocol | `msr-vehicle-attributes-2026-01-protocol.md`, not yet written (S2c.2) |
| Incumbent | **none.** The S2b fixture inferencer is a Development-only test double |
| Baseline | VC-B0: MAVI-owned deterministic body-region chroma clustering + CIE-Lab naming |
| Discovery sources | `docs/qualification/stage2-s2c/model-candidate-survey.md` (2026-09-28); re-run at S2c.2 |
| Target profiles (licence gate G1) | the Development deployment profiles where S2c runs the learned pack; their profile ids are named in the protocol at S2c.2. Production profiles are determined later, by addendum; none in S2c |
| Frozen-test access count | 0 (the frozen test is not yet sealed) |

## 1. Task definition

**T-VC:** vehicle dominant colour, with the vocabulary in plan §6–§7.1.

## 2. Candidate ledger

Checkpoint identities are pinned at S2c.2. Licence status is `NOT_ASSESSED` for all candidates: the survey's class (§6 there) is an input to the review, not a determination.

| Id | Role | Candidate (family) | Exact identity | Technical disposition | Proposed at freeze | Survey ref |
|---|---|---|---|---|---|---|
| VC-B0 | baseline | deterministic chroma + Lab naming | MAVI code (commit at S2c.3) | `DISCOVERED` | shortlist | plan §9.2 |
| VC-1 | challenger | frozen DINOv3 (and DINOv2) + MAVI colour head; CNN ensemble variant (Orrú 2026 design) | pin at S2c.2 | `DISCOVERED` | shortlist | §3, §4 |
| VC-2 | challenger | frozen SigLIP 2 + MAVI colour head | pin at S2c.2 | `DISCOVERED` | shortlist | §4 |
| VC-3 | challenger | PP-Vehicle PP-LCNet attribute (checkpoint) | pin at S2c.2 | `DISCOVERED` | shortlist if evaluation is permitted, else `REFERENCE_ONLY` | §3 |
| VC-4 | challenger | CNN / ViT fine-tuned on MAVI labels (Lima et al. recipe; method) | backbone pin at S2c.2 | `DISCOVERED` | shortlist | §3 |
| VC-5 | challenger | Intel OMZ vehicle-attributes-recognition-barrier-0042 (0039 as the small reference) | pin at S2c.2 | `DISCOVERED` | shortlist | §3 |
| VC-R | reference | SigLIP 2 / CLIP zero-shot prompts | pin at S2c.2 | `DISCOVERED` | shortlist as an uncalibrated reference, not selectable unless it passes every gate | plan §9.2 |
| C-SEG | component | SAM 2.1 / SAM 3 masks for the body region | pin at S2c.2 | `DISCOVERED` | `DEFERRED`: evaluated only if unmasked regions lose materially | §4 |
| R-VCR | reference | other published vehicle-colour methods (SMNN-MSFF, HF EfficientNet-B4 card, NVIDIA DeepStream/TAO) | — | `DISCOVERED` | reported evidence retained; S2c.2 decides on technical and evaluation-permission grounds (DeepStream colour is deprecated, and TAO has no colour output) | §3 |

Candidate cards (methodology §5) are written at S2c.2.

## 3–7. Evidence, gates, ranking, licence qualification

Not started. Reported evidence is in the survey; §3 snapshots it at S2c.2. No MAVI evidence exists.

## 8. Decision

None. No model is selected in the planning change.

## 9. Resulting identities

None.

## 10. Closure

Open.
