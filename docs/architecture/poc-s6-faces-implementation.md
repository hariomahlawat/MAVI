# PoC S6 faces: implementation design (ADR-022)

This is the contract between the parts of slice S6: the Python role, the platform, the web UI and setup. It follows the S4 `embeddings` role (ADR-021) everywhere it does not say otherwise. Names and payloads here are binding for the slice.

## 1. Identity and profile

- **Pipeline profile:** `src/vision/config/faces/development-faces-<embedder>-v1.json`, schema `mavi-face-pipeline-v1`.

  ```json
  {
    "schemaVersion": "mavi-face-pipeline-v1",
    "pipelineId": "faces-yunet-<embedder>-dev",
    "pipelineVersion": "1.0.0",
    "developmentOnly": true,
    "modelManifest": "models/manifests/faces-yunet-<embedder>-dev-v1.json",
    "dimension": 512,
    "detector": { "scoreThreshold": 0.9, "nmsThreshold": 0.3, "topK": 5000 },
    "minimumFaceSide": 32,
    "alignment": "arcface-112-similarity-v1",
    "preprocessing": "adaface-ir50-v1",
    "referenceThreshold": { "cosine": 0.0, "provenance": "..." },
    "objectClasses": ["Person"],
    "queryImageMaximumBytes": 2097152
  }
  ```

  The `preprocessing` value is `adaface-ir50-v1` (RGB, `(x/255 − 0.5)/0.5`) or `sface-v1` (RGB, raw 0–255).
