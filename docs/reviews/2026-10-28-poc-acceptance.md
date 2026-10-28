# MAVI end-to-end PoC — Acceptance Register

**Status:** **OPEN** — S0 opened 2026-10-28; no row is PASS.
**Date opened:** 2026-10-28
**Baseline:** `main@393a16ed74e617291aa6f0efe5ed27687851e457`
**Plan:** `docs/superpowers/plans/2026-10-28-mavi-poc-end-to-end.md` (accepted 2026-10-28, D1–D9). **Profile:** `poc-single-host` (ADR-020).

This register is the only authoritative exit gate for the PoC. The plan (§4, "Register rows per slice") references these row ids and keeps no second list. **Nothing unexecuted is marked PASS.** A row becomes PASS only when its evidence is entered here: commits, CI run ids, retained artefact SHA-256s and their location (`E:\MAVI-Controlled\PoC\…`). Dataset bytes, media, crops, embeddings and weights never enter Git.

Evidence class for every row is **Development** (ADR-020 §2, principle 6a): reproducible, provenance recorded, deterministic where the claim is deterministic, honest limits stated. No row claims Production qualification, model selection or identity.

States: `NOT STARTED` · `IN PROGRESS` · `PASS` · `FAIL` · `DESCOPED (owner)` — a descoped row records the owner decision and date; a criterion is never weakened to reach PASS (principle 10).

## A. Deployment and profile (S0, S1, S1b, S12)

| Id | Criterion | Slice | State | Evidence |
|---|---|---|---|---|
| A1 | ADR-020 accepted; this register and the plan merged; README and both roadmaps reconciled with `main` | S0 | IN PROGRESS | branch `poc/s0-decisions` |
| A2 | `Install-MAVI-PoC` installs the complete stack on a clean Windows machine (VM or fresh profile) **with the network disconnected**, from the kit + PoC bundle only | S1 | NOT STARTED | |
| A3 | Smoke test after install: import one demo clip → Tracks → search → Review; exit code and log retained | S1 | NOT STARTED | |
| A4 | System/About page and persistent banner show profile, "not Production-qualified", evidence class, resolved device and reason, every pack identity and verification status; a test proves the disclosure cannot be configured away | S1 | NOT STARTED | |
| A5 | `Auto` resolves CUDA on the laptop (`sm_75` variant) and CPU on a GPU-less VM, each with the recorded reason; explicit `CUDA` fails closed where unavailable | S1 | NOT STARTED | |
| A6 | Second Windows CUDA Runtime Pack variant (`sm_75;sm_89`) built under build contract v2, hashed, locked (status "built, hashed, locked"; `qualified-development-hardware` for the 4090 only after A7); `torch.cuda.get_arch_list()` recorded; `onnxruntime-gpu` pinned; dependency policy, catalogue, kit and runbooks updated | S1b | NOT STARTED | |
| A7 | 4090 host: install from the kit offline; every role on `cuda:0`; VRAM co-residency and throughput recorded | S12 | NOT STARTED | |

## B. Demo corpus (S2)

