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

Publish MAVI with an immutable build identity compiled into `Mavi.Api.dll`, then create the application artifact manifest with the same identities:

~~~text
dotnet publish src/platform/Mavi.Api/Mavi.Api.csproj -c Release -p:MaviBuild=<build-id> -p:MaviCommit=<exact-commit> -o <published-root>
python tools/phase1/build_application_artifact_manifest.py --artifact-root <published-root> --source-commit <exact-commit> --build <build-id> --output <published-root>/mavi-application-manifest.json
~~~

`GET /api/health` reads `MaviBuild` and `MaviCommit` from compile-time assembly metadata. Do not set environment variables to manufacture build identity. The lifecycle qualifier compares the manifest identity with the independently reported running binary identity; relabeling manifest JSON without rebuilding the binary must fail. `unknown-development` is never a formal promotion/production identity.

For fresh install use tools/phase1/qualify_application_lifecycle.ps1 with Mode=fresh-install against a clean/reprovisioned Windows/IIS destination. A pre-existing deployment is not acceptable.

For update use the same tool with Mode=offline-update against an explicitly supported prior release listed in config/acceptance/phase1-supported-updates-v1.json. The policy must contain the reviewed SHA-256 of that prior release's `mavi-application-manifest.json`; a null/unfrozen manifest hash keeps the update gate pending. Supply `-PreUpdateAcceptanceEvidence <prior-release-passed-acceptance.json>`. Before overwrite, the qualifier retains the exact approved prior manifest as `<EvidenceOutput>.prior-application-manifest.json`. It also retains `<EvidenceOutput>.prior-acceptance-evidence.json` and emits `<EvidenceOutput>.pre-update-state.json` and `<EvidenceOutput>.post-update-state.json`. Both state checks bind the live API to the exact expected commit **and build**, and must prove the same camera/video/run/tracks/artifact/source state across the update. If `migrationPolicy=required`, the canonical policy must freeze `migrationScriptSha256`; the supplied migration script must match that hash before execution.

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

Use tools/phase1/qualify_windows_offline.ps1 for Windows CPU+CUDA and tools/phase1/qualify_linux_offline.sh for Linux CPU+CUDA. Both wrappers require the frozen `config/acceptance/phase1-acceptance-v1.json`, the controlled qualification media/corpus, the MAVI API/media root, and the frozen MAVI build identity.

The variant qualifier creates a clean venv, installs the exact bundle lock with no-index/hash-only semantics, and then launches `mavi_vision.worker.main` from that newly installed venv. While that exact worker process is alive it runs the public-API E2E harness and generates the worker-flow evidence itself. A previously generated/detached worker-evidence JSON is not accepted. Variant evidence retains the installed Python executable SHA-256, worker-command SHA-256, worker-log SHA-256, worker-flow evidence SHA-256, bundle/lock identities, host identity, device and MAVI build.

A CPU run never substitutes for CUDA. A CUDA run that falls back to CPU fails.

## Linux NVIDIA recovery/performance

Raw observations must be bound to the exact acceptance-profile hash and evaluated by tools/phase1/evaluate_recovery_performance.py.

The evaluator refuses to pass until reviewed performance thresholds exist in the acceptance profile. Evidence must prove no Track-state leakage, bounded CUDA OOM recovery, no semantic fallback, watchdog containment, replacement runtime after recovery, no CUDA-to-CPU fallback, bounded soak-memory growth, measured processing FPS and measured p95 end-to-end latency.

## Backup and restore

Use PostgreSQL service definitions so credentials are not placed on command lines. Source and clean restore services must be distinct.

Execute `tools/phase1/qualify_backup_restore.py execute` with `--base-url <live-mavi-url>`, `--expected-mavi-build <build-id>`, `--acceptance-evidence <passed-acceptance.json>` and `--acceptance-profile config/acceptance/phase1-acceptance-v1.json`. Before any dump/copy, the tool queries the running MAVI `/api/system/storage-topology` attestation and requires its compiled commit/build, live PostgreSQL identity, hashed managed-media root and hashed accepted-evidence root to match the exact operator-supplied backup sources. It then independently queries source and restore PostgreSQL identities, rejects an identical target, and requires the restore database to contain no pre-existing public base tables before `pg_restore`.

Start MAVI against the restored target, then run tools/phase1/post_restore_check.py using both the original passed acceptance evidence and the exact `backup-restore-execution` evidence via `--execution-evidence`. It revalidates the original Camera ID, VideoAsset ID, ProcessingRun ID, every Track ID, representative Artifact, managed source bytes/ETag, completed-run attestation and search/detail retrieval, while cryptographically binding the result to the exact backup-set/store manifests.

Finalize with tools/phase1/qualify_backup_restore.py finalize. Restore evidence is not valid until the public-API post-restore check passes.

## Evidence verification and closure

tools/phase1/verify_phase1_evidence.py performs schema and semantic validation on transferred evidence.

