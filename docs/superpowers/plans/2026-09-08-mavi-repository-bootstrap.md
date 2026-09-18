# MAVI Repository Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a working, agent-ready MAVI monorepo skeleton that preserves the approved production architecture while implementing only minimal bootstrap/health slices.

**Architecture:** A .NET 10 modular operational platform, separate React/TypeScript SPA, and separate Python vision worker live in one Git repository. Cross-language contracts are explicit, PostgreSQL/pgvector and messaging are documented but not yet integrated, and the repository includes automated checks against accidental Internet dependencies.

**Tech Stack:** Git, C#/.NET 10, ASP.NET Core, React 19 + TypeScript + Vite, Python 3.13+, pytest, JSON Schema.

**Spec:** `docs/superpowers/specs/2026-09-08-mavi-repository-architecture-design.md`

## Global Constraints

- Final production operation must require no Internet connectivity.
- Operational platform target is Windows Server/IIS; AI worker target is Ubuntu/Linux GPU servers.
- Target scale is approximately 200–500 cameras.
- Architecture is modular monolith + independently deployable Python AI workers.
- Python never owns authoritative operational decisions.
- Do not introduce additional datastores, queues, model frameworks or cloud services in the bootstrap.
- Do not commit AI model weights, CCTV recordings, secrets or generated dependency folders.

---

### Task 1: Repository engineering baseline

**Files:**
- Create: `.gitignore`
- Create: `.editorconfig`
- Create: `global.json`
- Create: `Directory.Build.props`
- Create: `README.md`
- Create: `AGENTS.md`
- Create: `CLAUDE.md`
- Create: `docs/architecture/README.md`
- Create: `docs/decisions/ADR-001-technology-baseline.md`
- Create: `docs/decisions/ADR-002-modular-monolith-and-ai-workers.md`
- Create: `docs/decisions/ADR-003-offline-production.md`

**Interfaces:**
- Consumes: approved repository architecture spec.
- Produces: repository-wide conventions consumed by every later task and agent.

- [ ] **Step 1:** Create ignore/editor/build policy files with .NET 10, Node, Python, model-weight, media, secret and worktree exclusions.
- [ ] **Step 2:** Create root README with development topology, production topology, prerequisites and commands.
- [ ] **Step 3:** Create `AGENTS.md` and `CLAUDE.md` with dependency, security, test and offline-production rules.
- [ ] **Step 4:** Create the three initial ADRs and architecture index.
- [ ] **Step 5:** Run `git diff --check` and verify no secrets/media/model binaries are tracked.
- [ ] **Step 6:** Commit as `chore: add repository engineering baseline`.

### Task 2: .NET solution and project boundaries

**Files:**
- Create: `MAVI.sln`
- Create: `src/platform/Mavi.Domain/Mavi.Domain.csproj`
- Create: `src/platform/Mavi.Domain/Marker.cs`
- Create: `src/platform/Mavi.Contracts/Mavi.Contracts.csproj`
- Create: `src/platform/Mavi.Contracts/Worker/WorkerContracts.cs`
- Create: `src/platform/Mavi.Application/Mavi.Application.csproj`
- Create: `src/platform/Mavi.Application/Health/GetPlatformHealth.cs`
- Create: `src/platform/Mavi.Infrastructure/Mavi.Infrastructure.csproj`
- Create: `src/platform/Mavi.Infrastructure/DependencyInjection.cs`
- Create: `src/platform/Mavi.Api/Mavi.Api.csproj`
- Create: `src/platform/Mavi.Api/Program.cs`
- Create: `src/platform/Mavi.Api/appsettings.json`
- Create: `tests/Mavi.Domain.Tests/Mavi.Domain.Tests.csproj`
- Create: `tests/Mavi.Domain.Tests/ArchitectureBoundaryTests.cs`
- Create: `tests/Mavi.Application.Tests/Mavi.Application.Tests.csproj`
- Create: `tests/Mavi.Application.Tests/GetPlatformHealthTests.cs`
- Create: `tests/Mavi.IntegrationTests/Mavi.IntegrationTests.csproj`

**Interfaces:**
- Consumes: root engineering policies.
- Produces: `.NET` project references and `GET /api/health` returning `{ status, component, version }`.

- [ ] **Step 1:** Create SDK-style .NET 10 projects with nullable reference types and implicit usings enabled.
- [ ] **Step 2:** Encode references Domain <- Application <- Infrastructure/Api, with Contracts as a transport-only dependency.
- [ ] **Step 3:** Add immutable worker contract records for job identifiers and worker health without adding persistence or AI logic.
- [ ] **Step 4:** Add application health query and API `/api/health` endpoint.
- [ ] **Step 5:** Add xUnit tests for the application health result and explicit project-reference boundary assertions.
- [ ] **Step 6:** Run `dotnet restore`, `dotnet build MAVI.sln`, and `dotnet test MAVI.sln` when .NET 10 SDK is available; if unavailable in the execution environment, record that limitation and validate project XML/reference topology with `tools/verify_repo.py`.
- [ ] **Step 7:** Commit as `feat: scaffold dotnet operational platform`.

### Task 3: Python vision-worker package

