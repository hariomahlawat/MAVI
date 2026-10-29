# MAVI end-to-end PoC — plan (full roadmap scope)

**Status:** **ACCEPTED by the owner on 2026-10-28** (rev 2; decisions D1–D9 accepted as recommended, in a Claude Code session; this document transcribes the decision). S0 is open. No code, dependency or runtime change accompanies this document; ADR-020 is written with it.
**Baseline:** `main@393a16ed`.
**Owner brief (2026-10-28):** build a modular, functional, end-to-end PoC covering **every capability of the original roadmap, including Face Intelligence and Behaviour Analytics**, that can be deployed, tested and demonstrated and later improved to production grade. The owner sources no test data and does no research; everything comes from open-source assets and the agent's own knowledge. **Development machine:** the current laptop (GTX 1650 Ti, 4 GiB, `sm_75`). **Demonstration machine:** a Windows host with an RTX 4090 (16 or 24 GiB, `sm_89`), used after the PoC is complete.
**Governing documents:** `AGENTS.md`; operating principles 6a, 10, 11; ADR-003, ADR-008, ADR-009, ADR-013, ADR-014, ADR-017; `capability-roadmap.md` §2; `capability-implementation-roadmap.md` §2–§3.

## 1. What the PoC is, and is not

**Is.** One Windows host on which an installer puts MAVI, PostgreSQL, FFmpeg, the vision runtime and every capability runtime, plus a redistributable demo corpus. An operator imports recorded video and, in the same session, can: search persons and vehicles by time, class, zone, line crossing and dwell (Stage 1, done); by appearance attributes (Stage 2); by vehicle subclass (Stage 3, done); by plate text with crops (Stage 4); find visually similar Tracks (Stage 5); find a face's previous appearances and candidate matches against an enrolled gallery (Stage 5A); review ReID candidate associations and confirm them (Stage 6 + 10); see deterministic events on a timeline (Stage 7); compose counts, group-bys and time buckets (Stage 8); ask the same questions in plain language (Stage 9); and record attributable review decisions and cases (Stage 10). Every screen states: PoC profile, Development-grade evidence, not Production-qualified.