`tools/phase1/assess_phase1_closure.py` is the final truth-state assessor. Before real-world evidence exists it must report `implementation-complete-evidence-pending`. Promotion alone is not closure: the assessor also requires the application manifest, four production variant evidence files, final production E2E and the independently assembled production-acceptance record. It re-hashes the underlying files and compares them to that record before allowing `release-verified`. Use `--require-complete` only when expecting final production acceptance.

The assessor must never be weakened merely to remove a pending item.

## Promotion

Do not hand-edit pending release metadata to verified.

After every mandatory qualification gate has real evidence and the runtime is fully qualified, use `tools/phase1/promote_phase1_release.py`.

Promotion requires **all eight mandatory gate evidence files again**, even if the pending qualification record already contains an older `passed` entry. It never grandfathers prior evidence references. Supply the canonical acceptance profile, the exact approved corpus manifest and ground-truth manifest, the frozen MAVI build identity, and one `--gate-evidence gate=path` argument for every mandatory gate. Promotion re-hashes and schema-validates every supplied object, requires the canonical corpus/media/ground-truth relationship, recomputes the performance threshold decision from the canonical profile, verifies cross-gate source/build/profile/target-manifest identities, reconstructs deterministic final manifest/qualification bytes and re-runs canonical release selection.

Promotion must be status/evidence-only. Any model/config/profile/runtime/application-build behavior change invalidates earlier evidence.

## Production bundles and final acceptance

After promotion, final acceptance is a separate production-topology event. Per-variant production smoke evidence cannot be reused as the final system E2E.

### 1. Freeze and prove the production prerequisite baseline

The canonical policy is `config/acceptance/phase1-production-prerequisites-v1.json`. It remains `approvalStatus=pending` until the real approved deployment versions are reviewed and frozen. Do not invent versions to remove the pending state.

Capture observations on the actual acceptance topology:

~~~text
python tools/phase1/collect_production_prerequisites.py --role windows-operational-plane --output <windows-prereq.json>
python tools/phase1/collect_production_prerequisites.py --role database --pg-service <service> --output <database-prereq.json>
<exact Linux CUDA venv python> tools/phase1/collect_production_prerequisites.py --role linux-vision-worker --output <linux-prereq.json>
~~~

Once the canonical policy is formally approved, validate the three observed records:

~~~text
python tools/phase1/validate_production_prerequisites.py \
  --policy config/acceptance/phase1-production-prerequisites-v1.json \
  --source-commit <exact-commit> \
  --mavi-build <build-id> \
  --windows-observation <windows-prereq.json> \
  --database-observation <database-prereq.json> \
  --linux-observation <linux-prereq.json> \
  --output <production-prerequisites.json>
~~~

The validator fails if the policy is still pending, any approved field is unfrozen, or an observed Windows/IIS, PostgreSQL/pgvector, CPython, NVIDIA-driver or CUDA-runtime identity differs from the approved baseline.

### 2. Build and execute all four exact production bundles

Build **production** bundles for Windows/Linux CPU/CUDA. Run the disconnected variant qualifiers on every exact bundle. Each qualifier installs into a clean venv and launches the real worker from that venv; detached prior worker evidence is not accepted.

Retain all four `mavi-offline-variant-evidence-v1` files. They must bind the same source commit, MAVI build, promoted model-manifest hash and canonical acceptance-profile hash.

### 3. Create one immutable final-acceptance execution and checkpoint server logs

Before any final production scenario, create exactly one acceptance context:

~~~text
python tools/phase1/create_production_acceptance_context.py \
  --source-commit <exact-commit> \
  --mavi-build <build-id> \
  --output <acceptance-context.json>
~~~

Immediately checkpoint the current API, IIS and PostgreSQL log files:

~~~text
python tools/phase1/capture_production_log_checkpoints.py \
  --acceptance-context <acceptance-context.json> \
  --log api=<api.log> \
  --log iis=<iis.log> \
  --log postgres=<postgres.log> \
  --output <server-log-checkpoint.json>
~~~

The checkpoint records the exact file path, pre-run byte offset and prefix SHA-256. Final inspection accepts only bytes appended after this checkpoint and requires the checkpoint timestamp to precede every final scenario.

### 4. Run independent final formal and empty-scene scenarios

The final formal product E2E must be a new execution, separate from the Linux-CUDA per-variant smoke. Use `tools/phase1/run_production_scenario.py --mode formal --acceptance-context <acceptance-context.json>` with the exact qualified Linux-CUDA production venv/bundle, controlled target-containing media, canonical corpus and ground truth. The scenario record binds the exact worker Python, production bundle/lock, generated E2E file and worker log.

Run a second independent `--mode empty-scene-diagnostic` scenario with the same `--acceptance-context` using reviewed empty-scene media. This diagnostic passes only with **zero Tracks, zero resolved Track details and zero representative evidence reads**. Any detection is a false-positive acceptance failure.

The final assembler and closure explicitly reject reuse of the Linux-CUDA variant's earlier worker-flow E2E as the final formal scenario.

### 5. Execute the production failure/reprocess scenario

With the normal production worker stopped initially, run `tools/phase1/qualify_failure_reprocess.py --acceptance-context <acceptance-context.json>`. The qualifier:

