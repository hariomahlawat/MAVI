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
| Pedestrian | ≥ 2 | 2 until A5: s2-07 Shibuya scramble crossing, s2-08 Damascus Gate overhead. After A5 (owner decision 5(b)), s2-07 plus the indoor walking views s2-08 bus stop, s2-11 hallway and s2-12 stairwell |
| Car park | ≥ 1 | 1 after A4: s2-09 (MEVA G424). **GAP** in Commons, closed by MEVA (§7) |
| Lobby / close-range faces | ≥ 1 | 3 after A4: s2-10 cafe, s2-11 hallway, s2-12 stairwell; 4 after A5 with s2-08 bus-stop waiting room (MEVA; consent accepted, owner decision 3(a)). **GAP** in Commons, closed by MEVA (§7) |

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

**Release-level admissibility of MEVA video (ADR-017 §7).**
- **Status.** The MEVA public release is **RESEARCH-ADMISSIBLE** for Development. Redistribution in the kit is permitted by CC BY 4.0, with attribution and indication of changes.
- **Terms.** The verbatim licence file `https://mevadata.org/resources/MEVA-data-license.txt` is retained at `approvals\MEVA-data-license.txt`, SHA-256 `bdeedfb765049c87f92a2450369ad70882fca3371190b2a6b7e560e103c922e8`. It opens: '"Multiview Extended Video with Activities" (MEVA) dataset by Kitware Inc. and the Intelligence Advanced Research Projects Activity (IARPA) is licensed under a Creative Commons Attribution 4.0 International License'.
- **Access.** Public S3 bucket `mevadata-public-01` (us-east-1), over HTTPS, with no credentials or account.
- **Why release-level.** The terms are uniform across the release, so one release-level record covers all four files.

**Privacy and consent (B3).**
- **Who is shown.** The people are volunteer actors at an access-controlled training facility.
- **What the paper states.** The MEVA paper is retained as `approvals\meva-wacv2021-arxiv-2012.00914v1.pdf`, SHA-256 `48f7773d522358bf7509030f6059c7abe36aa8b6124cd181855f5afdd6d39831`. Its §3.1 "Releasability" (p. 4) states that:
  - the collection was overseen by an IRB;
  - a human-subjects protocol and informed-consent documents described how the data would be released;
  - the consent briefing included a sample licence, CC BY 4.0;
  - participants who chose to take part signed consent forms;
  - collection took place at an access-controlled facility, to minimise non-participants in view.
- **Faces.** This is consent with a stated CC BY release, but it is **not literally a "model release"** as B3 words it. That is **owner decision 3**.
- **What S2 creates.** No face is detected, cropped, counted or labelled in S2.

**Cross-camera repeat appearances.**
- **By design.** The same paper (§3.2, p. 4) says activities "were scripted to be performed by the same individual in different, singular cameras with the goal of associating the same individual across different cameras".
- **The selected clips.** The four clips come from one real 5-minute slot in one school building, all fixed cameras. Their demo start times keep the real offsets between cameras (09:40:00–09:40:02).

**MEVID identity labels: ADR-017 reuse record, added after the cold review.**
- **What MEVID is.** MEVID (Kitware, WACV 2023, `github.com/Kitware/mevid`) labels 158 actors and 598 person-outfits. Per its paper, it covers 33 MEVA views; the annotation files themselves contain 25 camera ids.
- **Where it is published.** In the same public MEVA bucket, under `mevid-annotations/`. mevadata.org states "All MEVA data is available for use under a CC BY-4.0 license". The MEVID GitHub repository carries no separate licence file. That ambiguity is recorded, not resolved.
- **Status.** **RESEARCH-ADMISSIBLE** for Development (ADR-017 §7: lawfully obtainable, and no term prohibits the use).
- **Use.** Read-only selection and statistics. No labels are created, and none enter the kit.
- **Files retained:**
  - `mevid-v1-video-URLS.txt`, SHA-256 `99b674beb9fb98192259d04e33cb3f95bfc6f94d8eb6d0d926573e5e0157530d`, used to select clips that contain labelled actors;
  - `mevid-v1-annotation-data.zip`, SHA-256 `18a91691a0ccb3b79302c55643840bc5b7f16a9ed813d93bbe91edd151f982e8`.
