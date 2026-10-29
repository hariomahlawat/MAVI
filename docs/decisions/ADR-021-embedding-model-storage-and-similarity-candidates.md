# ADR-021: Embedding model, storage and similarity-candidate semantics (PoC Stage 5)

**Status:** Accepted owner decision **pending** (register row C5.1 stays IN PROGRESS until the owner ratifies the decision text in §Owner decision). Written before any S4 code merges, as the PoC plan requires.

**Date:** 2026-10-29

**Related:**
- ADR-013 (post-Track roles over a lease-scoped, hash-verified Evidence Set; failure isolation; immutable analysis identity);
- ADR-014 (capability binding v2: the `embedding` capability and the manifest v2 `embedding.dimension` section);
- ADR-017 (benchmark first; Development evidence) and ADR-020 (`poc-single-host`, Development evidence class);
- plan `docs/superpowers/plans/2026-10-28-mavi-poc-end-to-end.md` (decision D5, slice S4);
- `capability-implementation-roadmap.md` (Stage 5);
- register `docs/reviews/2026-10-28-poc-acceptance.md` (rows C5.1–C5.4).

## Context

Stage 5 asks, from any Track, "what else looks like this?", and later Stage 2 zero-shot attributes and Stage 6 ReID candidates reuse the same embeddings. D5 chose SigLIP 2 base (Apache-2.0) as one Model Pack serving image–image similarity and text→image appearance queries. Four questions must be settled before code: the exact model and its normalisation, where and how vectors are stored and searched, how the role runs, and what a result means.

