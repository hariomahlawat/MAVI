# PoC S2 — demo corpus: discovery, ADR-017 admissibility and acquisition record

**Date:** 2026-10-28. **Base:** `main@393a16ed`. **Operator:** a Claude Code session (PoC S2) on the owner's instruction. The operator is not an independent reviewer. The two purpose-approval determinations (`poc-s2-commons-cc0-2026-10` and `poc-s2-commons-cc-by-2026-10`) are signed by the operator. **They need explicit owner ratification**, which is a condition of register B1. This is separate from owner acceptance of the attribution file (B2).

> **Note (2026-10-28, after the cold review).** Both purpose-approval JSON files (`s2-purpose-approvals-batch{1,2}.json`, and the copies in the controlled store) carry an earlier wording in their `reviewedBy` and `approvedBy` fields: "owner acceptance of the attribution file, register B2, ratifies". **That wording is superseded:** ratifying the two determinations is a separate owner act and a condition of B1. The JSON files are left byte-identical on purpose, because the receipts bind their SHA-256.

**Governing records:**
- scope declaration and amendments: `s2-demo-corpus-scope-declaration.md`, committed before each pass (`82e04c05`, A1 `bd7ccce3`, A2 `041513da`, A3 `9bde864d`);
- plan D3 and register rows B1–B5;
- ADR-017 §7;
- the source-acquisition helper README.

**Why per file.** Wikimedia Commons is a collection of individually licensed uploads. ADR-017's "release-level by default" therefore does not apply, and admissibility is recorded **once per source file**, below.

## 1. Discovery (metadata only)

Every **metadata** request went through `tools/qualification/source_acquisition_cli.py discover`. That tool applies the HTTPS and allow-list rules and retains each file's metadata response by content hash. The User-Agent contact was the repository URL. Discovery reports and evidence are in the controlled store, `E:\MAVI-Controlled\PoC\Corpus\source-store\discovery\` and `...\evidence\`. The per-scope result files are in `...\Corpus\discovery-log\`.

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

**Clips that depend on A2's window clarification.** A2 says a 60–180 s fixed, uncut window may sit inside a longer clip whose view changes elsewhere. It was written after passes 1–2 had been seen, and it reads rule 3's "fixed for the usable span" this way. Two selected clips depend on it:
- **s2-02** (Sofia): 441 s source, 2–90 s window;
- **s2-03** (Crest Hill): 91 s source, 1–69 s window.

The other six are fixed for their whole source.

**Selection (rules §4).** After rules 1–2 (kit licence; ≥ 60 s; ≥ 640×360), rule 3 was applied to the plausible candidates:
- **First screen:** three frames per candidate, about 45 candidates.
- **Finer screen:** one frame every 10–15 s for 26 candidates.
- **Frames used:** rendered by Commons at 330–500 px and kept only on `E:\MAVI-Working\tmp`. Rationale: confirm a fixed, uncut viewpoint so that zone and line geometry stays valid. No label, count or annotation was produced.
- **How the frames were fetched (outside the helper, disclosed):**
  - **Requests.** Small Python `urllib` scratch scripts made plain HTTPS GETs to `upload.wikimedia.org/wikipedia/commons/thumb/…/<width>px-seek=<s>-<file>.jpg`, Commons' public video-thumbnail renderer. Each script was run with `python -I` and was not committed.
  - **Headers.** A User-Agent naming MAVI and the repository URL; no credentials or cookies.
  - **Volume.** About 330 thumbnails.
  - **A further 8 frames.** Reference frames for drawing scene geometry were fetched the same way.
  - **Two metadata checks.** The `LicenseReview` lookups in §2 were two read-only `action=query&prop=revisions` calls to `commons.wikimedia.org/w/api.php`, made with `curl`.
  - **No original media** was fetched this way. Originals: §3.

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
- **YouTube-sourced pages.** s2-02 and s2-04 were imported to Commons from YouTube, where the uploader marked them CC BY. The Commons page licence governs (rule 1).
- **Both licence claims passed Commons licence review.** At the bound revisions, each page carries a passed `{{LicenseReview}}`. That is a Commons reviewer's check that the YouTube source showed the CC BY licence at review time, which mitigates the known YouTube licence-laundering risk:
  - s2-02, revision 1035020995: reviewer Explicit, 2017-11-24, YouTube `Fao9_a0ZgP4`;
  - s2-04, revision 1274270458: reviewer McZusatz, 2013-02-03, YouTube `Ina7KMV2OEI`.