- **Identity:** `{"model":{"dimension","id","manifestSha256","version"},"pipeline":{"id","sha256","version"},"schemaVersion":"mavi-face-identity-v1"}`. Canonical JSON (sorted keys, compact, UTF-8, trailing LF). The fingerprint is the SHA-256 of those bytes. Both stacks are pinned by `contracts/test-vectors/face-identity-v1.json`.
- **Model manifest:** v2, capability `["embedding"]`, `capabilitySpecific.embedding.dimension`.
  - Artifact roles: `onnx-face-detector`, `onnx-face-embedder`, `licence-notice` (the embedder's `LICENSE`), `licence-notice-detector` (`LICENSE-yunet`), `model-card`, `model-card-detector`.
  - `licence.noticeArtifactRole` = `licence-notice`.

## 2. Worker control plane (`mavi-face-control-v1`; routes under `/api/faces`)

The routes mirror `/api/embeddings`: the capability travels in the `X-Mavi-Lease-Capability` header, leases are fenced by worker, capability and attempt, and nothing here needs an operator.

| Route | Body / result |
|---|---|
| `POST /api/faces/analyses/lease` | `face-lease-v1`: as `embedding-lease-v1`, but only Person Tracks of opted-in cameras. |
| `POST /api/faces/analyses/{id}/heartbeat`, `/fail` | As embeddings. |
| `GET /api/faces/analyses/{id}/evidence/{observationId}` | Lease-scoped crop bytes. |
| `POST /api/faces/analyses/{id}/complete` | `face-complete-v1` (below). |
| `POST /api/faces/queries/lease` | `face-query-lease-v1`: `{schemaVersion, queryId, workerId, attemptCount, leaseExpiresAtUtc, identity, image:{mimeType, sizeBytes, sha256}}`. |
| `GET /api/faces/queries/{id}/image` | Query bytes (lease-scoped). |
| `POST /api/faces/queries/{id}/complete` | `face-query-complete-v1`. |
| `POST /api/faces/queries/{id}/fail` | As embeddings. |

**`face-complete-v1`:**

```json
{"schemaVersion":"mavi-face-control-v1","analysisId":"…","workerId":"…","attemptCount":1,
 "provenance":{"roleId":"faces", …the nine embedding provenance keys…},
 "tracks":[
   {"trackId":"…","outcome":"observed","faces":[
      {"observationId":"…","box":{"x":1.0,"y":2.0,"width":40.0,"height":48.0},
       "landmarks":[[x,y],[x,y],[x,y],[x,y],[x,y]],"score":0.93,"usable":true,"embedding":"<base64 float32 LE>"},
      {"observationId":"…","box":{…},"landmarks":[…],"score":0.91,"usable":false}]},
   {"trackId":"…","outcome":"unknown","reason":"face_too_small","faces":[ …usable:false only… ]},
   {"trackId":"…","outcome":"unknown","reason":"no_face_detected","faces":[]}]}
```

- Reasons: `no_evidence`, `evidence_unavailable`, `no_face_detected`, `face_too_small`.
- `observed` ⇔ at least one usable face.
- A face is reported only when its score ≥ the profile's `detector.scoreThreshold`. It is usable when its shorter side ≥ `minimumFaceSide`. Only usable faces carry `embedding`.
- At most 8 faces per crop, in score order.

**`face-query-complete-v1`:** `{schemaVersion, queryId, workerId, attemptCount, faces:[{box, landmarks, score, usable, embedding?, thumbnail?}]}`.
- `thumbnail` is a base64 JPEG of the aligned 112×112 face. It is present only for usable faces.
- An image with no face completes with `faces: []`.

## 3. Tables (migration `AddFaceIntelligence`)

| Table | Content |
|---|---|
| `cameras` | Gains `face_analysis_enabled boolean not null default false`. |
| `face_analyses` | As `embedding_analyses`, plus `camera_id`. |
| `face_track_outcomes` | `(analysis_id, track_id)`; `outcome` (Observed/Unknown), `reason`. |
| `face_observations` | `id`; `analysis_id`; `track_id`; `observation_id`; `box_x`, `box_y`, `box_w`, `box_h`; `landmarks real[10]`; `score`; `min_side`; `usable`. |
| `face_embeddings` | `face_observation_id` (PK, FK cascade); `embedding vector`. |
| `face_queries` | `id`; `status` (Pending/Leased/Completed/Failed); `image bytea null` (erased at completion, failure or 15 min); `image_sha256`; `mime_type`; `size_bytes`; lease columns; `identity_fingerprint`; `created_by_operator`; `created_at_utc`; `completed_at_utc`; `faces jsonb` (box, landmarks, score, usable); `purge_after_utc` (created + 1 h). |
| `face_query_embeddings` | `(query_id, face_index)`; `embedding vector`; `thumbnail bytea null`. |
| `enrolled_persons` | `id`, `label` (1–100), `note` (≤ 500), `created_at_utc`, `updated_at_utc`. |
| `enrolled_person_faces` | `id`; `enrolled_person_id` (FK cascade); `identity_fingerprint`; `embedding vector`; `source_kind` (Evidence/Query); `source_face_observation_id null` (no FK, so the run can be deleted); `thumbnail bytea null`; `created_at_utc`. |

Deletes cascade from `processing_runs`, through `face_analyses`, to the face rows. The camera opt-out deletes the camera's `face_analyses`. When a newer analysis of a run completes, the superseded analysis is deleted in the same transaction.

## 4. Operator API (all `.RequireAuthorization(OperatorPolicy.Name)`, JSON only)

Each endpoint marked *audited* writes one audit row through `IAuditWriter.RecordAsync` (action, ids and counts; no vector, image or label).

| Endpoint | Behaviour | Audited |
|---|---|---|
| `PUT /api/cameras/{id}/face-analysis` `{enabled}` | Sets the camera flag; opting out deletes the camera's face rows. | yes |
| `GET /api/tracks/{id}/faces` | `{state, reason?, identity, referenceThreshold, faces:[{faceId, observationId, evidenceCropUrl, box, landmarks, score, usable}]}`. `state` is one of `observed`, `unknown`, `pending`, `failed`, `notAnalysed`, `notEnabled`. | no |
| `POST /api/faces/queries` `{imageBase64, mimeType}` | Accepts `image/jpeg` or `image/png`, ≤ 2 MB decoded. Returns 202 `{queryId}`. | yes |
| `GET /api/faces/queries/{id}` | `{status, faces:[{faceIndex, box, score, usable, thumbnailDataUrl?}]}` | no |
| `POST /api/faces/search` `{source:{faceId}\|{queryId, faceIndex}, k?, snapshot?}` | Up to `k` candidate Person Tracks (1–50, default 20) by best face cosine: `{candidates:[{trackId, processingRunId, cameraId, cameraName, startTimestampUtc, score, aboveThreshold, faceId, observationId, box}], referenceThreshold, identity, snapshot}`. | yes |
| `POST /api/faces/gallery/compare` `{source}` | `{candidates:[{enrolledPersonId, label, score}] (≤ 3, above the threshold only), referenceThreshold}` | yes |
| `GET /api/faces/gallery` | `[{enrolledPersonId, label, note, templates:[{templateId, sourceKind, sourceFaceId?, evidenceCropUrl?, box?, thumbnailDataUrl?}]}]` | no |
| `POST /api/faces/gallery` `{label, note?, source}` | Enrol. | yes |
| `PATCH /api/faces/gallery/{id}` `{label?, note?}` | Update. | yes |
| `POST /api/faces/gallery/{id}/templates` `{source}` | Add a template. | yes |
| `POST /api/faces/gallery/{id}/templates/{templateId}/delete` `{}` | Remove a template. | yes |
| `POST /api/faces/gallery/{id}/delete` `{}` | Hard-delete the entry. | yes |

- With `Identity:Mode=disabled`, every face route refuses.
- `referenceThreshold` is `{cosine, provenance, calibratedOnCctv:false}`.

## 5. Web

Every surface carries "Face candidates — not identification — Development".

- **Track inspector, "Faces" panel:**
  - the face state, with Unknown shown with its reason, never "no match";
  - usable faces shown CSS-cropped from the evidence crop;
  - "Find this face", which lists candidate Tracks with score, threshold and an above/below marker;
  - "Compare with gallery", which lists candidate gallery matches or "No gallery candidate above the threshold";
  - "Enrol in gallery".
- **Faces page:**
  - upload a query image, then pick a face, then run "Find this face" or a gallery comparison;
  - the gallery: list, rename and note, add a template from a query face, delete.
- **Camera settings:** a "Face analysis (opt-in)" switch.

## 6. Setup

- **Runtime.** The faces worker runs on the `embeddings-onnx-v1` runtime family (onnxruntime, numpy, Pillow, httpx, pydantic). It adds no new library. It uses its own launcher, `Start-MaviFacesWorker.ps1`.
- **Packs.** Staged by `tools/vision/faces_packs.py` (check, collect, stage), bound by `Install-MAVI-PoC`, and carried in the developer cache, kit and bundle.
- **Uninstall.** `Uninstall-MAVI-PoC.ps1` stops MAVI, drops the PoC database, removes the PostgreSQL service and data, and deletes `DataRoot` and `InstallRoot`. It prints what it removed. It is covered by `Test-MaviPocSetupContracts.ps1` and an uninstall rehearsal (C5A.5).
