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

## Visual attributes (Stage 2; slice S5, register rows C2.1–C2.2)

- **Zero-shot, Development.** The attributes are upper and lower clothing colour, carried bag, headwear and vehicle colour. They come from SigLIP 2 base (the S4 Model Pack, Apache-2.0, `unverified`), scoring each crop against text prompts with no training. This is not the Stage-2 learned attribute Model Pack (S2c), closes no Stage-2 F/G register row, and is not Production-qualified. Every search, coverage, row and detail surface says "zero-shot, Development".
- **Candidates, not facts.** An attribute value is a model output with an abstention-normalised score (0.5 is the threshold, and the score is not a probability). Check it against the supporting crop before acting on it.
- **Unknown is not absent.** The model abstains (Unknown) when no value reaches its threshold. Bag and headwear are only ever `present` or Unknown: the PoC never claims a person carries no bag. A search never matches an Unknown or an unanalysed Track; the coverage line counts them instead.
- **Small crops.** A crop whose shorter side is under 80 px contributes zero scores (ADR-021 §1). These are averaged in and can only pull a Track towards Unknown, so distant subjects are usually Unknown.
- **Calibration.** Thresholds come from a frozen protocol on held BDD100K dash-camera crops (`docs/qualification/poc/s5-zero-shot-attributes.md`). They are a Development scope on a different domain from the demo corpus, not a measured accuracy for the demo cameras. Until that calibration is entered, the shipped thresholds are a provisional, uncalibrated 0.5 for every attribute.
- **Search scale.** Attribute search is exact and measured only at demo scale; the Stage-2 E8 volume measurement is not attempted.
