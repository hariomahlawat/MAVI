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

Formal evidence must bind the exact source/model/profile/runtime/bundle identities that were exercised and must keep unavailable hardware or offline gates explicitly pending rather than inferring success.

ADR-003 closure additionally requires two executed proofs during Task 17 final acceptance:

- **offline application deployment/update:** deploy the exact hashed MAVI application artifact from controlled offline media onto a clean/reprovisioned Windows/IIS plane, then independently verify the running build identity matches that artifact; hashing an artifact beside a pre-existing deployment is insufficient;
- **offline backup/restore:** back up PostgreSQL plus all required managed source/evidence stores to local/approved network storage, restore them to a clean/reprovisioned target, and revalidate retained IDs/relationships, source/evidence hashes, Track search/detail and completed-run provenance before the restored deployment is accepted.

Both proofs must produce immutable hashed evidence and fail closed on missing stores, mismatched bytes/identities, hidden external dependencies or unexercised install/restore paths.

See `docs/superpowers/plans/2026-09-14-task-17-phase1-hardening-qualification-acceptance.md` for the authoritative sequence and evidence requirements.
