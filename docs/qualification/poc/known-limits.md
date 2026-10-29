# MAVI PoC — known limits

**Profile:** `poc-single-host` (ADR-020). **Not Production-qualified. Evidence class: Development.** Every capability below is a proof of concept; its results are candidate evidence, never operational truth.

This page is the PoC's record of what each capability does not do. The operator UI carries the same statements on the System / About page (`src/web/mavi-web/src/features/system/PlateKnownLimits.tsx`, which a test holds to the numbers here). Slices add their capability's section; S13 (register row D3) completes it.

## Plate reading (Stage 4; slice S3, register rows C4.1–C4.3)

- **Composition.** PD5 (PP-OCRv5 mobile detection, PaddlePaddle official ONNX, Apache-2.0) detects plates in a Vehicle Track's evidence crops; OC1-S (fast-plate-ocr `cct_s_v2_global`, MIT) reads them (plan decision D4). Both are unverified Development Model Packs; each licence is read from the pack's own LICENSE at install. They run on CPU (`plates-onnx-v1`); GPU plates are not available in the PoC yet.
- **Measured capability, proxy data only.** The Development pilot on the BDD100K H3 holdout (`docs/qualification/stage4/anpr-dev-pilot-2026-10-17.md`, Issue #225, PR #226): exact plate search returned the associated Track for **52/110** ground-truth vehicles with a usable plate text, and for **45/79** of those whose plate the reference reader could read (oracle-readable). The main losses are Track association and evidence that does not show the plate, not OCR. BDD100K is US dash-camera footage, not fixed CCTV.
- **No Indian plates.** No Indian plate data exists in MAVI's evidence, and no accuracy is claimed for Indian plates or for any data beyond the numbers above. An Indian plate corpus is post-PoC work (plan §7, O1B).
- **Demo-corpus behaviour is not a measurement.** The PoC demo clips carry no plate ground truth (register B5); a plate read on a demo clip shows the pipeline working, not its accuracy.
- **Candidates, not identifications.** A reading is a model output with a confidence. Check it against the plate crop and the source frame before acting on it. The Stage-4 acceptance register (`docs/reviews/2026-10-12-stage4-anpr-ocr-acceptance.md`, frozen) is unchanged: evidence adequacy INADEQUATE (53/79), no model selection, no Production claim.
- **Re-analysis is authorised by Windows identity on a trusted host.** `POST /api/plates/reanalysis` requires an ADR-010 operator and records the request against the operator's Windows account. On a PoC install every local user is an operator (`BUILTIN\Users`, owner decision S1-T1), so attribution names the account but does not restrict who may ask; a browser opened at `127.0.0.1` instead of `localhost` sends no Windows credentials and is refused (401).

## Events (Stage 7; slice S8, register rows C7.1–C7.2)

- **What an event is.** A deterministic derivation from persisted scene-analytics facts by one rule of the versioned catalogue `mavi-events-v1` (ADR-025). No model decides an event. Each event names its rule version, scene revision, analytics algorithm version, the facts it came from and every parameter with its source. Events are only as good as the detections, Tracks and geometry beneath them. A fragmented Track (one vehicle split into several Tracks) produces several events.
- **Thresholds are disclosed, not tuned.** Dwell uses each zone's own threshold from the scene configuration. Stopped vehicle uses 30 s, the value the owner accepted for the demo after it was chosen post hoc (S2 admissibility record, decision 10). Here it is measured as the overlap of a stationary interval with a `Restricted` zone visit. Co-occurrence (a Person and a Vehicle in one zone at the same time) has no threshold. No threshold was changed after reading the events.
- **Wrong-way is defined but configured on no demo clip.** A trip line needs a permitted direction for it to fire. No S2 scene sets one, so the rule is shown by its test fixture only.
- **Repeated visit is disabled.** It is entity-conditioned. It needs confirmed Entities (ReID confirmation, slice S7), which do not exist yet. It is defined and tested against a fixture, the UI shows it as disabled with the reason, and no entity is faked.
- **One run at a time.** v1 rules see one run against one scene revision. Nothing spans runs or cameras.
- **Demo-corpus behaviour is not a measurement.** The demo clips carry no event ground truth (register B5). An event fired on a demo clip shows the rule working on pipeline output, not its accuracy.
