# PoC S2 — demo corpus: discovery, ADR-017 admissibility and acquisition record

**Date:** 2026-10-28. **Base:** `main@393a16ed`. **Operator:** a Claude Code session (PoC S2) on the owner's instruction. The operator is not an independent reviewer. Owner acceptance of `demo-corpus-attribution.md` (register B2) ratifies the determinations below.

**Governing records:**
- scope declaration and amendments: `s2-demo-corpus-scope-declaration.md`, committed before each pass (`82e04c05`, A1 `bd7ccce3`, A2 `041513da`, A3 `9bde864d`);
- plan D3 and register rows B1–B5;
- ADR-017 §7;
- the source-acquisition helper README.

**Why per file.** Wikimedia Commons is a collection of individually licensed uploads. ADR-017's "release-level by default" therefore does not apply, and admissibility is recorded **once per source file**, below.

## 1. Discovery (metadata only)

Every request went through `tools/qualification/source_acquisition_cli.py discover`. That tool applies the HTTPS and allow-list rules and retains each file's metadata response by content hash. The User-Agent contact was the repository URL. Discovery reports and evidence are in the controlled store, `E:\MAVI-Controlled\PoC\Corpus\source-store\discovery\` and `...\evidence\`. The per-scope result files are in `...\Corpus\discovery-log\`.

| Pass | Scopes | Unique files described (cumulative) | Notes |
|---|---|---|---|
| 1 | Q1–Q12, plain searches | 212 | Q2, Q8 and Q10 returned no file. Licence mix: PD 77, CC-BY-SA 75, CC-BY 43, CC0 17. |
| 2 (A1) | R1–R14, searches and categories | 501 | R13 (`Category:Videos of crowds`) returned no file. |
| 3 (A2) | T1–T10, structured-data licence filters | 835 | |
| 4 (A3, final) | U1–U10, car park and indoor | 964 | U5 returned no file. |

Discovery-report SHA-256 prefixes, per scope:

| Pass | Report SHA-256 prefixes |
|---|---|
| 1 | Q1 `2b486cbc`, Q3 `c2a8b9e6`, Q4 `0463b7ae`, Q5 `404fcb1e`, Q6 `af898478`, Q7 `dfda40d0`, Q9 `4f97b299`, Q11 `0cda7db9`, Q12 `2185d673` |
| 2 | R1 `de450765`, R2 `df0894de`, R3 `0b148bb7`, R4 `267ec94e`, R5 `6372fb5b`, R6 `3ff64e4a`, R7 `70b34949`, R8 `a94b7641`, R9 `399c5b6c`, R10 `202576ea`, R11 `3841ec9a`, R12 `8d9dd80c`, R14 `4e6ca278` |
| 3 | T1 `2d01a7e0`, T2 `ee169b62`, T3 `78977d05`, T4 `e305fcad`, T5 `5421ba92`, T6 `1201ed9d`, T7 `b40ead9e`, T8 `38098eff`, T9 `f7267319`, T10 `8921c11f` |
| 4 | U1 `11e7288e`, U2 `4b5916d6`, U3 `94afd909`, U4 `90c6fe06`, U6 `98c15e0d`, U7 `0d2752fc`, U8 `1af5cfad`, U9 `6a45cfd9`, U10 `f9647297` |

**Selection (rules §4).** After rules 1–2 (kit licence; ≥ 60 s; ≥ 640×360), rule 3 was applied to the plausible candidates:
- **First screen:** three frames per candidate, about 45 candidates.
- **Finer screen:** one frame every 10–15 s for 26 candidates.
- **Frames used:** rendered by Commons at 330–500 px and kept only on `E:\MAVI-Working\tmp`. Rationale: confirm a fixed, uncut viewpoint so that zone and line geometry stays valid. No label, count or annotation was produced.

Rule 3 rejected most kit-licensed files: walking tours, drive-throughs, drone and dashcam footage, handheld or edited news pieces, slideshows and press events. Eight files passed.

## 2. Per-source admissibility (ADR-017 §7)

For all eight files:
- **Status:** **RESEARCH-ADMISSIBLE** for Development. **Redistribution in the kit is permitted** by the licence (CC0, or CC BY with attribution and indication of changes).
- **Basis:** the licence on the file's own description page (`extmetadata`) at the bound page revision. The retained metadata response is identified by its SHA-256 (`metadataEvidenceSha256`) in the store.
- **Rights and privacy:** recorded in the purpose-approval determinations (§3).
- **Purpose:** `development` (PoC demonstration media).
- **B0 decision:** none. The helper's automatic state is `DISCOVERED`, and acquisition rests on `PURPOSE_APPROVAL`.

