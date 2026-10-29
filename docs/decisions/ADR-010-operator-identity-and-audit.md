# ADR-010: Operator identity, authorization and audit for attributable mutations

**Status:** **Proposed — owner decision required** (PoC slice S11-min, register row C10.1). Implemented on the S11-min PR so that it can be reviewed against working code; the row stays IN PROGRESS until the owner accepts this ADR. The decision text for the owner is in §9.

**Date:** 2026-10-29

**Related:** ADR-003 (offline Production); ADR-004 (time authority); ADR-008 (Phase-1 topology: Production behind IIS on Windows); ADR-020 (`poc-single-host`); `docs/superpowers/plans/2026-09-20-audited-review-and-cases-plan.md` (Slice 0 is this ADR, Slice 1 and the append-only principle of Slice 2 are implemented with it); `docs/superpowers/plans/2026-10-28-mavi-poc-end-to-end.md` (S11-min); register `docs/reviews/2026-10-28-poc-acceptance.md` row C10.1.

## Context

Until now MAVI has had no operator mutation that needed attribution: the API has no authentication or authorization middleware and every endpoint is anonymous. The PoC adds several: plate reanalysis (S3), gallery enrolment and update (S6), Entity confirm/dismiss (S7), review decisions and cases (S11-full). Each must record **who** acted, **when** (by the server's clock), and **what**, in a record that cannot be rewritten afterwards.

Constraints:

- Production is offline (ADR-003): no remote identity provider, no OIDC endpoint, no cloud directory.
- Production runs on a Windows host behind IIS (ADR-008); the PoC runs Kestrel on loopback on one Windows host (ADR-020), started by the operator, environment name `PoC`.
- The Production profiles P1–P3 are not to change behaviour in this slice: none of them has an operator mutation yet, and their IIS sites do not enable Windows Authentication.
- Development and CI need a way to exercise attributable endpoints without a Windows token (CI runs on Linux).

**Correction to the plan's premise.** The plans call Negotiate "in-box". It is not part of the ASP.NET Core shared framework: Windows authentication under Kestrel needs the Microsoft package `Microsoft.AspNetCore.Authentication.Negotiate` (same release train as the framework, 10.0.11 here). It is a managed, Microsoft-published, application-local assembly: no native payload, no machine prerequisite, no network at run time (SSPI on Windows). It is recorded in `config/dependencies/offline-dependency-policy-v1.json`; the developer NuGet cache and `dotnet publish` carry it like the other ASP.NET packages, so the binary catalogue does not change. Under IIS, the same handler defers to IIS's own Windows Authentication — and **throws on every request** if IIS has Windows Authentication disabled. That is why the default mode below is `disabled`.

## Decision

### 1. Identity source: the Windows host, one mode per installation

`Identity:Mode` selects exactly one identity mode for the process:

| Mode | Authentication | Who may act | Where allowed |
|---|---|---|---|
| `disabled` (default) | none registered | nobody: every attributable endpoint answers 401 | everywhere; it is the default so that P1–P3 and existing hosts are unchanged |
| `windows-negotiate` | Negotiate (Kerberos/NTLM via SSPI) under Kestrel; deferred to IIS Windows Authentication under IIS | a Windows principal that is a member of a configured group (`Identity:Operators:AuthorizedGroups`) or named in the allow-list (`Identity:Operators:AuthorizedUsers`); an empty configuration authorizes nobody | everywhere; under IIS the site must enable Windows **and** Anonymous Authentication (a Production Setup change, not made here) |
| `development-unattributed` | a fixed fallback identity for every request | everyone who can reach the host | only when the environment is `Development`, or the effective deployment profile is `poc-single-host`; never when the environment is `Production`. Any other combination stops the host at start-up |

Choosing `development-unattributed` is the explicit setting the fallback requires; there is no implicit fallback. A Windows principal that fails the group/allow-list check is refused (403); an unauthenticated request in `windows-negotiate` mode is challenged (401 `WWW-Authenticate: Negotiate`). Existing endpoints stay anonymous: there is no fallback authorization policy. A new attributable endpoint opts in with `.RequireAuthorization(OperatorPolicy.Name)` and takes its actor from `ICurrentOperator`, never from the request body.

### 2. The operator identity

`ICurrentOperator` (`Mavi.Application.Modules.Identity`) yields `OperatorIdentity(OperatorId, DisplayName, IdentitySource)`:

- `windows-negotiate`: `OperatorId` is the account SID (stable across renames) when the principal carries one, else the account name; `DisplayName` is `DOMAIN\user`; `IdentitySource` = `windows-negotiate`.
- `development-unattributed`: `OperatorId` = `development-unattributed`, `DisplayName` = `Development operator (unattributed)`, `IdentitySource` = `development-unattributed`. The label is carried into every audit record it produces, so an unattributed action can never be read as an attributed one.

### 3. Disclosure

The deployment disclosure (`GET /api/system/deployment`, the System page, ADR-020 §3) gains an `identity` block: the mode in effect, whether actions are attributable, whether any operator is configured, and a statement. Under `poc-single-host` the release metadata written by the installer records the identity mode installed (`identityMode`), and the disclosure shows both. The PoC installer writes `windows-negotiate` with `BUILTIN\Users` as the operator group: on a dedicated demonstration host with trusted local users (owner decision S1-T1), every interactive local user is an operator, and every action is attributed to that user's Windows account.

### 4. Append-only audit

One table, `audit_entries`, records every attributable mutation: entry id, operator id, display name and identity source, action, subject type and id, server timestamp (`recorded_at_utc`), SHA-256 of the canonical payload, and correlation id (the request's trace identifier).

- **Same transaction.** `IAuditWriter.Append` stages the entry on the request's unit of work (the scoped `MaviDbContext`); it never commits on its own. The mutation's `SaveChanges` (or its explicit transaction) commits both or neither. There is no separate audit write that could diverge from the state it describes.
- **Append-only in the database.** Row-level `BEFORE UPDATE` / `BEFORE DELETE` and statement-level `BEFORE TRUNCATE` triggers raise an error, whatever the client. A table owner can still drop the triggers; the guard protects against application defects and casual edits, not against the database owner (privilege separation between the migration role and the application role is a Production hardening item outside the PoC).
- **No payload storage.** The audit row carries the payload hash, not the payload: the mutation's own table holds the state. S11-full adds the read surface.

### 5. Server time authority

Every audit timestamp comes from the injected `TimeProvider` (ADR-004, AGENTS.md); no client-supplied time is accepted.

### 6. Trade-off accepted

- **Ties Phase 1 to the Windows host.** Operator identity is whatever Windows says it is; a non-Windows host gets only `disabled` or the labelled fallback. A portable identity provider (an offline OIDC server, local accounts with passwords) is **deferred**; when a Linux host or a non-domain multi-user deployment needs attributable actions, a new ADR replaces §1.
- **Groups resolve at sign-in.** Membership changes take effect on the next Windows logon token, not immediately.
- **The guard is not tamper-proof against the database owner.** It is an integrity control for the application, not a forensic one (no hash chain). A hash-chained or externally anchored audit log is out of scope.
- **The fallback exists.** It is accepted because CI and Development need to exercise attributable endpoints without a Windows token; it is confined by environment and profile, refused under `Production`, labelled in every record and disclosed.

### 7. Production

P1–P3 behaviour does not change: their configuration does not set `Identity:Mode`, so it is `disabled`, no authentication handler is registered and no existing endpoint changes. Enabling `windows-negotiate` for a Production profile requires the IIS site to enable Windows and Anonymous Authentication, which is a Setup change and Production evidence for a later slice.

### 8. Consequences for later slices

S3 (`POST /api/plates/reanalysis`), S6 (gallery), S7 (Entity confirm/dismiss) and S11-full (review decisions, cases) each add `.RequireAuthorization(OperatorPolicy.Name)` to their endpoint and call `IAuditWriter.Append` before their `SaveChanges`. S11-full adds the audit read surface.

### 9. Owner decision requested

> **ADR-010 — decision requested.** Accept Windows-integrated operator identity for Phase 1 and the PoC: `Identity:Mode` = `disabled` (default; P1–P3 unchanged) | `windows-negotiate` (Negotiate via the Microsoft package `Microsoft.AspNetCore.Authentication.Negotiate` 10.0.11 under Kestrel, deferring to IIS Windows Authentication under IIS; operators = configured Windows groups or allow-listed accounts) | `development-unattributed` (fixed labelled fallback, allowed only in `Development` or under `poc-single-host`, refused under `Production`, disclosed and labelled in every audit record). The PoC installer configures `windows-negotiate` with `BUILTIN\Users` as the operator group (trusted-host assumption S1-T1). Every attributable mutation writes one row to an append-only `audit_entries` table in the same transaction, with server time from `TimeProvider`; UPDATE, DELETE and TRUNCATE are refused by database triggers. Accepted trade-off: attribution is tied to the Windows host and a portable identity provider is deferred; the audit guard is an application-integrity control, not a forensic one.
