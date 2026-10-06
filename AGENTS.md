# MAVI Agent Engineering Rules

This repository is designed for human developers and coding agents. Read this file, the architecture design, and all accepted ADRs before modifying code.

## Non-negotiable architecture

1. MAVI is a standalone product; do not couple it to PRISM or another ERP.
2. The operational platform is a modular ASP.NET Core application. Do not split it into microservices without an accepted ADR and measured need.
3. Python owns video/AI inference. It does not own authoritative investigations, identities, mission decisions, accepted relationships or operator actions.
4. React communicates through MAVI APIs only. It never accesses PostgreSQL or media storage directly.
5. PostgreSQL + pgvector is the initial authoritative datastore. Do not add another database/search engine without an accepted ADR and measured requirement.
6. Raw video frames must not be transported between .NET and Python through ordinary request/response APIs. Pass media references and structured analytical results.
7. Production must operate fully offline.

## Dependency direction

```text
Mavi.Domain          -> no MAVI project dependency
Mavi.Contracts       -> no MAVI project dependency
Mavi.Application     -> Domain + Contracts
Mavi.Infrastructure  -> Application + Domain + Contracts
Mavi.Api             -> Application + Infrastructure + Contracts
```

Do not introduce circular references or business logic in API controllers/endpoints.

## Offline-production rules

Do not introduce production runtime dependencies on:

- cloud AI APIs;
- remote authentication;
- CDNs or Google/remote fonts;
- external JavaScript/CSS/image assets;
- first-run model downloads;
- Internet telemetry;
- external map tiles;
- online licence validation.

Development may use the Internet. Release artifacts must be self-contained and support controlled offline transfer.

## Dependency and packaging changes

A library/runtime prerequisite is part of the feature that introduces it; do not defer offline packaging to a later task.

Before adding or changing any NuGet, npm, Python, native, model/runtime or OS dependency:

1. justify the dependency and prefer existing framework/platform capability when reasonable;
2. update `config/dependencies/offline-dependency-policy-v1.json` and, for external/native/toolchain payloads, `config/dependencies/offline-binary-catalog-v1.json`;
3. define its disconnected Development and Production strategy and whether it belongs in the companion MAVI Offline Binary Kit;
4. integrate machine prerequisites into MAVI Setup, or make the dependency application-local;
5. add deterministic version/hash/viability checks for native/external payloads;
6. retain required licences/notices;
7. update offline caches/runtime locks/release bundles and qualification evidence as applicable;
8. update the affected runbooks and tests.

`python tools/verify_repo.py` must remain green. It intentionally fails when direct .NET/npm/Python dependency surfaces drift from the declared offline dependency policy.

Do not make normal operator setup depend on manual PATH edits, package-manager commands, pgAdmin steps or first-run downloads. Do not commit third-party/generated EXE/DLL/MSI/ZIP/7z/WHL/SO/PYD payloads to ordinary Git; retain them through the manifest-verified binary kit instead. See `docs/architecture/dependency-and-offline-packaging-policy.md` and `docs/architecture/offline-binary-inventory.md`.

## Data and security

- Never commit credentials, secrets, certificates, CCTV recordings, biometric datasets or model weights.
- Every future analytical result must carry model/version provenance and evidence traceability.
- AI matches and associations are candidate findings until verified by authorized logic/human workflow.
- Use UTC in cross-system contracts unless a contract explicitly says otherwise.

## Data, benchmarks and annotation

ADR-017 governs Development data strategy. Small diagnostic labelling (a handful of examples to debug, check semantics or confirm an adapter bug) needs only a one-line technical rationale and never enters a measurement as truth. Before proposing a significant annotation campaign, a bespoke dataset, new Development capture or a large human-review effort:

1. search for established labelled datasets and benchmarks that answer the engineering question, and record what was found;
2. prefer benchmark reuse with deterministic adapters, mappings and ground-truth association over new labels;
3. respect each dataset's native taxonomy; map a native class to a MAVI capability only where the mapping is defensible, declared as `exact`, `subset` or `unsupported`, with its reason;
4. let capability scope follow what existing evidence proves: a supported subset may advance while unsupported classes are deferred, and no mapping is fabricated to keep an ontology intact;
5. record public-benchmark exposure and domain caveats with every result; a benchmark score is Development or reference evidence, never final qualification;
6. treat a significant annotation campaign as a documented fallback for a demonstrated benchmark gap that the owner has accepted;
7. apply the ADR-017 admissibility statuses (RESEARCH-ADMISSIBLE, RESEARCH-UNCERTAIN, BLOCKED) once per dataset release, not per file, unless the terms vary by file: research-use permission suffices for Development, ambiguity is recorded rather than treated as a prohibition, and an explicit prohibition of the intended use blocks;
8. never bypass payment, authentication or access controls, and never use data that cannot actually be obtained;
9. keep dataset bytes, frames, crops and labels out of ordinary Git; commit hashes, metadata and mappings;
10. preserve the separation between Development or benchmark evidence and protected final qualification (ADR-015 §3–§4), and use the lightest evidence process appropriate to the claim (operating principle 6a): Development benchmarks need reproducibility, provenance, deterministic evaluation and honest limitations, not Production qualification ceremony.

## Experimental methodology

A request states a question to investigate; it is not evidence that the proposed method answers it. This applies to consequential evidence-producing work: an experiment, benchmark, qualification activity, parameter study, dataset or taxonomy mapping, diagnostic analysis or architectural intervention whose result could influence architecture, Production profiles or parameters, benchmark interpretation, qualification or acceptance-register status, capability claims, detector/tracker/model selection or tuning, or dataset and taxonomy decisions. For such work, the executing agent challenges the method before running it (`docs/architecture/experimental-methodology.md`):

1. state the question and the assumptions the proposed method needs in order to answer it;
2. verify those assumptions against the actual implementation, the pinned dependency behaviour and existing evidence, not remembered semantics;
3. identify confounders and alternative explanations; check that the metric measures the claimed mechanism and that the intervention changes only the intended variable; prefer the smallest controlled experiment, or an analysis of existing evidence, that can discriminate between them.

Being asked to run an experiment is not methodological approval. If a material flaw is found, keep the objective but do not run the flawed method to complete the task. Stop and report the assumption, the evidence against it, the conclusion it would invalidate and the smallest corrected experiment. If the requester, once informed, still wants the original run, run it as a labelled limited run whose limitation goes with every conclusion drawn from it. Disagreeing with a proposed method is expected. A failed methodology review, a null result or a falsified hypothesis is a valid outcome.

Freeze the question, intervention, metrics and attribution rules before reading outcomes, and do not broaden the experiment after seeing results. Label conclusions as observed, derived, inferred or hypothesis, and claim causation only from a controlled intervention or a direct mechanism trace. Disclose a defective analysis and keep it as superseded evidence; never silently overwrite it. A consequential conclusion is independently cold-reviewed before it changes architecture, Production configuration, qualification status or a capability claim.

Routine bug fixes, formatting, mechanical refactors, test repairs, implementation of an approved design and trivial documentation corrections are out of scope until they start to change a benchmark definition, a causal interpretation, a qualification criterion, Production behaviour or a capability claim. When unsure whether work is in scope, treat it as in scope. The gate adds no approval ceremony (operating principle 6a).

## Engineering practice

Work implementation-first: see `docs/architecture/engineering-operating-principles.md`.

- Prefer small, cohesive modules and explicit interfaces.
- Keep model-specific libraries behind Python vision interfaces.
- Add tests with each behavior change.
- Run `python tools/verify_repo.py` before committing.
- Run language-specific tests/builds for every affected subsystem.
- Document architectural changes as ADRs before implementation.
- For feature sequencing and stage prerequisites, use the two current roadmap documents — `docs/superpowers/plans/capability-roadmap.md` (what and in which order) and `docs/superpowers/plans/capability-implementation-roadmap.md` (technical dependencies, impact and qualification preservation) — not dated historical task plans, which record the state at the time they were written.

## Time naming and semantics

- `...Utc` identifies an absolute UTC system instant; persist these as PostgreSQL `timestamptz` and prefer `DateTimeOffset` in .NET.
- `...Local` identifies timezone-less wall-clock input that must travel with an explicit `...TimeZoneId`.
- `...TimeZoneId` is an IANA timezone identity. Camera timezones interpret source input; evidence records snapshot that interpretation.
- `...OffsetMs` and `...DurationMs` are media-relative values and must never undergo timezone conversion.
- Avoid ambiguous time names such as `CreatedAt`, `StartTime`, or `Timestamp`. Obtain current application time through injected .NET `TimeProvider`.