- **Order of events, disclosed.** A4 said any further use of the labels would need a separate recorded reuse. The annotation zip was nevertheless fetched and read before this record existed. This record is that reuse record, written afterwards. Keeping or dropping the statistics is **owner decision 9**.

**Statistics** from `track_{train,test}_info.txt`:
- **132** of the 598 person-outfits have tracklets in at least two of the four selected cameras;
- by camera pair: G419–G421 68, G419–G424 61, G419–G423 54, G421–G424 42, G421–G423 28, G423–G424 24;
- **11** appear in all four.
- **After A5, G331** (same method and files, same read-only reuse under decision 9): 37 person-outfits have G331 tracklets, and 18 of them also appear in at least one of the four school cameras (G331–G421 11, G331–G419 10, G331–G424 7, G331–G423 7). Across all five cameras, 138 person-outfits appear in at least two, and none in all five.

MEVID's files carry no clip or time stamp, so S2 does **not** claim which actors repeat inside the selected slot. Any ReID result on these clips is a *candidate*. It is not identity evidence and not a ReID performance measure (D3, C6).

**Files.** Slot 2018-03-11 16:20; fixed cameras, 1920×1072/1080 at 30 fps, 300 s. The four A4 files are school-building cameras; G331 (added by A5) is the bus-stop building:

| Clip | Camera / view | Object (`drops-123-r13/2018-03-11/16/…`) | Bytes | Original SHA-256 |
|---|---|---|---|---|
| s2-09 | G424 parking lot | `2018-03-11.16-20-02.16-25-02.school.G424.r13.avi` | 97 989 578 | `a092f15c3c55dce8c30418aa78f60ff6921962e01b373c616233c7a3e27dd952` |
| s2-10 | G421 cafe | `2018-03-11.16-20-00.16-25-00.school.G421.r13.avi` | 103 000 564 | `bba8290ef6e8f9c81516b15eb6fa36372bbe4346f9d8acb0360c3a6cfdd6d28c` |
| s2-11 | G423 hallway | `2018-03-11.16-20-00.16-25-01.school.G423.r13.avi` | 80 699 352 | `443bce856d638f002fcfb19d6da9212bfce58814ed6bd1f36520151c0fb37d91` |
| s2-12 | G419 stairwell | `2018-03-11.16-20-01.16-25-01.school.G419.r13.avi` | 88 315 936 | `93ec12fafcb0ee166c71ec7a46061223e4257de9404d9992f118de275bfc416a` |
| s2-08 (A5) | G331 bus-stop waiting room | `2018-03-11.16-20-00.16-25-00.bus.G331.r13.avi` | 87 225 020 | `e9428729f0ef403fa8676d6bd7c7b9f274cbdb6b1b5a1f7b0bbe658154f2995c` |

**Transfer.**
- **Method.** Resumable HTTPS `curl`, with no credentials, into `source-store\media\meva\…`.
- **Integrity.** Each file's size matched the bucket's declared `Content-Length`. S3 publishes no content digest for these multipart objects, so integrity rests on the declared size and on the SHA-256 recorded at acquisition (`approvals\meva-originals.sha256`).
- **Order, and its limit.** The order "A4 committed (23:08:09), then the first MEVA media file created (23:08:32)" rests on filesystem times. `meva-fetch.log` holds no timestamps. This is disclosed.
- **B1 wording.** This is not `tools/qualification/source_acquisition`, so accepting this path is **owner decision 2**.

**Diagnostic look (B5).** Three frames per clip, at 5, 90 and 175 s, to confirm a fixed and populated view. No label or count was made.

## 8. Functional evidence per event (owner instruction 5)

