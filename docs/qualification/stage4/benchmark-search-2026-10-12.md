# Stage 4 — Plate Benchmark Search and Intake Status (ADR-017 §1, §7)

**Date:** 2026-10-12. **Purpose:** to find established labelled plate data for the evidence-adequacy experiments (Stage 4 plan §3.3), before considering any labelling. **Class:** Development data strategy. Nothing here is a measurement.

Each status is the ADR-017 §7 admissibility of the intended Development use. **Obtainable** says whether the data can be acquired without an owner action.

## Track-level vehicle sequences (E-B; also E-A stills)

| Release | Content | Terms / access | ADR-017 status | Obtainable now | Use |
|---|---|---|---|---|---|
| **UFPR-ALPR** (Laroca et al., IJCNN 2018; `github.com/raysonlaroca/ufpr-alpr-dataset`) | 150 vehicles × 30 consecutive 1920×1080 frames; per-frame vehicle box, plate box, plate text, character boxes; cars and motorcycles (two-row plates); Brazil | Academic research only, non-commercial, through a **licence agreement** the requester signs | RESEARCH-ADMISSIBLE | **No — the owner must sign the agreement and request the release** | Primary E-B source (testing split); also E-A |
| LSV-LP (IEEE 2022) | 1,402 videos, 401,347 frames, 364,607 plates; China | Hosting and terms not established in this search | not assessed | No (unverified) | Candidate if E-B needs more support |
| LRLPR-26 (ICPR 2026 low-resolution LPR competition) | Track-based patches (5 far, 5 near per track) | Competition terms not established | not assessed | No (unverified) | Candidate for a low-resolution stratum |

**Indian ALPR video.** No labelled Indian ALPR video benchmark was found. The plan's decision O1 applies: either accept partial Indian Track-level evidence (Indian stills plus non-Indian sequences), or the owner approves a bounded ADR-017 §2 labelling of Development footage. This is not decided here.

## Indian still images (E-A)

| Release | Content | Terms / access | ADR-017 status | Obtainable now | Use |
|---|---|---|---|---|---|
| Indian Licence Plate Dataset in the wild (Tanwar et al., arXiv 2111.06054; `github.com/sanchit2843/Indian_LPR`) | 16,192 images, 21,683 plates, 4-point plate and per-character annotation | The README states the data cannot be made public for legal reasons; access only by contacting the author | BLOCKED until access is granted (§7: access unavailable) | **No** | The plan's primary Indian still source, if the author grants access |
| DataCluster Labs *Indian Number Plates — sample* (Hugging Face `Dataclusterlabspvtltd/indian-number-plates-dataset`, revision `2bb7cd4e46e58af4f6fa413ce8e205ac69e605a7`) | ~200 mobile-phone images; Pascal VOC plate boxes; plate text where the `number_plate_text` attribute is present (absent on image 0001) | CC BY-NC-ND 4.0, "free sample subset for evaluation purposes"; public, not gated | RESEARCH-ADMISSIBLE (no redistribution; derived crops stay local) | Yes (direct download; the owner authorises it) | Indian stills, small and **not surveillance** (close-up phone photographs). No vehicle box, so E-A needs phase-1 detector vehicle candidates |
| IEEE DataPort *Indian License Plate Recognition Dataset (YOLO & OCR)* (DOI 10.21227/ee39-dp36) | YOLO plate boxes; cropped character images; stylised and multi-line plates | IEEE DataPort access; may require a subscription | BLOCKED if payment is required (§7), otherwise to be assessed | No (unverified) | Indian two-line stratum, if accessible |
| IEEE DataPort *IND-VNP* | Indian vehicle and number-plate images | As above | as above | No (unverified) | — |
| Kaggle *Indian Number Plates Dataset* (DataCluster, full) and `kedarsai/indian-license-plates-with-labels` | Larger Indian sets | Kaggle login; the full DataCluster set is a commercial product | full set: BLOCKED (licence purchase not obtained); Kaggle sets: login, to be assessed by the owner | No | — |

## Robustness strata (E-A)

| Release | Content | Terms / access | ADR-017 status | Obtainable now | Use |
|---|---|---|---|---|---|
| CCPD (ECCV 2018; `github.com/detectRecog/CCPD`) | About 300k parking-lot images; tilt, blur, challenge, dark/bright subsets; 4-corner plate polygons (oblique stratum available) | The repository states MIT; citation requested | RESEARCH-ADMISSIBLE | Large public download (about 12 GB; the owner authorises it) | Oblique, blur and illumination strata. The leading province glyph is `unsupported`, so text is evaluated on the alphanumeric remainder (`subset`). No vehicle box, so it needs detector candidates. **No adapter in PR-1** |
| RodoSol-ALPR | 20,000 toll-camera images; cars and motorcycles (two-row) | Licence agreement (UFPR group) | to be assessed | No | Two-line stratum |

## Consequence for PR-1

The harness, adapters (UFPR-ALPR and VOC plates) and tests are complete and run on fixtures. **No release is on the
Development host yet.** The register therefore records P3 as NOT MEASURED, with the exact inputs that would execute it.
No measurement is inferred from fixtures.
