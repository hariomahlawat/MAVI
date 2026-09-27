# Model Manifests

Model weights are never committed to Git. Each manifest here is a **v2 Model Pack source manifest** (`schemaVersion: "2.0"`, ADR-014; Stage 2 S2a plan §4.2): model id and version, the capabilities it provides, every artefact by `artifactRole` with its `relativePath` (all under one pack directory, P-10) and SHA-256 (the licence notice included, role `licence-notice`, P-15), input/output contracts, the compatible Runtime Pack families, licence metadata and review status, provenance, verification status and capability-specific sections (for example `detector`).

A source manifest carries **no** `modelPackId` and **no** byte sizes: the id is derived from the material inputs (P-3) by `mavi_vision.runtime.model_manifest_v2`, and sizes are measured by `tools/vision/build_model_pack.py` (P-14). The component binding (`src/vision/config/components/phase1-bindings-v2.json`) names a manifest only by that derived id, and `tools/verify_repo.py` re-derives and cross-checks it. A v1 manifest is refused everywhere.

Model/runtime dependency changes must also follow `docs/architecture/dependency-and-offline-packaging-policy.md` and update the applicable runtime locks, offline bundles and qualification evidence; model-hub or first-run downloads are not permitted in Production.