| Clip | Commons file | pageId / revision | Licence | Provider SHA-1 | Original SHA-256 | Metadata evidence SHA-256 | Final receipt SHA-256 |
|---|---|---|---|---|---|---|---|
| s2-01 | Straßenverkehr in Düsseldorf.ogv | 31636169 / 1227822546 | cc0 | `1b834e34bb25624de11ddd5ce4ea211c293a8a62` | `bf63e9fcdf42fa429617d5e991f183baff619d06dd8aafdc97f76c13d22cc5eb` | `a4047cdd…` | `f5a36c49…` |
| s2-02 | Trams and road cars at Macedonia square in Sofia.webm | 62252665 / 1035020995 | cc-by-3.0 | `6c2562d63a6265dbc3dc58d17d19634fbd56c339` | `5b2890759899f1e5b000ad789037d6d7c339b4867e5c5b1d9a0e91820f9a5c96` | `ab5d63c7…` | `ca7024e3…` |
| s2-03 | Views of Caton Farm Road in Crest Hill, Illinois 04.webm | 198954882 / 1292261971 | cc-by-4.0 | `186c93582ee722504738943890766131fa2b3547` | `bb237e157d04179bd178ab12e1658edf892c15a4b98e60563e7c7bf949b340ce` | `4cfeed56…` | `c9e5aba2…` |
| s2-04 | Cars driving at night.webm | 24403804 / 1274270458 | cc-by-3.0 | `53fc56b2e6c053243f9ef377ada946abce4dcf63` | `3dfc2c1ae60762e45ea68bc417695cc25a4fde5fcd771d4e3f8e59b0f2f7e9f8` | `74445c6d…` | `ed94763f…` |
| s2-05 | Road traffic – cobblestone road.webm | 75044923 / 1035455639 | cc-by-3.0 | `9a7d1ce86635d2c9bc53f0de30cb541ae42cae47` | `a022c1adc52d5693704fd695bf4c66c3b4571229409dc5eaedd3cac3046764b6` | `b0027ce6…` | `e42ac63c…` |
| s2-06 | Passage à niveaux Beynost 2016.webm | 50746298 / 993905209 | cc0 | `63a9a9d549b4ac964dcaeb7cf68d642491cba4ec` | `39efd8c7af0cca621e69dc8b05a2cabee6db82a8f4db20a03a61902d08046d5e` | `6442c4e4…` | `2d12402c…` |
| s2-07 | Shibuya Crossing.ogv | 8804999 / 1048146516 | cc-by-2.0 | `2ef3c927d5c5e5ccd7c537e4bad0e4b7c074cd55` | `68f0d2f3b7acd107c462ac14ba30c7ffce7572594b30fe576c45f68ad1b43d42` | `37ad7719…` | `1fe6b7b5…` |
| s2-08 | Three Minutes of Damascus Gate.webm | 71591077 / 689333972 | cc0 | `8ec674205cff86c3c07ea697fcfd1660518af62c` | `db67701634363a9a7b53fa0a516d384fb0cdb526bdf8090fbc313edcf518a25b` | `9e2b3b86…` | `ddbe34e0…` |

The full hashes are in the receipts, `E:\MAVI-Controlled\PoC\Corpus\source-store\receipts\<sha256>.json`, and in `tools/poc/demo-corpus/demo-corpus-v1.json`.

**Licence notes.**
- s2-02 and s2-04 were imported to Commons from YouTube, where the uploader marked them CC BY. The Commons page licence governs (rule 1).
- s2-02's YouTube title contains "PD". The file page licence is CC BY 3.0, so the clip is attributed under CC BY.

**Privacy and faces (B3).** All eight clips show public streets, squares, a level crossing or a gate passage.
- **People are incidental.** People appear distant or from above, are not identifiable at close range and are not the subject.
- **Damascus Gate is overhead.** s2-08 shows heads from above.
- **No face-bearing clip.** None of the eight is a face-bearing clip in the sense of rule 4. The three CC0 clips (s2-01, s2-06, s2-08) would satisfy B3 even if a face were recognisable.
- **Plates.** Vehicle registration plates may be legible in s2-03, s2-05 and s2-06. They are published by the uploaders under open licences, and the demo neither looks them up nor links them to any person.
- **Audio removed.** Audio is stripped from every derivative.

