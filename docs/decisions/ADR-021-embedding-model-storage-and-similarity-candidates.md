# ADR-021: Embedding model, storage and similarity-candidate semantics (PoC Stage 5)

**Status:** **Accepted** owner decision, 2026-10-29. The owner ratified the decision text in §Owner decision as written, in the S4 Claude Code session, on PR #244, before any S4 code merged (register C5.1).

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
- **Spike CUDA caveat:** the spike's CUDA leg (agreement ≥ 0.9997, 29.6 ms per crop) ran on a spike-only `onnxruntime-gpu 1.22.0`. The end-to-end run used the bound pin `1.26.0` and gave identical Track outcomes and rankings to the CPU run.
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
  - Its CUDA variant uses the one GPU pin S1b chose for the ONNX roles: `onnxruntime-gpu 1.26.0`, the last CUDA 12 build. The S4 spike found that the PyPI `onnxruntime-gpu 1.31.0` needs CUDA 13 and fails on the laptop's driver. The CUDA 12.4 / cuDNN 9.1 DLLs come from the vision CUDA Runtime Pack's `torch/lib`. The variant is locked here once S1b's pin merges (PR #243); until then the packaged runtime is CPU and explicit CUDA fails closed.

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
| `track_embeddings` | One row per Track per analysis: `outcome`, `unavailable_reason`, `embedding vector` (null when Unavailable), `source_observation_ids uuid[]`. The column is dimension-free; each analysis records its dimension, the completion checks every vector against it, and search compares vectors of one identity only. |
| `appearance_query_embeddings` | Cached text-query vectors per (identity, normalised-text SHA-256), filled by the role's text-query lease. At most 50 texts wait at once; at most 8 requests wait for a vector at once; a Failed text can be asked for again after 5 minutes. The operator's texts are kept with the database. A retention rule follows with the audit work (C10.1). |

- **Search is exact and deterministic.** Candidates come from the existing base Track candidate set at the snapshot (one shared implementation with Track search). They are joined to the pinned identity's fact-bearing analysis of each run, published inside the snapshot, and ordered by `cosine distance ASC, track id ASC`.
- **No ANN index.** HNSW, which plan S4 named, is deliberately not created in this slice:
  - an approximate index is not deterministic under concurrent inserts, so it would break snapshot stability;
  - at demo-corpus scale an exact scan meets the latency budget (measured; register C5.4).
  - The trigger to add HNSW (or IVFFlat) is a recorded p95 above 300 ms at the volume being served. Adding it then is a schema decision in a migration, with the recall/latency trade-off measured as the roadmap requires.
