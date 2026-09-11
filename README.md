# MAVI — Mission-Aware Visual Intelligence

MAVI is a standalone, offline-production visual-intelligence platform. The proof of concept is intentionally structured as the first increment of the eventual product rather than as disposable prototype code.

## Architecture baseline

- **Operational platform:** ASP.NET Core / C# / .NET 10 LTS
- **Operator UI:** React + TypeScript + Vite
- **Vision/AI:** Python workers, later hosted on Linux GPU nodes
- **Authoritative data:** PostgreSQL 18 + pgvector
- **Production deployment:** Windows Server/IIS for the operational plane; Ubuntu/Linux GPU servers for vision workers
- **Scale target:** approximately 200–500 cameras per large establishment
- **Production constraint:** no Internet connectivity required for installation or operation

The current Phase-1 implementation includes PostgreSQL persistence and migrations, managed MP4 ingestion, camera/video APIs, the lease/heartbeat/fail worker control plane, and the deterministic Task-9 track-processing pipeline with attempt-scoped secure artifact staging. Task 10 is in progress: the self-contained RTMDet-M hosted CPU runtime candidate is frozen and has passed real Linux/Windows CPU inference, and security-equivalent POSIX/native-Windows staging is implemented. Production RTMDet/ByteTrack adapters, GPU qualification, hashed offline runtime bundles, result persistence/completion, and searchable evidence UI remain later Phase-1 work.

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

## Development prerequisites

Install the following on a connected development workstation:

- Visual Studio with the ASP.NET and web-development workloads
- .NET 10 SDK
- PostgreSQL 18 with pgvector
- FFmpeg/ffprobe
- Node.js 22 or later
- Python 3.13 for the current core development/test baseline; the Task-10 qualified RTMDet runtime candidate uses Python 3.12
- Git

For Windows/Visual Studio database and test setup, follow `docs/runbooks/local-development.md` before running the integration tests. The integration suite intentionally requires a dedicated `mavi_test` database and never falls back to the development database.

CUDA, PyTorch and computer-vision model packages are introduced only when the corresponding vision-processing task requires them. Production runtime must not download models or other dependencies from the Internet.

## First checks

```bash
python tools/verify_repo.py
```

For Python:

```bash
cd src/vision
python -m pytest -q
```

For .NET after configuring `MAVI_TEST_DB_CONNECTION` as described in the local-development runbook:

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
- `docs/decisions/`
- `AGENTS.md`

Do not add production dependencies on cloud APIs, CDNs, remote fonts, online authentication, first-run model downloads, online licence checks or Internet telemetry.
