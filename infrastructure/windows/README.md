# Windows Operational Deployment

## Operational plane

The supported Production operational plane is ASP.NET Core behind IIS on Windows. Normal installation is performed from the canonical MAVI offline setup media by double-clicking:

```text
Setup-MAVI-Production.cmd
```

Setup verifies the complete media, provisions/repairs the MAVI-owned PostgreSQL 18 + pgvector service, protected machine configuration, IIS/ASP.NET Core 10 hosting prerequisites, storage ACLs and LAN firewall rule, deploys the qualified application artifact, starts MAVI and verifies health/UI readiness. EF Core migrations are then applied automatically by fail-closed application startup.

Do not make a Production deployment depend on manual PATH edits, pgAdmin, package-manager commands or first-run Internet access.

See `docs/runbooks/mavi-offline-setup.md`.

## Vision workers on Windows

Where a native Windows vision worker is required, it remains a separately qualified runtime bundle tied to its exact platform/device variant. Install only from the supplied wheelhouse and immutable runtime lock; do not infer CUDA qualification from CPU qualification.

Model/config/profile/runtime artifacts are consumed from local controlled storage. No package-index, model-hub, online licence or first-run download fallback is permitted.

The exact current runtime/qualification truth is governed by the model manifest, runtime profile, platform locks and `docs/runbooks/phase1-acceptance.md`, not by this infrastructure overview.

## Future prerequisites

Any new Windows library/runtime/native/OS prerequisite must follow `docs/architecture/dependency-and-offline-packaging-policy.md`: update dependency policy, offline media, Setup/readiness, hashes/version checks, licences and qualification in the same feature.