The S4 spike (`tools/poc/embeddings_spike.py`; evidence in `E:\MAVI-Controlled\PoC\S4\`) ran two frozen protocols over held BDD100K H3 evidence crops, read-only:

| Protocol | Sample | SigLIP 2 R@1 / MRR | 16×16 thumbnail R@1 / MRR | Verdict |
|---|---|---|---|---|
| `s4-sanity-v1` | 100 Tracks × 2 crops, min side ≥ 24 px | 0.555 / 0.597 | 0.675 / 0.745 | **failed** (baseline clause) |
| `s4-confirm-80-v1` | 100 Tracks × 2 crops, min side ≥ 80 px, 64 videos disjoint from the first sample | 0.81 / 0.849 | 0.785 / 0.835 | **passed** (frozen before it ran) |

Chance R@1 is 0.005. A post-hoc breakdown of the first run (hypothesis only) found that crops under about 80 px collapse into a generic cross-video cluster. The confirmatory pass is narrow: SigLIP 2 beats a trivial thumbnail baseline by 5 of 200 queries on a test that mostly rewards near-duplicate matching. It is evidence that the embedding is sane on adequately sized crops, not that it is a good re-identification model. This ADR therefore scopes the capability to that evidence.

## Decision

### 1. Model and normalisation

- **Model:** `google/siglip2-base-patch16-224`, revision `75de2d55ec2d0b4efc50b3e9ad70dba96a7b2fa2`, Apache-2.0.
- **Export:** the image tower and the text tower are exported to two ONNX graphs (opset 17) by `tools/vision/build_siglip2_pack.py`. The export is checked against PyTorch: minimum cosine 0.99999994 for both towers. CPU and CUDA ONNX Runtime agree to a minimum cosine of 0.9997.
- **Image preprocessing** (`siglip2-fixed-224-v1`): RGB; bilinear resize to 224×224; `(x/255 − 0.5)/0.5`.
- **Text preprocessing:** lowercase, then the pack's SentencePiece `tokenizer.model`, then EOS (id 1), then pad (id 0) to 64. This equals the reference Hugging Face tokenizer on the build's parity texts. The runtime does not use `transformers` or `tokenizers`.
- **Vectors:** 768 dimensions, L2-normalised, cosine similarity.
- **Track vector** (`mean-l2-v1`): every accepted crop of the Track whose shorter side is at least **80 px** is embedded; the crop vectors are normalised, averaged and the mean is normalised again. The source Observation ids are recorded with the vector.
- **No usable crop:** a Track whose accepted crops are all smaller is `Unavailable` with reason `evidence_too_small` and has no vector. This is a first-class "similarity unavailable" state, never "not similar".

### 2. Model Pack and offline packaging

- **Model Pack:** one pack, `embeddings-siglip2-base-p16-224-dev-v1` (manifest v2, capability `embedding`, `embedding.dimension: 768`).
  - It holds `vision.onnx`, `text.onnx`, `tokenizer.model`, the model card `README.md` and `LICENSE`.
  - It records every SHA-256 and `verificationStatus: unverified`: it is a Development-grade pack (ADR-020).
- **Licence:**
  - The model repository declares Apache-2.0 in its README front matter but carries no LICENSE file.
  - The pack therefore ships the Apache-2.0 text from the repository that publishes the SigLIP 2 checkpoints, google-research/big_vision at commit `0127fb6b337ee2a27bf4e54dea79cff176527356` (SHA-256 `43070e2d…79c1`).
  - It also ships the model card that states the licence.
- **Delivery:**
  - The pack bytes never enter Git. A payload list pins them, and the developer offline cache, the Offline Binary Kit and the PoC setup bundle carry them.
  - The installer stages them with SHA-256 verification.
  - Nothing is downloaded at install or first run.
- **Runtime:** a new Development runtime family, `embeddings-onnx-v1` (Python 3.12, ONNX Runtime 1.31.0 CPU, NumPy, Pillow, SentencePiece, httpx, pydantic), with its own lock.
  - It is not part of the vision lock or any qualified Runtime Pack.
  - Its CUDA variant uses whatever `onnxruntime-gpu` build S1b pins for the ONNX roles. The S4 spike found that the PyPI `onnxruntime-gpu 1.31.0` needs CUDA 13 and fails on the laptop's driver, so the CUDA variant is a dependency on S1b, not a decision here.

### 3. The `embeddings` role: post-Track, lease-scoped, failure-isolated

The role follows ADR-013 §8–§12 and the plate role's control plane (`mavi-embedding-control-v1`, routes under `/api/embeddings/analyses`).

- **Unit:** one `EmbeddingAnalysis` per (ProcessingRun, identity). It is queued for every visible completed run with at least one Person or Vehicle Track, completed after the identity's activation. History is queued only by an explicit, bounded re-analysis request.
- **Lease:** claim with `FOR UPDATE SKIP LOCKED`, heartbeat, fail and complete, fenced by worker, capability and attempt. The capability travels only in `X-Mavi-Lease-Capability`.
- **Evidence:** the worker reads each crop through the shared lease-scoped evidence endpoint and verifies size and SHA-256 before decoding. It never mounts the evidence root.
- **Identity** (immutable, ADR-013 §11) is the model id and version, the manifest SHA-256, and the pipeline profile id, version and SHA-256. The pipeline profile pins preprocessing, aggregation and the 80 px floor. The fingerprint is SHA-256 of the identity's canonical JSON; a contract test vector pins it for both stacks. Device, runtime variant and commit are provenance, not identity.
- **Completion:** one fenced transaction writes every Track outcome and vector, allocates a visibility sequence under the shared processing-visibility barrier, and supersedes the run's previous completed analysis only when this identity is the preferred one.
  - There is **no sealed predictions artefact**. The vectors are the analysis's only output, and they are re-derivable from sealed evidence by re-running the role.
  - The completion digest (SHA-256 of the exact request body) authenticates an idempotent replay.
- **Failure isolation:** embedding state lives only in the embedding tables. A crash, a refused completion, exhausted attempts or a deadline fail the `EmbeddingAnalysis` and nothing else. ProcessingRun status, visibility sequence, Tracks, Observations and the other roles' units are never read for update or written. A test pins this (C5.2).

### 4. Storage and search

| Table | Content |
|---|---|
| `embedding_analyses` | The unit header: identity, lease, attempts, outcome, visibility sequence, provenance. Unique `(processing_run_id, identity_fingerprint)`. |
| `track_embeddings` | One row per Track per analysis: `outcome`, `unavailable_reason`, `embedding vector(768)` (null when Unavailable), `source_observation_ids uuid[]`, `crop_count`. |
| `appearance_query_embeddings` | Cached text-query vectors per (identity, normalised-text SHA-256), filled by the role's text-query lease. |

- **Search is exact and deterministic.** Candidates come from the existing base Track candidate set at the snapshot (one shared implementation with Track search). They are joined to the pinned identity's fact-bearing analysis of each run, published inside the snapshot, and ordered by `cosine distance ASC, track id ASC`.
- **No ANN index.** HNSW, which plan S4 named, is deliberately not created in this slice:
  - an approximate index is not deterministic under concurrent inserts, so it would break snapshot stability;
  - at demo-corpus scale an exact scan meets the latency budget (measured; register C5.4).
  - The trigger to add HNSW (or IVFFlat) is a recorded p95 above 300 ms at the volume being served. Adding it then is a schema decision in a migration, with the recall/latency trade-off measured as the roadmap requires.
- **`GET /api/tracks/{id}/similar`:**
  - Parameters: `k` (1–50, default 20), optional `cameraId`, `fromUtc`, `toUtc`, `objectClass` (default: the query Track's class) and `snapshot`.
  - Every other key is refused (whitelisted).
  - The query Track must have a vector in the pinned identity. Otherwise the endpoint answers with explicit states: `similarity_unavailable` (with its reason) when the Track's evidence is too small, `similarity_pending` while its analysis has not completed.
- **`appearanceQuery`** is a whitelisted key on `GET /api/tracks` (1–200 characters after normalisation: trim, collapse whitespace, lowercase).
  - It ranks the base candidates by text→image cosine and returns the top `k` (≤ 100) in one page with no continuation cursor.
  - It cannot be combined with plate or analytic predicates in this slice (refused with `appearance_query_combination_unsupported`).
  - If the text has no cached vector yet, the API queues it and waits a bounded time. It then answers 503 `appearance_query_pending` with `Retry-After`.
- **Fingerprint and snapshot:**
  - Both responses carry a `snapshot` token: an HMAC-authenticated envelope under the installation's cursor signing key, with its own derived key labels.
  - It pins the kind, a keyed filter fingerprint (base filters, `k`, the query Track or the normalised text, the identity), the snapshot visibility sequence and the snapshot time.
  - Replaying a request with its `snapshot` returns the identical ranked list after later analyses complete; a token presented with different filters is refused.
  - Tokens are valid for one hour, as cursors are.

### 5. Result semantics: similarity candidates

- **Similarity candidates, never identity.** Every result is a *similarity candidate* with a cosine score, the model identity and the supporting crop.
- **No automatic grouping.** Nothing in this slice writes `Track.EntityId`, creates an Entity, merges Tracks or thresholds a score into a decision.
- **No threshold.** The API returns the ranked list with scores and no "match" threshold. The UI labels every surface "Similarity candidates — Development" and shows the score, not a verdict.
- **Sensitive derived data.** Person appearance embeddings are sensitive derived data:
  - they are not exported or shared between installations;
  - they are deleted with their run;
  - the PoC uninstall removes the database that holds them.

## Trade-offs accepted

- **Scope limited to evidence ≥ 80 px.** Small and distant subjects, which in CCTV are many, get "similarity unavailable" instead of unreliable candidates. The evidence supports nothing better today.
- **A general model, not ReID.** SigLIP 2 is a general image–text model, not a re-identification model. Its margin over a trivial baseline on the sanity test is small. Cross-camera candidates will include look-alikes of the same type and colour. A specialist ReID model (OSNet/TransReID, or a fine-tuned head) is the later swap under ADR-014. It needs a labelled benchmark (e.g. VeRi-776, Market-1501) per ADR-017, not more spike data.
- **Exact search.** It costs O(N) per query. It is chosen for determinism and is acceptable to roughly 10⁵ Tracks; the ANN trigger is explicit.
- **No sealed artefact.** No raw per-crop vectors are kept, so forensic replay re-embeds the sealed crops instead of reading a sealed vector file.
- **Bounded, pull-based text queries.** The first use of a new appearance text waits up to about 10 s for the worker; repeated texts are immediate.
- **A large text tower.** `text.onnx` is about 1.13 GB, mostly the 256k-token embedding table. The pack is about 1.5 GB. This is accepted for one pack that serves Stages 2, 5 and 6 (D5).

## Owner decision (to ratify)

> **ADR-021 (PoC Stage 5) is accepted:**
> 1. SigLIP 2 base `google/siglip2-base-patch16-224` @ `75de2d55`, Apache-2.0, is the PoC embedding model:
>    - packaged offline as Development-grade Model Pack `embeddings-siglip2-base-p16-224-dev-v1` (two ONNX towers plus a SentencePiece tokenizer; hashes and licence recorded, `unverified`);
>    - run by the `embeddings` post-Track role over lease-scoped, hash-verified Evidence Set crops, whose failure never changes a ProcessingRun.
> 2. Track vectors are 768-d, L2-normalised mean embeddings of accepted crops with shorter side ≥ 80 px; Tracks without such a crop are "similarity unavailable".
> 3. Vectors are stored in pgvector table `track_embeddings`, searched exactly by cosine distance with deterministic ordering and a signed snapshot. No ANN index until a measured p95 > 300 ms requires one; this deliberately departs from the plan's "HNSW".
> 4. `GET /api/tracks/{id}/similar` and the `appearanceQuery` search key return *Similarity candidates* with scores. They are never identity, never grouped automatically, and never write `EntityId`.
> 5. A specialist ReID model is a later swap under ADR-014, after a labelled-benchmark comparison.
