# MAVI — Mission-Aware Visual Intelligence

MAVI is a standalone, offline-production visual-intelligence platform. The proof of concept is intentionally structured as the first increment of the eventual product rather than as disposable prototype code.

## Architecture baseline

- **Operational platform:** ASP.NET Core / C# / .NET 10 LTS
- **Operator UI:** React + TypeScript + Vite
- **Vision/AI:** Python workers, later hosted on Linux GPU nodes
- **Authoritative data:** PostgreSQL + pgvector (integration follows in the next implementation phase)
- **Production deployment:** Windows Server/IIS for the operational plane; Ubuntu/Linux GPU servers for vision workers
- **Scale target:** approximately 200–500 cameras per large establishment
- **Production constraint:** no Internet connectivity required for installation or operation

## Repository layout

```text
src/platform   .NET operational platform
src/web        React operator application
src/vision     Python vision-worker package
contracts      language-neutral worker JSON schemas and examples
tests          .NET tests and later end-to-end tests
database       database design/migration notes
models         model manifests only; weights are never committed
infrastructure development/Windows/Linux/offline packaging notes
docs           architecture decisions, specifications and runbooks
tools          repository verification tooling
```

## Development prerequisites

Install the following on a connected development workstation:

- Visual Studio with the ASP.NET and web-development workloads
- .NET 10 SDK
- Node.js 22 or later
- Python 3.13 or later
- Git

PostgreSQL, pgvector, CUDA, PyTorch and computer-vision models are deliberately not introduced in this bootstrap. They will be added against specific PoC use cases rather than as speculative dependencies.

## First checks

```bash
python tools/verify_repo.py
pytest src/vision/tests -q
```

When the .NET 10 SDK is installed:

```bash
dotnet restore MAVI.sln
dotnet build MAVI.sln
dotnet test MAVI.sln
```

When npm registry access is available:

```bash
cd src/web/mavi-web
npm install
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
