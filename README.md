# MAVI — Mission-Aware Visual Intelligence

MAVI is a standalone, offline-production visual-intelligence platform. The proof of concept is intentionally structured as the first increment of the eventual product rather than as disposable prototype code.

## Architecture baseline

- **Operational platform:** ASP.NET Core / C# / .NET 10 LTS
- **Operator UI:** React + TypeScript + Vite
- **Vision/AI:** Python workers with CPU/CUDA device-specific Runtime Packs
- **Authoritative data:** PostgreSQL 18 + pgvector
- **Development:** one Windows laptop/workstation; CPU or compatible Windows CUDA when available
- **Production deployment profiles:** P1 single-host Windows GPU, P2 split-host Windows + Linux GPU, P3 single-host Windows CPU
- **Scale target:** approximately 200–500 cameras per large establishment
- **Production constraint:** no Internet connectivity required for installation or operation

The current Phase-1 product implementation is complete through Task 17. Task 18 is the active production-qualification and closure task. The operator application provides Overview, Cameras, Videos, Import, Processing, Search and Review workflows; see `docs/superpowers/plans/2026-09-19-visual-intelligence-workspace.md` for the current search/review workspace. ADR-008 defines profile-based qualification: Development remains a single Windows workstation/laptop with Auto/CUDA/CPU device intent, while Production profiles are qualified independently. Implementation completion is distinct from release verification: unavailable profile/device/offline/quality/performance evidence remains explicitly pending, and no Production profile is advertised as supported until its exact evidence passes.

## Repository layout

```text
src/platform   .NET operational platform
src/web        React operator application
src/vision     Python vision-worker package
contracts      language-neutral worker JSON schemas and examples
tests          .NET unit/integration tests
database       database scripts and notes
models         model manifests only; weights are never committed
infrastructure development/Windows/Linux/offline packaging notes
docs           architecture decisions, specifications and runbooks
tools          repository verification tooling
```

## Development setup

The supported Windows Development path is one-click. On a prepared repository, double-click:

```text
Setup-MAVI-Development.cmd
```

Approve elevation, allow Setup to prepare/verify the supported toolchain and MAVI-owned PostgreSQL/pgvector/FFmpeg/offline caches, then restart Visual Studio once and press **F5**.

Do not manually choose PostgreSQL ports, install pgvector, edit connection strings, or configure FFmpeg PATH as the normal workflow. See `docs/runbooks/local-development.md`.


### Development device use

Development does not require a separate Linux/GPU host. On the Windows development machine, the intended device policy is:

- **Auto:** prefer compatible Windows CUDA when available, otherwise CPU with visible fallback/provenance;
- **CUDA:** require CUDA and fail if unavailable;
- **CPU:** force CPU for debugging/reproducibility.

Windows CPU is currently qualified. Windows CUDA remains a separate qualification target; its addition must preserve the CPU path.

### Dependency policy

Any future feature that adds or changes a .NET, npm, Python, native, model/runtime or operating-system dependency must update the offline dependency contract in the same PR. `python tools/verify_repo.py` fails if direct .NET/npm/Python dependency surfaces change without an update to `config/dependencies/offline-dependency-policy-v1.json`.

The full methodology is defined in `docs/architecture/dependency-and-offline-packaging-policy.md`. External binary/version baselines are recorded in `config/dependencies/offline-binary-catalog-v1.json` and summarized in `docs/architecture/offline-binary-inventory.md`.

Large third-party payloads are retained in the separately downloadable **MAVI Offline Binary Kit**, not ordinary Git. A prepared Development workstation can keep that extracted kit beside the repository; `Setup-MAVI-Development.cmd` auto-detects and verifies it. Production must never download models, packages or runtime dependencies from the Internet.

## First checks

```bash
python tools/verify_repo.py
python -m pytest -q tools/phase1/tests
```

For Python:

```bash
cd src/vision
python -m pytest -q
```

For .NET after `Setup-MAVI-Development.cmd` has prepared the Development/test database environment:

```bash
dotnet restore MAVI.sln
dotnet build MAVI.sln
dotnet test MAVI.sln
```

For the frontend:

```bash
cd src/web/mavi-web
npm ci
npm test
npm run typecheck
npm run build
```

## Architecture source of truth

Start with:

- `docs/superpowers/specs/2026-09-08-mavi-repository-architecture-design.md`
- `docs/architecture/README.md`
- `docs/architecture/dependency-and-offline-packaging-policy.md`
- `docs/architecture/offline-binary-inventory.md`
- `docs/architecture/phase1-production-topology.md`
- `docs/decisions/ADR-008-phase1-production-topology.md`
- `docs/decisions/`
- `AGENTS.md`

Do not add production dependencies on cloud APIs, CDNs, remote fonts, online authentication, first-run model downloads, online licence checks or Internet telemetry.

For formal Phase-1 acceptance sequencing and evidence handling, see `docs/runbooks/phase1-acceptance.md`.
