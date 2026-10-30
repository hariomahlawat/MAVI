# ADR-022: Face biometric data handling, gallery and candidate-match semantics (PoC Stage 5A)

**Status:** **Accepted** owner decision, 2026-10-29. The owner ratified the decision text in §Owner decision as written ("Yes, all three", relayed by the PoC coordinator session; register C5A.1, decisions D-S6-1 to D-S6-3), before any face code merged. **Amended 2026-10-30** (owner decisions D-S6-4 and D-S6-6; §Amendment 2026-10-30 below): status unchanged.

**Date:** 2026-10-29

**Related:**
- ADR-010 (operator identity, `OperatorPolicy`, append-only audit through `IAuditWriter`; §8 names the S6 gallery);
- ADR-013 (post-Track roles over a lease-scoped, hash-verified Evidence Set; §19 forbids face-oriented evidence selection);
- ADR-014 (capability binding; Development-only packs) and ADR-017 (benchmark first);
- ADR-020 (`poc-single-host`; §4: "Biometric … data handling under this profile follow their own ADRs (ADR-022 for faces); the PoC profile grants no exemption");
- ADR-021 (the `embeddings` role, whose pattern this role follows);
- plan `docs/superpowers/plans/2026-10-28-mavi-poc-end-to-end.md` (decisions D3 and D6, slice S6);
- register `docs/reviews/2026-10-28-poc-acceptance.md` (rows C5A.1–C5A.5);
- coverage record `docs/qualification/poc/s6-face-coverage.md` (C5A.2).

## Context

Stage 5A asks two questions of a Person Track: "where else does this face appear?" and "does this face resemble someone in an enrolled gallery?". Both process biometric data. A face embedding is a biometric template: it can single out a person across recordings, and a wrong match can attach the wrong name to a person. MAVI is offline and single-installation, but that removes only the transfer risk, not the others.

Settle five things before any face code: what is stored and where; how long it lives and how it is removed; what a match means; who may act and how that is recorded; and which model terms limit use.

The measured starting point is weak. On the demo corpus (protocol `s6-face-coverage-v1`, frozen before it ran), YuNet finds a face of at least 32 px at the publisher's score 0.9 in **2 of 110** Person Tracks. Both are in one clip (s2-12, 2 of 9). Most demo Person crops are too small for a face. This ADR therefore treats "no usable face" as the normal outcome and states it as Unknown, never as "no match".

## Decision

### 1. Meaning: candidates, never identity

- Every face result is a **candidate**: a similarity score between two face templates, with the model identity and the reference threshold beside it.
  - "Find this face" returns **candidate appearances** (Person Tracks).
  - A gallery comparison returns **candidate gallery matches** (enrolled persons).
- **Nothing stores a match.** No column, table or event links a Track, Observation or face to an enrolled person. Gallery comparisons are computed when asked and returned, never persisted. No Entity is created and `Track.EntityId` is never written (Stage 6 confirmation, ADR-023, is the only path to an Entity).
- The UI and the API never present a candidate as identity. API fields are named `candidate…`, and every surface carries "Face candidates — not identification — Development". A candidate gallery match shows the enrolled label with its score and the threshold, never "this is <label>".
- **Unknown is first-class.** A Track whose Evidence Set holds no usable face is `Unknown`, with a reason: `no_evidence`, `no_face_detected` or `face_too_small`. It is never shown as "no match" and never excluded from other searches.

### 2. Models and their terms

- **Detector:** YuNet, OpenCV Zoo `face_detection_yunet_2026may.onnx` at opencv_zoo commit `48b10fa5`. Its model folder's own LICENSE is **MIT** (Copyright (c) 2020 Shiqi Yu). The role decodes the graph with numpy on ONNX Runtime; OpenCV is not a dependency. The decoder equals OpenCV `FaceDetectorYN` on 137 demo crops (43 of 43 faces, maximum difference 3e-5).
- **Spike result.** The frozen spike `s6-embedder-spike-v1` chose **AdaFace IR-50** (`docs/qualification/poc/s6-face-embedder-spike.md`).
  - LFW 10-fold accuracy 99.8 % at native resolution and 99.7 % with faces downscaled to 32 px.
  - SFace scored 99.27 % and 98.7 %.
  - The reference threshold is cosine **0.2121**, the 32-px operating point at FAR 0.1 %.