| Id | Criterion | Slice | State | Evidence |
|---|---|---|---|---|
| B1 | 8–12 fixed-camera clips acquired through `tools/qualification/source_acquisition` with predeclared scopes; each source has an ADR-017 admissibility record (`RESEARCH-ADMISSIBLE` or better) and, for kit media, a CC0 or CC-BY licence; platform-licensed (Pexels/Pixabay) clips are owner-machine demo media only and never enter the kit | S2 | IN PROGRESS | 8 clips (minimum met), all Wikimedia Commons (3 CC0, 5 CC BY 2.0/3.0/4.0), acquired through `tools/qualification/source_acquisition` (`discover` under scopes predeclared and committed before each pass: `82e04c05`, amendments A1 `bd7ccce3`, A2 `041513da`, A3 `9bde864d`; `acquire --purpose-approvals`, receipts `APPROVED`, `verify` clean). ADR-017 status per file: RESEARCH-ADMISSIBLE, redistribution permitted by licence (`docs/qualification/poc/s2-demo-corpus-admissibility.md` §2). 4 of 8 originals transferred by resumable `curl` into the helper's store paths because of Wikimedia per-connection throttling, then size + provider SHA-1 verified by `acquire` (`ALREADY_PRESENT_VERIFIED`), disclosed in §3. No Pexels/Pixabay clip acquired; `owner-machine-only` is empty. **Coverage gaps (predeclared targets not met): car park, lobby/close-range faces** (§4); PASS needs (a) owner ratification of the operator-signed determinations `poc-s2-commons-cc0-2026-10` and `poc-s2-commons-cc-by-2026-10` (`docs/qualification/poc/s2-purpose-approvals-batch{1,2}.json`) and (b) owner acceptance of the gaps or a further pass. Store `E:\MAVI-Controlled\PoC\Corpus\source-store`; originals manifest `manifests\originals.sha256`. |
| B2 | Attribution and licence file shipped in the kit; accepted by the owner | S2 | IN PROGRESS | `docs/qualification/poc/demo-corpus-attribution.md` drafted from each file page's own licence metadata (author, source, licence, changes, no endorsement). **Pending owner acceptance** of the attribution file; shipping it in the kit is S1/S13 (D5). |
| B3 | Face-bearing clips are model-released or CC0; no biometric derivative enters the kit | S2 | IN PROGRESS | No clip is face-bearing (rule 4: people incidental, distant or overhead); the three CC0 clips would satisfy B3 regardless; CC BY clips with recognisable close faces were excluded (e.g. Pyrkon hall). No biometric derivative created in S2; audio stripped from every derivative (admissibility §2). PASS with B1/B2 owner acceptance; the face-demo gap is recorded under B1. |
| B4 | Per-clip scene configuration (zones, trip lines) and scripted import reproduce the demo state from a clean install | S2 | IN PROGRESS | `tools/poc/demo-corpus/demo-corpus-v1.json` (8 scenes: 14 zones incl. 6 `Restricted`, 8 directed trip lines, server `SceneRules` mirrored and unit-tested) + `tools/poc/demo_corpus.py import` (public API only: camera → import → scene → process). Run from a fresh empty database `mavi_poc_s2_20261028` with this branch's Development API build and the CUDA worker (not yet a kit install; PASS needs the same import after `Install-MAVI-PoC`, S1): 8 cameras, 8 assets, 8 scene revisions, 8 runs `Completed`, analytics `Ready`, exit 0; reruns idempotent (API mutation extract: 8 camera/import/scene/process each, plus 24 `409 video_duplicate` across runs 2–4). Trims deterministic: second pass reproduced all 8 derivative SHA-256s. Evidence `E:\MAVI-Controlled\PoC\Corpus\evidence-2026-10-28\SHA256SUMS` = `98118e3661c7c223be764dafb9f980af02160fff96be2ccb5717fa238a91d548` (admissibility §6). Observed: s2-08 overhead yields 0 Tracks (detector limit). |
| B5 | No label, annotation or ground truth is created for the PoC (any diagnostic labelling has a one-line technical rationale) | S2 | PASS | No label, annotation, box, count, identity or ground truth created. Diagnostic looks only: viewpoint screens (Commons-rendered frames, rationale: confirm a fixed uncut view for valid geometry) and reference frames to draw scene geometry (configuration, not annotation); no model output read during selection (admissibility §1, §5). |

## C. Capabilities (one block per stage)