**Is not.** Production qualification (Task 18); Indian-plate accuracy; live RTSP/VMS ingestion (the roadmap's own "later platform phase", §6 — see D8); model selection events, protected D or any change to frozen Stage-4 rules; biometric claims of identity (every face or ReID result is a candidate with evidence).

**Why this shape.** Phase 1, Stage 1, Stage 3, Stage 3.5 and the Stage-4 pipeline/search/UI already exist on `main`, and the Stage-2 attribute lifecycle (`attributes` role, D1–D8 PASS) runs with a fixture inferencer. The PoC adds: a deployable profile and installer proven on a clean machine; a demo corpus; the model-bearing capabilities (plates bound, embeddings, zero-shot attributes, faces, Ask MAVI) each as its own Model/Runtime Pack and post-Track role; the deterministic layers (events, structured query, ReID candidates, review/cases); and a PoC-sized acceptance record.

## 2. Decisions the owner must take first (principle 10)

| Id | Decision | Recommendation |
|---|---|---|
| D1 | **PoC deployment profile** `poc-single-host` (ADR-020, amends ADR-008): P3 machinery plus a CUDA Runtime Pack when a compatible GPU is present; Development-grade evidence; mandatory "not Production-qualified" disclosure in UI and release metadata; promotion path = Task 18 unchanged. | Accept. |
| D2 | **Evidence process.** Principle 6a and ADR-017 §10: reproducible, provenance, deterministic evaluation, honest limits; one independent cold review per PR; no protocol freeze, M3 authority or protected D inside the PoC. Stage-4 rows P4–P6/P13–P15 and IP-2/3/4 stay NOT STARTED. | Accept. |
| D3 | **Demo corpus licence and privacy class.** Kit media = **CC0 / CC-BY only** (Wikimedia Commons and similar), attribution file shipped. Pexels/Pixabay-licensed clips are not redistributable as standalone files and, like BDD100K, may be used only in live demos on owner machines, each with a per-source admissibility record. For face demos, prefer model-released stock footage; biometric derivatives (face crops, embeddings, gallery) never enter the kit and are deleted by the uninstall path. BDD100K (research licence) is used only in live demos on owner machines. | Accept. |
| D4 | **Plate composition:** PD5 PP-OCRv5-mobile det (Apache-2.0) + OC1-S fast-plate-ocr (MIT), the #226 pair (52/110 on H3). Not yolo-v9 (GPL question open), not yolo11 (AGPL). Adapter selection stays so a cleared detector can replace PD5 later. | Accept. |
| D5 | **Embedding model** for similarity, appearance query and zero-shot attributes: SigLIP 2 base (`google/siglip2-base-patch16-224`, Apache-2.0), ONNX, one Model Pack serving Stages 2, 5 and 6. | Accept. Specialist ReID (OSNet/TransReID) is a later swap under ADR-014. |
| D6 | **Face stack:** detector YuNet (OpenCV Zoo, ONNX; its model folder carries its own LICENSE — MIT or Apache-2.0 — recorded at the S6 spike); embedder AdaFace IR-50 (MIT code; checkpoints not separately licensed and trained on WebFace4M, whose terms are research/non-commercial — recorded as Development-only scope in ADR-022) with SFace (OpenCV Zoo, Apache-2.0) as the fallback if AdaFace export or quality fails the S6 spike. Requires ADR-022 (biometric data handling, gallery and candidate-match semantics, ADR-013 §19 note on face-oriented selection). | Accept; the spike decides AdaFace vs SFace. |
| D7 | **Language model for Ask MAVI:** Qwen2.5-1.5B-Instruct (Apache-2.0) in GGUF via llama.cpp (MIT) for the laptop; the same pack may select Qwen2.5-7B-Instruct (Apache-2.0) on the 4090. The 3B and 72B Qwen2.5 sizes are under the non-commercial Qwen Research License and are not used. The model only emits Stage-8 structured queries; MAVI computes. | Accept. |
| D8 | **Live RTSP/VMS** stays out of the PoC, as the roadmap states (§6). | Accept; revisit after S14. |
| D9 | **4090 runtime.** The frozen CUDA build contract (`config/vision/windows-cuda-development-build-v1.json`) compiles mmcv for `sm_75` only; the 4090 is `sm_89`. A second Windows CUDA Runtime Pack variant is built under a **second build contract** (`windows-cuda-development-build-v2.json`: target GPU list `7.5;8.9`, its own native ABI; the v1 contract is unchanged) with mmcv compiled for `sm_75;sm_89`; the pinned torch 2.6.0+cu124 wheels run on `sm_89` through 8.x SASS/PTX compatibility (confirmed with `torch.cuda.get_arch_list()` in S1b). The v1 contract names a controlled build host as authoritative; for the PoC profile only, the owner accepts the Development laptop as the v2 variant's build host. `onnxruntime-gpu` (CUDA EP) replaces CPU onnxruntime for plates, embeddings and faces on GPU hosts. Both are Development-grade packs under the PoC profile; the v2 variant is "built, hashed, locked" at S1b and earns `qualified-development-hardware` for the 4090 only on the S12 host observation (ADR-009). | Accept; S1b below. |

## 3. Target demonstration (30 minutes, on the 4090 host)

1. Fresh machine, network disconnected: `Install-MAVI-PoC.cmd`; System page shows profile, device `cuda:0` (RTX 4090) with reason, every Model/Runtime Pack identity, the non-qualified banner.
2. Import the demo clips (gate, junction, car park, pedestrian area, lobby); processing and all post-Track roles complete.
3. Scene search: vehicles inbound over Gate line 09:00–10:00; persons dwelling > 2 min in Zone A; cars only.
4. Attributes: "person, red upper clothing, backpack"; "white vehicle" — Observed/Unknown rows with evidence.
5. Plates: partial plate text → Tracks, crops, source frame, player seek.
6. Find similar from a vehicle Track across cameras; similarity candidates with scores and side-by-side evidence.
7. Face: pick a Person Track with a usable face → previous appearances across cameras; compare against an enrolled gallery → candidate known-person match with score; Unknown where no usable face exists.
8. ReID: candidate Entity associations with their evidence factors; confirm one as an attributable decision; `Track.EntityId` written with audit.
9. Events timeline: crossings per hour per direction, dwell, stopped vehicle, repeated visit (needs 8), co-occurrence.
10. Advanced Search: "count Person Tracks that crossed Main Gate between 08:00 and 14:00, by hour"; "top 5 cameras by Vehicle Tracks today".
11. Ask MAVI: the same two questions in plain language; "Interpreted as" disclosure; answer with drill-through.
12. Case: collect Tracks, events and a face match into a case with notes; append-only audit visible.

## 4. Slices

Each slice is one PR (some two), thin end-to-end first, exact-head CI, one cold review, owner merge. Durations are agent working time; principle-10 timeboxes apply (reassess at half a day of infrastructure or debugging; owner approval beyond one day). Every model-bearing slice starts with a half-day spike on held H3 / demo crops before infrastructure is built.

| Slice | Stage | Deliverable | Depends on | Est. (days) |
|---|---|---|---|---|
| **S0** Decisions | — | ADR-020 (PoC profile); this plan accepted; PoC acceptance register skeleton; one-paragraph reconciliation of README / both roadmaps / Stage-4 register header. | — | ½ |
| **S1** Deployable PoC v0 | — | `Install-MAVI-PoC.ps1/.cmd` on `Setup-MAVI.ps1` + `New-MaviOfflineSetupBundle.ps1` + P3 path: platform, PostgreSQL, FFmpeg, vision runtime (CPU, or CUDA pack if detected), plates runtime, demo cameras/scenes seeded, smoke test. System/About page: profile, device + reason, pack identities, banner. Verified offline on a clean Windows VM / fresh profile. | S0 | 3 |
| **S1b** 4090 runtime variant | — | Second Windows CUDA Runtime Pack variant (`sm_75;sm_89` mmcv, locked); `onnxruntime-gpu` pin for the ONNX roles; device-capability check in the installer; verified on the laptop (`sm_75` path) now and on the 4090 when available. | S1 | 1–2 |
| **S2** Demo corpus | — | 8–12 CC0/CC-BY fixed-camera clips (traffic, gate, car park, pedestrians, lobby with visible faces) discovered and admitted with `tools/qualification/source_acquisition` (predeclared scopes, ADR-017 admissibility once per source), trimmed, attribution file, scene configs, scripted import. No labels created. | S0 | 2 |
| **S3** Plates bound | 4 | D4 composition bound in the PoC profile; GPU-first per issue #229 with recorded reason; close PR-3 limits (reanalysis authorisation; `Plates:Enabled` loop); cite H3 numbers verbatim. | S1 | 1–2 |
| **S4** Embeddings + Find similar | 5 | ADR-021 embedding storage (`track_embeddings`: model/version/dimension, HNSW cosine). SigLIP 2 ONNX Model Pack; `embeddings` post-Track role on the plates-role pattern over the Evidence Set; `GET /api/tracks/{id}/similar`; `appearanceQuery` text predicate (whitelisted, fingerprinted, snapshot-stable); UI "Find similar" + *Similarity candidates* panel. Dependency policy, pack, licence in the PR. | S1, S2 | 4 |
| **S5** Zero-shot attributes | 2 | Real inferencer for the existing `attributes` role: SigLIP 2 zero-shot over the frozen vocabulary (upper/lower colour, bag, headwear, vehicle colour) with calibrated abstention → Observed/Unknown rows through the merged S2b lifecycle; attribute search v4 cursor (E5–E8); UI per spec. Labelled "zero-shot, Development" — it is not the S2c learned Model Pack and closes no F/G row. | S4 | 3 |
| **S6** Face Intelligence | 5A | ADR-022. YuNet + AdaFace/SFace Model Packs; `faces` post-Track role over Person Evidence Set; `face_observations`, `face_embeddings`, `enrolled_persons` (+pgvector); usable-face coverage measured on the demo corpus first (roadmap entry decision); `Find this face` from evidence or a transient query image; gallery CRUD (pulls forward S11's minimal identity/audit); candidates with score and threshold context; Unknown preserved. | S4, S11-min | 4–5 |
| **S7** ReID candidates | 6 | ADR-023 Entity semantics. `entity_candidates` from Stage-5 embeddings + time/camera plausibility (+ face similarity as a separate visible factor); candidate list with side-by-side evidence; confirm/dismiss attributable; `Track.EntityId` written only by confirmation. No automatic merge. | S4, S6, S11-min | 3 |
| **S8** Events | 7 | Versioned rule catalogue v1: line-crossing counts per direction/bucket, dwell, stopped vehicle, wrong-way, repeated visit (entity-conditioned, after S7), co-occurrence; `analytic_events` bound to inputs and rule version; Events timeline with evidence drill-through. | S2 (S7 for entity rules) | 3 |
| **S9** Structured query | 8 | ADR-024 query contract: whitelisted predicates + `find/count/countDistinct/groupBy/timeBucket/first/last/top/compare`; explicit Track/Event/Entity units; typed result envelope; Advanced Search builder UI; golden tests; latency on the demo corpus. | S4, S5, S8 | 3–4 |
| **S10** Ask MAVI | 9 | Language Runtime Pack (llama.cpp) + Qwen2.5 Model Pack; translation to the S9 contract with schema validation and refusal; Ask MAVI surface with "Interpreted as", answer, chart/table, drill-through; frozen question corpus (agent-written, ~60 questions) for translation/grounding tests. | S9 | 4–5 |
| **S11** Review / cases | 10 | **S11-min (early, before S6):** ADR-010 operator identity (in-box Negotiate; `development-unattributed` fallback), append-only audit table, attributable mutation plumbing. **S11-full:** confirm/reject Tracks, Entity confirmation UI (with S7), cases with Tracks/events/notes. | S1 (min); S7 (full) | 1 + 3 |
| **S12** 4090 bring-up | — | Install on the demonstration host from the kit, offline; verify `cuda:0` for every role, VRAM co-residency, throughput; record device/reason evidence. | S1b, all roles | 1 (plus owner host time) |
| **S13** Acceptance + demo pack | — | PoC acceptance register (steps 1–12 of §3, retained evidence); throughput CPU/1650 Ti/4090; known-limits page; scripted demo; kit assembled with `New-MaviOfflineBinaryKit.ps1` + media + attribution + licences. | all | 2–3 |

**Register rows per slice:** S0→A1; S1→A2–A5; S1b→A6; S2→B1–B5; S3→C4.1–C4.3; S4→C5.1–C5.4; S5→C2.1–C2.2; S6→C5A.1–C5A.5; S7→C6.1–C6.2; S8→C7.1–C7.2; S9→C8.1–C8.2; S10→C9.1–C9.3; S11→C10.1–C10.2; S12→A7; S13→D1–D5.

**Principle-10 approval.** The owner's acceptance of these estimates is the principle-10 approval for the infrastructure slices S1, S1b and S12 to exceed one working day; a slice that exceeds its estimate by half a day returns to the owner before continuing.

**Total:** ≈ 40–48 agent working days. With two or three streams in separate worktrees on disjoint modules (deployment; embeddings→attributes→faces→ReID; events→query→Ask MAVI), roughly 5–7 calendar weeks. Owner time: ADR approvals (020–024, 010, 022), attribution-file acceptance, ~16 merges, two host sessions (laptop CUDA variant check; 4090 bring-up).

**Order.** S0 → {S1, S2} → {S1b, S3, S4, S11-min} → {S5, S8} → S6 → S7 → S9 → S10 → S11-full → S12 → S13.

## 5. Assets (all open; none collected by the owner)

| Need | Asset | Licence | State |
|---|---|---|---|
| Detector/tracker | RTMDet-m + ByteTrack packs | Apache-2.0 | in `main` |
| Plate det / OCR | PP-OCRv5 mobile det; fast-plate-ocr cct-s-v2 | Apache-2.0; MIT | in `main` (#226) |
| Embeddings, attributes, appearance query | SigLIP 2 base patch16-224 | Apache-2.0 | resolved in S2c survey; export in S4 |
| Face detector / embedder | YuNet; AdaFace IR-50 (fallback SFace) | YuNet per its model-folder LICENSE (verify at spike); AdaFace MIT code, checkpoints research provenance; SFace Apache-2.0 | spike in S6 |
| Language model / runtime | Qwen2.5-1.5B / 7B-Instruct GGUF; llama.cpp | Apache-2.0; MIT | spike in S10 |
| ONNX runtime | onnxruntime 1.31.0 CPU; onnxruntime-gpu 1.26.0 (S1b: the last CUDA 12 build on PyPI; 1.27.0+ are CUDA 13 builds, so "same pin" was not possible) | MIT | CPU pinned; GPU pinned in S1b |
| Demo media (kit) | Wikimedia Commons and similar | CC0 / CC-BY only | S2 |
| Demo media (owner-machine demos only) | Pexels/Pixabay clips; BDD100K H3 sequences | platform licences (no standalone redistribution); research licence | S2, held locally |
| Plate demo media | BDD100K H3 sequences | research, non-redistributable | held locally |

No weights, dataset bytes or media in Git. Each asset updates `offline-dependency-policy-v1.json`, the binary catalogue, the kit, licences and runbooks in its PR.

## 6. Risks and honest limits

| Risk | Handling |
|---|---|
| **Scope.** Ten capabilities in one PoC is 40+ agent days; drift and half-built slices are the main risk. | Thin end-to-end per slice; nothing merges without its demo step working; S13 lists any slice that was descoped rather than weakened (principle 10). |
| **4090 `sm_89`** vs frozen `sm_75` build. | S1b builds and locks a second variant now, verified on the laptop; the 4090 session (S12) is bring-up, not development. |
| **CCTV faces are small**; usable-face coverage may be low. | Measured first on the demo corpus (S6); lobby/close-range clips chosen in S2; Unknown is a first-class result. |
| **Biometric and privacy exposure** in a demo. | ADR-022 before any face code; model-released footage; local-only derivatives; uninstall deletes them. |
| **Plate accuracy on proxy data; no Indian plates.** | H3 numbers stated; Indian capability needs O1B data (v2). |
| **Zero-shot attributes drift into claims.** | Abstention calibrated on held crops; UI says zero-shot Development; Stage-2 register rows untouched. |
| **Ask MAVI hallucinating facts.** | Model emits a schema-validated S9 query or refuses; renderer uses only the result envelope; grounding tests in CI. |
| **CPU hosts are slow.** | PoC profile reports measured throughput; demo host is the 4090. |
| **Ceremony creep.** | D2; any freeze/selection/protected-D request inside the PoC returns to the owner. |
| **Two similar defects from one assumption.** | Architectural reassessment, per principle 10. |

## 7. After the PoC

Indian plate corpus and detector clearance (O1B, RT-DETRv2 or a written yolo-v9 weight licence); Track association (O1A); Stage-2 learned Model Pack through the frozen S2c protocol; specialist ReID models; CUDA C5.4/C6/C7 and Task 18 on the profile's successor; live ingestion ADR.

## 8. Acceptance for this plan

Accepted when the owner records D1–D9 and S0 opens. **Recorded 2026-10-28: D1–D9 accepted as recommended; S0 opened on branch `poc/s0-decisions`.** The PoC acceptance register is `docs/reviews/2026-10-28-poc-acceptance.md`; it is the only exit gate for the PoC and this plan keeps no second list.