- **Embedder:** one of two packs, as decision D6 set out:
  - **AdaFace IR-50** (code MIT). The WebFace4M checkpoint ships with no LICENSE file. Its card says to follow the training dataset's licence, and WebFace4M (a WebFace260M subset) is for non-commercial research only. The pack is therefore **Development-only**:
    - its manifest is `developmentOnly`, and the platform refuses it outside the `poc-single-host` and Development profiles;
    - it may be used only for non-commercial demonstration and evaluation;
    - the pack's notice records the code's MIT LICENSE and the checkpoint's research-only terms.
  - **SFace** (`face_recognition_sface_2021dec.onnx`). Its model folder's own LICENSE is **Apache-2.0**. It is the fallback if AdaFace's export, parity or quality fails, and the default if the owner rules out research-only checkpoints.
- **One Model Pack per face pipeline:** `faces-yunet-adaface-ir50-dev-v1` or `faces-yunet-sface-dev-v1`.
  - Each holds `detector.onnx` (YuNet) and `embedder.onnx`, plus each component's own LICENSE file and card: `LICENSE-yunet` and `LICENSE`.
  - The manifest's capability is `embedding`, because the pack's output is a face embedding, and `embedding.dimension` is the embedder's.
  - No new capability id is added. The closed capability registry is bound to the published VisionJob completion 3.2 enum, and a face pipeline does not justify changing that contract.
  - The detector is a pipeline stage inside the pack, as the tokenizer is inside the SigLIP 2 pack.
- **Licences and grade.** Both packs are Development-grade (`unverified`, ADR-020). Each licence is read from its own LICENSE file in the pack and recorded with its SHA-256. A Production face capability needs its own model selection and licence review (§9).

### 3. What is processed: opt-in per camera, the existing Person Evidence Set only

- **Opt-in per camera.** Face analysis runs only on runs of cameras whose `faceAnalysisEnabled` flag is on. The flag is off by default. Switching it on or off is an attributable operator mutation (§6).
  - Switching it off deletes that camera's face rows: observations, embeddings and Track outcomes.
  - In the PoC demonstration, it is on only for the MEVA clips with consented actors: s2-10, s2-11 and s2-12 (owner decision 3 on B3).
- **Input.** The `faces` role is post-Track, following ADR-013 §8–§12 and ADR-021 §3. It reads the Person Evidence Set that already exists, through the lease-scoped evidence endpoint, and verifies each crop's size and SHA-256.
  - Evidence selection is unchanged and model-neutral (ADR-013 §19): no frame or crop is chosen because it shows a face.
  - Raising coverage through face-oriented selection would need an ADR-013 amendment, and this ADR does not make one.
- **Failure isolation.** The role's failure never changes a ProcessingRun, Track, Observation or another role's unit. The test pattern is the same as C5.2.
- **Usable face.** A YuNet detection with score ≥ the profile's detection threshold whose box has a shorter side of at least **32 px** in source pixels. It is aligned to 112×112 by a similarity transform from its five landmarks to the standard template, then embedded and L2-normalised. Smaller detections are recorded as `face_too_small` and are not embedded.

### 4. What is stored, and where

Only in the installation's own PostgreSQL database (pgvector). Nothing goes to files outside it, the kit, exports, logs, telemetry or another installation.

| Table | Content | Biometric |
|---|---|---|
| `face_analyses` | The unit header, as `embedding_analyses`: identity, lease, attempts, outcome, visibility sequence, provenance. | no |
| `face_track_outcomes` | One row per Person Track per analysis: `Observed` or `Unknown` plus the reason. | no |
| `face_observations` | One row per detection: the evidence Observation, box and five landmarks in crop pixels, score, shorter side, `usable`. **No image bytes.** A face is shown by cropping the existing evidence crop in the browser. | location only |
| `face_embeddings` | One vector per usable face observation, from one model identity. Exact cosine search, no ANN index (ADR-021 §4 reasoning). | **yes (template)** |
| `enrolled_persons` | The gallery entry: operator-entered label and note, state, created/updated metadata. | personal data |
| `enrolled_person_faces` | One or more templates per enrolled person: vector, model identity and source (a face observation or a transient query face). A template enrolled from an uploaded image keeps a 112×112 aligned JPEG thumbnail made by the worker, so the gallery stays reviewable once the upload is erased. A template enrolled from evidence keeps no image: it is shown from its evidence crop while that exists. | **yes** |
| `face_queries` | A transient query image (JPEG or PNG, ≤ 2 MB, sent as JSON base64), its detected faces and their vectors. | **yes, transient** |

