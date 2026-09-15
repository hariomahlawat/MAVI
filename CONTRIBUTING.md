# Contributing to MAVI

MAVI is offline-by-design. A change is not complete until it works through the supported Development and Production deployment paths without hidden Internet or machine-local assumptions.

## Before coding

Read:

- `AGENTS.md`
- `docs/architecture/README.md`
- `docs/architecture/dependency-and-offline-packaging-policy.md`
- relevant ADRs under `docs/decisions/`

Use an ADR first when changing an architectural boundary, datastore, deployment topology or other accepted platform decision.

## Dependencies

If the feature adds or changes any library, SDK, native executable, runtime, model, database extension or OS prerequisite, treat that work as part of the feature.

The same PR must update all applicable items:

- package/lock files;
- `config/dependencies/offline-dependency-policy-v1.json`;
- `config/dependencies/offline-binary-catalog-v1.json` when an external/native/toolchain payload changes;
- Development offline cache/binary-kit preparation;
- Production/offline bundle composition;
- MAVI Setup/repair when machine installation is required;
- version/hash/viability checks for native/external payloads;
- licences/notices;
- tests and qualification evidence;
- local-development/offline/readiness/acceptance documentation where workflows change.

Do not add a normal operator step such as “install this manually”, “add this to PATH”, “run this package manager command”, or “download on first startup” when Setup or application-local packaging can own it.

## Supported setup

Development:

```text
Setup-MAVI-Development.cmd
→ approve elevation
→ restart Visual Studio once
→ F5
```

Production is installed from the canonical offline setup bundle through `Setup-MAVI-Production.cmd`.

## Required verification

At minimum:

```text
python tools/verify_repo.py
```

Then run the affected subsystem build/tests. Before merge, the normal MAVI Quality Gate and Task 17 Acceptance Validation must be green on the exact PR head when applicable.

Hosted CI proves implementation correctness. It does not substitute for disconnected, CUDA, performance, update or backup/restore qualification evidence.

## Binary policy

Small deterministic source, configuration, manifests and scripts belong in Git.

Large third-party installers/runtime payloads are staged under the canonical `vendor/...` paths and assembled into a separately retained SHA-256-manifested **MAVI Offline Binary Kit**. The final Production setup media is assembled from that verified kit plus the qualified application artifact.

Third-party/generated EXE/DLL/MSI/ZIP/7z/WHL/SO/PYD payloads are not committed to ordinary Git, even when individually small. Git LFS or an approved internal binary repository may later retain the companion kit without changing the target-machine setup contract.

Never commit credentials, private keys, CCTV recordings, biometric datasets or model weights.
