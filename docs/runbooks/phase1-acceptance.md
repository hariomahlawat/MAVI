# Phase-1 Acceptance and Qualification Runbook

Task 17 closes Phase 1 by proving the existing Camera → Import → Processing → Visual Search → Evidence Review system against explicit release, provenance, offline and recovery contracts. Hosted CI is not a substitute for disconnected or hardware qualification.

## Truth states

1. **Implementation complete** — deterministic tooling, APIs, tests, schemas and runbooks are implemented and exact-head CI is green.
2. **Implementation complete, evidence pending** — implementation is complete, but one or more mandatory hardware/offline/quality/performance proofs have not yet been executed.
3. **Release verified** — every mandatory gate has validated evidence, release metadata has been promoted without behavior changes, production bundles have passed disconnected smoke, and final production-topology acceptance has passed.

Never report state 2 as state 3.

## Authoritative contracts

- docs/superpowers/plans/2026-09-14-task-17-phase1-hardening-qualification-acceptance.md
- docs/superpowers/plans/2026-09-14-task-17-qualification-closure-addendum.md
- docs/decisions/ADR-003-offline-production.md
- docs/decisions/ADR-005-qualified-vision-runtime.md
- docs/decisions/ADR-006-platform-owned-accepted-evidence.md

## Deterministic connected checks

Run from the repository root:

~~~text
python tools/verify_repo.py
python -m pytest -q tools/phase1/tests
cd src/vision && python -m pytest -q
dotnet build MAVI.sln -c Release
dotnet test MAVI.sln -c Release
~~~

The normal Quality Gate and Task 17 Acceptance Validation workflow must be green on the same exact head. These checks prove implementation correctness only; they do not prove disconnected installation, CUDA operation, offline update, backup/restore or CCTV quality.

## Ground truth and quality

Ground truth uses sample-data/ground-truth/phase1-ground-truth.schema.json, sample-data/ground-truth/phase1-corpus.schema.json and config/acceptance/phase1-acceptance-v1.json.

Formal qualification requires exact media SHA-256, imported VideoAsset duration, explicit corpus-to-media-to-ground-truth mapping, nonzero Person coverage, nonzero Vehicle coverage, reviewed per-class precision/recall/F1 thresholds and deterministic spatial plus temporal matching. Aggregate results cannot compensate for a failing class.

The repository intentionally keeps quality thresholds unapproved until reviewed values are supplied. Do not invent values merely to make the gate pass.

## Public-API acceptance harness

tools/phase1/phase1_e2e_check.py is the canonical product-level acceptance harness. It uses public MAVI APIs and does not query PostgreSQL or inspect storage roots.

It verifies deployed application build/commit identity, Camera reconciliation, VideoAsset provenance, source bytes and strong ETag, exact ProcessingRun identity, completed-run release/runtime attestation, exact Track search/detail binding, opaque pagination, representative evidence integrity, Range semantics and ground-truth/media binding.

Formal runs require a target-containing corpus. Empty-scene diagnostic runs are separate and cannot satisfy the formal quality gate.

## Application artifact and offline lifecycle

Create the application artifact manifest after publishing MAVI:

~~~text
python tools/phase1/build_application_artifact_manifest.py --artifact-root <published-root> --source-commit <exact-commit> --build <build-id> --output <published-root>/mavi-application-manifest.json
~~~

The deployed host must set MAVI_BUILD and MAVI_COMMIT. GET /api/health must independently report those values.

For fresh install use tools/phase1/qualify_application_lifecycle.ps1 with Mode=fresh-install against a clean/reprovisioned Windows/IIS destination. A pre-existing deployment is not acceptable.

For update use the same tool with Mode=offline-update against an explicitly supported prior release listed in config/acceptance/phase1-supported-updates-v1.json. The policy must contain the reviewed SHA-256 of that prior release's `mavi-application-manifest.json`; a null/unfrozen manifest hash keeps the update gate pending. Supply `-PreUpdateAcceptanceEvidence <prior-release-passed-acceptance.json>`. The qualifier verifies the complete prior deployment against its manifest, proves the representative authoritative state before update, performs the update/migration, and proves the same state again after the target build starts. If migrationPolicy is required, the reviewed migration script is mandatory.

Fresh-install and update evidence are distinct mandatory proofs.

## Completed-run attestation

GET /api/processing/runs/{processingRunId}/attestation returns only completed runs. Unknown and non-completed runs use the same non-disclosing 404. Persisted provenance is parsed through the canonical validator and only stable allowlisted identities are returned.

Candidate runs legitimately have platformLockSha256=null; the candidate bundle-manifest and selected-lock hashes are proven separately. Production runs must carry the verified platform lock.