### 5. Retention and removal

| Data | Lifetime |
|---|---|
| Face observations, embeddings, Track outcomes | Deleted with their ProcessingRun (cascade); deleted when the camera's face analysis is switched off; a superseded analysis's rows are deleted when the newer analysis completes (unlike ADR-021, no face history is kept). |
| Gallery (`enrolled_persons`, `enrolled_person_faces`) | Until an operator deletes the entry. Deletion is a hard delete of the label, note, templates and thumbnails, audited by id only. |
| Transient query image | The image bytes are erased when its analysis completes or fails, and at most 15 minutes after upload. |
| Query faces and vectors | At most 1 hour (the snapshot validity), then purged by the hosted sweep. |
| Uninstall | `Uninstall-MAVI-PoC` drops the installation's database (which removes every table above) and deletes the PoC data root (evidence, media, logs). Removal is verified by the uninstall test (C5A.5). |

Face crops never exist as files. The evidence crops they come from are the existing Track evidence, governed by ADR-013 §19.

### 6. Who may act, and the audit record

These mutations require `OperatorPolicy` and write one `audit_entries` row each, through `IAuditWriter.RecordAsync` in the mutation's transaction:
- the camera face-analysis switch;
- gallery enrol, update (label, note, add or remove a template) and delete;
- transient query upload;
- "Find this face" searches;
- gallery comparisons.

Searches are audited because a biometric search is itself a sensitive act. The rules for audit rows:
- **No biometric or personal content:** ids, action and counts only. No vector, image or enrolled label.
- **Uploads stay JSON.** The image is base64 in a JSON body, so ADR-010 §3's JSON rule holds and no multipart exemption or extra CSRF control is needed.
- **Reads need the operator too.** Face reads (outcomes, observations, gallery list, thumbnails) require `OperatorPolicy`. With `Identity:Mode=disabled`, every face surface is refused.

### 7. Scores and threshold context

- Every candidate carries:
  - the cosine score;
  - the identity's **reference threshold**;
  - whether the score is above it;
  - the model identity;
  - the supporting face (Observation and box).
- **Where the threshold comes from.** The pipeline profile records it with its provenance, set by the S6 spike. It is either a verification operating point measured on an established public benchmark (ADR-017) or the publisher's stated threshold. It is **uncalibrated on CCTV**, and the UI says so.
- **"Find this face"** (from a face observation or a transient query face):
  - it returns up to `k` (≤ 50) candidate Person Tracks, ranked by the best face cosine per Track;
  - each candidate is marked above or below the threshold;
  - the exact search is snapshot-stable, as in ADR-021 §4.
- **A gallery comparison** returns only enrolled persons above the threshold, at most 3, ranked. With none, it says "No gallery candidate above the threshold". It never says "unknown person".

### 8. What the PoC profile does not exempt

Under `poc-single-host`, all of §1–§7 apply in full: opt-in per camera, local-only storage, retention and removal, attribution and audit, candidate semantics, and Unknown.

The profile's only allowance is Development-grade packs, including the research-provenance AdaFace checkpoint for non-commercial demonstration. Biometric derivatives never enter the kit (D3).

### 9. Production

The `faces` role and its packs are refused under P1–P3. A Production face capability needs all of the following:
- a Production ADR covering the lawful basis, a DPIA, a retention policy, access review and model licensing;
- a qualified model, selected on a labelled benchmark (ADR-017);
- a threshold calibrated for the target camera geometry.

## Trade-offs accepted

