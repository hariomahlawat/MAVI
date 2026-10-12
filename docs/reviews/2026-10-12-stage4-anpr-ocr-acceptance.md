# ANPR / OCR — Stage-4 Acceptance Register

**Status:** **OPEN.**
- PR-1 has implemented and tested the plate benchmark harness and the frozen normalisation contract (P1, P2).
- The evidence-adequacy measurement **has not been executed**, because no labelled plate release is on the Development host yet. P3 is NOT MEASURED, and capability selection (PR-2) does not start.

**Date opened:** 2026-10-12\
**Baseline:** `main@78ec81de514874ed7dc536f2eee19669d1cfec6b` (merge of PR #212, the Stage 4 plan)

This register is the only authoritative exit gate for Stage 4. The plan
`docs/superpowers/plans/2026-10-12-stage4-anpr-ocr.md` (§7 PR sequence, §8 rows) references these row IDs; it keeps no second acceptance list.

**Nothing unexecuted is marked PASS.** A row becomes PASS only when its evidence is entered here: commits, CI run IDs, or artefact SHA-256s with their retained location. Dataset bytes, crops and model weights never enter Git.

## Completion levels (never implied by one another)

1. **Harness implemented and tested** — code and deterministic fixture tests, in CI.
2. **Dataset onboarded and validated** — a release obtained under its ADR-017 record, the manifest frozen, the adapter's fail-closed reconciliation run on the real bytes, and the truth document written and hashed.
3. **Experiment executed** — E-A and E-B run on onboarded data with pinned, verified instruments; results retained by hash.
4. **Measurement accepted** — the verdict recorded under the frozen protocol and accepted here.

Every Stage-4 row is **Development** evidence (ADR-009, ADR-017 §9). No row is Production qualification. Production
plate search would additionally need a protected Indian holdout (ADR-015 §3–§4), qualified Runtime Pack variants, a
plate retention/access policy and the Production audit profile (plan §8).

## P. Rows

| Row | Requirement | Status | Evidence |
|---|---|---|---|
| P1 | Plate harness: ground truth, adapters, mappings, association, evaluators and verdict, with tests; ADR-017 release records | **PASS (level 1: harness implemented and tested)** | Ground truth `benchmark-plate-truth-v1` (`contracts/schemas/benchmark-plate-truth-v1.schema.json`, `tools/benchmarks/capabilities/plates/truth.py`). Production-path measurement `measure.py` imports `crop_region` and `JpegLadderEncoder(PRODUCTION_ENCODER_POLICY)`; a test pins byte equality with the production encoder. E-A `adequacy.py`; E-B `coverage.py` over the existing `benchmark-association-v1`; verdict `verdict.py`; instruments `instruments.py` (pinned by hash). Adapters `tools/benchmarks/datasets/ufpr_alpr.py` (sequences; also drives `prepare`/association) and `voc_plates.py` (Indian stills). CLI `tools/benchmarks/plates/cli.py`; result schema `benchmark-plate-adequacy-v1`. Tests: `tools/benchmarks/tests/test_plates_{contract,measurement,datasets}.py` (fixtures only). Release records: `docs/qualification/stage4/benchmarks/*.descriptor-template.json` (pinned to the adapters by test). Search record: `docs/qualification/stage4/benchmark-search-2026-10-12.md`. **Not** level 2: no release is onboarded (P3a) |
| P2 | Normalisation `mavi-plate-normalisation-v1` frozen; identical in Python and .NET | **PASS** | Contract and 36 vectors: `contracts/test-vectors/plate-normalisation-v1.json` (NFKC; ASCII-only upper-casing; nine named separators removed; everything else outside `[A-Z0-9]` rejects; no confusable substitution; advisory format class). Python `tools/benchmarks/plates/normalisation.py`, tested by `test_plates_contract.py`. .NET `Mavi.Application.Modules.Plates.PlateNormalisation`, tested by `tests/Mavi.Application.Tests/Plates/PlateNormalisationVectorTests.cs` (38 tests). Both read the same vector file |
| P3a | Level 2: at least one Indian still release and one Track-level sequence release onboarded (ADR-017 record, frozen manifest, fail-closed reconciliation on real bytes, truth hashed) | **OPEN — blocked on owner action** | UFPR-ALPR needs the owner's signed licence agreement. *Indian Licence Plate Dataset in the wild* is not public (author contact). The DataCluster Indian sample is downloadable (CC BY-NC-ND 4.0) but is close-up phone imagery without vehicle boxes, so it needs phase-1 detector vehicle candidates. See the search record |
| P3b | Instruments pinned and verified: two pretrained OCR readers (plate-specific, generic), exact package versions and model SHA-256 in `docs/qualification/stage4/instruments/*.json`; benchmark environment declared in `tools/benchmarks/plates/requirements-instruments.txt` with a dependency-policy entry | **OPEN** | Candidates: `fast-plate-ocr` 1.1.0 (MIT; ONNX Runtime CPU) and `rapidocr-onnxruntime` 1.4.4 recognition (Apache-2.0; PP-OCR models in the wheel; Python < 3.13, so a separate 3.12 environment). The adapters in `instruments.py` are **unverified against the real packages** until this row executes. Downloading the packages and models needs owner authorisation |
| P3c | Level 3: E-A executed (encoding loss; `h_min`; ΔEM per instrument at both caps; strata) | **NOT MEASURED** | Needs P3a and P3b |
| P3d | Level 3: E-B executed (real MAVI runs on the UFPR-ALPR testing split; association; C with denominators and states) | **NOT MEASURED** | Needs P3a (UFPR-ALPR), P3b and the Development host's MAVI runtime |
| P3 | Level 4: evidence-adequacy verdict (plan §3.4) with strata; protocol hashed before results | **NOT MEASURED** | Protocol frozen: `docs/qualification/stage4/adequacy-protocol.md` (SHA-256 recorded with the first result). The verdict command refuses to report anything but NOT_MEASURED without both experiments at support ≥ 50 |
| P4 | MSR events PLANNED → PROTOCOL_FROZEN; entry criteria §4.2 met | NOT STARTED | Gated on P3 (plan §4.2 item 1) |
| P5 | A–E measured; gates; technical ranking by D; consistent-wrong gate | NOT STARTED | PR-2 |
| P6 | Licence/deployment determinations per profile; owner implementation choice | NOT STARTED | PR-2 |
| P7 | Plate lifecycle: lease, fencing, evidence integrity, three-phase completion, supersession | NOT STARTED | PR-3 |
| P8 | Failure isolation (VisionJob, attributes and runs unaffected by a plate crash or OOM) | NOT STARTED | PR-3 |
| P9 | Bounded re-analysis; idempotent queueing | NOT STARTED | PR-3 |
| P10 | Search semantics, coverage, cursor v4, regression of existing populations, wire tests | NOT STARTED | PR-4 |
| P11 | Index plan and p95 budget at seeded scale; log redaction | NOT STARTED | PR-4 |
| P12 | UI journey, §34 sweep and a11y on plate states | NOT STARTED | PR-5 |
| P13 | Model/Runtime Packs: hashes, licence notices, `verify_repo`, disconnected install | NOT STARTED | PR-6 |
| P14 | Real end-to-end Track-level D through the product path, consistent with P5 | NOT STARTED | PR-6 |
| P15 | Engineering budget and 500-camera projection (M-E, projected) | NOT STARTED | PR-6 |
| P16 | Exact-head CI green for each Stage-4 PR | **PR-1: pending** | Recorded on the PR-1 head when CI completes |

## Shortest path to P3

1. **Owner:**
   - request UFPR-ALPR under its licence agreement;
   - authorise the instrument packages and model downloads (P3b);
   - optionally authorise the DataCluster Indian sample;
   - decide O1 (Indian Track-level evidence).
2. Freeze each release's descriptor from the obtained tree and write the truth (`cli truth`). This is level 2.
3. Create the instruments environment, write and verify the two specifications, and run E-A (`cli ea`).
4. Run `prepare` → `execute` on the UFPR-ALPR testing split on the Development host. Then run association and E-B (`cli eb`).
5. Run `cli verdict` and record the hashes and the verdict here.

**Support limitation, stated now.**
- UFPR-ALPR's testing split holds 60 vehicles (40 % of 150). R_oracle can reach the support floor of 50 only if almost every testing vehicle is oracle-readable. Otherwise C is *insufficient* and the verdict stays NOT MEASURED until a second sequence release is onboarded.
- This follows from the frozen floor, not from any result.
