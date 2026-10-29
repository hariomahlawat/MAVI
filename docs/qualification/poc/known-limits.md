# MAVI PoC — known limits

**Profile:** `poc-single-host` (ADR-020). **Not Production-qualified. Evidence class: Development.** Every capability below is a proof of concept; its results are candidate evidence, never operational truth.

This page is the PoC's record of what each capability does not do. The operator UI carries the same statements on the System / About page (`src/web/mavi-web/src/features/system/PlateKnownLimits.tsx`, which a test holds to the numbers here). Slices add their capability's section; S13 (register row D3) completes it.

## Face intelligence (Stage 5A; slice S6, register rows C5A.1–C5A.5)

- **Face candidates, never identification.**
  - Every face result is a candidate: a cosine score next to the reference threshold and the model identity.
  - "Find this face" lists candidate Person Tracks. A gallery comparison lists candidate gallery matches.
  - Nothing stores a match or writes an `EntityId`, and nothing says "this is <name>" (ADR-022).
- **Usable faces are rare in the demo corpus.** Protocols `s6-face-coverage-v1` (12 clips) and `s6-face-coverage-v2` (the A6 clip s2-13): YuNet score ≥ 0.9, face shorter side ≥ 32 px.
  - **7 of 140** Person Tracks (5 %) have a usable face, all in the two indoor MEVA clips: the stairwell s2-12 (2 of 9) and the entrance hall s2-13 (5 of 30).
  - The cafe lobby s2-10, the school hall s2-11 and every traffic clip have none.
  - Most Person Tracks are therefore **Unknown (no usable face)**, which means "not analysable", not "no match".
  - **Demonstration scope.** ADR-022 §3 opts in only s2-10, s2-11 and s2-12, where only s2-12 has usable faces, so no cross-camera face demonstration is possible there. s2-13 may be opted in only after the owner confirms consent for its camera (G420) and ADR-022 §3 and the runbook are amended to name it. Even then, "Find this face" across s2-12 and s2-13 works only for an actor whose face is usable in both, and no identity label confirms it is the same actor.
  - The detector threshold stays at 0.9: the predeclared v2 rule found only 77 % of the 0.8–0.9 band to be faces, under its 90 % bar (`docs/qualification/poc/s6-face-coverage.md`).
- **Opt-in per camera.** Face analysis runs only on cameras an operator has switched on. In the demonstration that is only the MEVA clips with consented actors.
- **Model and threshold.**
  - AdaFace IR-50 scores 99.8 % on LFW 10-fold and 99.7 % with faces downscaled to 32 px.
  - The reference threshold is cosine 0.2121, the 32-px operating point at 0.1 % false accepts on LFW (`docs/qualification/poc/s6-face-embedder-spike.md`).
  - LFW is frontal and well lit, and it may overlap the training identities. **The threshold is not calibrated on CCTV.**
  - On the demo clips, two usable faces of the same Track scored 0.14, below the threshold (`s6-face-e2e-rehearsal.md`). A candidate below the threshold is not evidence of a different person, and one above it is not evidence of the same person.
- **Research-only checkpoint.** The AdaFace weights follow WebFace4M's non-commercial research terms. The pack is Development-only and may be used only for non-commercial demonstration. SFace (Apache-2.0) is the built fallback.
- **Biometric data stays on this machine.** Face templates, the gallery and query images live only in this installation's database:
  - query images are erased once analysed;
  - query vectors are purged after 1 hour;
  - `Uninstall-MAVI-PoC` removes all of it.
  - Every face search, comparison and gallery change is attributed to the operator and audited.

## Plate reading (Stage 4; slice S3, register rows C4.1–C4.3)

- **Composition.** PD5 (PP-OCRv5 mobile detection, PaddlePaddle official ONNX, Apache-2.0) detects plates in a Vehicle Track's evidence crops; OC1-S (fast-plate-ocr `cct_s_v2_global`, MIT) reads them (plan decision D4). Both are unverified Development Model Packs; each licence is read from the pack's own LICENSE at install. They run on CPU (`plates-onnx-v1`); GPU plates are not available in the PoC yet.
- **Measured capability, proxy data only.** The Development pilot on the BDD100K H3 holdout (`docs/qualification/stage4/anpr-dev-pilot-2026-10-17.md`, Issue #225, PR #226): exact plate search returned the associated Track for **52/110** ground-truth vehicles with a usable plate text, and for **45/79** of those whose plate the reference reader could read (oracle-readable). The main losses are Track association and evidence that does not show the plate, not OCR. BDD100K is US dash-camera footage, not fixed CCTV.
- **No Indian plates.** No Indian plate data exists in MAVI's evidence, and no accuracy is claimed for Indian plates or for any data beyond the numbers above. An Indian plate corpus is post-PoC work (plan §7, O1B).
- **Demo-corpus behaviour is not a measurement.** The PoC demo clips carry no plate ground truth (register B5); a plate read on a demo clip shows the pipeline working, not its accuracy.
- **Candidates, not identifications.** A reading is a model output with a confidence. Check it against the plate crop and the source frame before acting on it. The Stage-4 acceptance register (`docs/reviews/2026-10-12-stage4-anpr-ocr-acceptance.md`, frozen) is unchanged: evidence adequacy INADEQUATE (53/79), no model selection, no Production claim.
- **Re-analysis is authorised by Windows identity on a trusted host.** `POST /api/plates/reanalysis` requires an ADR-010 operator and records the request against the operator's Windows account. On a PoC install every local user is an operator (`BUILTIN\Users`, owner decision S1-T1), so attribution names the account but does not restrict who may ask; a browser opened at `127.0.0.1` instead of `localhost` sends no Windows credentials and is refused (401).

## Events (Stage 7; slice S8, register rows C7.1–C7.2)

- **What an event is.** A deterministic derivation from persisted scene-analytics facts by one rule of the versioned catalogue `mavi-events-v1` (ADR-025). No model decides an event. Each event names its rule version, scene revision, analytics algorithm version, the facts it came from and every parameter with its source. Events are only as good as the detections, Tracks and geometry beneath them. A fragmented Track (one vehicle split into several Tracks) produces several events.
- **Thresholds are disclosed, not tuned.** Dwell uses each zone's own threshold from the scene configuration. Stopped vehicle uses 30 s, the value the owner accepted for the demo after it was chosen post hoc (S2 admissibility record, decision 10). Here it is measured as the overlap of a stationary interval with a `Restricted` zone visit. Each qualifying interval is one event, so a vehicle that stands, moves briefly and stands again gives two events (on s2-09 one parked vehicle's two intervals, 3.4 s apart, give two of its six events). The overlap is measured against one zone visit at a time: if tracking jitter at the zone edge splits a stationary vehicle's visit into two shorter visits, each under 30 s, nothing fires. Merging such visits would be a new catalogue version. Co-occurrence (a Person and a Vehicle in one zone at the same time) has no threshold. No threshold was changed after reading the events.
- **Wrong-way is defined but configured on no demo clip.** A trip line needs a permitted direction for it to fire. No S2 scene sets one, so the rule is shown by its test fixture only.
- **Repeated visit is disabled.** It is entity-conditioned. It needs confirmed Entities (ReID confirmation, slice S7), which do not exist yet. It is defined and tested against a fixture, the UI shows it as disabled with the reason, and no entity is faked.
- **One run at a time.** v1 rules see one run against one scene revision. Nothing spans runs or cameras.
- **Demo-corpus behaviour is not a measurement.** The demo clips carry no event ground truth (register B5). An event fired on a demo clip shows the rule working on pipeline output, not its accuracy.