**Thresholds (fixed before any loitering output was read).** A loitering threshold must be demonstrable inside its clip. The rule is: threshold ≤ half the trimmed window, rounded down to 5 s. `validate` enforces it, and a zone with no threshold is checked at the engine default of 120 s. Changes:

| Clip | Zone | Old | New | Applied in |
|---|---|---|---|---|
| s2-02 | Right pavement | 60 s | 40 s | run 5 |
| s2-03 | Roadside lot bays | 120 s | 30 s | run 5 |
| s2-05 | Parking bay | 60 s | 50 s | run 5 |
| s2-07 | Crossing | 60 s | 40 s | run 5 |
| s2-07 | Near corner | 120 s | 40 s | run 5 |
| s2-09 | Upper bays | unset (default 120 s) | 90 s | run 7, after the cold review |
| s2-09 | Lower bays | unset (default 120 s) | 90 s | run 7, after the cold review |

Each change saved a new scene revision. The runs went `Stale`, and the importer's re-analysis request (202) returned them to `Ready`.

**Audit definition** (`python tools/poc/demo_corpus.py audit`). For each clip it reads aggregates over whole UTC hours covering the clip, plus Track search, for each configured event. It compares two **disjoint sets in the same unit**:

| Event | Unit | Positive | Negative |
|---|---|---|---|
| Zone entry | Tracks | Tracks with an entry event (`zoneRelation=entered`) | Analysed Tracks never present in the zone |
| Crossing, each direction | Crossings | That direction | The opposite direction |
| Person loitering (the engine's rule is person-only, plan §M) | Tracks | Persons whose dwell reached the threshold | Persons who dwelled below it |
| Vehicle in a `Restricted` zone, stationary ≥ 30 s | Tracks | Vehicles present in the zone whose **longest stationary period anywhere** reached 30 s | Vehicles present in the zone that never stood that long |

Notes on the definitions:
- **Zone entry.** Tracks that start inside the zone are in neither set. A zero-length entry visit would count as entered without counting as present in the aggregate, so it could fall in both sets. That case is not expected in practice. The aggregate's entry-*event* count is reported separately, as `entryEvents`.
- **Stationary.** The query cannot show that the vehicle stood *inside* the zone, because `minStationaryMs` filters the Track's longest stationary period. The 30 s value was **chosen after the first audit**, so accepting it is **owner decision 10**.

An event is *demonstrable* only when both sets are non-empty. The numbers are pipeline output for one run each. They are not counts of real objects; no ground truth exists.

**Results** (`audit-4.json`). Audit tool SHA-256 `618954f7f98f7888fcbeba411a7879aba11764da9e8f5e904621bee458c222e8`, definition SHA-256 `6a4e2c9bb74385011f3d02d1af040d51afd311ad49f76f8084328b7925ad0c97`. Each event is shown as positive / negative; ✔ marks one that is demonstrable.

| Clip | Tracks (Person / Vehicle) | Demonstrable | Not demonstrable |
|---|---|---|---|
| s2-01-dusseldorf-junction | 36 / 66 | ✔ zone entry — Corner pavement 43 / 40; ✔ zone entry — Tram box 5 / 96; ✔ crossing Outbound — Junction exit 11 / 9; ✔ crossing Inbound — Junction exit 9 / 11 | person loitering >= 60 s — Corner pavement 0 / 27; person loitering >= 20 s — Tram box 0 / 3; vehicle in zone, stationary >= 30 s (anywhere) — Tram box 0 / 3 |
| s2-02-sofia-junction | 29 / 112 | ✔ zone entry — Junction box 47 / 94; ✔ zone entry — Right pavement 41 / 61; ✔ crossing Away — Crosswalk 3 / 24; ✔ crossing Toward — Crosswalk 24 / 3 | person loitering >= 30 s — Junction box 0 / 4; vehicle in zone, stationary >= 30 s (anywhere) — Junction box 0 / 43; person loitering >= 40 s — Right pavement 0 / 10 |
| s2-03-crest-hill-road | 0 / 55 | ✔ zone entry — Roadside lot bays 39 / 14; ✔ crossing Rightward — Count line 12 / 7; ✔ crossing Leftward — Count line 7 / 12 | person loitering >= 30 s — Roadside lot bays 0 / 0; vehicle in zone, stationary >= 30 s (anywhere) — Roadside lot bays 0 / 41 |
| s2-04-night-highway | 0 / 333 | ✔ zone entry — Near carriageway 258 / 53; ✔ crossing Away — Overpass line 123 / 223; ✔ crossing Toward — Overpass line 223 / 123 | person loitering >= 10 s — Near carriageway 0 / 0 |
| s2-05-vrhnika-arch-gate | 0 / 23 | ✔ vehicle in zone, stationary >= 30 s (anywhere) — Parking bay 3 / 20 | zone entry — Gate approach 0 / 23; person loitering >= 30 s — Gate approach 0 / 0; zone entry — Parking bay 6 / 0; person loitering >= 50 s — Parking bay 0 / 0; crossing Exit — Arch gate 0 / 0; crossing Entry — Arch gate 0 / 0 |
| s2-06-beynost-level-crossing | 1 / 3 | ✔ zone entry — Crossing box 2 / 2 | person loitering >= 10 s — Crossing box 0 / 1; vehicle in zone, stationary >= 30 s (anywhere) — Crossing box 0 / 1; zone entry — Waiting area 0 / 1; person loitering >= 30 s — Waiting area 0 / 0; crossing Away — Barrier line 0 / 1; crossing Toward — Barrier line 1 / 0 |
| s2-07-shibuya-crossing | 2 / 17 | ✔ zone entry — Crossing 4 / 1; ✔ zone entry — Near corner 6 / 12; ✔ crossing Away — Crossing midline 2 / 3; ✔ crossing Toward — Crossing midline 3 / 2 | person loitering >= 40 s — Crossing 0 / 1; person loitering >= 40 s — Near corner 0 / 2 |
| s2-08-damascus-gate-overhead | 0 / 0 | — | zone entry — Passage centre 0 / 0; person loitering >= 30 s — Passage centre 0 / 0; vehicle in zone, stationary >= 30 s (anywhere) — Passage centre 0 / 0; zone entry — Stall front 0 / 0; person loitering >= 60 s — Stall front 0 / 0; crossing Rightward — Gate midline 0 / 0; crossing Leftward — Gate midline 0 / 0 |
| s2-09-meva-parking-lot | 2 / 10 | ✔ zone entry — Upper bays 1 / 6; ✔ person loitering >= 90 s — Upper bays 1 / 1 | zone entry — Lower bays 0 / 11; person loitering >= 90 s — Lower bays 0 / 0; vehicle in zone, stationary >= 30 s (anywhere) — Lower bays 1 / 0; vehicle in zone, stationary >= 30 s (anywhere) — Upper bays 4 / 0; crossing Rightward — Lot lane 1 / 0; crossing Leftward — Lot lane 0 / 1 |
| s2-10-meva-cafe-lobby | 8 / 0 | ✔ zone entry — Seating area 3 / 5 | zone entry — Entrance floor 8 / 0; person loitering >= 30 s — Entrance floor 0 / 8; person loitering >= 30 s — Seating area 0 / 3; crossing Out — Doorway line 0 / 0; crossing In — Doorway line 0 / 0 |
| s2-11-meva-school-hall | 20 / 0 | — | zone entry — Corridor near 0 / 20; person loitering >= 30 s — Corridor near 0 / 0; crossing Away — Hall midline 0 / 0; crossing Toward — Hall midline 0 / 0 |
| s2-12-meva-stairwell | 9 / 0 | ✔ zone entry — Landing 6 / 3; ✔ crossing To door — Landing line 2 / 3; ✔ crossing From door — Landing line 3 / 2 | person loitering >= 30 s — Landing 0 / 6 |

**Person-dwell profile** (retained in `audit-4.json`): persons with dwell ≥ 5 / 10 / 15 / 20 / 30 s, for zones where any person dwelled ≥ 5 s.

| Clip | Zone | ≥ 5 / 10 / 15 / 20 / 30 s |
|---|---|---|
| s2-01-dusseldorf-junction | Corner pavement | 8 / 4 / 2 / 1 / 0 |
| s2-02-sofia-junction | Right pavement | 4 / 1 / 0 / 0 / 0 |
| s2-07-shibuya-crossing | Crossing | 1 / 0 / 0 / 0 / 0 |
| s2-07-shibuya-crossing | Near corner | 1 / 0 / 0 / 0 / 0 |
| s2-09-meva-parking-lot | Upper bays | 1 / 1 / 1 / 1 / 1 |

**Findings.**
- **Zone entry and two-direction crossing** are demonstrable on s2-01, s2-02, s2-03, s2-04, s2-07 and s2-12. Zone entry alone is demonstrable on s2-06, s2-09 and s2-10.
- **Person loitering** is demonstrable **once**, and weakly: s2-09 upper bays, at 90 s, 1 / 1. That threshold came from the predeclared cap, not from reading the output. Elsewhere people pass through: no person dwelled ≥ 30 s in any other zone, and the longest dwell in the street clips is between 20 and 30 s (s2-01 corner: one person ≥ 20 s, none ≥ 30 s).
- **Vehicle in a restricted zone, stationary ≥ 30 s**, with the query semantics above, is demonstrable only on s2-05 (3 / 20).
- **No usable event** on s2-08 (overhead, 0 Tracks) or s2-11 (hallway). On s2-11 the 20 person Tracks stay far down the corridor, and the near zone and line are never reached. The geometry was **not** moved after reading the output; see decision 6.
- **No demonstrable crossing** on s2-05, s2-06, s2-09 or s2-10: Tracks are few, or none crosses in both directions.

## 9. Owner decisions (all decided 2026-10-29)

The owner decided all ten on 2026-10-29 ("Accept all"), each as the operator recommended. The options are kept as they were put to the owner.

| # | Decision | Row | Operator recommendation | Owner decision |
|---|---|---|---|---|
| 1 | **Ratify** the operator-signed Commons determinations `poc-s2-commons-cc0-2026-10` and `poc-s2-commons-cc-by-2026-10`. This is separate from accepting the attribution file. The hash-bound approval JSONs stay unchanged. | B1 | Ratify | **Ratified** (2026-10-29). |
| 2 | **MEVA acquisition path.** It uses a release-level ADR-017 record and an HTTPS transfer with SHA-256, not `tools/qualification/source_acquisition`, against B1's wording. Options:<br>(a) accept it;<br>(b) the non-relaxing alternative: extend the helper with a MEVA provider and re-acquire through it. | B1 | (a), or (b) if the literal wording is to hold | **(a) accepted** (2026-10-29). Also applied to G331 under A5. |
| 3 | **MEVA consent and B3.** Options:<br>(a) accept MEVA's IRB-overseen informed consent, with its CC BY 4.0 release, as satisfying B3's "model-released" for the face-bearing clips s2-10, s2-11 and s2-12;<br>(b) the non-relaxing alternative: keep those three clips **owner-machine-only**, out of the kit, so the kit has no face-bearing clip. | B3 | (a) | **(a) accepted** (2026-10-29). MEVA consent satisfies B3; s2-10, s2-11 and s2-12 (and s2-08 under A5) ship in the kit. |
| 4 | **Accept `demo-corpus-attribution.md`** (12 clips; MEVA notice). | B2 | Accept | **Accepted** (2026-10-29). Clip 8's row was then updated for A5, under the accepted MEVA notice. |
| 5 | **Person loitering** is demonstrated once, weakly (s2-09, 1 / 1). Options:<br>(a) accept that;<br>(b) replace s2-08 (0 Tracks) with MEVA G331, the bus-stop interior in the same slot, where actors wait. That keeps the cap of 12 and needs a recorded amendment;<br>(c) set a disclosed post-hoc threshold of 15 s on s2-01's corner. The retained profile shows 2 persons ≥ 15 s. | B1 | (b) | **(b)** (2026-10-29). s2-08 replaced by MEVA G331 under amendment A5; the cap stays 12. Result in §11. |
| 6 | **s2-11 (hallway) has no usable event.** Options:<br>(a) allow one disclosed geometry redraw over the far corridor;<br>(b) keep it as a face and cross-camera view only. | B1 | (b) for S2, revisit in S6 | **(b)** (2026-10-29). s2-11 stays a face and cross-camera view; geometry unchanged. |
| 7 | **The car-park class is met by s2-09** (MEVA G424), which has little through-traffic. Accept it, or ask for a busier lot slot. | B1 | Accept | **Accepted** (2026-10-29). |
| 8 | **B4 closes only after the S2 import runs on a kit install** (`Install-MAVI-PoC`, S1). S1 must also seed `config/poc/demo-cameras-v1.json` equal to `tools/poc/demo-corpus/demo-cameras-v1.json`. The hand-over has been sent, and a test enforces it once both files are on one branch. | B4 | — | **Noted** (2026-10-29). B4 waits for the kit install. |
| 9 | **MEVID label reuse**, recorded after the files were read (§7). Keep the read-only cross-camera statistics, or drop them and cite only the paper's design statement. B5 is unaffected either way, because reuse creates no label. | B1 | Keep | **Keep** (2026-10-29). |
| 10 | **Accept the post-hoc 30 s value** for the stationary-vehicle demonstration (§8), or choose another value before any further reading. | B1 | Accept, disclosed | **Accepted, disclosed** (2026-10-29). |

## 10. Evidence for the MEVA addition and the audit (retained outside Git)

`E:\MAVI-Controlled\PoC\Corpus\evidence-2026-10-29\`, `SHA256SUMS` = `41f45b285fc6831fd22444b57fe29fa09812f5a34abad2a0bd550f6c210d3168`. It holds:
- the import logs for run 5 (scene revision 2 and re-analysis) and run 6 (MEVA);
- the three audit outputs;
- trim passes 3 and 4;
- the manifests and derivation record;
- the MEVA originals manifest, licence file, MEVID video list, MEVID annotation-zip hash and fetch log;
- the worker identity;
- the API mutation extract.

**API mutation extract**, covering the whole life of the restarted API:

| Calls | Status |
|---|---|
| 4 `POST /api/cameras` | 201 |
| 8 scene `PUT` (4 × revision 2 + 4 new) | 201 |
| 4 `…/scene/analyses` | 202 |
| 4 `POST /api/videos/import` | 201 |
| 16 `POST /api/videos/import` | 409 `video_duplicate` |
| 4 `…/process` | 202 |

**Reproducibility.** All **12** derivatives reproduced byte for byte on trim pass 4. The 8 Commons derivatives have now reproduced on three passes. Run 6 is pinned by the definition SHA-256 `014706a7fe28133a3742938320085eb296c7db0762c1182e28b12583823318fc` and the tool SHA-256 logged at its start.

**After the cold review** (`E:\MAVI-Controlled\PoC\Corpus\evidence-2026-10-29-r2\`, `SHA256SUMS` = `e8d5e6a00b081750bd17a95adf53f1ceb1c1a6e1bfdc39f04f3b75f2dab1141f`). The bundle holds:
- `audit-4.json`, the corrected audit with its retained person-dwell profile;
- `import-run7.log`: s2-09 scene revision 2, re-analysis 202, everything else unchanged with 12 × `409 video_duplicate`;
- the MEVA paper, which is the consent source;
- the cumulative API mutation extract for the restarted API.

The mutation extract counts:

| Calls | Status |
|---|---|
| 4 cameras | 201 |
| 9 scene saves | 201 |
| 5 re-analyses | 202 |
| 4 imports | 201 |
| 28 duplicate imports | 409 |
| 4 process | 202 |

Run 7 is pinned by the definition SHA-256 `6a4e2c9bb74385011f3d02d1af040d51afd311ad49f76f8084328b7925ad0c97`. The s2-09 threshold change touched scene configuration only; every derivative SHA-256 is unchanged.

## 11. Owner decisions applied (2026-10-29): A5 replacement and clean re-import

**Order of events.** Each step happened in this order:
1. Amendment A5 was committed (`4223bd3b`) and pushed before any G331 request.
2. G331 was then fetched over HTTPS. Its size matched the bucket's `Content-Length` (87 225 020), and its SHA-256 `e9428729f0ef403fa8676d6bd7c7b9f274cbdb6b1b5a1f7b0bbe658154f2995c` was added to `approvals\meva-originals.sha256`.
3. A diagnostic look at three frames (5, 90 and 170 s) confirmed a fixed view with people waiting.
4. The geometry was drawn on the 5 s frame, with the 60 s threshold fixed in A5, before any pipeline output for G331 was read.

**Retired, not deleted.** The old s2-08 derivative (Damascus Gate) moved to `E:\MAVI-Controlled\PoC\Corpus\retired\`, so it cannot be packaged by mistake. Its original, receipt and admissibility record are unchanged (§2–§3).

**Trims.**
- Pass 5 derived the new s2-08 (`02ed784a35626ea7aee87d6c8fd6c7ccb484f9cffc83e7c6f97a9bf71df30517`) and reproduced the other eleven.
- Pass 6 reproduced all **12** byte for byte, s2-08 included, with the same pinned FFmpeg.

**Clean re-import.** This run used a fresh, empty database `mavi_poc_s2_20261029` and `Mavi.Api` built from this branch on `main` (`4223bd3b`). The worker was `Start-MaviVisionWorker.ps1`, which resolved `cuda_selected`, `windows-x86_64-cuda`. The run is pinned by the definition SHA-256 `2527ee6b0ce87c320301cf16b703c3e37579a4b63e6a1416646e3b711778b676` and the tool SHA-256 `618954f7f98f7888fcbeba411a7879aba11764da9e8f5e904621bee458c222e8`.
- **Run 1** created 12 cameras, 12 assets, 12 scene revisions (r1) and 12 runs, all `Completed` with analytics `Ready`. It exited `0`.
- **Run 2** changed nothing: 12 × `409 video_duplicate`, the same ids, and no scene or process call.
- **API mutation extract:** 12 cameras 201, 12 imports 201, 12 scene saves 201, 12 process 202, 12 duplicate imports 409.
- **Same output on the unchanged clips.** The eleven unchanged clips produced the same Track counts as the 2026-10-28 runs, and their audit results equal `audit-4.json` event for event.

**Audit of s2-08 (G331)** (`audit-1.json`):
- **Tracks.** 3 Person Tracks. All three start inside the waiting area, so zone entry is 0 / 0.
- **Person loitering ≥ 60 s.** 3 / 0. Every person in the zone dwelled at least 60 s (the dwell profile shows all three ≥ 30 s). Loitering fires on all three, but no person in that zone dwelled below the threshold.
- **Hall midline.** No crossing.

**What this shows for person loitering.** Under the audit's same-zone rule (§8), s2-08 is **not demonstrable on its own**, because its negative set is empty. Across the corpus:
- **Positives.** Loitering fires on 4 persons in 2 clips: s2-08 3 and s2-09 1.
- **Contrast in the same zone.** Only s2-09 has one (1 / 1).
- **Persons below a threshold.** They occur in other zones, for example s2-10 entrance 0 / 8 and s2-12 landing 0 / 6.

The threshold was **not** changed after the audit (A5).

**Evidence.** `E:\MAVI-Controlled\PoC\Corpus\evidence-2026-10-29-a5\`, `SHA256SUMS` = `1df3384b2e4d88c4ae26eb8f552b04059229ba4e28fe392faa049ca5c06d7d52`. It holds:
- both import logs and the audit;
- trim passes 5 and 6, with their derivation records;
- the manifests, the MEVA originals manifest and the fetch log;
- the API mutation extract;
- the worker identity and the device report;
- the three G331 diagnostic frames.