- **s2-02's "PD" title.** s2-02's YouTube title contains "PD". The reviewed licence is CC BY 3.0, so the clip is attributed under CC BY.

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
- **Helper-transferred files.** The helper's own transport downloaded four files. Their `ACQUIRED` receipts are kept beside the later `ALREADY_PRESENT_VERIFIED` ones:
  - s2-01: `d23f39fe70f472f6c894685bae2a4ec20ebe9e65ccfefe889cc6f559557b2dd2`;
  - s2-04: `723de7d668ced6a78a5e474d8ab7cb1da0d9b8a54b4904c563b29b0a53538e7d`;
  - s2-05: `52920cf349f028208dccd06f740cc6232b5d9d0e37efc8b1e0831ed9b0e9ab09`;
  - s2-07: `6df4e69db2f69eda7bcddb11409864af8fbc0f0252e702505b609ff42a9df8b5`.
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

## 6. Trims, manifests and the end-to-end import (B4)

**Trims.** `tools/poc/demo_corpus.py trim` derived all eight clips. It used the repository FFmpeg 9.0.1 essentials build, `ffmpeg.exe` SHA-256 `72a489eccd008c2ec2c0a5856c5c75bc3d8bbfa90166c4566865c246445e6aa3`, with the pinned argument list `FFMPEG_ARGS` (single-threaded libx264 CRF 20, bit-exact flags, audio and metadata dropped).
- The trim windows run 68–180 s.
- s2-03 and s2-04 are resampled to 30 fps: s2-03 is AV1 4K at 59.94 fps, and s2-04 reports an unreliable average rate. Every other clip keeps its native rate.
- **Reproduced.** A second full trim pass reproduced all eight derivative SHA-256 values byte for byte (`"reproduced": true` × 8).

The derivative hashes are pinned in `tools/poc/demo-corpus/demo-corpus-v1.json`.

**Retained on E:.** Everything below is in `E:\MAVI-Controlled\PoC\Corpus\`:
- `manifests\originals.sha256`, `manifests\derivatives.sha256` and `manifests\derivation-record.json`;
- the run evidence, in `evidence-2026-10-28\`, whose `SHA256SUMS` file has SHA-256 `98118e3661c7c223be764dafb9f980af02160fff96be2ccb5717fa238a91d548`. It holds the four import logs, the API mutation extract, the two licence-review responses, both trim outputs, the manifests and the worker identity.

**Import into a fresh database (B4).** This run used a fresh, empty database and a Development build of this branch. It is **not** a kit installation. The row's "clean install" criterion is met only when the same import runs after `Install-MAVI-PoC` (S1). B4 therefore stays IN PROGRESS. The setup:
- **Database.** A new, empty database `mavi_poc_s2_20261028` on the Development PostgreSQL (no cameras or videos).
- **API.** `Mavi.Api` built from this branch, Development environment, on `http://127.0.0.1:62183`, with media and evidence roots on `E:\MAVI-Working\poc-s2-runtime`.
- **Worker.** `Start-MaviVisionWorker.ps1`, which resolved `cuda_selected` with Runtime Pack `windows-x86_64-cuda` and the bound RTMDet Model Pack.

`python tools/poc/demo_corpus.py import --root E:\MAVI-Controlled\PoC\Corpus --api http://127.0.0.1:62183` then created eight cameras (`POC-S2-01`–`08`), eight assets and eight scene revisions (r1). It processed all eight runs to `Completed` with analytics `Ready`, and exited `0`.

**Reruns (idempotence).** The API ran four imports in its lifetime. `evidence-2026-10-28\api-mutations-extract.log` holds every non-worker mutating request. It shows exactly:
- 8 `POST /api/cameras` → 201;
- 8 `POST /api/videos/import` → 201;
- 8 `PUT …/scene` → 201;
- 8 `POST …/process` → 202;
- 24 `POST /api/videos/import` → 409 `video_duplicate`, from runs 2–4.

No rerun created, saved or queued anything, and every rerun returned the same ids, revisions and runs.

