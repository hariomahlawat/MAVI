# Dependency and Offline Packaging Policy

## Purpose

Every MAVI feature must remain easy to develop, install and operate on disconnected machines. A feature is not complete merely because its code compiles on a connected developer PC.

Any new library, SDK, native executable, runtime, model, database extension, operating-system prerequisite or build tool must be treated as part of the product's deployment contract.

The machine-readable baseline is:

`config/dependencies/offline-dependency-policy-v1.json`

`python tools/verify_repo.py` validates the direct .NET, npm and Python dependency surfaces against that baseline. If a developer adds or changes a direct dependency without updating the policy, repository verification fails.

## Default rule

Prefer the existing platform/framework before introducing another dependency.

When a dependency is genuinely required, the feature must answer all of the following before merge:

1. **Why is it needed?** Record the functional/technical reason and reject convenience-only duplication.
2. **Where does it run?** Classify it as build-only, Development/test, application runtime, native runtime, vision/model runtime, or OS prerequisite.
3. **How does it work offline?** Define the exact local source, cache, runtime pack or release-bundle path. First-run downloads are prohibited.
4. **How is it installed or resolved?** Integrate it into MAVI Setup or make it application-local. Do not add manual PATH/pgAdmin/registry/configuration instructions as the normal workflow.
5. **How is it verified?** Native/external payloads require deterministic version/hash/viability checks. Managed dependencies must be exercised by the relevant build/test/restore gate.
6. **What licences/notices must travel with it?** Redistribution requirements must be retained in the staged/release payload.
7. **What changes in recovery/update/qualification?** If the dependency affects Production or persisted data, update the applicable lifecycle, disconnected, backup/restore or hardware qualification evidence.
8. **What documentation changes?** Update the dependency policy and any user/release runbook whose actual workflow changes.

A dependency change is therefore part of the feature, not a later deployment task.

## Ecosystem handling

### .NET / NuGet

Direct `PackageReference` entries in the solution are policy-controlled.

Development offline restore is supplied through the canonical NuGet cache prepared by `Prepare-MaviDeveloperOfflineCache.ps1`. Production dependencies are captured by the qualified `dotnet publish` output; the ASP.NET Core 10 Hosting Bundle is carried in the offline setup media.

Adding/changing a package requires:

- updating the machine-readable dependency policy;
- verifying the disconnected Development restore cache still contains the complete closure;
- passing .NET build/test;
- validating the Production publish artifact when the package is runtime-relevant.

### React / npm

`dependencies` and `devDependencies` in `src/web/mavi-web/package.json` are policy-controlled and must stay synchronized with `package-lock.json`.

Development uses the bundled npm cache and `npm ci --offline`. Production receives compiled local static assets only; npm is not a Production runtime prerequisite and UI assets must never come from a CDN.

### Python

`src/vision/pyproject.toml` and `tools/requirements.txt` are policy-controlled.

Development uses the bundled Python wheelhouse with `--no-index`. Production vision dependencies must be represented by the applicable platform-specific runtime lock/bundle and qualification evidence. Model/runtime dependencies may not auto-download weights or packages.

### Native binaries and system prerequisites

Examples include PostgreSQL/pgvector, FFmpeg, CUDA/NVIDIA components and future native libraries.

These must have:

- an approved version/baseline;
- a canonical staging location;
- a deterministic offline packaging path;
- SHA-256 or equivalent identity verification;
- executable/runtime viability checks where practical;
- required licence/notices;
- Setup/repair integration when machine installation is required;
- readiness/qualification checks.

Do not make normal MAVI operation depend on whatever happens to be installed on PATH.

## Setup contract

The normal operator experience remains intentionally small:

**Development:** `Setup-MAVI-Development.cmd` → restart Visual Studio once → F5.

**Production:** `Setup-MAVI-Production.cmd` → Setup completes → open MAVI.

A future feature that introduces another prerequisite must extend this setup path rather than adding a separate operator checklist, unless an ADR explicitly approves a different deployment boundary.

Setup must remain idempotent: rerunning the same approved media verifies/repairs MAVI-owned state rather than creating duplicate installations.

## Review and CI contract

A PR that changes dependencies must:

- update `config/dependencies/offline-dependency-policy-v1.json`;
- update package/lock files as applicable;
- update staging/cache/setup/readiness logic if required;
- update licences/notices for redistributable payloads;
- run `python tools/verify_repo.py`;
- pass affected language build/tests;
- pass offline/setup contract validation;
- update relevant runbooks when the user/release workflow changes.

The PR template and `AGENTS.md` repeat this requirement so both human developers and coding agents follow the same methodology.

## Binary storage

Large third-party binaries should not normally be committed into ordinary Git history.

Use the canonical `vendor/...` staging locations and assemble one SHA-256-manifested MAVI offline release bundle. Git LFS or an approved internal binary repository may later be used for controlled binary retention without changing the target-machine setup contract.

Small deterministic source/configuration/manifests belong in Git. Model weights, CCTV media, credentials and large generated dependency caches remain outside ordinary Git history.

## Definition of done for a dependency-bearing feature

The feature is complete only when all applicable code, tests, dependency policy, offline staging/cache, installer/setup integration, version/hash verification, licence handling, readiness checks and documentation are updated together and exact-head CI is green.

If a new dependency cannot be installed and operated disconnected under this methodology, it is not yet ready for MAVI Production.
