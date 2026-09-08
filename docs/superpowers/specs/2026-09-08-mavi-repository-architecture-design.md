# MAVI Repository Architecture Design

**Date:** 2026-09-08  
**Product:** MAVI — Mission-Aware Visual Intelligence  
**Status:** Approved design baseline for repository bootstrap

## 1. Purpose

Create the initial source repository for MAVI so that the proof of concept is the first increment of the eventual production system rather than disposable prototype code. Development may use Internet-connected tools and public services, but the production release must be installable and operable on an air-gapped establishment LAN without any Internet dependency.

## 2. Target Deployment Model

- Operational platform: Windows Server + IIS.
- AI/computer-vision workers: Ubuntu/Linux GPU servers.
- User interface: React + TypeScript SPA.
- Core application: C# / ASP.NET Core on .NET 10 LTS.
- AI/computer vision: Python 3.13-compatible package.
- Authoritative datastore: PostgreSQL + pgvector.
- Initial media store: local/network filesystem behind an abstraction.
- Initial worker transport: simple HTTP job/result contract; replaceable by durable messaging when scale requires it.
- Final scale target: large establishments, approximately 200–500 cameras.

## 3. Architecture Style

Use a modular monolith for the operational platform plus independently deployable Python AI workers. Do not begin with full microservices. The .NET platform owns operational state, missions, investigations, human decisions, evidence, audit and authoritative entity records. Python owns video decoding and analytical inference outputs such as detections, tracks, embeddings, attributes and quality measurements.

## 4. Repository Layout

One Git repository contains the .NET solution, React application, Python vision worker, cross-language contracts, tests, infrastructure scripts, model manifests, sample-data conventions and architecture documentation.

```text
MAVI/
├── MAVI.sln
├── README.md
├── AGENTS.md
├── CLAUDE.md
├── .editorconfig
├── .gitignore
├── global.json
├── Directory.Build.props
├── src/
│   ├── platform/
│   │   ├── Mavi.Api/
│   │   ├── Mavi.Application/
│   │   ├── Mavi.Domain/
│   │   ├── Mavi.Infrastructure/
│   │   └── Mavi.Contracts/
│   ├── web/mavi-web/
│   └── vision/
├── contracts/
├── tests/
├── database/
├── models/
├── sample-data/
├── infrastructure/
├── tools/
└── docs/
```

## 5. Dependency Rules

- `Mavi.Domain` depends on no other MAVI project.
- `Mavi.Application` depends on `Mavi.Domain` and `Mavi.Contracts` only.
- `Mavi.Infrastructure` depends on `Mavi.Application`, `Mavi.Domain` and `Mavi.Contracts`.
- `Mavi.Api` depends on `Mavi.Application`, `Mavi.Infrastructure` and `Mavi.Contracts`.
- React communicates only through HTTP/SignalR APIs; it never accesses PostgreSQL directly.
- Python communicates through stable worker contracts; it does not own operational decisions or authoritative mission/intelligence state.

## 6. Initial Internal Modules

The operational platform will be organized by business capability rather than generic `Services`/`Helpers` folders. Initial module namespaces are:

- Identity
- Cameras
- Media
- Intelligence
- Entities
- Investigations
- Missions
- Evidence
- Audit
- SystemHealth

Only the repository structure and minimal health/bootstrap slices are created now; feature modules will be implemented incrementally.

## 7. AI Worker Boundary

Python may produce:

- detections
- within-camera tracks
- embeddings
- attributes
- ANPR candidates
- image/video quality metrics
- candidate analytical events

Python must not autonomously create or confirm investigations, identities, mission alerts, threat labels, or relationships as accepted facts. Those remain operational-platform concerns subject to policy and human verification.

## 8. Media and Data Boundaries

- Do not stream raw frames between .NET and Python through ordinary application APIs.
- Jobs pass references to video assets and time ranges.
- Workers read media from an authorized media store and return structured results plus artifact references.
- PostgreSQL is the initial authoritative data store. Additional databases/search engines are not introduced until a measured requirement justifies them.

## 9. Offline-Production Requirement

Production operation must not require Internet connectivity. Release engineering must prevent hidden online dependencies including CDN assets, Google Fonts, first-run model downloads, remote authentication, cloud AI APIs, telemetry endpoints, online license checks or external map tiles.

AI model weights are not stored in Git. `models/manifests/` records approved model identity, version, checksum, local path convention, runtime requirements and provenance. Offline release bundles later package the required weights and software dependencies through controlled transfer.

## 10. Agentic Development Rules

`AGENTS.md` and `CLAUDE.md` are first-class engineering controls. Agents must read the architecture and ADRs before changes, preserve dependency boundaries, add tests, avoid Internet dependencies in production code, avoid model-specific coupling outside the vision layer, and never infer operational facts directly from unverified AI outputs.

## 11. Bootstrap Success Criteria

The initial repository is successful when:

1. Git history is initialized and the architecture baseline is documented.
2. Visual Studio can open `MAVI.sln` once .NET 10 SDK is installed.
3. The .NET projects encode the intended dependency direction.
4. The React app has a minimal local-only shell with no CDN references.
5. The Python vision package exposes replaceable detector/tracker/embedding protocols and a health-capable worker shell.
6. Cross-language job/result JSON schemas exist with examples.
7. Baseline tests validate Python contracts and repository offline-policy checks.
8. No actual CCTV feature implementation is attempted in this bootstrap.