Runs 3 and 4 log each mutating call themselves. Run 4 was made with the committed tool at `75b43dc3`, and its log pins both inputs:
- definition SHA-256 `7661ddb4e1f906104d65d3224e0e123eb04a91fb06d62f755b918607ab0dd7e2`;
- `demo_corpus.py` SHA-256 `9e7933559d80b38374bde61c0d727eb79b53ec75464eb4512d3539aed2f25999`.

The duplicate path now also checks each asset's recording start, against the server's own UTC offset, and that check passed in runs 3 and 4.

**Retained licence-review responses.** The two `LicenseReview` responses cited in §2 are retained as `licensereview-*.json`.

| Clip | Run | Tracks created | Analytics |
|---|---|---|---|
| s2-01 Düsseldorf junction | `01a1830f-d22e-7ef5-a366-7eeb28bec06a` | 104 | Ready |
| s2-02 Sofia junction | `01a18314-44e7-7402-bfe6-d6a76f46e6d6` | 141 | Ready |
| s2-03 Crest Hill road | `01a18318-6870-7451-98c9-73b35624132c` | 55 | Ready |
| s2-04 night highway | `01a1831c-68ae-78d8-89fa-25cbedb6f71b` | 334 | Ready |
| s2-05 archway gate | `01a18325-21df-7731-8e2a-2fb25aa2bc11` | 23 | Ready |
| s2-06 level crossing | `01a18329-475f-7d5e-aee0-3f4e36dc2416` | 4 | Ready |
| s2-07 Shibuya crossing | `01a1832c-cd7b-73b1-83ab-1360398bd012` | 19 | Ready |
| s2-08 Damascus Gate overhead | `01a18330-2e8f-7544-9a94-c3277bdd3807` | **0** | Ready |

**Observed limits.** These are operational observations, not measurements. Track counts are pipeline output, not counts of objects; no ground truth exists or was created.
- **s2-08 yields no Tracks.** The phase-1 RTMDet (COCO) detector does not detect people seen from directly above. The clip still demonstrates import, scene configuration and an empty-result path, but it is weak for person demos.
- **s2-07 yields few Tracks.** It is 640×480 with a dense, small-scale crowd, so it yields few Tracks for its content.
- **Replacement needs an owner decision.** Replacing either clip would need a new discovery pass. Selection closed at A3, so that is an owner decision.

## 7. MEVA addition: car park, indoor faces, cross-camera (amendment A4, owner instruction)

**Release-level admissibility (ADR-017 §7).**
- **Status.** The MEVA public release is **RESEARCH-ADMISSIBLE** for Development. Redistribution in the kit is permitted by CC BY 4.0, with attribution and indication of changes.
- **Terms.** The verbatim licence file `https://mevadata.org/resources/MEVA-data-license.txt` is retained at `E:\MAVI-Controlled\PoC\Corpus\approvals\MEVA-data-license.txt`, SHA-256 `bdeedfb765049c87f92a2450369ad70882fca3371190b2a6b7e560e103c922e8`. It opens: '"Multiview Extended Video with Activities" (MEVA) dataset by Kitware Inc. and the Intelligence Advanced Research Projects Activity (IARPA) is licensed under a Creative Commons Attribution 4.0 International License'.
- **Access.** Public S3 bucket `mevadata-public-01` (us-east-1), over HTTPS, with no credentials or account.
- **Why release-level.** The terms are uniform across the release, so one release-level record covers all four files (ADR-017 "release-level by default").

**Privacy and consent (B3).**
- **Who is shown.** The people are volunteer actors at the Muscatatuck Urban Training Center.
- **What the paper states.** The MEVA paper (Corona et al., WACV 2021, arXiv:2012.00914) states that participants signed informed-consent forms after a briefing. It also states that the protocol and briefing included the CC BY 4.0 licence under which the data may be released, and that collection was under IRB oversight and approval.
- **Faces.** This is a consented, release-cleared recording, but it is **not literally a "model release"** as B3 words it. Whether it satisfies B3 is an **owner decision**.
- **What S2 creates.** No face is detected, cropped, counted or labelled in S2.