- **`GET /api/tracks/{id}/similar`:**
  - Parameters: `k` (1–50, default 20), optional `cameraId`, `fromUtc`, `toUtc`, `objectClass` (default: the query Track's class) and `snapshot`.
  - Every other key is refused (whitelisted).
  - The query Track must have a vector in the pinned identity. Otherwise the endpoint answers with an explicit state:
    - `unavailable` (with its reason), for example when the Track's evidence is too small;
    - `pending` while its analysis is queued or running;
    - `failed` (with the failure code) when its analysis failed;
    - `notAnalysed` when its run has no analysis under the identity (it predates the activation).
  - The explicit, bounded `POST /api/embeddings/reanalysis` (run ids only, audited) queues a not-analysed run and requeues a Failed unit with a fresh attempt budget. Automatic queueing never retries a failure.
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
- **Text→image is unvalidated.** The appearance query has been checked for determinism and plausible class ordering only (person→Person, car→Vehicle on the demo corpus). Its retrieval quality is unmeasured. Raw text–image cosines are small (about 0.04–0.15), so its results are ordering hints, not detections. S5 calibrates the zero-shot use with the model's logit scale and bias.
- **A general model, not ReID.** SigLIP 2 is a general image–text model, not a re-identification model. Its margin over a trivial baseline on the sanity test is small. Cross-camera candidates will include look-alikes of the same type and colour. A specialist ReID model (OSNet/TransReID, or a fine-tuned head) is the later swap under ADR-014. It needs a labelled benchmark (e.g. VeRi-776, Market-1501) per ADR-017, not more spike data.
- **Exact search.** It costs O(N) per query and is chosen for determinism. It is measured only at demo scale (40 Tracks: p95 under 40 ms). The ANN trigger is explicit, and any larger-scale claim needs a measurement.
- **No sealed artefact.** No raw per-crop vectors are kept, so forensic replay re-embeds the sealed crops instead of reading a sealed vector file.
- **Bounded, pull-based text queries.** The first use of a new appearance text waits up to about 10 s for the worker; repeated texts are immediate.
- **Explicit composition, not a Component Binding.** The role is composed from explicit paths (model manifest, pipeline profile, Model Pack root) rather than an ADR-014 Component Binding with a Runtime Pack id. ADR-014's Development role-binding path is plate-specific today. Generalising it is not needed for the PoC claim, and doing it now would have reworked the plate binding code that slice S3 is changing in parallel.
  - The same guarantees are enforced instead: the worker verifies every artefact SHA-256 before loading; the identity is pinned by the manifest and profile bytes; `tools/verify_repo.py` (`check_embedding_profiles`) requires a developmentOnly profile, an unverified, unqualified `embedding` manifest of the same dimension, and a declared Development runtime family.
  - Moving the role into the binding machinery is the promotion path.
- **A large text tower.** `text.onnx` is about 1.13 GB, mostly the 256k-token embedding table. The pack is about 1.5 GB. This is accepted for one pack that serves Stages 2, 5 and 6 (D5).

## Owner decision (ratified 2026-10-29)

> **ADR-021 (PoC Stage 5) is accepted:**
> 1. SigLIP 2 base `google/siglip2-base-patch16-224` @ `75de2d55`, Apache-2.0, is the PoC embedding model:
>    - packaged offline as Development-grade Model Pack `embeddings-siglip2-base-p16-224-dev-v1` (two ONNX towers plus a SentencePiece tokenizer; hashes and licence recorded, `unverified`);
>    - run by the `embeddings` post-Track role over lease-scoped, hash-verified Evidence Set crops, whose failure never changes a ProcessingRun.
> 2. Track vectors are 768-d, L2-normalised mean embeddings of accepted crops with shorter side ≥ 80 px; Tracks without such a crop are "similarity unavailable".
> 3. Vectors are stored in pgvector table `track_embeddings`, searched exactly by cosine distance with deterministic ordering and a signed snapshot. No ANN index until a measured p95 > 300 ms requires one; this deliberately departs from the plan's "HNSW".
> 4. `GET /api/tracks/{id}/similar` and the `appearanceQuery` search key return *Similarity candidates* with scores. They are never identity, never grouped automatically, and never write `EntityId`.
> 5. A specialist ReID model is a later swap under ADR-014, after a labelled-benchmark comparison.

## Amendment 2026-10-29 (PoC S5): zero-shot attributes on the same Model Pack

**Status:** **Proposed**, for owner ratification (register C2.1; S5 owner decision S5-ADR). Nothing below changes §1–§5 or the decision ratified above.

**Context.** Plan slice S5 replaces the S2b fixture inferencer of the existing `attributes` role with SigLIP 2 zero-shot scoring and adds attribute search (Stage-2 plan §16) and its UI. D5 says one Model Pack serves Stages 2, 5 and 6. Stage-2's frozen register rows (E5–E8, F, G) and the S2c learned-pack work are not touched. This amendment states how the role is composed, what a row means and how search is paged.

**Decision.**

1. **One Model Pack, no copy.** The attributes role binds the S4 pack `embeddings-siglip2-base-p16-224-dev-v1` (manifest `models/manifests/embeddings-siglip2-base-p16-224-dev-v1.json`, unchanged) for both `person-attributes` and `vehicle-attributes`. The binding names that manifest's derived `modelPackId`. The worker refuses any other manifest, checked by file name, by SHA-256 and by the pinned `modelPackId`. The manifest still declares only `embedding`: the pack is capability-neutral, and the zero-shot semantics live in the identity-bearing attribute pipeline (schema, `mean-score-argmax` policy, parameters with prompts and thresholds).
2. **Explicit Development composition.** The role is composed the way §3 composes the `embeddings` role, not through the Component Binding resolver.
   - **Runtime and gating.** It runs from the locked `embeddings-onnx-v1` environment. Production mode is refused. The profile must be `developmentOnly` and must name `siglip2-zero-shot-v1`.
   - **Release.** The binding `src/vision/config/attributes/development-attributes-siglip2-binding-v1.json` is the one document both the platform (`VisualAttributeReleaseParser`) and the worker read. Its role names the `embeddings-onnx-v1` family.
   - **Truthful provenance.** The runtime is `unpacked-environment` with no Runtime Pack id, and the capabilities are `unverified`. A Development record (`attributes-siglip2-zero-shot-development.json`, `status: development-unqualified`) stands where a qualification record would.
   - **Verification.** Every pack artefact is SHA-256 verified before ONNX Runtime loads it. `tools/verify_repo.py` holds the release to its generator (`tools/poc/attributes_zero_shot_profile.py`) and to the identity vector `contracts/test-vectors/poc-zero-shot-attribute-identity-v1.json`.
3. **Row semantics.**
   - **Colours.** `p = softmax(logitScale · cos(image, prototype))` over the schema's values, with prompt-ensembled prototypes.
   - **Bag and headwear.** These emit only `present`, so a Track is `present` or Unknown. No negative is claimed (Stage-2 plan §13).
   - **Abstention and confidence.** A monotone map puts each attribute's abstention threshold at the policy's 0.5. A row's confidence is therefore an abstention-normalised score, not a probability, and the UI calls it "score".
   - **Small crops.** A crop with shorter side under 80 px contributes zero scores (§1's scope). This can only move a Track towards Unknown.
4. **Disclosure.** The parameters state `disclosure: "zero-shot, Development"`. The platform reads it into the release definition, and the attribute rail, coverage line, every matched result row and the detail panels show it.
5. **Search.**
   - **Grammar and cursor.** Repeated `attribute=type:value` predicates are ANDed and canonically ordered. They are paged by the v4 cursor with a new `attributes` derived pin: the identity fingerprint, plus coverage of in-scope / analysed / unavailable / not analysed and one Unknown count per predicate. This uses the capability-tagged pin list the v4 cursor was designed to extend, so there is no v5.
   - **Scope.** Attribute-only search spans cameras. A combination with analytic predicates keeps the analytic camera scope and pins both identities.
   - **Combinations refused.** Attribute plus plate, and attribute plus appearance query, are refused (400).
   - **Matching and coverage.** `Unknown` never matches, and a Track with no visible analysis never matches; both are counted in coverage.
   - **Execution.** The predicate is an EF correlated EXISTS per predicate through `ix_visual_attributes_track`. It has no new index and is measured only at demo scale.

**Trade-offs accepted.**
- The pack's manifest does not list the attribute capabilities it is bound to. The alternative was a second manifest over the same bytes, which is a second pack identity for one set of weights. That was judged worse than one pack, one identity.
- The resolver's Runtime Pack, qualification and gate-set checks do not apply to this role, exactly as for `embeddings`. Moving both roles into the binding machinery is the promotion path.
- Calibration is only as good as its held set. The method and numbers are in `docs/qualification/poc/s5-zero-shot-attributes.md`, and the result is a Development scope, not qualification.
- Stage-2 E5–E8 behaviour is implemented here for the PoC, but rows E5–E8 stay OPEN. E8 (measured plans at realistic and worst-supported volume) in particular is not attempted.