1. imports/resolves controlled target-containing media through the public API;
2. queues the first ProcessingRun;
3. leases that exact run as a controlled fault-injection worker;
4. fails it through the public worker control-plane API with `task17_controlled_failure`;
5. proves the managed source bytes/ETag remain unchanged;
6. queues a new ProcessingRun;
7. launches `mavi_vision.worker.main` from the exact qualified Linux-CUDA production venv/bundle;
8. requires verified CUDA completion, a new ProcessingRun ID, retained source integrity and at least one Track.

A connected integration test is not a substitute for this final production-topology execution.

### 6. Inspect the complete acceptance logs

Retain UTF-8 logs for these six mandatory roles:

- `api`
- `iis`
- `postgres`
- `formal-worker`
- `empty-worker`
- `failure-worker`

Run `tools/phase1/inspect_production_logs.py` with `--acceptance-context <acceptance-context.json>`, `--server-log-checkpoint <server-log-checkpoint.json>`, the formal/empty scenario records, and one `--log role=path` argument for every role, plus any internal MAVI hostnames via `--allowed-host`. Loopback hosts are always allowed.

For API/IIS/PostgreSQL it verifies the checkpoint prefix and scans only the bytes appended during the acceptance event. Worker logs are scanned in full and remain hash-bound to their exact scenario. The inspection fails on any non-allowlisted HTTP(S) endpoint or telemetry/licensing/activation indicator. Its evidence is bound to the exact formal E2E, empty-scene E2E and failure/reprocess evidence. Final acceptance independently verifies that the three worker-log hashes are the logs produced by those exact executions.

### 7. Fresh install, supported update, and backup/restore

Execute the separate fresh-install and offline-update application lifecycle proofs for the exact compiled application artifact.

After the successful **formal production scenario**, execute backup/restore using that exact formal E2E evidence as `--acceptance-evidence`. Therefore the final backup evidence's `acceptanceEvidenceSha256` must equal the final formal E2E file SHA-256.

### 8. Assemble final production acceptance

Use `tools/phase1/assemble_production_acceptance.py` with:

- the immutable acceptance context and server-log checkpoint;
- promoted verified model manifest and canonical acceptance profile;
- exact compiled application artifact and manifest;
- validated prerequisite evidence plus all three raw prerequisite observations;
- fresh-install and supported-update evidence;
- the retained prior application manifest, retained prior acceptance evidence, and the exact pre-update and post-update authoritative-state check files emitted by the update qualifier;
- all four production variant evidence files;
- formal scenario record + formal E2E;
- empty-scene scenario record + empty-scene E2E;
- failure/reprocess evidence;
- production log-inspection evidence;
- backup/restore evidence.

Supply the same six raw topology logs again as `--production-log role=path` arguments. The assembler re-hashes and re-scans them independently rather than trusting the log-inspection JSON.

The resulting `mavi-phase1-production-acceptance-evidence-v1` is an immutable aggregate of hashes, not a self-asserted pass.

### 9. Final closure

Pass the aggregate record **and every underlying evidence file**, including `--prior-application-manifest`, `--prior-acceptance-evidence`, `--pre-update-state-check`, `--post-update-state-check`, and the same six raw `--production-log role=path` files, to `tools/phase1/assess_phase1_closure.py`. Closure reopens, re-hashes and revalidates them against the canonical supported-update policy before allowing `release-verified`.

`release-verified` is impossible if the prerequisite policy is pending, any production variant is missing, the formal/empty scenarios are reused or mismatched, failure/reprocess is absent, required topology logs are absent/dirty, backup/restore references another case, or the aggregate record contains hashes from another acceptance execution.

Candidate-bundle evidence, promotion alone, connected CI, or a deterministic failure-recovery test never substitute for this final production-topology evidence.


## Engineering stopping rule

Implementation is ready for final independent review when deterministic implementation/tests and repository verification are green on one exact head, no known Critical/P1/P2-equivalent implementation defect remains, unavailable real-world evidence is explicitly pending rather than bypassed, and documentation/tooling agree.

After final independent review, only materially reachable violations of accepted requirements block closure. Optional hardening or new scope goes to backlog. Do not repeatedly review an unchanged accepted head merely to generate more comments.


### Evidence-integrity rule

Formal Task-17 evidence is not interchangeable merely because it names the same source commit. Quality, performance, worker-flow, offline-install, update and restore evidence must retain and match the exact frozen acceptance-policy hash and all applicable target-manifest, bundle/lock, prior-artifact, execution and store-manifest identities. Evidence assembled from different qualification events must be rejected.


### Topology and exact-environment continuity

Final acceptance binds approved prerequisite **versions** to the concrete systems actually exercised. Windows prerequisite evidence must match the lifecycle host identity, the database prerequisite identity must equal the backup source database identity, and the Linux prerequisite host identity must equal the Linux-CUDA production variant host identity.

Each qualified variant records an exact virtual-environment fingerprint derived from the venv root, `pyvenv.cfg`, resolved interpreter and installed-distribution metadata. Final formal, empty-scene and failure/reprocess scenarios recompute this fingerprint and must match the Linux-CUDA production qualification; sharing the same base Python executable is insufficient.