**Identity labels reused, none created.**
- **The source.** MEVID (Kitware, WACV 2023) labels 158 actors (598 person-outfits) across 33 MEVA views. Two of its public files are retained in the controlled store:
  - `mevid-v1-video-URLS.txt`, SHA-256 `99b674beb9fb98192259d04e33cb3f95bfc6f94d8eb6d0d926573e5e0157530d`, used only to select clips that contain labelled actors;
  - `mevid-v1-annotation-data.zip`, SHA-256 `18a91691a0ccb3b79302c55643840bc5b7f16a9ed813d93bbe91edd151f982e8`.
- **Read-only statistics** from `track_{train,test}_info.txt`:
  - **132** of the 598 person-outfits have tracklets in at least two of the four selected cameras;
  - by camera pair: G419–G421 68, G419–G424 61, G419–G423 54, G421–G424 42, G421–G423 28, G423–G424 24;
  - **11** appear in all four.
- **What this shows, and what it does not.** Genuine cross-camera repeat appearances between these views are an established fact of the source, not something MEVA staged for us. MEVID's files carry no clip or time stamp, so S2 does **not** claim which actors repeat inside the selected 5-minute slot. Any ReID result on these clips is a *candidate*. It is not identity evidence and not a ReID performance measure (D3, C6).

**Files.** Slot 2018-03-11 16:20; all four are school-building cameras, fixed, 1920×1072/1080 at 30 fps, 300 s:

| Clip | Camera / view | Object (`drops-123-r13/2018-03-11/16/…`) | Bytes | Original SHA-256 |
|---|---|---|---|---|
| s2-09 | G424 parking lot | `2018-03-11.16-20-02.16-25-02.school.G424.r13.avi` | 97 989 578 | `a092f15c3c55dce8c30418aa78f60ff6921962e01b373c616233c7a3e27dd952` |
| s2-10 | G421 cafe | `2018-03-11.16-20-00.16-25-00.school.G421.r13.avi` | 103 000 564 | `bba8290ef6e8f9c81516b15eb6fa36372bbe4346f9d8acb0360c3a6cfdd6d28c` |
| s2-11 | G423 hallway | `2018-03-11.16-20-00.16-25-01.school.G423.r13.avi` | 80 699 352 | `443bce856d638f002fcfb19d6da9212bfce58814ed6bd1f36520151c0fb37d91` |
| s2-12 | G419 stairwell | `2018-03-11.16-20-01.16-25-01.school.G419.r13.avi` | 88 315 936 | `93ec12fafcb0ee166c71ec7a46061223e4257de9404d9992f118de275bfc416a` |

**Transfer.**
- **Method.** Resumable HTTPS `curl`, with no credentials, into `source-store\media\meva\…`.
- **Integrity.** Each file's size matched the bucket's declared `Content-Length`. S3 publishes no content digest for these multipart objects (the ETags are multipart, not MD5), so integrity rests on the declared size and on the SHA-256 recorded at acquisition (`approvals\meva-originals.sha256`).
- **B1 wording.** This is not `tools/qualification/source_acquisition`, which implements only Commons. B1 says "acquired through `tools/qualification/source_acquisition`", so accepting this path is an **owner decision**.

**Diagnostic look (B5).** Three frames per clip, at 5, 90 and 175 s, to confirm a fixed and populated view. No label or count was made.

**Demo timing.** The demo start times keep the real offsets between cameras (09:40:00–09:40:02), so cross-camera timing in the demo is genuine.

## 8. Functional evidence per event (owner instruction 5)

**Thresholds (fixed before any loitering output was read).** A loitering threshold must be demonstrable inside its clip. The rule is: threshold ≤ half the trimmed window, rounded down to 5 s. `validate` enforces it. It lowered five thresholds:

| Clip | Zone | Old | New |
|---|---|---|---|
| s2-02 | Right pavement | 60 s | 40 s |
| s2-03 | Roadside lot bays | 120 s | 30 s |
| s2-05 | Parking bay | 60 s | 50 s |
| s2-07 | Crossing | 60 s | 40 s |
| s2-07 | Near corner | 120 s | 40 s |

The import saved revision 2 for the four affected cameras. Their runs went `Stale` and the importer's re-analysis path requested analysis (202), after which they returned to `Ready`.

**Audit.** `python tools/poc/demo_corpus.py audit` reads aggregates and Track search for each clip's own window. It reports, for every configured event, a **positive** (the event fired) and a **meaningful negative** (the same population where it did not), and calls an event *demonstrable* only when both are non-zero:

