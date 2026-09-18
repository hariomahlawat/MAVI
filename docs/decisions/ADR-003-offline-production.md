# ADR-003: Online Development, Offline-by-Design Production

**Status:** Accepted  
**Date:** 2026-09-08

## Decision

Development may use Internet-connected tooling, package registries, coding agents, public datasets and model repositories. Production installation and operation must require no Internet connectivity.

## Required properties

- all application and UI assets are local;
- all AI models run locally;
- authentication is local to the deployment boundary;
- model weights are imported through controlled release bundles;
- no runtime cloud API, CDN, telemetry or online licence dependency exists;
- offline installation, backup, restore and update procedures are testable.


## Dependency-change control

A dependency is part of the feature that introduces it. New or changed NuGet/npm/Python packages, native binaries, runtimes, models, database extensions and OS prerequisites must be integrated into the supported disconnected Development/Production methodology in the same change.

The binding operational policy is `docs/architecture/dependency-and-offline-packaging-policy.md`, with a machine-readable direct-dependency baseline at `config/dependencies/offline-dependency-policy-v1.json`.

Repository verification fails when direct .NET/npm/Python dependencies drift from that baseline. Native/external prerequisites additionally require controlled staging, release-bundle inclusion, licence/notices, deterministic identity/version checks, Setup/readiness integration where applicable, and disconnected qualification proportional to their Production impact.

Normal operator workflows must not accumulate manual PATH edits, one-off package-manager commands or first-run downloads as features are added.
