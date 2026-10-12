# Stage 4 — Plate Benchmark Search and Intake Status (ADR-017 §1, §7)

**Date:** 2026-10-12, with a second pass the same day after the owner authorised Development downloads.
**Purpose:** find established labelled plate data for the evidence-adequacy experiments (Stage 4 plan §3.3) before
considering any labelling.
**Class:** Development data strategy. Measurements are recorded in the register, not here.

**Authorisation boundary.** The owner authorised downloading publicly accessible data whose terms permit Development
evaluation. The authorisation does not cover:
- signing restricted licence agreements, or accepting academic-only terms on the owner's behalf;
- paying for data;
- redistribution.
A source whose licence or provenance is ambiguous is not used.

## Track-level vehicle sequences (E-B)

| Release | Content | Terms and access | Decision |
|---|---|---|---|
| **UFPR-ALPR** (Laroca et al., IJCNN 2018) | 150 vehicles × 30 frames (1920×1080); per-frame vehicle box, plate box, text; Brazil | `license-agreement.md`: academic research only, non-commercial. The request is an **e-mail from a valid university account** to rblsantos@inf.ufpr.br quoting a fixed agreement paragraph ("only for research purposes … not make any part … available to a third party … not sell … or make any profit"). Redistribution and **modification** need the lab's permission. Indemnity clause | **Not obtained — owner decision.** Eligibility needs a university affiliation and acceptance of the terms; whether deriving MP4s for MAVI processing counts as "modification" needs the owner's reading or the lab's confirmation |
| LSV-LP; LRLPR-26; PatrolVision | Video LPR sets (China; competition; Singapore dashcam) | Hosting and terms not public, or competition-only | Not obtainable |
| UCSD car dataset | Campus-entrance video frames with plate text | Terms not established | Not used (licence unknown) |

**No openly licensed labelled ALPR video with per-frame plate truth was found**, Indian or otherwise. E-B has no admissible input.

## Still images (E-A)

| Release | Content | Terms and access | Decision |
|---|---|---|---|
| **DataCluster Labs Indian Number Plates — sample** (Hugging Face `Dataclusterlabspvtltd/indian-number-plates-dataset`, revision `2bb7cd4e46e58af4f6fa413ce8e205ac69e605a7`) | **47** phone photographs (not ~200), 52 plates, 25 with a text label; no vehicle box | CC BY NC-ND 4.0, "evaluation purposes" | **Obtained and onboarded** (Indian diagnostic; below every support floor) |
| **UC3M-LP** (Ramajo-Ballester et al., RAS 2024; Zenodo record 17152029, `UC3M-LP.zip`, MD5 `496e3b5e66b78d231f71d85c0e5e11a3`) | 1,975 street photographs (5184×3888), 2,547 Spanish plates; four-corner polygons; type (incl. two-row motorcycle) and day/night labels; **characters anonymised as `*`**; no vehicle box | Zenodo: **CC BY 4.0**, open access. The documenting repository: ODbL-1.0 | **Obtained** (test split measured; train reserved). Masked labels handled by protocol R6, vehicle boxes by R7 |
| Number Plate Number Identification Dataset (Zenodo 13954136; Bapatla, Andhra Pradesh, India) | 1,700 phone photographs (50–200 MP); one plate number per image in a spreadsheet; **no plate geometry** | CC BY 4.0 | **Not usable under the frozen protocol.** E-A reads the ground-truth plate region; a plate box from a detector would be a prediction, not ground truth. It is the strongest Indian lead: plate boxes are the only missing annotation |
| `thundarstrom/indian-*` (Hugging Face) | Aggregated Indian plate crops and detection images | Tagged CC BY 4.0, but the detection set says it merges a "Cleaned VOC Rescued Subset (47 images)" — the DataCluster sample is CC BY NC-ND — plus unattributed DashCop and "Perfect Indian Plates" sources. The OCR sets are plate crops with no vehicle context | **Not used: ambiguous provenance and licence** (owner rule) |
| Indian Licence Plate Dataset in the wild (Tanwar et al.) | 16,192 images; 4-point plates and characters | Not public (the README cites legal constraints); author contact only | Not obtainable |
| IEEE DataPort Indian LPR / IND-VNP; Kaggle Indian sets | Indian plates | Subscription or login; the full DataCluster set is commercial | Not used (access controls or purchase) |
| CCPD (ECCV 2018) | About 300k Chinese parking images; 4-corner plates; blur, tilt and illumination subsets | MIT; the original is one 12 GB Google Drive archive | Not used in PR-1. Every plate begins with a Chinese province glyph, which mavi-plate-normalisation-v1 rejects, so the generic instrument could never match. A subset mapping would need its own protocol rule; UC3M-LP covers the open-licence E-A need without one |

## Consequence

- **E-A** runs on UC3M-LP (test split) and on the DataCluster Indian sample (diagnostic).
- **E-B** cannot run: no admissible sequence release exists without an owner action.
- Representative **Indian** evidence at the support floor needs either:
  - the owner's decision on UFPR-ALPR and/or a bounded labelling of plate boxes; or
  - Development footage (register, decision O1).
