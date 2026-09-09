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

## Data and security

- Never commit credentials, secrets, certificates, CCTV recordings, biometric datasets or model weights.
- Every future analytical result must carry model/version provenance and evidence traceability.
- AI matches and associations are candidate findings until verified by authorized logic/human workflow.
- Use UTC in cross-system contracts unless a contract explicitly says otherwise.

## Engineering practice

- Prefer small, cohesive modules and explicit interfaces.
- Keep model-specific libraries behind Python vision interfaces.
- Add tests with each behavior change.
- Run `python tools/verify_repo.py` before committing.
- Run language-specific tests/builds for every affected subsystem.
- Document architectural changes as ADRs before implementation.

## Time naming and semantics

- `...Utc` identifies an absolute UTC system instant; persist these as PostgreSQL `timestamptz` and prefer `DateTimeOffset` in .NET.
- `...Local` identifies timezone-less wall-clock input that must travel with an explicit `...TimeZoneId`.
- `...TimeZoneId` is an IANA timezone identity. Camera timezones interpret source input; evidence records snapshot that interpretation.
- `...OffsetMs` and `...DurationMs` are media-relative values and must never undergo timezone conversion.
- Avoid ambiguous time names such as `CreatedAt`, `StartTime`, or `Timestamp`. Obtain current application time through injected .NET `TimeProvider`.