| Event | Positive | Negative |
|---|---|---|
| Zone entry | Tracks that entered | Analysed Tracks that never entered |
| Crossing, each direction | Crossings in that direction | Crossings in the opposite direction |
| Person loitering | Persons whose dwell reached the threshold | Persons who dwelled below it |
| Vehicle stationary ≥ 30 s in a `Restricted` zone | Vehicles stationary that long | Vehicles that dwelled there without |

The person-only loitering rule is the engine's own (plan §M). The 30 s stationary value was **chosen after the first audit, and is disclosed as such**.

The numbers are pipeline output for one run each. They are not counts of real objects; no ground truth exists.

**Results (audit of the final definition, 12 clips).** Audit tool SHA-256 `db649df4f4dbada71a5154fe04d723e76b7fe1a38cefb5b16c5748ef4866203e`, definition SHA-256 `014706a7fe28133a3742938320085eb296c7db0762c1182e28b12583823318fc`. Each event is shown as positive / negative; ✔ marks one that is demonstrable.

| Clip | Tracks (P/V) | Demonstrable events (positive / negative) | Not demonstrable |
|---|---|---|---|
| s2-01-dusseldorf-junction | 36/66 | ✔ zone entry Corner pavement 64/40; ✔ zone entry Tram box 6/96; ✔ crossing Outbound Junction exit 11/9; ✔ crossing Inbound Junction exit 9/11 | person loitering >= 60 s Corner pavement 0/27; person loitering >= 20 s Tram box 0/3; vehicle stationary >= 30 s Tram box 0/3 |
| s2-02-sofia-junction | 29/112 | ✔ zone entry Junction box 54/94; ✔ zone entry Right pavement 70/61; ✔ crossing Away Crosswalk 3/24; ✔ crossing Toward Crosswalk 24/3 | person loitering >= 30 s Junction box 0/4; vehicle stationary >= 30 s Junction box 0/43; person loitering >= 40 s Right pavement 0/10 |
| s2-03-crest-hill-road | 0/55 | ✔ zone entry Roadside lot bays 84/14; ✔ crossing Rightward Count line 12/7; ✔ crossing Leftward Count line 7/12 | person loitering >= 30 s Roadside lot bays 0/0; vehicle stationary >= 30 s Roadside lot bays 0/41 |
| s2-04-night-highway | 0/333 | ✔ zone entry Near carriageway 275/53; ✔ crossing Away Overpass line 123/223; ✔ crossing Toward Overpass line 223/123 | person loitering >= 10 s Near carriageway 0/0 |
| s2-05-vrhnika-arch-gate | 0/23 | ✔ vehicle stationary >= 30 s Parking bay 3/20 | zone entry Gate approach 0/23; person loitering >= 30 s Gate approach 0/0; zone entry Parking bay 16/0; person loitering >= 50 s Parking bay 0/0; crossing Exit Arch gate 0/0; crossing Entry Arch gate 0/0 |
| s2-06-beynost-level-crossing | 1/3 | ✔ zone entry Crossing box 2/2 | person loitering >= 10 s Crossing box 0/1; vehicle stationary >= 30 s Crossing box 0/1; zone entry Waiting area 0/1; person loitering >= 30 s Waiting area 0/0; crossing Away Barrier line 0/1; crossing Toward Barrier line 1/0 |
| s2-07-shibuya-crossing | 2/17 | ✔ zone entry Crossing 4/1; ✔ zone entry Near corner 8/12; ✔ crossing Away Crossing midline 2/3; ✔ crossing Toward Crossing midline 3/2 | person loitering >= 40 s Crossing 0/1; person loitering >= 40 s Near corner 0/2 |
| s2-08-damascus-gate-overhead | 0/0 | — | zone entry Passage centre 0/0; person loitering >= 30 s Passage centre 0/0; vehicle stationary >= 30 s Passage centre 0/0; zone entry Stall front 0/0; person loitering >= 60 s Stall front 0/0; crossing Rightward Gate midline 0/0; crossing Leftward Gate midline 0/0 |
| s2-09-meva-parking-lot | 2/10 | ✔ zone entry Upper bays 1/6 | zone entry Lower bays 0/11; vehicle stationary >= 30 s Lower bays 1/0; vehicle stationary >= 30 s Upper bays 4/0; crossing Rightward Lot lane 1/0; crossing Leftward Lot lane 0/1 |
| s2-10-meva-cafe-lobby | 8/0 | ✔ zone entry Seating area 5/5 | zone entry Entrance floor 8/0; person loitering >= 30 s Entrance floor 0/8; person loitering >= 30 s Seating area 0/3; crossing Out Doorway line 0/0; crossing In Doorway line 0/0 |
| s2-11-meva-school-hall | 20/0 | — | zone entry Corridor near 0/20; person loitering >= 30 s Corridor near 0/0; crossing Away Hall midline 0/0; crossing Toward Hall midline 0/0 |
| s2-12-meva-stairwell | 9/0 | ✔ zone entry Landing 7/3; ✔ crossing To door Landing line 2/3; ✔ crossing From door Landing line 3/2 | person loitering >= 30 s Landing 0/6 |

