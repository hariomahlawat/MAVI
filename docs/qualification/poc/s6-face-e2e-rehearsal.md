# PoC S6: face intelligence end-to-end rehearsal (register C5A.4, C5A.5)

**Date:** 2026-10-30. **Evidence class:** Development (ADR-020). Face results are candidates, never identification (ADR-022).
**Evidence:** `E:\MAVI-Controlled\PoC\S6\e2e-2026-10-30\`, `SHA256SUMS` SHA-256 recorded in the register (C5A.4). No face crop, query image, thumbnail or vector is kept in the evidence: thumbnails are replaced by `<omitted: biometric>` and vectors are never fetched.

## Set-up (clean import)

| | |
|---|---|
| Database | A fresh, empty `mavi_poc_s6_20261030` on the Development PostgreSQL 18 instance; the API applied every migration at start. |
| API | `Mavi.Api` built from this branch (`447d6006`, then `cb53b754` for the flows below), `Development`, `Identity:Mode=windows-negotiate` with the host's Windows account as the only authorised operator, `Faces:Enabled=true` on the committed manifest and pipeline profile. |
| Vision worker | `Start-MaviVisionWorker.ps1`: `cuda_selected`, Runtime Pack `mavi-runtime-v2-89fd8bfc…` (`windows-x86_64-cuda`). |
| Faces worker | `Start-MaviFacesWorker.ps1` on the `embeddings-onnx-v1` CPU environment, Model Pack `faces-yunet-adaface-ir50-dev-v1` staged by `tools/vision/faces_packs.py stage` from the controlled store (every artefact SHA-256 checked). Identity fingerprint `03f627a3…7a00`, the committed test vector. |
| Clips | The six MEVA clips s2-08 to s2-13, imported and processed by `tools/poc/demo_corpus.py import --clip …` (Tracks 3, 12, 8, 20, 9, 30; every run Completed). |

## Results

1. **Off by default.** Before opt-in, a Person Track of s2-13 reports `notEnabled`. Without Windows credentials the same read is refused (401).
2. **Opt-in.** The six MEVA cameras were switched on (`PUT /api/cameras/{id}/face-analysis`, one audit row each). The faces worker leased and completed one analysis per run within a minute, with no failure.

   **Deviation from ADR-022 §3.** §3 and the runbook opt in only s2-10, s2-11 and s2-12. This rehearsal also opted in s2-08, s2-09 and s2-13; consent for s2-13 (G420) is not yet owner-confirmed. The cold review found this. s2-08, s2-09 and s2-13 were opted out again the same morning, which deleted their face rows. Their two transient query embeddings (both from one s2-13 crop) were purged by the 1-hour sweep, and the uninstall rehearsal then dropped the whole database. The table below keeps the measured numbers, for comparison with the coverage protocol only.
3. **Coverage reproduced.** Per Track, `GET /api/tracks/{id}/faces`:

   | Clip | Person Tracks | `observed` (usable face) | `unknown` |
   |---|---:|---:|---:|
   | s2-08 bus stop | 3 | 0 | 3 |
   | s2-09 parking lot | 2 | 0 | 2 |
   | s2-10 cafe lobby | 8 | 0 | 8 |
   | s2-11 school hall | 20 | 0 | 20 |
   | s2-12 stairwell | 9 | **2** | 7 |
   | s2-13 entrance hall | 30 | **5** | 25 |

   This equals the frozen coverage measurement (`s6-face-coverage.md`: s2-12 2/9, s2-13 5/30, others 0) on an independent re-processing. Every response carries the label "Face candidates — not identification — Development", the model identity and the reference threshold with `calibratedOnCctv: false`.
4. **Find this face (evidence).** From the best s2-13 face, k = 10 returned the 7 other usable faces' Tracks with cosine scores. One is above the reference threshold 0.2121: an s2-12 stairwell Track at 0.47, a same-slot cross-camera candidate. The rest scored 0.14 to −0.07. The source face's own Track appears at rank 2 through another of its faces at 0.14: two faces of one Track scored below the threshold, which shows how weak the embedding is on CCTV-scale faces.
5. **Gallery.** Enrol from the s2-13 face (201), compare the same face (score 1.0, above), compare an s2-12 face of another Track ("No gallery candidate above the threshold"), update the note, add a template from evidence and one from a query image, remove a template, delete the entry (all JSON; 201/200/204). A body-less `DELETE` is refused (405). After the delete, `enrolled_persons` and `enrolled_person_faces` hold 0 rows.
6. **Transient query image.** The s2-13 evidence crop (9,840 bytes, JPEG, SHA-256 `1f632901…4c78`) was uploaded as base64 JSON (202). The worker found one usable face (score 0.91). `face_queries.image` was null as soon as the query completed; only its SHA-256 remained, with `purge_after_utc` at upload + 1 h. A search from the query face returned its source Track at 1.0 and the stairwell Track at 0.47.
7. **Audit.** Every opt-in, search, comparison, gallery change and upload wrote one `audit_entries` row with the operator's Windows SID and `identity_source = windows-negotiate`, and ids only (no label, vector or image).
8. **No identity.** `tracks.entity_id` is null for every Track; no table stores a match.
9. **Opt-out.** Switching s2-08 off deleted its analysis and face observations (1 → 0) and its Track reads `notEnabled` again.

## Defect found and fixed

The first flow pass (kept as `05-flows-before-cb53b754.json`) showed the enrolment audit row naming the source face and the upload row naming `new`, so neither could be tied to the entry or query it created (ADR-022 §6). Commit `cb53b754` fixes the id before the audited mutation. The second pass (`05-flows.json`) shows `faces.gallery-enrolled` with the entry id and `faces.query-uploaded` with the query id, and `FaceApiTests` now asserts both.

## Not covered here

- The operator UI was not driven in a browser; the web layer is covered by its component tests.
- GPU face inference: the faces worker ran on CPU (`-DevicePolicy cpu`, the default).