## Runtime and disconnected qualification

Required variants:

- windows-x86_64-cpu
- windows-x86_64-cuda
- linux-x86_64-cpu
- linux-x86_64-cuda

Each variant qualification verifies all bundle hashes, source commit, full frozen hostCompatibility, exact CPython patch version, unavailable outbound Internet, clean venv, strict no-index/hash-only installation, pip check, real local RTMDet inference, required actual device and full worker-flow evidence for the same variant.

Use tools/phase1/qualify_windows_offline.ps1 for Windows CPU+CUDA and tools/phase1/qualify_linux_offline.sh for Linux CPU+CUDA. Both wrappers require the frozen `config/acceptance/phase1-acceptance-v1.json` so worker-flow, variant and OS-level evidence retain the exact acceptance-policy SHA-256. Worker-flow evidence must come from the same exact candidate bundle/lock and attested runtime platform as the qualification host.

A CPU run never substitutes for CUDA. A CUDA run that falls back to CPU fails.

## Linux NVIDIA recovery/performance

Raw observations must be bound to the exact acceptance-profile hash and evaluated by tools/phase1/evaluate_recovery_performance.py.

The evaluator refuses to pass until reviewed performance thresholds exist in the acceptance profile. Evidence must prove no Track-state leakage, bounded CUDA OOM recovery, no semantic fallback, watchdog containment, replacement runtime after recovery, no CUDA-to-CPU fallback, bounded soak-memory growth, measured processing FPS and measured p95 end-to-end latency.

## Backup and restore

Use PostgreSQL service definitions so credentials are not placed on command lines. Source and clean restore services must be distinct.

Execute tools/phase1/qualify_backup_restore.py execute with `--acceptance-evidence <passed-acceptance.json>` to back up PostgreSQL plus managed source and accepted evidence to approved local storage. The tool independently queries source and restore PostgreSQL endpoint/database identities, rejects an identical target, and requires the restore database to contain no pre-existing public base tables before `pg_restore`.

Start MAVI against the restored target, then run tools/phase1/post_restore_check.py using both the original passed acceptance evidence and the exact `backup-restore-execution` evidence via `--execution-evidence`. It revalidates the original Camera ID, VideoAsset ID, ProcessingRun ID, every Track ID, representative Artifact, managed source bytes/ETag, completed-run attestation and search/detail retrieval, while cryptographically binding the result to the exact backup-set/store manifests.

Finalize with tools/phase1/qualify_backup_restore.py finalize. Restore evidence is not valid until the public-API post-restore check passes.

## Evidence verification and closure

tools/phase1/verify_phase1_evidence.py performs schema and semantic validation on transferred evidence.

tools/phase1/assess_phase1_closure.py is the final truth-state assessor. Before real-world evidence exists it must report implementation-complete-evidence-pending. Use --require-complete only when expecting release-verified.

The assessor must never be weakened merely to remove a pending item.

## Promotion

Do not hand-edit pending release metadata to verified.

After every mandatory qualification gate has real evidence and the runtime is fully qualified, use tools/phase1/promote_phase1_release.py. The promotion constructor requires exact-source evidence, all four qualified runtime variants and locks, preserves mandatory gate names, constructs deterministic final manifest/qualification bytes and re-runs canonical release selection.

Promotion must be status/evidence-only. Any model/config/profile/runtime behavior change invalidates earlier evidence.

## Production bundles and final acceptance

After promotion: build production bundles for all four variants; run disconnected production-mode smoke on every exact bundle; execute final production-topology acceptance on Windows/IIS plus Linux NVIDIA; execute fresh-install and update proofs; execute formal target-containing E2E; execute empty-scene diagnostic and failure/reprocess; execute backup/restore; verify no Internet, telemetry or licence dependency; retain immutable evidence hashes.

Candidate-bundle evidence does not replace post-promotion production-bundle smoke.

## Engineering stopping rule

Implementation is ready for final independent review when deterministic implementation/tests and repository verification are green on one exact head, no known Critical/P1/P2-equivalent implementation defect remains, unavailable real-world evidence is explicitly pending rather than bypassed, and documentation/tooling agree.

After final independent review, only materially reachable violations of accepted requirements block closure. Optional hardening or new scope goes to backlog. Do not repeatedly review an unchanged accepted head merely to generate more comments.


### Evidence-integrity rule

Formal Task-17 evidence is not interchangeable merely because it names the same source commit. Quality, performance, worker-flow, offline-install, update and restore evidence must retain and match the exact frozen acceptance-policy hash and all applicable target-manifest, bundle/lock, prior-artifact, execution and store-manifest identities. Evidence assembled from different qualification events must be rejected.