## 3. Purpose approvals and acquisition

| Document | SHA-256 | Files |
|---|---|---|
| `s2-purpose-approvals-batch1.json` (byte-identical copy) | `9b3156fd4d81ffca4bd8270881902a9feb19a2859604ad6e980357af0afc130f` | 7 |
| `s2-purpose-approvals-batch2.json` | `5f679291698275a820c3ecb136806cc5e68e57160d9bb70638309da6e971c6bf` | 1 (Beynost) |

Each document holds two determinations:
- `poc-s2-commons-cc0-2026-10`, covering `cc0`;
- `poc-s2-commons-cc-by-2026-10`, covering `cc-by-2.0`, `cc-by-3.0` and `cc-by-4.0`.

Both have purposes `development`, rights `PERMITTED_FOR_ENGINEERING_USE` and privacy `PERMITTED`. Neither needs an R-5 ruling, because no ShareAlike or unknown licence is involved. Every approval binds the exact page revision and provider SHA-1. `acquire` re-fetched each page's metadata and reported `APPROVED` with no blockers for all eight. The final summaries are retained in `E:\MAVI-Controlled\PoC\Corpus\approvals\summary-batch{1,2}.json`:
- batch 1: SHA-256 `4c8630cc6ed0661150ee4c4f3b66181070f660bf864f528ac985be172e8c0b64`;
- batch 2: SHA-256 `9893d629a786f42008a46056c3eebe002d0e82e24d93e4e1af16c5993df2abec`.

`verify` reports no problems.

**Transfer deviation, disclosed.**
- **Helper-transferred files.** The helper's own transport downloaded four files, recorded in receipts with status `ACQUIRED`: s2-01, s2-04, s2-05 and s2-07.
- **The problem.** Wikimedia throttled each long-lived download connection to about 50–65 KB/s after an initial burst, which put the remaining ~575 MB at several hours.
- **What was done instead.** The other four originals (s2-02, s2-03, s2-06, s2-08) were transferred with resumable `curl`, which restarted on a stalled connection. Each request went over HTTPS to the same `upload.wikimedia.org` original URL, used the helper's User-Agent and sent no credentials. The files were written into the helper's exact store paths.
- **How they were verified.** `acquire` then checked each file against the provider's declared size and SHA-1 and issued its receipt with status `ALREADY_PRESENT_VERIFIED`. This is the same integrity check a helper download applies before promotion.
- **What did not change.** Admission, approval and receipt logic were untouched.

## 4. Coverage against the predeclared targets

| Class | Target (rule 5) | Selected |
|---|---|---|
| Junction / gate / road | ≥ 3 | 6: s2-01 Düsseldorf junction, s2-02 Sofia junction, s2-03 Crest Hill road, s2-04 night highway, s2-05 archway gate, s2-06 level-crossing barrier |
| Pedestrian | ≥ 2 | 2: s2-07 Shibuya scramble crossing, s2-08 Damascus Gate overhead |
| Car park | ≥ 1 | **GAP** |
| Lobby / close-range faces | ≥ 1 | **GAP** |

**Car park gap.** No kit-licensed fixed-camera car-park clip of at least 60 s was found in 964 described files. What is available instead:
- Two clips carry a "Restricted" bay zone: s2-03, over the roadside lot, and s2-05, over the parked cars beside the gate. They support dwell and restricted-area demos, but they are not car-park scenes.

**Lobby / face gap.** No CC0 or model-released indoor or close-range face clip was found. CC BY clips with recognisable faces were excluded by rule 4, for example the Pyrkon convention-hall clips. The consequences:
- **S6.** S6 measures usable-face coverage on this corpus first (register C5A.2). Coverage is expected to be low, and that will be recorded as such.
- **Owner-only option.** Filling the gap from Pexels/Pixabay is an owner-machine-only option under D3. The acquisition tool does not implement those hosts, so it would need an owner decision and a separate record. It is **not** done here.

## 5. B5 statement

No label, annotation, bounding box, count, identity or ground truth was created. The only looks at content were:
- the viewpoint screens (§1);
- reference frames used to place scene geometry. Rationale: draw zones and lines on the actual view; this is operator configuration, not annotation.

No model output was read during selection.