**Findings.**
- **Zone entry and two-direction crossing** are demonstrable on s2-01, s2-02, s2-03, s2-04, s2-07 and s2-12. Zone entry alone is demonstrable on s2-06, s2-09 and s2-10.
- **Stationary vehicle ≥ 30 s in a restricted bay** has a real negative only on s2-05 (3 / 20). On s2-09 (parking lot), parked vehicles are positive (4 and 1), but no vehicle passed through a bay without stopping, so it has no in-zone negative.
- **Person loitering** is **not demonstrated on any clip.** The longest person dwell in any zone is about 20 s (s2-01 corner, threshold 60 s). The zones with 10–20 s thresholds (s2-01 tram box, s2-04, s2-06 crossing box) had no person dwelling at all. People in this corpus pass through; none waits. Lowering thresholds after reading the output would be tuning to the result, so it was not done.
- **No usable event:** s2-08 (overhead, 0 Tracks) and s2-11 (hallway). On s2-11 the 20 person Tracks stay far down the corridor; the zone and line drawn near the camera are never reached. The geometry was **not** moved after reading the output; that is an owner choice (§9).
- **No demonstrable crossing:** s2-05 (gate line) and s2-06 (barrier line); their Tracks are few or never cross.

## 9. Owner decisions required (none is taken by the operator)

| # | Decision | Row | Operator recommendation |
|---|---|---|---|
| 1 | **Ratify** the operator-signed determinations `poc-s2-commons-cc0-2026-10` and `poc-s2-commons-cc-by-2026-10`. This is separate from accepting the attribution file. The hash-bound approval JSONs stay unchanged. | B1 | Ratify |
| 2 | **Accept the MEVA acquisition path.** It uses a release-level ADR-017 record and an HTTPS transfer with SHA-256, not `tools/qualification/source_acquisition`, against B1's wording. | B1 | Accept, or have the helper extended later |
| 3 | **Accept MEVA's IRB informed consent with its CC BY 4.0 release as satisfying B3's "model-released"** for the face-bearing clips s2-10, s2-11 and s2-12. | B3 | Accept |
| 4 | **Accept `demo-corpus-attribution.md`** (12 clips; MEVA notice). | B2 | Accept |
| 5 | **Person loitering is not demonstrated** on any clip. Options:<br>(a) record it as a known limit;<br>(b) replace s2-08 (0 Tracks) with MEVA G331, the bus-stop interior in the same 2018-03-11 16:20 slot, where actors wait. That keeps the cap of 12 and needs a recorded amendment;<br>(c) authorise a disclosed post-hoc threshold on s2-01's corner. That threshold would be 15 s, giving 2 / 20. | B1 | (b) |
| 6 | **s2-11 (hallway) has no usable event**, because people stay far down the corridor. Options:<br>(a) authorise one disclosed geometry redraw over the far corridor;<br>(b) keep it as a face and cross-camera view only. | B1 | (b) for S2, revisit in S6 |
| 7 | **The car-park class is met by s2-09** (MEVA G424): parked vehicles are stationary ≥ 30 s, but little traffic passes. Accept it, or ask for a busier lot slot. | B1 | Accept |
| 8 | **B4 closes only after the S2 import runs on a kit install** (`Install-MAVI-PoC`, S1). S1 must also seed `config/poc/demo-cameras-v1.json` equal to `tools/poc/demo-corpus/demo-cameras-v1.json` (hand-over sent). | B4 | — |