**Files:**
- Create: `src/vision/pyproject.toml`
- Create: `src/vision/mavi_vision/__init__.py`
- Create: `src/vision/mavi_vision/common/contracts.py`
- Create: `src/vision/mavi_vision/detection/interfaces.py`
- Create: `src/vision/mavi_vision/tracking/interfaces.py`
- Create: `src/vision/mavi_vision/embeddings/interfaces.py`
- Create: `src/vision/mavi_vision/video/media_reference.py`
- Create: `src/vision/mavi_vision/worker/health.py`
- Create: `src/vision/tests/test_contracts.py`
- Create: `src/vision/tests/test_worker_health.py`

**Interfaces:**
- Consumes: worker contract semantics from `Mavi.Contracts` and JSON schemas.
- Produces: typed Python protocols `Detector`, `Tracker`, `EmbeddingExtractor`, plus worker-health/processing-job dataclasses.

- [ ] **Step 1:** Write tests asserting valid worker health and processing-job serialization.
- [ ] **Step 2:** Run `pytest src/vision/tests -q` and confirm failure because package modules do not yet exist.
- [ ] **Step 3:** Implement minimal frozen dataclasses and replaceable Protocol interfaces with no model dependency.
- [ ] **Step 4:** Run `pytest src/vision/tests -q` and confirm all tests pass.
- [ ] **Step 5:** Commit as `feat: scaffold python vision worker`.

### Task 4: React/TypeScript application shell

**Files:**
- Create: `src/web/mavi-web/package.json`
- Create: `src/web/mavi-web/tsconfig.json`
- Create: `src/web/mavi-web/tsconfig.node.json`
- Create: `src/web/mavi-web/vite.config.ts`
- Create: `src/web/mavi-web/index.html`
- Create: `src/web/mavi-web/src/main.tsx`
- Create: `src/web/mavi-web/src/App.tsx`
- Create: `src/web/mavi-web/src/app.css`
- Create: `src/web/mavi-web/src/api/platform.ts`
- Create: `src/web/mavi-web/src/vite-env.d.ts`

**Interfaces:**
- Consumes: `GET /api/health` from Mavi.Api.
- Produces: local-only operator shell that displays MAVI identity and platform health without external assets/CDNs.

- [ ] **Step 1:** Define React/TypeScript/Vite package metadata with scripts `dev`, `build`, `typecheck`.
- [ ] **Step 2:** Implement a minimal shell and typed health client using relative `/api` URLs only.
- [ ] **Step 3:** Run `npm install`, `npm run typecheck`, and `npm run build` when registry access is available; otherwise run offline-policy verification and preserve lockfile generation for the first connected developer run.
- [ ] **Step 4:** Verify `index.html` contains no remote stylesheet, script, font or image URL.
- [ ] **Step 5:** Commit as `feat: scaffold react operator shell`.

### Task 5: Cross-language worker contracts and examples

**Files:**
- Create: `contracts/schemas/vision-job.schema.json`
- Create: `contracts/schemas/vision-result.schema.json`
- Create: `contracts/schemas/worker-health.schema.json`
- Create: `contracts/examples/vision-job.example.json`
- Create: `contracts/examples/vision-result.example.json`
- Create: `contracts/examples/worker-health.example.json`
- Create: `contracts/README.md`

**Interfaces:**
- Consumes: C# and Python bootstrap transport types.
- Produces: implementation-neutral JSON wire contract baseline.

- [ ] **Step 1:** Create JSON Schemas for job, result and worker health envelopes with UUID identifiers and explicit schema versions.
- [ ] **Step 2:** Add example payloads that validate against those schemas.
- [ ] **Step 3:** Add contract README documenting versioning and Python/.NET ownership rules.
- [ ] **Step 4:** Add schema/example validation to `tools/verify_repo.py`.
- [ ] **Step 5:** Commit as `feat: define vision worker contracts`.

### Task 6: Repository verification and offline guardrails

**Files:**
- Create: `tools/verify_repo.py`
- Create: `models/manifests/README.md`
- Create: `database/README.md`
- Create: `sample-data/README.md`
- Create: `infrastructure/development/README.md`
- Create: `infrastructure/windows/README.md`
- Create: `infrastructure/linux/README.md`
- Create: `infrastructure/offline-bundle/README.md`
- Create: `docs/runbooks/offline-readiness.md`

**Interfaces:**
- Consumes: all repository content.
- Produces: `python tools/verify_repo.py` with non-zero exit on forbidden production Internet URLs, committed secrets/model binaries/media, invalid contract examples, missing required files or invalid project-reference topology.

- [ ] **Step 1:** Write verification tests/fixtures internally in `verify_repo.py` for required path, contract and dependency checks.
- [ ] **Step 2:** Implement repository scan for `http://`/`https://` in executable production assets, with allow-list limited to documentation and package metadata.
- [ ] **Step 3:** Implement checks for prohibited tracked extensions (`.pt`, `.pth`, `.onnx`, `.mp4`, `.avi`, secret key files) outside explicitly allowed documentation examples.
- [ ] **Step 4:** Implement JSON Schema example validation and .NET project-reference topology validation.
- [ ] **Step 5:** Run `python tools/verify_repo.py` and `pytest src/vision/tests -q`; expect PASS.
- [ ] **Step 6:** Run `git status --short` and `git diff --check`; expect clean/valid state after commit.
- [ ] **Step 7:** Commit as `chore: add offline and repository verification guardrails`.