| Id | Stage | Criterion | Slice | State | Evidence |
|---|---|---|---|---|---|
| C4.1 | 4 | PD5 + OC1-S bound under the PoC profile; GPU-first where the runtime supports it, otherwise CPU with recorded reason | S3 | NOT STARTED | |
| C4.2 | 4 | `POST /api/plates/reanalysis` requires authorisation; `Plates:Enabled=false` no longer halts the authority loop | S3 | NOT STARTED | |
| C4.3 | 4 | Partial plate search on a demo clip returns Tracks with crop, source frame and player seek; H3 capability numbers (52/110, 45/79) cited verbatim on the known-limits page | S3 | NOT STARTED | |
| C5.1 | 5 | ADR-021 accepted; SigLIP 2 Model Pack (Apache-2.0) hashed, licensed, in the kit | S4 | NOT STARTED | |
| C5.2 | 5 | `embeddings` role runs post-Track over lease-scoped, hash-verified Evidence Set crops; its failure never changes a ProcessingRun | S4 | NOT STARTED | |
| C5.3 | 5 | `GET /api/tracks/{id}/similar` and `appearanceQuery` are whitelisted, fingerprinted and snapshot-stable; results labelled *Similarity candidates*; no `EntityId` written | S4 | NOT STARTED | |
| C5.4 | 5 | Retrieval sanity on 200 held H3 crops (spike) retained; latency at the demo-corpus scale recorded | S4 | NOT STARTED | |
| C2.1 | 2 | Zero-shot SigLIP 2 inferencer replaces the fixture in the existing `attributes` role; Observed/Unknown rows per the S2b lifecycle; abstention calibrated on held crops | S5 | NOT STARTED | |
| C2.2 | 2 | Attribute search (v4 cursor) and UI per spec; every surface says "zero-shot, Development"; Stage-2 F/G rows untouched | S5 | NOT STARTED | |
| C5A.1 | 5A | ADR-022 (biometric handling, gallery and candidate-match semantics) accepted **before** any face code merges | S6 | NOT STARTED | |
| C5A.2 | 5A | Usable-face coverage on the demo corpus measured and recorded first | S6 | NOT STARTED | |
| C5A.3 | 5A | YuNet + AdaFace (or SFace) packs hashed, each licence read from its own LICENSE file and recorded (AdaFace checkpoints: research provenance, Development-only scope); `faces` role post-Track; Unknown preserved where no usable face | S6 | NOT STARTED | |
| C5A.4 | 5A | `Find this face` from evidence or a transient query image returns candidate Person Tracks with score and threshold context; gallery enrol/update is attributable (S11-min); candidate known-person match never shown as identity | S6 | NOT STARTED | |
| C5A.5 | 5A | Face crops, embeddings and gallery are local-only and removed by uninstall | S6 | NOT STARTED | |
| C6.1 | 6 | ADR-023 accepted; `entity_candidates` from embeddings + time/camera plausibility (+ face as a separate visible factor) | S7 | NOT STARTED | |
| C6.2 | 6 | Confirm/dismiss is attributable; `Track.EntityId` written only by confirmation; no automatic merge | S7 | NOT STARTED | |
| C7.1 | 7 | Rule catalogue v1 (crossing counts, dwell, stopped vehicle, wrong-way, repeated visit, co-occurrence) versioned; `analytic_events` bound to inputs and rule version; deterministic fixtures per rule | S8 | NOT STARTED | |
| C7.2 | 7 | Events timeline with evidence drill-through | S8 | NOT STARTED | |
| C8.1 | 8 | ADR-024 accepted; typed query contract with explicit Track/Event/Entity units; golden tests | S9 | NOT STARTED | |
| C8.2 | 8 | Advanced Search builder; latency budget on the demo corpus recorded | S9 | NOT STARTED | |
| C9.1 | 9 | Language Runtime and Model Packs (llama.cpp MIT; Qwen2.5-1.5B/7B-Instruct, Apache-2.0 — not the research-licensed 3B/72B sizes) hashed, licensed, offline | S10 | NOT STARTED | |
| C9.2 | 9 | Translation to the C8 contract is schema-validated; out-of-contract requests are refused; frozen question corpus (~60) passes translation and grounding tests in CI | S10 | NOT STARTED | |
| C9.3 | 9 | Ask MAVI surface shows "Interpreted as", answer, chart/table and drill-through; every displayed fact equals the deterministic result envelope | S10 | NOT STARTED | |
| C10.1 | 10 | ADR-010 (operator identity, in-box Negotiate; `development-unattributed` fallback) accepted; append-only audit table; attributable mutation plumbing | S11-min | NOT STARTED | |
| C10.2 | 10 | Confirm/reject Tracks, Entity confirmation, cases with Tracks/events/notes; audit visible | S11-full | NOT STARTED | |

## D. Closure (S13)

| Id | Criterion | State | Evidence |
|---|---|---|---|
| D1 | Scripted demonstration (plan §3 steps 1–12) executed end to end on the 4090 host, offline, from the kit; recording or log retained | NOT STARTED | |
| D2 | Throughput per device (CPU, 1650 Ti, 4090) for the demo corpus recorded | NOT STARTED | |
| D3 | Known-limits page: plate accuracy on proxy data and absence of Indian plates; zero-shot attributes; faces/ReID as candidates; not Production-qualified | NOT STARTED | |
| D4 | Every slice merged with exact-head CI green and one independent cold review (plan D2); any descoped row carries its owner decision | NOT STARTED | |
| D5 | Kit assembled with `New-MaviOfflineBinaryKit.ps1` + media + attribution + licences; hash manifest retained | NOT STARTED | |

## Owner decisions

| Id | Decision | Date |
|---|---|---|
| D1–D9 | Accepted as recommended in the plan §2 | 2026-10-28 |
