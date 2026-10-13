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
| **LSV-LP** (Wang et al., T-PAMI 2022; `github.com/Forest-art/LSV-LP` at `337cbcf9`) | 1,402 videos, 401,347 frames, 364,607 plates; per-frame vehicle id, car box, 4-point plate, plate number (Chinese province glyph first) | README: "only be used for academic research, not for commercial use"; no agreement to sign. The owner declared MAVI a non-commercial, open-source academic research project (2026-10-12), so the terms permit Development use. README retained (`902ce892…`) | **Admissible but not obtainable now.** The Dropbox share returns "Link temporarily disabled" (traffic limit); the Baidu mirror needs an account. The 3-video official Google Drive sample was obtained (`LMV-LP-Sample.zip`, SHA-256 `95c5c7c5…`; real format confirmed) but is below support. Using it later also needs a declared province-glyph rule (as for CCPD) |
| LRLPR-26; PatrolVision | Track patches (competition); Singapore dashcam | Competition-only, or terms not public | Not obtainable |
| **BDD100K MOT 2020 val** (already held for Stage 3 under the BDD100K licence; descriptor `7169263a…`) | 200 dashcam sequences with independent ground-truth vehicle tracks and per-frame boxes, already processed by real MAVI on the release profile; **no plate labels** | BDD100K licence (research, not-for-profit; modification permitted) | **Used for E-B with bounded R8 labelling.** A plate detector proposed geometry; the agent transcribed text blind and verified the boxes; 106 tracks were labelled |
| UCSD car dataset | Campus-entrance video frames with plate text | Terms not established | Not used (licence unknown) |

No openly licensed **and currently obtainable** labelled ALPR video with per-frame plate truth was found. LSV-LP qualifies on its terms but is not downloadable at present. E-B therefore ran on BDD100K MOT with bounded, agent-verified plate labels (protocol R8). That is US and Israeli dashcam footage, and is evidence-retention evidence only, never Indian-domain validation.

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
- **E-B** ran on BDD100K MOT val with R8 labels; LSV-LP remains the preferred fully annotated source once its share is re-enabled.
- Representative **Indian** evidence at the support floor needs either:
  - the owner's decision on UFPR-ALPR and/or a bounded labelling of plate boxes; or
  - Development footage (register, decision O1).

## Indian traffic video — continued search (2026-10-13, O1 kept open)

| Release | Content | Terms and access | Decision |
|---|---|---|---|
| IDD-X (IIIT Hyderabad) | 85 h of 25 fps dual-view (front and rear) driving video around Hyderabad; tracked boxes for road users relevant to the ego vehicle's decisions | Distributed through IIIT's portal (`idd.insaan.iiit.ac.in`), which requires registration; whether plates are unblurred is unconfirmed | **Strongest Indian video lead.** Needs the owner to register; it would need R8-style plate labelling |
| IDD-3D | LiDAR and camera | CC BY 4.0, but plates are blurred | Not usable for plates |
| IITH accident dataset (Hyderabad CCTV, 30 fps) | Accident clips from city CCTV | Terms not established | Lead only |
| Kaggle "Car number plate video" | A few clips | Apache-2.0, but Kaggle needs a login | Not obtainable without an account |

### IDD-X — registration information for the owner (O1 approved 2026-10-13; nothing accepted on the owner's behalf)

Read on 2026-10-13 from the public pages only. No account was created, no terms were accepted and no access was requested.

**Sources:**
- the project page `idd-x.github.io`;
- the paper (arXiv 2404.08561, ICRA 2024, DOI 10.1109/ICRA57147.2024.10609989);
- the IIIT INSAAN dataset list;
- the India Data listing `india-data.org/dataset-details/99124475-fc84-46dc-9dad-f5e34c18f9e0`.

| Question | Finding |
|---|---|
| Where access is requested | The project page directs users to **India Data** (IHub-Data, IIIT Hyderabad, "Data Foundation for Smart Mobility"). Listing: Access Type **Private**, Status Verified, 171 GB, "videos with text annotations", owner Ravi Kiran Sarvadevabhatla. Access is by **Request Access** after signing up. The older INSAAN portal also lists IDD-X (160 GB) behind a login (sign-up asks for name, email, affiliation and role) and says "License will be displayed before downloading a dataset". |
| Licence / agreement | India Data **Data User Agreement** (read, not accepted). The terms relevant to MAVI are summarised below this table. |
| Frame rate | Recorded at **25 fps**: front 2560×1440, rear 1920×1080. Important-object boxes are tracked "at the frequency of 25Hz for the entire duration of the driving scenario" (paper). Whether the release ships full-rate video or extracted frames is **not stated publicly**. The listing says "videos". |
| Plate visibility | **Not stated anywhere publicly.** The paper does not mention anonymisation. The DUA requires DPDPA-compliant handling of personal data. Plate legibility can only be confirmed after access. |
| Fit to E-B | It has native-rate tracks of Indian vehicles in dense traffic, which is exactly the O1/O3 gap. However, the annotations are boxes on *important objects* only, with no plate text or plate boxes. Using it for E-B would need bounded R8-style plate labelling under ADR-017, and tracking measurement would be limited to the annotated objects. |
| Cost | No price is shown on the listing. The portal has a "Pricing Details" page. **If access requires payment, MAVI's authorisation excludes it.** |

**The Data User Agreement's terms relevant to MAVI:**
- a non-exclusive, non-transferable licence "for research, analysis, and other lawful purposes";
- compliance with the DPDPA 2023;
- attribution as the dataset metadata specifies;
- no commercial use without prior written consent;
- modification only if the dataset's own terms of use allow it, and no misrepresentation of the data;
- respect for privacy, with sensitive personal data never shared without the data subjects' consent;
- no warranty;
- Indian law and courts;
- the provider may amend the terms;
- "By accessing or using any dataset … you agree".

**Assessment on MAVI's classification (non-commercial, open-source academic research).** The research-use and non-commercial terms fit internal benchmark measurement. Three points need the owner's attention **before accepting**:
1. **Derived labels.** R8 plate labels and plate crops are derived data. "Modification only if explicitly stated" should be confirmed with the provider, and MAVI must not redistribute them.
2. **Personal data.** Plate text is personal data under the DPDPA. Labels and crops must stay outside Git and on controlled storage, as for BDD100K.
3. **Amendable terms.** The terms can be amended, so preserve a dated copy of the DUA at acceptance (licence evidence).

**For the owner to do (MAVI cannot do it):**
1. Create an India Data account in your own name and affiliation.
2. Read the DUA as displayed and decide whether to accept it.
3. Press **Request Access** on the IDD-X listing, stating the purpose truthfully: non-commercial academic research benchmark of plate legibility in Indian traffic; no redistribution; data kept on controlled storage.
4. If a price or institutional-eligibility condition appears, stop; it is outside the current authorisation.
5. Before downloading, ask the provider whether plates are unblurred and whether full 25 fps video is included. If plates are anonymised, IDD-X is recorded as unusable for E-B and the Indian search continues.
6. When access is granted, share only the download link or files. MAVI will then record the descriptor, hashes and licence evidence and run a small legibility check before any labelling.