- **Low coverage, stated rather than engineered around.** On this corpus at the frozen threshold, 2 of 110 Person Tracks have a usable face. Unknown will dominate. Face-oriented evidence selection or higher-resolution capture is the real fix, and it needs an ADR-013 amendment.
- **No face crop files.** The browser crops the evidence image to show a face. A gallery template enrolled from an uploaded image keeps one small aligned thumbnail, because the upload itself is erased. A template enrolled from evidence loses its picture when its run is deleted, which is accepted to avoid copying evidence faces.
- **One pack per pipeline, capability `embedding`.** This avoids a change to a published contract enum. The cost is that the detector is not separately bound or swappable: changing it means a new pack and a new identity.
- **Searches are audited.** Each search adds a row and requires an operator. That is the price of a biometric search being attributable.
- **No face history.** Superseded face analyses are deleted, not kept. Forensic replay re-runs the role over the sealed evidence.
- **Uncalibrated threshold.** Benchmark faces are large and frontal, and CCTV faces are not. The threshold is context for the operator, not a decision rule. Gallery comparisons hide sub-threshold entries to avoid showing a name next to a weak score.
- **Research-only checkpoint (if AdaFace).** It is better on low-quality faces in the literature, but its terms confine it to non-commercial Development use. SFace avoids that at some accuracy cost.

## Owner decision (ratified 2026-10-29)

> **ADR-022 (PoC Stage 5A) is accepted:**
> 1. Face results are **candidates** with score, reference threshold and model identity. They are never identity, never stored as a match, and never write `EntityId`. Unknown (no usable face) is first-class.
> 2. Face analysis is **opt-in per camera** (off by default, attributable). It runs as the post-Track `faces` role over the existing, model-neutral Person Evidence Set, with no face-oriented selection (ADR-013 §19 unchanged).
> 3. Templates, gallery and transient queries are stored only in the installation's PostgreSQL database (pgvector):
>    - no face image files;
>    - one 112×112 thumbnail per gallery template enrolled from an uploaded image;
>    - query images erased on analysis, query vectors purged after 1 h;
>    - face rows deleted with their run or when the camera is opted out;
>    - the gallery is kept until an operator deletes it;
>    - everything is removed by `Uninstall-MAVI-PoC`.
> 4. Gallery enrol/update/delete, the camera switch, query uploads and face searches require `OperatorPolicy` and are audited through `IAuditWriter` without biometric or personal content.
> 5. YuNet 2026may (MIT) detects faces. The embedder is AdaFace IR-50 WebFace4M (MIT code, research-only checkpoint, Development-only, non-commercial demonstration only), with SFace (Apache-2.0) as fallback; the S6 spike decides.
> 6. The PoC profile exempts none of this. The role is refused under P1–P3.

## Amendment 2026-10-30 (owner decisions D-S6-4, D-S6-6)

The owner accepted these changes ("Yes, all", 2026-10-30, relayed by the PoC coordinator session). The decision text above is otherwise unchanged; where it differs, this amendment governs.

1. **§3, cameras in the demonstration.** Face analysis may also be switched on for **s2-13** (MEVA G420, school entrance hall, S2 amendment A6). D-S6-4 confirms that MEVA decisions 2(a) (transfer path) and 3(a) (consent) cover G420, as decision 13(a) did for G331. The opt-in cameras of the demonstration are therefore s2-10, s2-11, s2-12 and s2-13.
2. **§1, Unknown reasons.** The Unknown reasons are `no_evidence`, `evidence_unavailable` (an evidence crop could not be read or failed its size or SHA-256 check), `no_face_detected` and `face_too_small`.
3. **§3 and §5, opt-out and the gallery.** Switching a camera off deletes that camera's face analyses, observations, embeddings and Track outcomes. It does not delete gallery templates enrolled from that camera's evidence: a template is a gallery row, kept until an operator deletes it (§5).
4. **Context, coverage.** After amendment A6, protocol `s6-face-coverage-v2` measured 5 of 30 usable Person Tracks on s2-13, so the corpus has **7 of 140** (s2-12 2/9, s2-13 5/30). Its predeclared rule kept the detector threshold at 0.9 (`docs/qualification/poc/s6-face-coverage.md`). The 2 of 110 in the Context and the Trade-offs is the v1 starting point.
