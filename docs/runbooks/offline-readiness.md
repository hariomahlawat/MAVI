# Offline Readiness Runbook

Every major milestone should be exercised on a test machine with Internet access disabled.

Verify that:

1. the operational API starts without external connectivity;
2. the React UI loads with all fonts, scripts, styles and images local;
3. authentication does not call an external identity provider;
4. the Python worker starts without downloading packages or model weights;
5. model files are resolved from approved local storage;
6. video processing, search and evidence retrieval function on the LAN;
7. logs contain no failed Internet telemetry or licence-check calls;
8. backup and restore use only local/approved network storage;
9. an update can be applied from a controlled offline bundle.


## Phase-1 formal acceptance

Task 17 owns the formal Phase-1 disconnected-install and end-to-end offline acceptance event. Hosted CI, an invalid proxy, or the existence of a qualification-candidate bundle is not by itself proof of a disconnected deployment.

Formal evidence must bind the exact source/application-build/model/profile/runtime/bundle identities that were exercised and must keep unavailable hardware or offline gates explicitly pending rather than inferring success. Application build identity is compiled into `Mavi.Api.dll`; mutable environment variables are not accepted as binary identity. Each platform qualification must execute the full worker flow from the clean venv created from the exact tested bundle/lock rather than attaching a previously generated worker-evidence file.

ADR-003 closure additionally requires three executed proofs during Task 17 final acceptance:

- **fresh offline application installation:** install the exact hashed MAVI application artifact from controlled offline media onto a clean/reprovisioned Windows/IIS plane, then independently verify the running build identity matches that artifact; hashing an artifact beside a pre-existing deployment is insufficient;
- **offline application update:** in a separate case, start from an explicitly supported prior MAVI release with representative configuration/database state, apply the accepted target artifact with Internet unavailable, execute all applicable migrations, verify retained state, and independently attest the post-update running build identity; fresh-install evidence cannot substitute for this proof;
- **offline backup/restore:** back up PostgreSQL plus all required managed source/evidence stores to local/approved network storage, restore them to a clean/reprovisioned target, and revalidate retained IDs/relationships, source/evidence hashes, Track search/detail and completed-run provenance before the restored deployment is accepted.

All three proofs must produce distinct immutable hashed evidence and fail closed on missing stores, mismatched bytes/identities, hidden external dependencies or unexercised install/restore paths.

After release promotion, all four exact **production** bundles must be executed disconnected. The final Linux-CUDA production E2E must attest the exact production bundle-manifest SHA-256 and promoted platform lock. Backup/restore must then use that final production E2E as its accepted case. `tools/phase1/assemble_production_acceptance.py` reconciles the compiled application artifact, fresh install, supported update, four production variant executions, final production E2E and final backup/restore into one immutable production-acceptance record. `assess_phase1_closure.py` independently reopens those underlying files; promotion or candidate evidence alone can never yield `release-verified`.

Operational commands and evidence handling are documented in `docs/runbooks/phase1-acceptance.md`. The authoritative requirements remain `docs/superpowers/plans/2026-09-14-task-17-phase1-hardening-qualification-acceptance.md` plus its qualification-closure addendum.


## Final production-topology acceptance

A promoted release is not yet Phase-1 accepted. Final disconnected acceptance additionally requires:

- a repository-owned approved prerequisite baseline and observed matching identities for Windows/IIS, PostgreSQL/pgvector and Linux/NVIDIA/CPython/CUDA;
- an independent target-containing formal production E2E using the exact Linux-CUDA production venv/bundle;
- a distinct empty-scene production diagnostic with zero false-positive Tracks;
- a controlled public-API failure/reprocess scenario followed by successful processing from the exact production worker environment;
- inspected API, IIS, PostgreSQL and scenario-worker logs with no external network, telemetry, licensing or activation dependency;
- backup/restore bound to the exact final formal production E2E.

These proofs are assembled by `tools/phase1/assemble_production_acceptance.py` and independently reopened by `tools/phase1/assess_phase1_closure.py`. Missing or cross-spliced evidence remains pending/fails closed.


Final production evidence is one acceptance execution, not a collection of independently clean files. Create a single immutable acceptance context before the final scenarios, checkpoint API/IIS/PostgreSQL logs at that point, and scan only the server/database bytes appended after the checkpoint. Formal, empty-scene and failure/reprocess scenarios must carry the same execution ID/context hash.

Approved prerequisite versions must also be bound to the concrete topology exercised: the Windows prerequisite host identity must match lifecycle evidence, the database identity must match the backup source database, and the Linux prerequisite host identity must match the Linux-CUDA production worker host. Final Linux-CUDA scenarios must recompute and match the qualified virtual-environment fingerprint; the same base Python executable alone is not sufficient.
